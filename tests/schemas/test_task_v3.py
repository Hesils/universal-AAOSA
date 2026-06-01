from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def make_output(task_id="t1") -> Output:
    return Output(
        task_id=task_id,
        agent_id="a1",
        content="some content",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestTaskV3Fields:
    def test_new_optional_fields_default(self):
        t = Task(description="d", required_tags={"python": 60})
        assert t.parent_task_id is None
        assert t.order_index is None
        assert t.depends_on == []
        assert t.required_outputs == []

    def test_depends_on_roundtrip(self):
        t = Task(description="d", required_tags={"python": 60}, depends_on=["x", "y"])
        restored = Task.model_validate_json(t.model_dump_json())
        assert restored.depends_on == ["x", "y"]

    def test_required_outputs_roundtrip(self):
        t = Task(
            description="d",
            required_tags={"python": 60},
            required_outputs=[make_output("t1"), make_output("t2")],
        )
        restored = Task.model_validate_json(t.model_dump_json())
        assert len(restored.required_outputs) == 2
        assert {o.task_id for o in restored.required_outputs} == {"t1", "t2"}

    def test_existing_task_unaffected(self):
        t = Task(description="Build API", required_tags={"python": 60})
        assert t.description == "Build API"
        assert t.required_tags == {"python": 60}
