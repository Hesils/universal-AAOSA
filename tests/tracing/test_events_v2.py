import pytest
from pydantic import TypeAdapter

from aaosa.qa.judge import JudgeBreakdown, DimensionScore
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    ClaimEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    QAEvaluatedEvent,
    TagAcquiredEvent,
)


class TestQAEvaluatedEvent:
    def test_valid_event(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=True, score=0.95,
            reason="All criteria passed",
        )
        assert e.type == "qa_evaluated"
        assert e.success is True
        assert e.score == 0.95

    def test_failure_event(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=False, score=0.2,
            reason="Too short",
        )
        assert e.success is False

    def test_json_roundtrip(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", success=True, score=0.8,
            reason="ok",
        )
        data = e.model_dump_json()
        e2 = QAEvaluatedEvent.model_validate_json(data)
        assert e2.type == "qa_evaluated"
        assert e2.score == 0.8

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            QAEvaluatedEvent(
                session_id="s1", task_id="t1",
                agent_id="a1", success=True, score=0.8,
                reason="ok", extra_field="bad",
            )


class TestEloUpdatedEvent:
    def test_valid_event(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={"python": 5, "backend": -3},
        )
        assert e.type == "elo_updated"
        assert e.deltas == {"python": 5, "backend": -3}

    def test_empty_deltas(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={},
        )
        assert e.deltas == {}

    def test_json_roundtrip(self):
        e = EloUpdatedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", deltas={"css": 10},
        )
        data = e.model_dump_json()
        e2 = EloUpdatedEvent.model_validate_json(data)
        assert e2.deltas == {"css": 10}


class TestTagAcquiredEvent:
    def test_valid_event(self):
        e = TagAcquiredEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", tag="docker", initial_elo=20,
        )
        assert e.type == "tag_acquired"
        assert e.tag == "docker"
        assert e.initial_elo == 20

    def test_json_roundtrip(self):
        e = TagAcquiredEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", tag="k8s", initial_elo=15,
        )
        data = e.model_dump_json()
        e2 = TagAcquiredEvent.model_validate_json(data)
        assert e2.tag == "k8s"
        assert e2.initial_elo == 15


class TestClaimEventUnionV2:
    def test_discriminator_qa_evaluated(self):
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "qa_evaluated",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "success": True, "score": 0.9,
            "reason": "ok",
        }
        event = adapter.validate_python(data)
        assert isinstance(event, QAEvaluatedEvent)

    def test_discriminator_elo_updated(self):
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "elo_updated",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "deltas": {"python": 5},
        }
        event = adapter.validate_python(data)
        assert isinstance(event, EloUpdatedEvent)

    def test_discriminator_tag_acquired(self):
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "tag_acquired",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "tag": "docker", "initial_elo": 20,
        }
        event = adapter.validate_python(data)
        assert isinstance(event, TagAcquiredEvent)

    def test_existing_types_still_work(self):
        adapter = TypeAdapter(ClaimEvent)
        data = {
            "type": "phase1_filtered",
            "session_id": "s1", "task_id": "t1",
            "agent_id": "a1", "passed": True, "fit_score": 0.9,
        }
        event = adapter.validate_python(data)
        assert isinstance(event, Phase1FilteredEvent)


class TestExecutedEventLLMMetadata:
    def test_defaults_to_none(self):
        """Rétrocompat : ExecutedEvent sans llm_metadata reste valide, défaut None."""
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
        )
        assert e.llm_metadata is None

    def test_carries_llm_metadata(self):
        meta = LLMMetadata(
            model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0,
        )
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done", llm_metadata=meta,
        )
        assert e.llm_metadata is not None
        assert e.llm_metadata.tokens_in == 10

    def test_json_roundtrip_with_metadata(self):
        meta = LLMMetadata(
            model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0,
        )
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done", llm_metadata=meta,
        )
        e2 = ExecutedEvent.model_validate_json(e.model_dump_json())
        assert e2.llm_metadata is not None
        assert e2.llm_metadata.model_name == "gpt-4o-mini"
        assert e2.llm_metadata.latency_ms == 42.0


class TestExecutedEventOutputContent:
    def test_defaults_to_none(self):
        """Rétrocompat : output_content optionnel, défaut None."""
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
        )
        assert e.output_content is None

    def test_carries_full_content(self):
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done"[:100],
            output_content="the full multi-line output content",
        )
        assert e.output_content == "the full multi-line output content"

    def test_json_roundtrip_with_content(self):
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
            output_content="full body",
        )
        e2 = ExecutedEvent.model_validate_json(e.model_dump_json())
        assert e2.output_content == "full body"


class TestQAEvaluatedEventEnrichment:
    def test_criteria_results_defaults_empty(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=True, score=1.0, reason="ok",
        )
        assert e.criteria_results == {}
        assert e.judge is None

    def test_carries_criteria_and_judge(self):
        jb = JudgeBreakdown(
            mode="rubric", overall=0.8,
            dimension_scores=[DimensionScore(name="clarity", score=0.8)],
            reason="clear",
        )
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=True, score=0.9, reason="ok",
            criteria_results={"non_empty": True, "min_length": True},
            judge=jb,
        )
        assert e.criteria_results["non_empty"] is True
        assert e.judge is not None
        assert e.judge.mode == "rubric"

    def test_json_roundtrip(self):
        jb = JudgeBreakdown(
            mode="reference_based", overall=0.5,
            dimension_scores=[], reason="meh",
        )
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=False, score=0.5, reason="x",
            criteria_results={"gate": False}, judge=jb,
        )
        e2 = QAEvaluatedEvent.model_validate_json(e.model_dump_json())
        assert e2.criteria_results == {"gate": False}
        assert e2.judge.mode == "reference_based"
