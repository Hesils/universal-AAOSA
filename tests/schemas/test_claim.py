"""Tests for the Claim schema."""

import pytest
from datetime import datetime
from pydantic import ValidationError
from aaosa.schemas.claim import Claim


def test_claim_valid_claim_decision():
    """Create Claim with decision='claim', all other fields provided. Assert fields are set correctly."""
    claim = Claim(
        agent_id="agent-1",
        task_id="task-1",
        decision="claim",
        justification="Agent believes it can complete this task."
    )
    assert claim.agent_id == "agent-1"
    assert claim.task_id == "task-1"
    assert claim.decision == "claim"
    assert claim.justification == "Agent believes it can complete this task."
    assert isinstance(claim.timestamp, datetime)


def test_claim_valid_no_claim_decision():
    """Create Claim with decision='no_claim'. Assert decision == 'no_claim'."""
    claim = Claim(
        agent_id="agent-2",
        task_id="task-2",
        decision="no_claim",
        justification="Agent lacks required resources."
    )
    assert claim.decision == "no_claim"
    assert claim.agent_id == "agent-2"
    assert claim.task_id == "task-2"


def test_claim_timestamp_auto_generated():
    """Create Claim, assert timestamp is a datetime instance."""
    before = datetime.utcnow()
    claim = Claim(
        agent_id="agent-3",
        task_id="task-3",
        decision="claim",
        justification="Auto-generated timestamp test."
    )
    after = datetime.utcnow()

    assert isinstance(claim.timestamp, datetime)
    assert before <= claim.timestamp <= after


def test_claim_invalid_decision_raises():
    """Pass decision='maybe', expect ValidationError."""
    with pytest.raises(ValidationError):
        Claim(
            agent_id="agent-4",
            task_id="task-4",
            decision="maybe",
            justification="Invalid decision value."
        )


def test_claim_missing_agent_id_raises():
    """Omit agent_id, expect ValidationError."""
    with pytest.raises(ValidationError):
        Claim(
            task_id="task-5",
            decision="claim",
            justification="Missing agent_id."
        )


def test_claim_missing_task_id_raises():
    """Omit task_id, expect ValidationError."""
    with pytest.raises(ValidationError):
        Claim(
            agent_id="agent-5",
            decision="claim",
            justification="Missing task_id."
        )


def test_claim_missing_justification_raises():
    """Omit justification, expect ValidationError."""
    with pytest.raises(ValidationError):
        Claim(
            agent_id="agent-6",
            task_id="task-6",
            decision="claim"
        )


def test_claim_no_confidence_field():
    """Pass confidence=0.9 as extra kwarg, expect ValidationError (extra fields forbidden)."""
    with pytest.raises(ValidationError):
        Claim(
            agent_id="agent-7",
            task_id="task-7",
            decision="claim",
            justification="Trying to pass confidence field.",
            confidence=0.9
        )
