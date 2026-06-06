from unittest.mock import MagicMock, patch

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import (
    DEMO_TASKS,
    TASK_FIX_CSS_HOVER,
    TASK_OPTIMIZE_SQL,
    TASK_SECURITY_AUDIT,
    TASK_WRITE_PYTHON_TESTS,
)
from aaosa.runtime.runner import run_task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import (
    DispatchedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    UnassignedEvent,
)
from aaosa.tracing.tracer import Tracer

_by_name = {a.name: a for a in DEMO_AGENTS}
AGENT_FRONTEND = _by_name["Frontend"]
AGENT_BACKEND = _by_name["Backend"]
AGENT_FULLSTACK = _by_name["Fullstack"]


def _make_claim(agent: Agent, task: Task, decision: str = "claim") -> Claim:
    return Claim(
        agent_id=agent.id,
        task_id=task.id,
        decision=decision,
        justification="Mock justification.",
    )


def _make_output(agent: Agent, task: Task) -> Output:
    return Output(
        task_id=task.id,
        agent_id=agent.id,
        content="Mock output content.",
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            latency_ms=50.0,
        ),
    )


class TestDemoTasksList:
    """Tests for DEMO_TASKS list structure and size."""

    def test_demo_tasks_list_length(self):
        """DEMO_TASKS should contain at least 6 tasks."""
        assert len(DEMO_TASKS) >= 6


class TestAllDemoTasksBasics:
    """Tests for basic properties of all tasks in DEMO_TASKS."""

    def test_all_demo_tasks_are_task_instances(self):
        """Every task in DEMO_TASKS should be a Task instance."""
        for task in DEMO_TASKS:
            assert isinstance(task, Task)

    def test_all_demo_tasks_have_non_empty_required_tags(self):
        """Every task should have at least one required tag."""
        for task in DEMO_TASKS:
            assert len(task.required_tags) >= 1

    def test_all_demo_tasks_have_description(self):
        """Every task should have a non-empty description string."""
        for task in DEMO_TASKS:
            assert isinstance(task.description, str)
            assert len(task.description) > 0

    def test_all_demo_tasks_have_unique_ids(self):
        """All task IDs in DEMO_TASKS should be unique."""
        ids = [task.id for task in DEMO_TASKS]
        assert len(ids) == len(set(ids))

    def test_tag_elo_values_are_valid_integers(self):
        """All tag ELO values should be integers in range [1, 100]."""
        for task in DEMO_TASKS:
            for value in task.required_tags.values():
                assert isinstance(value, int)
                assert 1 <= value <= 100


class TestSingleClaimTask:
    """Tests for single-claim task (TASK_FIX_CSS_HOVER)."""

    def test_single_claim_task_has_css_tag(self):
        """TASK_FIX_CSS_HOVER should have css tag with ELO >= 60."""
        assert "css" in TASK_FIX_CSS_HOVER.required_tags
        assert TASK_FIX_CSS_HOVER.required_tags["css"] >= 60


class TestMultiClaimTask:
    """Tests for multi-claim task (TASK_WRITE_PYTHON_TESTS)."""

    def test_multi_claim_task_has_multiple_tags(self):
        """TASK_WRITE_PYTHON_TESTS should have at least 2 required tags."""
        assert len(TASK_WRITE_PYTHON_TESTS.required_tags) >= 2


class TestNoClaimTask:
    """Tests for no-claim task with high ELO (TASK_SECURITY_AUDIT)."""

    def test_no_claim_task_has_high_elo(self):
        """TASK_SECURITY_AUDIT should have at least one tag with ELO >= 75."""
        assert max(TASK_SECURITY_AUDIT.required_tags.values()) >= 75


class TestUnderClaimTask:
    """Tests for under-claim task with low ELO (TASK_OPTIMIZE_SQL)."""

    def test_under_claim_task_has_low_elo(self):
        """TASK_OPTIMIZE_SQL should have all tags with ELO <= 50."""
        assert all(v <= 50 for v in TASK_OPTIMIZE_SQL.required_tags.values())


class TestDemoEndToEnd:
    """Tests end-to-end du pipeline run_task avec les fixtures demo et LLM mocké."""

    def test_css_hover_assigned_to_frontend(self):
        """TASK_FIX_CSS_HOVER : seul FRONTEND passe Phase 1 (css:90 >= 70).
        Mock claim + execute → Output avec agent_id == FRONTEND."""
        task = TASK_FIX_CSS_HOVER
        claim = _make_claim(AGENT_FRONTEND, task)
        output = _make_output(AGENT_FRONTEND, task)

        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, DEMO_AGENTS, MagicMock())

        assert isinstance(result, Output)
        assert result.agent_id == AGENT_FRONTEND.id

    def test_security_audit_unassigned(self):
        """TASK_SECURITY_AUDIT : aucun agent n'a le tag 'security' → 0 candidats.
        Pas de mock LLM nécessaire → DispatchResult status='unassigned'."""
        result = run_task(TASK_SECURITY_AUDIT, DEMO_AGENTS, MagicMock())

        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"

    def test_optimize_sql_backend_wins_over_fullstack(self):
        """TASK_OPTIMIZE_SQL : BACKEND (database:85, score=2.125) et FULLSTACK (database:40, score=1.0).
        Les deux clament. BACKEND gagne par fit_score → Output avec BACKEND.id."""
        task = TASK_OPTIMIZE_SQL
        claim_backend = _make_claim(AGENT_BACKEND, task)
        claim_fullstack = _make_claim(AGENT_FULLSTACK, task)
        output = _make_output(AGENT_BACKEND, task)

        # filter_candidates itère DEMO_AGENTS dans l'ordre → BACKEND avant FULLSTACK
        with patch.object(Agent, "claim", side_effect=[claim_backend, claim_fullstack]):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, DEMO_AGENTS, MagicMock())

        assert isinstance(result, Output)
        assert result.agent_id == AGENT_BACKEND.id

    def test_assigned_task_emits_tracer_events(self):
        """TASK_FIX_CSS_HOVER avec tracer : vérifier Phase1Filtered (1 passed=True pour FRONTEND),
        Phase2Claimed, Dispatched et Executed sont émis."""
        task = TASK_FIX_CSS_HOVER
        tracer = Tracer(session_id="test-e2e")
        claim = _make_claim(AGENT_FRONTEND, task)
        output = _make_output(AGENT_FRONTEND, task)

        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, DEMO_AGENTS, MagicMock(), tracer=tracer)

        event_types = {type(e) for e in tracer.events}
        assert Phase1FilteredEvent in event_types
        assert Phase2ClaimedEvent in event_types
        assert DispatchedEvent in event_types
        assert ExecutedEvent in event_types

        phase1_passed = [e for e in tracer.events if isinstance(e, Phase1FilteredEvent) and e.passed]
        assert len(phase1_passed) == 1
        assert phase1_passed[0].agent_id == AGENT_FRONTEND.id

    def test_unassigned_task_emits_unassigned_event(self):
        """TASK_SECURITY_AUDIT avec tracer : vérifier UnassignedEvent est émis."""
        tracer = Tracer(session_id="test-e2e")

        run_task(TASK_SECURITY_AUDIT, DEMO_AGENTS, MagicMock(), tracer=tracer)

        event_types = {type(e) for e in tracer.events}
        assert UnassignedEvent in event_types
