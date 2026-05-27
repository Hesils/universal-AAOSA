from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from aaosa.qa.health_check import run_health_check, HealthCheckReport, TestCase
from aaosa.qa.protocol import QAResult, QAFailure
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.tracing.tracer import Tracer


def make_agent(name: str = "A", elo: int = 80) -> Agent:
    return Agent(name=name, tags_with_elo={"python": elo}, system_prompt="test")


def make_task(required: dict[str, int] | None = None) -> Task:
    return Task(description="Test", required_tags=required or {"python": 50})


def make_claim(agent, task, decision="claim"):
    return Claim(agent_id=agent.id, task_id=task.id, decision=decision, justification="ok")


def make_output(agent, task, content="x" * 60 + " python"):
    return Output(
        task_id=task.id,
        agent_id=agent.id,
        content=content,
        llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
    )


class AlwaysPassEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id,
            agent_id=output.agent_id,
            success=True,
            score=1.0,
            reason="ok",
            criteria_results={},
        )


class AlwaysFailEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id,
            agent_id=output.agent_id,
            success=False,
            score=0.0,
            reason="bad",
            criteria_results={},
        )


class TestHealthCheckReport:
    def test_valid_report(self):
        r = HealthCheckReport(
            timestamp=datetime.now(timezone.utc),
            total_tasks=3,
            passed=2,
            failed=1,
            skipped=0,
            qa_results=[],
            qa_failures=[],
        )
        assert r.total_tasks == 3

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            HealthCheckReport(
                timestamp=datetime.now(timezone.utc),
                total_tasks=0,
                passed=0,
                failed=0,
                skipped=0,
                qa_results=[],
                qa_failures=[],
                extra="bad",
            )


class TestRunHealthCheck:
    def test_all_pass(self):
        """Toutes les taches passent leur QA respectif."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 1
        assert report.failed == 0
        assert report.total_tasks == 1
        assert len(report.qa_results) == 1
        assert report.qa_results[0].success is True

    def test_all_fail(self):
        """Toutes les taches echouent leur QA."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 0
        assert report.failed == 1
        assert len(report.qa_failures) == 1
        assert report.qa_failures[0].qa_result.success is False

    def test_different_evaluator_per_task(self):
        """Chaque tache utilise son propre evaluateur."""
        agent = make_agent("A", 80)
        t1 = make_task()
        t2 = make_task()
        test_suite: list[TestCase] = [
            (t1, AlwaysPassEvaluator()),
            (t2, AlwaysFailEvaluator()),
        ]
        claim1 = make_claim(agent, t1)
        claim2 = make_claim(agent, t2)
        output1 = make_output(agent, t1)
        output2 = make_output(agent, t2)
        with patch.object(Agent, "claim", side_effect=[claim1, claim2]):
            with patch.object(Agent, "execute", side_effect=[output1, output2]):
                report = run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 1
        assert report.failed == 1
        assert report.total_tasks == 2

    def test_unassigned_task_skipped(self):
        """Tache unassigned -> skipped, pas de QA."""
        agent = make_agent("A", 10)
        task = make_task({"python": 50})
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        report = run_health_check(
            agents=[agent],
            test_suite=test_suite,
            client=MagicMock(),
        )
        assert report.skipped == 1
        assert report.passed == 0
        assert report.failed == 0
        assert len(report.qa_results) == 0

    def test_no_elo_mutation(self):
        """Le health check ne mute PAS l'ELO des agents (succes)."""
        agent = make_agent("A", 80)
        task = make_task()
        elo_before = dict(agent.tags_with_elo)
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert agent.tags_with_elo == elo_before

    def test_no_elo_mutation_on_failure(self):
        """Le health check ne mute PAS l'ELO meme sur echec QA."""
        agent = make_agent("A", 80)
        task = make_task()
        elo_before = dict(agent.tags_with_elo)
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert agent.tags_with_elo == elo_before

    def test_empty_test_suite(self):
        """Test suite vide -> rapport vide."""
        agent = make_agent("A", 80)
        report = run_health_check(
            agents=[agent],
            test_suite=[],
            client=MagicMock(),
        )
        assert report.total_tasks == 0
        assert report.passed == 0
        assert report.qa_results == []

    def test_tracer_optional(self):
        """tracer=None ne cause pas d'erreur."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                    tracer=None,
                )
        assert isinstance(report, HealthCheckReport)

    def test_qa_failure_preserves_output(self):
        """QAFailure dans le rapport contient l'output rejete complet."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task, content="specific content for debugging")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.qa_failures[0].output.content == "specific content for debugging"

    def test_tracer_receives_qa_events(self):
        """Le tracer recoit les QAEvaluatedEvent du health check."""
        from aaosa.tracing.events import QAEvaluatedEvent

        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        tracer = Tracer(session_id="hc")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent],
                    test_suite=test_suite,
                    client=MagicMock(),
                    tracer=tracer,
                )
        qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
        assert len(qa_events) == 1
        assert qa_events[0].success is True
