from aaosa.runtime.runner import _sinks
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _task(description, depends_on=None) -> Task:
    return Task(description=description, required_tags={"python": 30}, depends_on=depends_on or [])


def _out(task_id) -> Output:
    return Output(
        task_id=task_id, agent_id="x", content=f"c-{task_id}",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _by_id(*tasks) -> dict[str, Output]:
    return {t.id: _out(t.id) for t in tasks}


class TestSinks:
    def test_chain_last_is_only_sink(self):
        # investigate -> analyze -> fix (tous réussis) => sink = {fix}
        a = _task("investigate")
        b = _task("analyze", depends_on=[a.id])
        c = _task("fix", depends_on=[b.id])
        sinks = _sinks([a, b, c], _by_id(a, b, c))
        assert [o.task_id for o in sinks] == [c.id]

    def test_parallel_all_are_sinks(self):
        # parse_logs, check_db indépendants (tous réussis) => sinks = {parse_logs, check_db}
        a = _task("parse_logs")
        b = _task("check_db")
        sinks = _sinks([a, b], _by_id(a, b))
        assert {o.task_id for o in sinks} == {a.id, b.id}

    def test_convergent_diamond_single_sink(self):
        # A->B->D, A->C->D (tous réussis) => sink = {D}
        a = _task("A")
        b = _task("B", depends_on=[a.id])
        c = _task("C", depends_on=[a.id])
        d = _task("D", depends_on=[b.id, c.id])
        sinks = _sinks([a, b, c, d], _by_id(a, b, c, d))
        assert [o.task_id for o in sinks] == [d.id]

    def test_failed_merge_resurfaces_inputs_as_sinks(self):
        # A->B->D, A->C->D mais D a ÉCHOUÉ (absent du dict) => sinks = {B, C}
        a = _task("A")
        b = _task("B", depends_on=[a.id])
        c = _task("C", depends_on=[a.id])
        d = _task("D", depends_on=[b.id, c.id])
        outputs = _by_id(a, b, c)  # D échoué : pas dans outputs
        sinks = _sinks([a, b, c, d], outputs)
        assert {o.task_id for o in sinks} == {b.id, c.id}

    def test_consumed_by_failed_sibling_is_still_sink(self):
        # S réussi, T (qui dépend de S) a échoué => S non consommé => S est un sink
        s = _task("S")
        t = _task("T", depends_on=[s.id])
        sinks = _sinks([s, t], _by_id(s))  # T absent
        assert [o.task_id for o in sinks] == [s.id]

    def test_consumed_by_succeeded_sibling_is_not_sink(self):
        s = _task("S")
        t = _task("T", depends_on=[s.id])
        sinks = _sinks([s, t], _by_id(s, t))
        assert [o.task_id for o in sinks] == [t.id]
