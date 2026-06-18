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
    monkeypatch.setattr(mod, "AdaptiveSpecEvaluator", lambda provider, failure_context=None, model=None: None)
    # tagger renvoie set() -> EmptyTaggingError
    monkeypatch.setattr("aaosa.runtime.tagger.Tagger.tag", lambda self, d, a, p, model=None: set())
    roster = _roster(tmp_path / "r")
    with pytest.raises(EmptyTaggingError):
        solve_once([roster], "ambiguous", context=None, runs_root=tmp_path / "runs")
