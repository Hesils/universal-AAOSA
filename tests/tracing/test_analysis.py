from datetime import datetime, timezone

import pytest

from aaosa.tracing.analysis import classify_run, detect_overclaims, detect_underclaims
from aaosa.tracing.events import (
    DiagnosedEvent,
    DividedSubTask,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)


class TestDetectOverclaims:
    """Test over-claim detection: fit_score < 1.0 in Phase1 + claim in Phase2."""

    def test_overclaim_detected_with_low_fit_score(self):
        """Over-claim: fit_score < 1.0 in Phase1 + claim in Phase2 → detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=0.8,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="claim",
            justification="I can handle this",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_overclaims(events)

        assert len(result) == 1
        assert result[0]["agent_id"] == "agent1"
        assert result[0]["task_id"] == "task1"
        assert result[0]["fit_score"] == 0.8
        assert result[0]["justification"] == "I can handle this"

    def test_no_overclaim_with_high_fit_score(self):
        """No over-claim: fit_score >= 1.0 in Phase1 + claim in Phase2 → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=1.0,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="claim",
            justification="I can handle this",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_overclaims(events)

        assert len(result) == 0

    def test_no_overclaim_with_low_fit_score_but_no_claim(self):
        """No over-claim: fit_score < 1.0 in Phase1 + no_claim in Phase2 → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=0.8,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="no_claim",
            justification="Too risky",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_overclaims(events)

        assert len(result) == 0

    def test_no_overclaim_without_phase1_event(self):
        """No over-claim: Phase2 claim without Phase1 event → not detected."""
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="claim",
            justification="I can handle this",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p2]
        result = detect_overclaims(events)

        assert len(result) == 0

    def test_overclaim_with_high_fit_score_not_detected(self):
        """No over-claim: fit_score > 1.0 in Phase1 + claim in Phase2 → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=1.5,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="claim",
            justification="I can handle this",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_overclaims(events)

        assert len(result) == 0


class TestDetectUnderclaims:
    """Test under-claim detection: passed=True in Phase1 + no_claim in Phase2."""

    def test_underclaim_detected_with_passed_true(self):
        """Under-claim: passed=True in Phase1 + no_claim in Phase2 → detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=1.2,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="no_claim",
            justification="Changed my mind",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_underclaims(events)

        assert len(result) == 1
        assert result[0]["agent_id"] == "agent1"
        assert result[0]["task_id"] == "task1"
        assert result[0]["fit_score"] == 1.2
        assert result[0]["justification"] == "Changed my mind"

    def test_no_underclaim_with_claim_decision(self):
        """No under-claim: passed=True in Phase1 + claim in Phase2 → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=1.2,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="claim",
            justification="I can handle this",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_underclaims(events)

        assert len(result) == 0

    def test_no_underclaim_with_passed_false(self):
        """No under-claim: passed=False in Phase1 + no_claim in Phase2 → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=False,
            fit_score=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            decision="no_claim",
            justification="I failed the filter",
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1, p2]
        result = detect_underclaims(events)

        assert len(result) == 0

    def test_no_underclaim_without_phase2_event(self):
        """No under-claim: Phase1 passed=True without Phase2 event → not detected."""
        p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agent1",
            passed=True,
            fit_score=1.2,
            timestamp=datetime.now(timezone.utc),
        )
        events = [p1]
        result = detect_underclaims(events)

        assert len(result) == 0


class TestEmptyEvents:
    """Test behavior with empty event lists."""

    def test_overclaims_empty_events(self):
        """Empty events → empty result."""
        result = detect_overclaims([])
        assert result == []

    def test_underclaims_empty_events(self):
        """Empty events → empty result."""
        result = detect_underclaims([])
        assert result == []


class TestMultiTaskCorrelation:
    """Test correct correlation by (task_id, agent_id) key across multiple tasks."""

    def test_overclaims_multiple_tasks(self):
        """Multiple tasks and agents are correctly keyed by (task_id, agent_id)."""
        # Task 1, Agent A: overclaim
        p1_t1a = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            passed=True,
            fit_score=0.7,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t1a = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            decision="claim",
            justification="Claim A",
            timestamp=datetime.now(timezone.utc),
        )

        # Task 2, Agent A: not overclaim (fit_score >= 1.0)
        p1_t2a = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentA",
            passed=True,
            fit_score=1.1,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t2a = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentA",
            decision="claim",
            justification="Claim A2",
            timestamp=datetime.now(timezone.utc),
        )

        # Task 1, Agent B: not overclaim (no_claim)
        p1_t1b = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentB",
            passed=True,
            fit_score=0.6,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t1b = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentB",
            decision="no_claim",
            justification="No claim B",
            timestamp=datetime.now(timezone.utc),
        )

        events = [p1_t1a, p2_t1a, p1_t2a, p2_t2a, p1_t1b, p2_t1b]
        result = detect_overclaims(events)

        # Only Task 1, Agent A should be detected as overclaim
        assert len(result) == 1
        assert result[0]["agent_id"] == "agentA"
        assert result[0]["task_id"] == "task1"
        assert result[0]["fit_score"] == 0.7

    def test_underclaims_multiple_tasks(self):
        """Multiple tasks and agents are correctly keyed by (task_id, agent_id)."""
        # Task 1, Agent A: underclaim
        p1_t1a = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            passed=True,
            fit_score=1.2,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t1a = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            decision="no_claim",
            justification="Underclaim A",
            timestamp=datetime.now(timezone.utc),
        )

        # Task 2, Agent A: not underclaim (decision=claim)
        p1_t2a = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentA",
            passed=True,
            fit_score=1.1,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t2a = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentA",
            decision="claim",
            justification="Claim A2",
            timestamp=datetime.now(timezone.utc),
        )

        # Task 1, Agent B: not underclaim (passed=False)
        p1_t1b = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentB",
            passed=False,
            fit_score=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        p2_t1b = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentB",
            decision="no_claim",
            justification="No claim B",
            timestamp=datetime.now(timezone.utc),
        )

        events = [p1_t1a, p2_t1a, p1_t2a, p2_t2a, p1_t1b, p2_t1b]
        result = detect_underclaims(events)

        # Only Task 1, Agent A should be detected as underclaim
        assert len(result) == 1
        assert result[0]["agent_id"] == "agentA"
        assert result[0]["task_id"] == "task1"
        assert result[0]["fit_score"] == 1.2

    def test_multiple_overclaims_and_underclaims_mixed(self):
        """Mixed scenario with both overclaims and underclaims."""
        # Overclaim: Agent A, Task 1
        oc_p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            passed=True,
            fit_score=0.7,
            timestamp=datetime.now(timezone.utc),
        )
        oc_p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task1",
            agent_id="agentA",
            decision="claim",
            justification="Overclaim A",
            timestamp=datetime.now(timezone.utc),
        )

        # Underclaim: Agent B, Task 2
        uc_p1 = Phase1FilteredEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentB",
            passed=True,
            fit_score=1.3,
            timestamp=datetime.now(timezone.utc),
        )
        uc_p2 = Phase2ClaimedEvent(
            session_id="sess1",
            task_id="task2",
            agent_id="agentB",
            decision="no_claim",
            justification="Underclaim B",
            timestamp=datetime.now(timezone.utc),
        )

        events = [oc_p1, oc_p2, uc_p1, uc_p2]

        overclaims = detect_overclaims(events)
        underclaims = detect_underclaims(events)

        assert len(overclaims) == 1
        assert overclaims[0]["task_id"] == "task1"
        assert overclaims[0]["agent_id"] == "agentA"

        assert len(underclaims) == 1
        assert underclaims[0]["task_id"] == "task2"
        assert underclaims[0]["agent_id"] == "agentB"


def _divided(task_id: str, sub_ids: list[str]) -> TaskDividedEvent:
    return TaskDividedEvent(
        session_id="sess1",
        task_id=task_id,
        sub_tasks=[DividedSubTask(id=i, description=f"sub {i}") for i in sub_ids],
    )


def _gap() -> RosterGapEvent:
    return RosterGapEvent(session_id="sess1", task_id="task1", missing_tags=["gdpr"])


def _diag(attribution: str) -> DiagnosedEvent:
    return DiagnosedEvent(
        session_id="sess1", task_id="task1", attribution=attribution, reason="r"
    )


def _agg() -> TaskAggregatedEvent:
    return TaskAggregatedEvent(
        session_id="sess1",
        task_id="task1",
        sub_task_ids=["s1", "s2"],
        output_summary="merged",
        output_content="merged content",
    )


class TestClassifyRun:
    """Typologies détectées depuis la trace, ordre canonique fixe (spec phase 4 §5)."""

    def test_empty_trace_is_simple(self):
        assert classify_run([]) == ["simple"]

    def test_claiming_events_alone_are_simple(self):
        p1 = Phase1FilteredEvent(
            session_id="sess1", task_id="task1", agent_id="a1",
            passed=True, fit_score=1.0,
        )
        assert classify_run([p1]) == ["simple"]

    def test_divided(self):
        assert classify_run([_divided("root", ["s1", "s2"])]) == ["divided"]

    def test_recursion_when_division_is_nested(self):
        # s1 est une sous-tâche de root ET le parent d'une autre division → D1 récursif
        events = [_divided("root", ["s1", "s2"]), _divided("s1", ["s1a", "s1b"])]
        assert classify_run(events) == ["divided", "recursion"]

    def test_sibling_divisions_are_not_recursion(self):
        events = [_divided("root-a", ["x"]), _divided("root-b", ["y"])]
        assert classify_run(events) == ["divided"]

    def test_roster_gap(self):
        assert classify_run([_gap()]) == ["simple", "roster_gap"]

    def test_diagnosed_one_label_per_distinct_attribution(self):
        # task_spec émis avant agent, agent en double → ordre canonique, dédupliqué
        events = [_diag("task_spec"), _diag("agent"), _diag("agent")]
        assert classify_run(events) == ["simple", "diagnosed:agent", "diagnosed:task_spec"]

    def test_aggregated(self):
        events = [_divided("root", ["s1", "s2"]), _agg()]
        assert classify_run(events) == ["divided", "aggregated"]

    def test_full_combination_canonical_order(self):
        # Events volontairement mélangés : l'ordre des labels ne dépend pas de la trace
        events = [
            _agg(),
            _diag("unattributed"),
            _gap(),
            _divided("root", ["s1", "s2"]),
            _divided("s1", ["s1a"]),
            _diag("evaluator"),
        ]
        assert classify_run(events) == [
            "divided",
            "recursion",
            "roster_gap",
            "diagnosed:evaluator",
            "diagnosed:unattributed",
            "aggregated",
        ]
