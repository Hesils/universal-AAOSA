"""Runner integration tests for role-based provider routing (Task 6 — u9l).

Tests that when RunContext.roles routes 'tagger' and 'divider' to separate fake
providers, the runner actually uses those fakes for the respective LLM calls.

Reuses the fake-provider pattern from test_runner_provider.py.
"""

from unittest.mock import MagicMock, patch, call as mock_call

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.config.role_providers import RoleProvider, RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.runner import run_with_recovery, build_root_task, build_sub_tasks
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_response(content: str = "done"):
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = content
    choice.message.tool_calls = None

    usage = MagicMock()
    usage.prompt_tokens = 5
    usage.completion_tokens = 3

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "test-model"
    return response


def _fake_provider(name: str = "fake") -> MagicMock:
    """MagicMock(spec=LLMProvider) with complete() and parse() wired."""
    m = MagicMock(spec=LLMProvider)
    m.complete.return_value = _make_response()
    m.__repr__ = lambda self: f"<FakeProvider {name}>"
    return m


def _agent(provider: str | None = None) -> Agent:
    return Agent(
        name="AgentPy",
        tags_with_elo={"python": 80},
        system_prompt="You are AgentPy.",
        provider=provider,
    )


def _claim(agent: Agent, task: Task) -> Claim:
    return Claim(agent_id=agent.id, task_id=task.id, decision="claim", justification="fits")


# ---------------------------------------------------------------------------
# Fake tagger that records calls (provider + model)
# ---------------------------------------------------------------------------

class _RecordingTagger:
    """Tagger fake that records (provider, model) of each call and returns a fixed tag set."""

    def __init__(self, tags=("python",)):
        self._tags = set(tags)
        self.calls: list[tuple] = []  # (provider, model)

    def tag(self, description: str, agents, provider, model=None):
        self.calls.append((provider, model))
        return set(self._tags)


# ---------------------------------------------------------------------------
# Fake divider that records calls
# ---------------------------------------------------------------------------

class _RecordingDivider:
    """Divider fake that records (provider, model) and returns a fixed single-subtask division."""

    def __init__(self, sub_descriptions=("sub-task",)):
        self._subs = [SubTaskSpec(description=d) for d in sub_descriptions]
        self.calls: list[tuple] = []  # (provider, model)

    def divide(self, task, provider, chained_context=None, failure_context=None,
               cycle_context=None, model=None):
        self.calls.append((provider, model))
        return DivisionResult(sub_tasks=list(self._subs))


# ---------------------------------------------------------------------------
# Fake aggregator
# ---------------------------------------------------------------------------

class _FakeAggregator:
    def aggregate(self, parent_task, sub_outputs, provider, tracer=None, model=None):
        return Output(
            task_id=parent_task.id, agent_id="aggregator", content="agg",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )


# ---------------------------------------------------------------------------
# Test 1 — build_root_task routes tagger call through tagger role
# ---------------------------------------------------------------------------

def test_build_root_task_uses_tagger_role():
    """When roles.tagger points to 'tagger_prov', build_root_task uses tagger_mock,
    not default_mock, and forwards the configured model."""
    default_mock = _fake_provider("default")
    tagger_mock = _fake_provider("tagger_prov")

    recording_tagger = _RecordingTagger(tags=("python",))

    roles = RoleProviders(tagger=RoleProvider(provider="tagger_prov", model="tag-model"))
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=_RecordingDivider(),
        aggregator=_FakeAggregator(),
        tagger=recording_tagger,
        provider_registry={"tagger_prov": tagger_mock},
        roles=roles,
    )

    task = build_root_task("write a function", ctx)

    assert len(recording_tagger.calls) == 1, "tagger should have been called once"
    called_provider, called_model = recording_tagger.calls[0]
    assert called_provider is tagger_mock, (
        f"expected tagger_mock, got {called_provider!r}"
    )
    assert called_model == "tag-model", f"expected 'tag-model', got {called_model!r}"


# ---------------------------------------------------------------------------
# Test 2 — build_sub_tasks routes tagger call through tagger role
# ---------------------------------------------------------------------------

def test_build_sub_tasks_uses_tagger_role():
    """build_sub_tasks calls ctx.tagger.tag with the tagger-role provider and model."""
    default_mock = _fake_provider("default")
    tagger_mock = _fake_provider("tagger_prov")

    recording_tagger = _RecordingTagger(tags=("python",))

    roles = RoleProviders(tagger=RoleProvider(provider="tagger_prov", model="tag-m"))
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=_RecordingDivider(),
        aggregator=_FakeAggregator(),
        tagger=recording_tagger,
        provider_registry={"tagger_prov": tagger_mock},
        roles=roles,
    )

    parent = Task(description="parent", required_tags={"python": 50})
    division = DivisionResult(sub_tasks=[SubTaskSpec(description="sub")])
    build_sub_tasks(parent, division, ctx)

    assert len(recording_tagger.calls) == 1
    called_provider, called_model = recording_tagger.calls[0]
    assert called_provider is tagger_mock, f"expected tagger_mock, got {called_provider!r}"
    assert called_model == "tag-m"


# ---------------------------------------------------------------------------
# Test 3 — divider gets its role provider on a divided run
# ---------------------------------------------------------------------------

def test_divided_run_uses_divider_role_provider():
    """A run that goes unassigned and falls through to division uses divider_mock,
    not default_mock, for the divider.divide() call."""
    default_mock = _fake_provider("default")
    divider_mock = _fake_provider("divider_prov")
    tagger_mock = _fake_provider("tagger_prov")

    recording_tagger = _RecordingTagger(tags=("python",))
    recording_divider = _RecordingDivider(sub_descriptions=("sub-one",))

    roles = RoleProviders(
        divider=RoleProvider(provider="divider_prov", model="div-model"),
        tagger=RoleProvider(provider="tagger_prov", model="tag-model"),
    )

    agent = _agent()
    ctx = RunContext(
        agents=[agent],
        provider=default_mock,
        divider=recording_divider,
        aggregator=_FakeAggregator(),
        tagger=recording_tagger,
        provider_registry={
            "divider_prov": divider_mock,
            "tagger_prov": tagger_mock,
        },
        roles=roles,
    )

    task = Task(description="do something", required_tags={"python": 50})
    claim = _claim(agent, task)

    # Force run_task to return 'unassigned' → division path kicked in
    with patch("aaosa.runtime.runner.run_task", return_value=DispatchResult(
        status="unassigned", agent_id=None, reason="no takers"
    )):
        # The sub-task produced by the divider will also be run_task'd;
        # patch it to return an Output for the sub-task
        sub_output = Output(
            task_id="ignored", agent_id="x", content="sub done",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )

        # We need the inner run_with_recovery (depth+1) to succeed.
        # Use side_effect: first call = unassigned (root), subsequent = output (sub)
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no takers")
        calls_iter = iter([unassigned, sub_output])

        with patch("aaosa.runtime.runner.run_task", side_effect=lambda *a, **k: next(calls_iter)):
            result = run_with_recovery(task, ctx, depth=0)

    # Division must have been invoked with divider_mock
    assert len(recording_divider.calls) >= 1, "divider must have been called"
    div_provider, div_model = recording_divider.calls[0]
    assert div_provider is divider_mock, (
        f"divider should use divider_mock, got {div_provider!r}"
    )
    assert div_model == "div-model", f"expected div-model, got {div_model!r}"

    # Tagger must have been invoked with tagger_mock for the sub-task tagging
    assert len(recording_tagger.calls) >= 1, "tagger must have been called"
    tag_provider, tag_model = recording_tagger.calls[0]
    assert tag_provider is tagger_mock, (
        f"tagger should use tagger_mock, got {tag_provider!r}"
    )
    assert tag_model == "tag-model", f"expected tag-model, got {tag_model!r}"


# ---------------------------------------------------------------------------
# Test 4 — retrocompat: no roles set → everything uses ctx.provider
# ---------------------------------------------------------------------------

def test_no_roles_all_use_default_provider():
    """RunContext without explicit roles uses ctx.provider for tagger and divider.
    Identical behavior to before Task 6."""
    default_mock = _fake_provider("default")

    recording_tagger = _RecordingTagger(tags=("python",))
    recording_divider = _RecordingDivider(sub_descriptions=("sub-one",))

    # No roles= → default_factory RoleProviders()
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=recording_divider,
        aggregator=_FakeAggregator(),
        tagger=recording_tagger,
    )

    parent = Task(description="parent", required_tags={"python": 50})
    division = DivisionResult(sub_tasks=[SubTaskSpec(description="sub")])
    build_sub_tasks(parent, division, ctx)

    assert len(recording_tagger.calls) == 1
    called_provider, called_model = recording_tagger.calls[0]
    assert called_provider is default_mock, (
        f"expected default_mock (no roles), got {called_provider!r}"
    )
    assert called_model is None
