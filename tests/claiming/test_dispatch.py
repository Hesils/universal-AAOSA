"""Tests for the DispatchResult schema."""

import pytest
from pydantic import ValidationError
from aaosa.claiming.dispatch import DispatchResult
from aaosa.schemas.claim import Claim


def test_dispatch_result_valid_assigned():
    """Create DispatchResult with status='assigned', agent_id='agent-1', reason, claims and fit_scores. Assert all fields."""
    claim = Claim(
        agent_id="agent-1",
        task_id="t1",
        decision="claim",
        justification="I can do it"
    )
    result = DispatchResult(
        status="assigned",
        agent_id="agent-1",
        reason="only claimer",
        all_claims=[claim],
        fit_scores={"agent-1": 0.9}
    )
    assert result.status == "assigned"
    assert result.agent_id == "agent-1"
    assert result.reason == "only claimer"
    assert len(result.all_claims) == 1
    assert result.all_claims[0].agent_id == "agent-1"
    assert result.fit_scores == {"agent-1": 0.9}


def test_dispatch_result_valid_unassigned():
    """Create DispatchResult with status='unassigned', agent_id=None, reason. Assert agent_id is None and status='unassigned'."""
    result = DispatchResult(
        status="unassigned",
        agent_id=None,
        reason="no claims received"
    )
    assert result.status == "unassigned"
    assert result.agent_id is None
    assert result.reason == "no claims received"


def test_dispatch_result_defaults_empty_collections():
    """Provide only status, agent_id, reason. Assert all_claims and fit_scores default to empty collections."""
    result = DispatchResult(
        status="assigned",
        agent_id="a1",
        reason="x"
    )
    assert result.all_claims == []
    assert result.fit_scores == {}


def test_dispatch_result_all_claims_coerces_claim_dicts():
    """Pass all_claims as list of dicts (not Claim instances). Assert dicts are coerced to Claim."""
    result = DispatchResult(
        status="assigned",
        agent_id="a1",
        reason="test",
        all_claims=[
            {
                "agent_id": "a1",
                "task_id": "t1",
                "decision": "claim",
                "justification": "ok"
            }
        ]
    )
    assert len(result.all_claims) == 1
    assert isinstance(result.all_claims[0], Claim)
    assert result.all_claims[0].agent_id == "a1"


def test_dispatch_result_invalid_claim_in_list_raises():
    """Pass all_claims with invalid data dict. Expect ValidationError."""
    with pytest.raises(ValidationError):
        DispatchResult(
            status="assigned",
            agent_id="a1",
            reason="test",
            all_claims=[{"invalid": "data"}]
        )


def test_dispatch_result_fit_scores_values_are_floats():
    """Create DispatchResult with fit_scores dict. Assert all values are floats."""
    result = DispatchResult(
        status="assigned",
        agent_id="agent-1",
        reason="test",
        fit_scores={"agent-1": 0.75, "agent-2": 0.3}
    )
    assert all(isinstance(v, float) for v in result.fit_scores.values())
    assert result.fit_scores["agent-1"] == 0.75
    assert result.fit_scores["agent-2"] == 0.3


def test_dispatch_result_invalid_status_raises():
    """Pass status='pending' (invalid literal). Expect ValidationError."""
    with pytest.raises(ValidationError):
        DispatchResult(
            status="pending",
            agent_id="a1",
            reason="test"
        )


def test_dispatch_result_extra_fields_forbidden():
    """Pass extra kwarg (priority=1). Expect ValidationError."""
    with pytest.raises(ValidationError):
        DispatchResult(
            status="assigned",
            agent_id="a1",
            reason="test",
            priority=1
        )
