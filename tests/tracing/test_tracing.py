import pytest
import json
from datetime import datetime
from pathlib import Path
from pydantic import TypeAdapter, ValidationError

from aaosa.tracing.events import (
    ClaimEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
)
from aaosa.tracing.tracer import Tracer


class TestPhase1FilteredEventValid:
    """Test Phase1FilteredEvent instantiation with valid data."""

    def test_phase1_filtered_event_valid(self):
        event = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=0.85,
        )
        assert event.session_id == "s1"
        assert event.agent_id == "a1"
        assert event.passed is True
        assert event.fit_score == 0.85
        assert event.type == "phase1_filtered"
        assert isinstance(event.timestamp, datetime)


class TestPhase2ClaimedEventValid:
    """Test Phase2ClaimedEvent instantiation with valid data."""

    def test_phase2_claimed_event_valid(self):
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            decision="claim",
            justification="I qualify",
        )
        assert event.session_id == "s1"
        assert event.agent_id == "a1"
        assert event.decision == "claim"
        assert event.justification == "I qualify"
        assert event.type == "phase2_claimed"
        assert isinstance(event.timestamp, datetime)


class TestDispatchedEventValid:
    """Test DispatchedEvent instantiation with valid data."""

    def test_dispatched_event_valid(self):
        event = DispatchedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            reason="only claimer",
        )
        assert event.session_id == "s1"
        assert event.agent_id == "a1"
        assert event.reason == "only claimer"
        assert event.type == "dispatched"
        assert isinstance(event.timestamp, datetime)


class TestExecutedEventValid:
    """Test ExecutedEvent instantiation with valid data."""

    def test_executed_event_valid(self):
        event = ExecutedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            output_summary="Fixed the bug",
        )
        assert event.session_id == "s1"
        assert event.agent_id == "a1"
        assert event.output_summary == "Fixed the bug"
        assert event.type == "executed"
        assert isinstance(event.timestamp, datetime)


class TestUnassignedEventValid:
    """Test UnassignedEvent instantiation with valid data."""

    def test_unassigned_event_valid(self):
        event = UnassignedEvent(
            session_id="s1",
            task_id="t1",
            reason="no agents claimed",
        )
        assert event.session_id == "s1"
        assert event.reason == "no agents claimed"
        assert event.type == "unassigned"
        assert isinstance(event.timestamp, datetime)


class TestClaimEventUnionDiscrimination:
    """Test ClaimEvent discriminated union with TypeAdapter."""

    def test_claim_event_union_discriminates_phase1_filtered(self):
        ta = TypeAdapter(ClaimEvent)
        data = {
            "type": "phase1_filtered",
            "session_id": "s1",
            "task_id": "t1",
            "agent_id": "a1",
            "passed": True,
            "fit_score": 0.9,
        }
        result = ta.validate_python(data)
        assert isinstance(result, Phase1FilteredEvent)
        assert result.session_id == "s1"
        assert result.agent_id == "a1"
        assert result.passed is True
        assert result.fit_score == 0.9

    def test_claim_event_union_wrong_type_raises(self):
        ta = TypeAdapter(ClaimEvent)
        data = {
            "type": "unknown_event",
            "session_id": "s1",
        }
        with pytest.raises(ValidationError):
            ta.validate_python(data)


class TestExtraFieldsForbidden:
    """Test that extra fields are forbidden on concrete classes."""

    def test_extra_fields_forbidden_on_concrete_class(self):
        with pytest.raises(ValidationError):
            Phase1FilteredEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                passed=True,
                fit_score=0.9,
                extra_field="bad",
            )


class TestFieldTypes:
    """Test field type validation."""

    def test_phase1_filtered_fit_score_is_float(self):
        event = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=0.85,
        )
        assert isinstance(event.fit_score, float)


class TestInvalidEnumValues:
    """Test invalid enum values raise ValidationError."""

    def test_phase2_claimed_invalid_decision_raises(self):
        with pytest.raises(ValidationError):
            Phase2ClaimedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                decision="maybe",
                justification="x",
            )


class TestAutoTimestamp:
    """Test that all event types have auto-generated timestamps."""

    def test_all_events_have_auto_timestamp(self):
        events = [
            Phase1FilteredEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                passed=True,
                fit_score=0.85,
            ),
            Phase2ClaimedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                decision="claim",
                justification="I qualify",
            ),
            DispatchedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                reason="only claimer",
            ),
            ExecutedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                output_summary="Fixed the bug",
            ),
            UnassignedEvent(
                session_id="s1",
                task_id="t1",
                reason="no agents claimed",
            ),
        ]
        for event in events:
            assert isinstance(event.timestamp, datetime)


# Fixtures
@pytest.fixture
def tracer():
    return Tracer("test-session")


@pytest.fixture
def sample_event():
    return Phase1FilteredEvent(
        session_id="test-session",
        task_id="t1",
        agent_id="a1",
        passed=True,
        fit_score=1.2,
    )


# Tests for Tracer
class TestTracer:
    """Test Tracer class for event emission and JSONL serialization."""

    def test_tracer_instantiation(self, tracer):
        """Tracer("session-1") should not raise an error."""
        assert tracer is not None

    def test_tracer_session_id_stored(self, tracer):
        """tracer.session_id should equal the provided session_id."""
        assert tracer.session_id == "test-session"

    def test_tracer_events_initially_empty(self, tracer):
        """tracer.events should be an empty list on instantiation."""
        assert tracer.events == []

    def test_tracer_emit_one_event(self, tracer, sample_event):
        """After emit(event), len(tracer.events) should be 1."""
        tracer.emit(sample_event)
        assert len(tracer.events) == 1

    def test_tracer_emit_returns_none(self, tracer, sample_event):
        """tracer.emit(event) should return None."""
        result = tracer.emit(sample_event)
        assert result is None

    def test_tracer_events_contain_correct_type(self, tracer, sample_event):
        """After emit, tracer.events[0] should be an instance of Phase1FilteredEvent."""
        tracer.emit(sample_event)
        assert isinstance(tracer.events[0], Phase1FilteredEvent)

    def test_tracer_emit_preserves_order(self, tracer):
        """Emitting 3 events should preserve order: Phase1, Phase2, Dispatched."""
        e1 = Phase1FilteredEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=1.0,
        )
        e2 = Phase2ClaimedEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            decision="claim",
            justification="ok",
        )
        e3 = DispatchedEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            reason="only claimer",
        )
        tracer.emit(e1)
        tracer.emit(e2)
        tracer.emit(e3)
        assert isinstance(tracer.events[0], Phase1FilteredEvent)
        assert isinstance(tracer.events[1], Phase2ClaimedEvent)
        assert isinstance(tracer.events[2], DispatchedEvent)

    def test_tracer_flush_creates_file(self, tracer, sample_event, tmp_path):
        """After emit and flush, the file should exist."""
        tracer.emit(sample_event)
        output_file = tmp_path / "events.jsonl"
        tracer.flush(output_file)
        assert output_file.exists()

    def test_tracer_flush_writes_jsonl(self, tracer, sample_event, tmp_path):
        """Each line of the JSONL file should be valid JSON."""
        tracer.emit(sample_event)
        output_file = tmp_path / "events.jsonl"
        tracer.flush(output_file)
        with open(output_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    json.loads(line)  # Should not raise

    def test_tracer_flush_line_count_matches_events(self, tracer, tmp_path):
        """Emitting 3 events, flushing, and counting non-empty lines should equal 3."""
        e1 = Phase1FilteredEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=1.0,
        )
        e2 = Phase2ClaimedEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            decision="claim",
            justification="ok",
        )
        e3 = DispatchedEvent(
            session_id="test-session",
            task_id="t1",
            agent_id="a1",
            reason="only claimer",
        )
        tracer.emit(e1)
        tracer.emit(e2)
        tracer.emit(e3)
        output_file = tmp_path / "events.jsonl"
        tracer.flush(output_file)
        with open(output_file, "r") as f:
            line_count = sum(1 for line in f if line.strip())
        assert line_count == 3

    def test_tracer_flush_preserves_event_type(self, tracer, sample_event, tmp_path):
        """Reading JSONL, the type field should match the event type."""
        tracer.emit(sample_event)
        output_file = tmp_path / "events.jsonl"
        tracer.flush(output_file)
        with open(output_file, "r") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert data["type"] == "phase1_filtered"

    def test_tracer_flush_preserves_session_id(self, tracer, sample_event, tmp_path):
        """Reading JSONL, session_id should be present in the JSON."""
        tracer.emit(sample_event)
        output_file = tmp_path / "events.jsonl"
        tracer.flush(output_file)
        with open(output_file, "r") as f:
            line = f.readline().strip()
            data = json.loads(line)
            assert "session_id" in data

    def test_tracer_flush_jsonl_round_trip(self, tmp_path):
        """Flush → read JSONL → reconstruct via TypeAdapter → verify event fields."""
        from pydantic import TypeAdapter
        tracer = Tracer("round-trip-session")
        event = Phase2ClaimedEvent(
            session_id="round-trip-session",
            task_id="t-rt",
            agent_id="a-rt",
            decision="claim",
            justification="Round-trip test",
        )
        tracer.emit(event)
        output_file = tmp_path / "rt.jsonl"
        tracer.flush(output_file)

        ta = TypeAdapter(ClaimEvent)
        with open(output_file, "r", encoding="utf-8") as f:
            reconstructed = ta.validate_json(f.readline().strip())

        assert isinstance(reconstructed, Phase2ClaimedEvent)
        assert reconstructed.session_id == "round-trip-session"
        assert reconstructed.task_id == "t-rt"
        assert reconstructed.agent_id == "a-rt"
        assert reconstructed.decision == "claim"
