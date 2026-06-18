# tests/cli/test_solve_runs_roles.py
"""Tests TDD pour le câblage roles_path dans solve_once (Task 7 — u9l)."""
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aaosa.cli.solve_runs import SolveOutcome, solve_once
from aaosa.config.role_providers import RoleProviders
from aaosa.runtime.tagger import EmptyTaggingError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

AGENTS_YAML = textwrap.dedent("""\
    - name: solo
      tags_with_elo: {python: 1500}
      system_prompt: You solve tasks.
""")

ROLES_YAML_OPENAI_EVALUATOR = textwrap.dedent("""\
    evaluator:
      provider: openai
      model: gpt-4o
""")


class _FakeProvider:
    """Provider factice couvrant parse() et complete()."""

    def __init__(self, name: str = "fake"):
        self._name = name

    def complete(self, *, messages, model=None, tools=None, **kwargs):
        class _Msg:
            def __init__(s, c):
                s.content = c
                s.tool_calls = None

        class _Choice:
            def __init__(s, c):
                s.message = _Msg(c)
                s.finish_reason = "stop"

        class _Usage:
            prompt_tokens = 1
            completion_tokens = 1

        class _Resp:
            model = "fake"
            usage = _Usage()

            def __init__(s, c):
                s.choices = [_Choice(c)]

        return _Resp("done")

    def parse(self, *, messages, schema, model=None, **kwargs):
        from aaosa.runtime.tagger import TagSet
        from aaosa.schemas.claim import Claim

        if schema is TagSet:
            return TagSet(tags=["python"])
        if schema is Claim:
            return Claim(agent_id="x", task_id="y", decision="claim", justification="fit")
        try:
            return schema()
        except Exception:
            return None


def _make_roster(dir: Path) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(AGENTS_YAML, encoding="utf-8")
    return dir


def _make_roles_file(dir: Path, content: str = ROLES_YAML_OPENAI_EVALUATOR) -> Path:
    p = dir / "roles.yaml"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helpers de patching
# ---------------------------------------------------------------------------

def _fake_registry(provider_name: str, providers: dict | None = None):
    """Retourne (fake_provider, registry) selon les noms demandés."""
    if providers is None:
        providers = {}
    default = _FakeProvider(provider_name)
    registry = {provider_name: default}
    registry.update(providers)
    return default, registry


# ---------------------------------------------------------------------------
# Test 1 : solve_once avec roles_path -> l'évaluateur est construit sur le
#          bon provider/model issu du YAML roles.
# ---------------------------------------------------------------------------

def test_solve_once_roles_path_evaluator_uses_resolved_provider_and_model(tmp_path, monkeypatch):
    """Avec roles_path pointant un YAML {evaluator: {provider: openai, model: gpt-4o}},
    AdaptiveSpecEvaluator doit être construit avec le provider openai et model gpt-4o."""
    import aaosa.cli.solve_runs as mod

    roster = _make_roster(tmp_path / "r")
    roles_file = _make_roles_file(tmp_path)
    runs_root = tmp_path / "runs"

    openai_provider = _FakeProvider("openai")
    ollama_provider = _FakeProvider("ollama")

    constructed_evaluators: list[dict] = []

    def fake_build_registry(agents, provider_name="ollama", roles=None):
        # Simule: ollama=default, openai=dans le registry (parce que roles.evaluator.provider=openai)
        return ollama_provider, {"ollama": ollama_provider, "openai": openai_provider}

    def fake_adaptive_evaluator(client, failure_context=None, model=None):
        constructed_evaluators.append({"provider": client, "model": model})
        return None  # evaluator None = pas de run LLM en test

    monkeypatch.setattr(mod, "build_provider_registry", fake_build_registry)
    monkeypatch.setattr(mod, "preflight_models", lambda agents, roles, registry, default_provider_name: None)
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", fake_adaptive_evaluator)

    outcome = solve_once(
        [roster], "write a python function", context=None,
        runs_root=runs_root, roles_path=roles_file,
    )

    assert isinstance(outcome, SolveOutcome)
    # L'évaluateur doit avoir été construit avec openai (provider résolu) et model gpt-4o
    assert len(constructed_evaluators) >= 1
    eval_call = constructed_evaluators[0]
    assert eval_call["provider"] is openai_provider, (
        f"Expected openai provider, got {eval_call['provider']}"
    )
    assert eval_call["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Test 2 : solve_once sans roles_path -> comportement identique à avant.
# ---------------------------------------------------------------------------

def test_solve_once_without_roles_path_uses_default_provider(tmp_path, monkeypatch):
    """Sans roles_path, le comportement est identique au code pré-task-7 :
    AdaptiveSpecEvaluator reçoit le provider par défaut du run."""
    import aaosa.cli.solve_runs as mod

    roster = _make_roster(tmp_path / "r")
    runs_root = tmp_path / "runs"

    default_provider = _FakeProvider("ollama")
    constructed_evaluators: list[dict] = []

    def fake_build_registry(agents, provider_name="ollama", roles=None):
        return default_provider, {provider_name: default_provider}

    def fake_adaptive_evaluator(client, failure_context=None, model=None):
        constructed_evaluators.append({"provider": client, "model": model})
        return None

    monkeypatch.setattr(mod, "build_provider_registry", fake_build_registry)
    monkeypatch.setattr(mod, "preflight_models", lambda agents, roles, registry, default_provider_name: None)
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", fake_adaptive_evaluator)

    outcome = solve_once(
        [roster], "write a python function", context=None,
        runs_root=runs_root,
        # roles_path absent -> comportement originel
    )

    assert isinstance(outcome, SolveOutcome)
    assert len(constructed_evaluators) >= 1
    eval_call = constructed_evaluators[0]
    assert eval_call["provider"] is default_provider
    assert eval_call["model"] is None  # pas de modèle configuré


# ---------------------------------------------------------------------------
# Test 3 : solve_once avec roles_path -> le registry contient le provider du rôle évaluateur.
# ---------------------------------------------------------------------------

def test_solve_once_roles_path_registry_contains_evaluator_provider(tmp_path, monkeypatch):
    """Avec roles.evaluator.provider=openai, build_provider_registry doit être appelé
    avec les roles chargés afin que openai figure dans le registry."""
    import aaosa.cli.solve_runs as mod

    roster = _make_roster(tmp_path / "r")
    roles_file = _make_roles_file(tmp_path)
    runs_root = tmp_path / "runs"

    registry_calls: list[dict] = []

    def fake_build_registry(agents, provider_name="ollama", roles=None):
        registry_calls.append({"roles": roles, "provider_name": provider_name})
        p = _FakeProvider("ollama")
        return p, {provider_name: p}

    monkeypatch.setattr(mod, "build_provider_registry", fake_build_registry)
    monkeypatch.setattr(mod, "preflight_models", lambda agents, roles, registry, default_provider_name: None)
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda *a, **k: None)

    solve_once(
        [roster], "write a python function", context=None,
        runs_root=runs_root, roles_path=roles_file,
    )

    assert len(registry_calls) == 1
    roles_passed = registry_calls[0]["roles"]
    assert isinstance(roles_passed, RoleProviders)
    # Les roles chargés portent bien la config evaluator
    assert roles_passed.evaluator.provider == "openai"
    assert roles_passed.evaluator.model == "gpt-4o"


# ---------------------------------------------------------------------------
# Test 4 : roles_path invalide -> ValueError propagé (capturé en Exit(1) par le CLI).
# ---------------------------------------------------------------------------

def test_solve_once_invalid_roles_path_raises_value_error(tmp_path, monkeypatch):
    """Un roles_path inexistant doit lever ValueError."""
    import aaosa.cli.solve_runs as mod

    roster = _make_roster(tmp_path / "r")
    runs_root = tmp_path / "runs"

    monkeypatch.setattr(mod, "build_provider_registry",
                        lambda agents, provider_name="ollama", roles=None: (_FakeProvider(), {}))
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda *a, **k: None)

    with pytest.raises(ValueError, match="Cannot read"):
        solve_once(
            [roster], "write a python function", context=None,
            runs_root=runs_root, roles_path=tmp_path / "nonexistent.yaml",
        )
