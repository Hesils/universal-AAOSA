import pytest
from datetime import datetime
from pydantic import TypeAdapter, ValidationError

from aaosa.tracing.events import (
    ClaimEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
)


class TestPhase1FilteredEventValid:
    """Test Phase1FilteredEvent instantiation with valid data."""

    def test_phase1_filtered_event_valid(self):
        event = Phase1FilteredEvent(
            session_id="s1",
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
                agent_id="a1",
                passed=True,
                fit_score=0.85,
            ),
            Phase2ClaimedEvent(
                session_id="s1",
                agent_id="a1",
                decision="claim",
                justification="I qualify",
            ),
            DispatchedEvent(
                session_id="s1",
                agent_id="a1",
                reason="only claimer",
            ),
            ExecutedEvent(
                session_id="s1",
                agent_id="a1",
                output_summary="Fixed the bug",
            ),
            UnassignedEvent(
                session_id="s1",
                reason="no agents claimed",
            ),
        ]
        for event in events:
            assert isinstance(event.timestamp, datetime)
