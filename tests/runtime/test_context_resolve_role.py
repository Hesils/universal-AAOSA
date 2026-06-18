"""Tests for RunContext.roles + resolve_role (Task 6 — u9l).

RED phase: written before implementing resolve_role.

Scenarios:
1. Role with named provider → returns the fake from the registry + configured model.
2. Role with None provider (default RoleProvider) → returns ctx.provider, None.
3. Role with named provider absent from registry → fallback to ctx.provider.
4. All five roles (divider, tagger, aggregator, diagnostic, evaluator) resolve correctly.
5. RunContext built without explicit `roles` (default) → all roles fall back to ctx.provider.
"""

from unittest.mock import MagicMock

import pytest

from aaosa.config.role_providers import RoleProvider, RoleProviders
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.tagger import Tagger
from aaosa.runtime.providers import LLMProvider
from aaosa.core.agent import Agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_provider(name: str = "fake") -> MagicMock:
    m = MagicMock(spec=LLMProvider)
    m.__repr__ = lambda self: f"<FakeProvider {name}>"
    return m


def _agent() -> Agent:
    return Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")


def _ctx(roles: RoleProviders | None = None, registry: dict | None = None) -> RunContext:
    default_provider = _fake_provider("default")
    kwargs = dict(
        agents=[_agent()],
        provider=default_provider,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry=registry,
    )
    if roles is not None:
        kwargs["roles"] = roles
    return RunContext(**kwargs)


# ---------------------------------------------------------------------------
# Test 1 — role with named provider pointing to a known registry entry
# ---------------------------------------------------------------------------

def test_resolve_role_named_provider_returns_registry_entry():
    """divider role set to provider='openai' → resolve_role('divider') returns openai_mock."""
    openai_mock = _fake_provider("openai")
    default_mock = _fake_provider("default")

    roles = RoleProviders(divider=RoleProvider(provider="openai", model="gpt-4"))
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry={"openai": openai_mock},
        roles=roles,
    )

    prov, model = ctx.resolve_role("divider")
    assert prov is openai_mock, f"expected openai_mock, got {prov!r}"
    assert model == "gpt-4"


# ---------------------------------------------------------------------------
# Test 2 — role with None provider → ctx.provider, None
# ---------------------------------------------------------------------------

def test_resolve_role_unset_returns_default_provider():
    """Unset role (default RoleProvider, provider=None) → (ctx.provider, None)."""
    openai_mock = _fake_provider("openai")
    default_mock = _fake_provider("default")

    roles = RoleProviders()  # all roles have provider=None
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry={"openai": openai_mock},
        roles=roles,
    )

    prov, model = ctx.resolve_role("tagger")
    assert prov is default_mock, f"expected default_mock, got {prov!r}"
    assert model is None


# ---------------------------------------------------------------------------
# Test 3 — provider name not in registry → fallback to ctx.provider
# ---------------------------------------------------------------------------

def test_resolve_role_unknown_provider_falls_back_to_default():
    """Role provider name absent from registry → ctx.provider returned (no error)."""
    default_mock = _fake_provider("default")

    roles = RoleProviders(aggregator=RoleProvider(provider="gemini", model="gemini-pro"))
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry={"openai": _fake_provider("openai")},  # gemini absent
        roles=roles,
    )

    prov, model = ctx.resolve_role("aggregator")
    assert prov is default_mock, f"expected default_mock (fallback), got {prov!r}"
    # model is still returned as configured
    assert model == "gemini-pro"


# ---------------------------------------------------------------------------
# Test 4 — all five canonical roles resolve independently
# ---------------------------------------------------------------------------

def test_resolve_role_all_five_canonical_roles():
    """Each of the five roles (divider, tagger, aggregator, diagnostic, evaluator)
    resolves to its own fake provider and model."""
    fakes = {name: _fake_provider(name) for name in ["div", "tag", "agg", "diag", "eval"]}
    registry = dict(fakes)

    roles = RoleProviders(
        divider=RoleProvider(provider="div", model="m-div"),
        tagger=RoleProvider(provider="tag", model="m-tag"),
        aggregator=RoleProvider(provider="agg", model="m-agg"),
        diagnostic=RoleProvider(provider="diag", model="m-diag"),
        evaluator=RoleProvider(provider="eval", model="m-eval"),
    )
    default_mock = _fake_provider("default")
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry=registry,
        roles=roles,
    )

    expected = {
        "divider": ("div", "m-div"),
        "tagger": ("tag", "m-tag"),
        "aggregator": ("agg", "m-agg"),
        "diagnostic": ("diag", "m-diag"),
        "evaluator": ("eval", "m-eval"),
    }
    for role_name, (prov_name, expected_model) in expected.items():
        prov, model = ctx.resolve_role(role_name)
        assert prov is fakes[prov_name], (
            f"role '{role_name}': expected fake '{prov_name}', got {prov!r}"
        )
        assert model == expected_model, (
            f"role '{role_name}': expected model '{expected_model}', got {model!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — RunContext without explicit `roles` (default_factory) → all fallback
# ---------------------------------------------------------------------------

def test_resolve_role_default_roles_all_fallback():
    """RunContext built without 'roles' uses default_factory=RoleProviders().
    Every role resolves to (ctx.provider, None)."""
    default_mock = _fake_provider("default")
    openai_mock = _fake_provider("openai")

    # No `roles=` kwarg → default_factory kicks in
    ctx = RunContext(
        agents=[_agent()],
        provider=default_mock,
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
        provider_registry={"openai": openai_mock},
    )

    for role_name in ("divider", "tagger", "aggregator", "diagnostic", "evaluator"):
        prov, model = ctx.resolve_role(role_name)
        assert prov is default_mock, (
            f"role '{role_name}': expected default_mock, got {prov!r}"
        )
        assert model is None, (
            f"role '{role_name}': expected model=None, got {model!r}"
        )
