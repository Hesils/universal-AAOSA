# tests/cli/test_solve_runs.py
import textwrap
from pathlib import Path

import pytest

from aaosa.cli.solve_runs import solve_once, SolveOutcome
from aaosa.runtime.tagger import EmptyTaggingError


class _FakeProvider:
    """Provider factice : parse() renvoie selon le schéma, complete() renvoie un message."""
    def __init__(self, content="done"):
        self._content = content
    def complete(self, *, messages, model=None, tools=None, **kwargs):
        class _Msg:
            def __init__(s, c): s.content = c; s.tool_calls = None
        class _Choice:
            def __init__(s, c): s.message = _Msg(c); s.finish_reason = "stop"
        class _Usage:
            prompt_tokens = 1; completion_tokens = 1
        class _Resp:
            model = "fake"; usage = _Usage()
            def __init__(s, c): s.choices = [_Choice(c)]
        return _Resp(self._content)
    def parse(self, *, messages, schema, model=None, **kwargs):
        # TagSet -> 1 tag matchant le roster ; Claim -> claim ; sinon best-effort
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


AGENTS_YAML = textwrap.dedent("""\
    - name: solo
      tags_with_elo: {python: 1500}
      system_prompt: You solve tasks.
""")


def _roster(dir: Path) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(AGENTS_YAML, encoding="utf-8")
    return dir


def _patch_provider(monkeypatch):
    import aaosa.cli.solve_runs as mod
    monkeypatch.setattr(mod, "build_provider_registry",
                        lambda agents, provider_name="ollama", roles=None: (_FakeProvider(), {provider_name: _FakeProvider()}))
    # preflight appelle available_models() sur le vrai registry -> no-op en test.
    monkeypatch.setattr(mod, "preflight_models", lambda agents, roles, registry, default_provider_name: None)
    # l'évaluateur LLM-judge ne doit pas tourner en test : forcer un evaluator None.
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda provider, failure_context=None, model=None: None)


def test_solve_once_produces_session_trace_and_manifest(tmp_path, monkeypatch):
    _patch_provider(monkeypatch)
    roster = _roster(tmp_path / "r")
    runs_root = tmp_path / "runs"
    outcome = solve_once([roster], "write a python function", context="# context: inline\nhello", runs_root=runs_root)
    assert isinstance(outcome, SolveOutcome)
    assert (outcome.session_dir / "trace.jsonl").exists()
    assert outcome.manifest_path.exists()
    assert outcome.manifest_path.name == "manifest.json"
    # mono-store ELO
    assert (runs_root / "elo_snapshots" / "latest.json").exists()


def test_solve_once_empty_tagging_raises(tmp_path, monkeypatch):
    import aaosa.cli.solve_runs as mod
    monkeypatch.setattr(mod, "build_provider_registry",
                        lambda agents, provider_name="ollama", roles=None: (_FakeProvider(), {}))
    monkeypatch.setattr(mod, "preflight_models", lambda agents, roles, registry, default_provider_name: None)
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda provider, failure_context=None, model=None: None)
    # tagger renvoie set() -> EmptyTaggingError
    monkeypatch.setattr("aaosa.runtime.tagger.Tagger.tag", lambda self, d, a, p, model=None: set())
    roster = _roster(tmp_path / "r")
    with pytest.raises(EmptyTaggingError):
        solve_once([roster], "ambiguous", context=None, runs_root=tmp_path / "runs")


def test_solve_once_raises_when_model_unavailable(tmp_path, monkeypatch):
    import aaosa.cli.solve_runs as sr
    from aaosa.runtime.preflight import PreflightError

    # Stub build_provider_registry to prevent real provider construction
    monkeypatch.setattr(sr, "build_provider_registry",
                        lambda agents, default_provider="ollama", roles=None: (object(), {}))

    def boom(agents, roles, registry, default_provider_name):
        raise PreflightError("Preflight model availability failed:\n  - agent 'x'")

    monkeypatch.setattr(sr, "preflight_models", boom)
    roster = _roster(tmp_path / "r")
    with pytest.raises(PreflightError):
        sr.solve_once([roster], "fais un truc", None, tmp_path / "runs", "ollama")


def _write_roster(dir: Path) -> None:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(
        textwrap.dedent(
            """
            - name: A
              tags_with_elo: {python: 80}
              system_prompt: You are A.
              tools: [ask_human]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_solve_once_injects_callback_into_agents_and_context(tmp_path, monkeypatch):
    from aaosa.cli import solve_runs
    from aaosa.core.hitl import ASK_HUMAN_TOOL_NAME

    roster = tmp_path / "r1"
    _write_roster(roster)

    seen = {}

    def fake_persisted_run(agents, runs_root, *, build_ctx, make_task):
        ctx = build_ctx(tracer=_FakeTracer())
        seen["agents"] = agents
        seen["ctx"] = ctx
        # On n'exécute pas le run réel : on inspecte le wiring.
        raise _StopForTest()

    class _StopForTest(Exception):
        pass

    class _FakeTracer:
        events = []

    # Court-circuite tout ce qui touche au provider/LLM en amont de _persisted_run.
    monkeypatch.setattr(solve_runs, "build_provider_registry",
                        lambda agents, name, roles: (object(), {}))
    monkeypatch.setattr(solve_runs, "preflight_models", lambda *a, **k: None)
    monkeypatch.setattr(solve_runs, "load_elo_into", lambda *a, **k: None)
    monkeypatch.setattr(solve_runs, "resolve_provider", lambda *a, **k: object())
    monkeypatch.setattr(solve_runs, "build_root_task", lambda text, ctx, context=None: object())
    monkeypatch.setattr(solve_runs, "_persisted_run", fake_persisted_run)

    cb = lambda q: "answer"
    try:
        solve_runs.solve_once([roster], "do it", None, tmp_path / "runs",
                              hitl_callback=cb)
    except _StopForTest:
        pass

    # 1) le tool ask_human a bien été injecté dans l'agent (built-ins fusionnés)
    assert any(t.name == ASK_HUMAN_TOOL_NAME for t in seen["agents"][0].tools)
    # 2) le callback est posé sur le RunContext (seam V2)
    assert seen["ctx"].hitl_callback is cb
