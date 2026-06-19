# tests/cli/test_solve_context_dir.py
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_mod
from aaosa.cli.app import app
from aaosa.cli.solve_runs import SolveOutcome

runner = CliRunner()


def _fake_outcome(tmp):
    sd = Path(tmp) / "sessions" / "s1"
    return SolveOutcome(
        kind="success", session_id="s1", session_dir=sd,
        snapshot_path=sd / "snap.json", manifest_path=sd / "manifest.json",
        events=[], task_description="do it", n_agents=1,
    )


def _roster(tmp_path) -> Path:
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8"
    )
    return d


def _ctxdir(tmp_path) -> Path:
    c = tmp_path / "vault"
    (c / "notes").mkdir(parents=True, exist_ok=True)
    (c / "notes" / "a.md").write_text("aaa", encoding="utf-8")
    (c / "b.py").write_text("bbb", encoding="utf-8")
    return c


def test_context_dir_injects_tree_with_provenance_header(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None):
        captured["context"] = context
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "do it",
        "--context-dir", str(c), "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert f"# context: tree of {c}\n" in captured["context"]
    assert "b.py" in captured["context"]
    assert "notes/a.md" in captured["context"]


def test_context_dir_combines_with_context_text(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None):
        captured["context"] = context
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-text", "inline-ctx", "--context-dir", str(c),
    ])
    assert result.exit_code == 0, result.output
    ctx = captured["context"]
    assert "# context: inline\ninline-ctx" in ctx
    assert f"# context: tree of {c}\n" in ctx
    assert ctx.index("inline-ctx") < ctx.index("tree of")  # ordre: text avant dir


def test_context_dir_overflow_refused(tmp_path, monkeypatch):
    called = {"n": 0}
    def fake_solve_once(*a, **k):
        called["n"] += 1
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    c = _ctxdir(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-dir", str(c), "--context-max", "5",
    ])
    assert result.exit_code == 1
    assert "too large" in result.output.lower()
    assert called["n"] == 0  # refus AVANT solve_once


def test_context_dir_invalid_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "solve_once", lambda *a, **k: _fake_outcome(tmp_path))
    missing = tmp_path / "nope"
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster(tmp_path)), "--task", "x",
        "--context-dir", str(missing),
    ])
    assert result.exit_code == 1
    assert "not found or not a directory" in result.output
