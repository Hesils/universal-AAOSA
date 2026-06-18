# tests/demo/test_run_health_check_v3_roles.py
"""Tests TDD pour le câblage roles dans run_demo_health_check_v3 (Task 7 — u9l)."""
from pathlib import Path

import pytest

from aaosa.config.role_providers import RoleProvider, RoleProviders


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProvider:
    def __init__(self, name: str = "fake"):
        self._name = name

    def complete(self, *, messages, model=None, tools=None, **kwargs):
        class _Msg:
            content = "attributed: agent"
            tool_calls = None

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Usage:
            prompt_tokens = 1
            completion_tokens = 1

        class _Resp:
            model = "fake"
            usage = _Usage()
            choices = [_Choice()]

        return _Resp()

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


def _roles_with_triage_model(model: str) -> RoleProviders:
    """RoleProviders avec triage et task_spec configurés sur le modèle donné."""
    return RoleProviders(
        triage=RoleProvider(model=model),
        task_spec=RoleProvider(model=model),
    )


# ---------------------------------------------------------------------------
# Test 1 : run_demo_health_check_v3 accepte roles=None sans changement de comportement.
# ---------------------------------------------------------------------------

def test_run_health_check_v3_accepts_roles_none(monkeypatch):
    """roles=None -> comportement identique à avant (signature rétrocompatible)."""
    import aaosa.demo.run_health_check_v3 as mod

    called = {"n": 0}

    def fake_triage(test_set, provider, model=None):
        called["n"] += 1
        called["model"] = model
        return test_set

    def fake_fix(test_set, provider, model=None):
        called["fix_model"] = model
        return test_set

    monkeypatch.setattr(mod, "triage_unattributed", fake_triage)
    monkeypatch.setattr(mod, "fix_task_spec_cases", fake_fix)
    monkeypatch.setattr(mod, "run_health_check", lambda *a, **k: _make_fake_report())
    monkeypatch.setattr(mod, "save_health_check", lambda *a, **k: Path("x"))
    monkeypatch.setattr(mod, "create_provider", lambda *a, **k: _FakeProvider())

    mod.run_demo_health_check_v3(roles=None)

    # Sans roles -> model=None transmis aux deux fonctions
    assert called.get("model") is None
    assert called.get("fix_model") is None


# ---------------------------------------------------------------------------
# Test 2 : run_demo_health_check_v3 avec roles -> model relayé à triage/task_spec.
# ---------------------------------------------------------------------------

def test_run_health_check_v3_with_roles_relays_model(monkeypatch):
    """roles avec triage.model=gpt-4o-mini -> model='gpt-4o-mini' transmis à
    triage_unattributed et fix_task_spec_cases."""
    import aaosa.demo.run_health_check_v3 as mod

    triage_calls: list[dict] = []
    fix_calls: list[dict] = []

    def fake_triage(test_set, provider, model=None):
        triage_calls.append({"model": model})
        return test_set

    def fake_fix(test_set, provider, model=None):
        fix_calls.append({"model": model})
        return test_set

    monkeypatch.setattr(mod, "triage_unattributed", fake_triage)
    monkeypatch.setattr(mod, "fix_task_spec_cases", fake_fix)
    monkeypatch.setattr(mod, "run_health_check", lambda *a, **k: _make_fake_report())
    monkeypatch.setattr(mod, "save_health_check", lambda *a, **k: Path("x"))
    monkeypatch.setattr(mod, "create_provider", lambda *a, **k: _FakeProvider())

    roles = _roles_with_triage_model("gpt-4o-mini")
    mod.run_demo_health_check_v3(roles=roles)

    # Toutes les invocations de triage_unattributed reçoivent le bon model
    assert all(c["model"] == "gpt-4o-mini" for c in triage_calls), triage_calls
    # fix_task_spec_cases aussi
    assert all(c["model"] == "gpt-4o-mini" for c in fix_calls), fix_calls


# ---------------------------------------------------------------------------
# Test 3 : roles=None -> model=None par défaut (invariant rétrocompat strict).
# ---------------------------------------------------------------------------

def test_run_health_check_v3_roles_none_model_is_none(monkeypatch):
    """Sans roles, les deux fonctions reçoivent model=None — jamais une valeur surprise."""
    import aaosa.demo.run_health_check_v3 as mod

    triage_calls: list[dict] = []
    fix_calls: list[dict] = []

    def fake_triage(test_set, provider, model=None):
        triage_calls.append({"model": model})
        return test_set

    def fake_fix(test_set, provider, model=None):
        fix_calls.append({"model": model})
        return test_set

    monkeypatch.setattr(mod, "triage_unattributed", fake_triage)
    monkeypatch.setattr(mod, "fix_task_spec_cases", fake_fix)
    monkeypatch.setattr(mod, "run_health_check", lambda *a, **k: _make_fake_report())
    monkeypatch.setattr(mod, "save_health_check", lambda *a, **k: Path("x"))
    monkeypatch.setattr(mod, "create_provider", lambda *a, **k: _FakeProvider())

    # Appel sans argument roles -> défaut None
    mod.run_demo_health_check_v3()

    assert all(c["model"] is None for c in triage_calls)
    assert all(c["model"] is None for c in fix_calls)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fake_report():
    """Rapport minimal suffisant pour que run_demo_health_check_v3 ne crashe pas."""
    from datetime import datetime, timezone
    from aaosa.qa.health_check import HealthCheckReport, CaseResult

    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc),
        n_runs=3,
        total_cases=1,
        fix_target_pass_rate=1.0,
        regression_guard_pass_rate=1.0,
        unstable_cases=[],
        unattributed=[],
        task_spec_quarantined=[],
        evaluator_quarantined=[],
        case_results=[
            CaseResult(
                task_id="t1",
                role="fix_target",
                pass_count=3,
                n_runs=3,
                unstable=False,
                pass_rate=1.0,
                qa_results=[],
                qa_failures=[],
            ),
        ],
    )
