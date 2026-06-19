# tests/cli/test_app_solve.py
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


def test_solve_assembles_context_with_provenance_headers(tmp_path, monkeypatch):
    captured = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        captured["context"] = context
        captured["task"] = task_text
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    cfile = tmp_path / "ctx.txt"
    cfile.write_text("from-file", encoding="utf-8")
    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "do it",
        "--context-text", "inline-ctx", "--context-file", str(cfile),
        "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert "# context: inline\ninline-ctx" in captured["context"]
    assert f"# context: {cfile}\nfrom-file" in captured["context"]


def test_solve_refuses_context_overflow(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "solve_once", lambda *a, **k: _fake_outcome(tmp_path))
    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "x",
        "--context-text", "y" * 50, "--context-max", "10",
    ])
    assert result.exit_code == 1
    assert "too large" in result.output.lower()


def test_solve_empty_tagging_exits_1(tmp_path, monkeypatch):
    from aaosa.runtime.tagger import EmptyTaggingError
    def boom(*a, **k):
        raise EmptyTaggingError("no tags")
    monkeypatch.setattr(app_mod, "solve_once", boom)
    r = _roster(tmp_path)
    result = runner.invoke(app, ["solve", "--roster", str(r), "--task", "x"])
    assert result.exit_code == 1
    assert "tag" in result.output.lower()


def test_solve_command_exits_1_on_preflight_error(monkeypatch, tmp_path):
    import aaosa.cli.app as app_mod
    from aaosa.runtime.preflight import PreflightError

    def boom(*a, **k):
        raise PreflightError("Preflight model availability failed:\n  - agent 'x': model 'absent:99b' absent")

    monkeypatch.setattr(app_mod, "solve_once", boom)
    result = runner.invoke(
        app_mod.app,
        ["solve", "--roster", str(tmp_path), "--task", "t"],
    )
    assert result.exit_code == 1
    assert "Preflight model availability failed" in result.output


def test_solve_hitl_flag_passes_callback(tmp_path, monkeypatch):
    seen = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        seen["hitl_callback"] = hitl_callback
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    r = _roster(tmp_path)
    result = runner.invoke(app, ["solve", "--roster", str(r), "--task", "do it", "--hitl"])
    assert result.exit_code == 0, result.output
    assert callable(seen["hitl_callback"])


def test_solve_no_hitl_defaults_none(tmp_path, monkeypatch):
    seen = {}
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        seen["hitl_callback"] = hitl_callback
        return _fake_outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    r = _roster(tmp_path)
    result = runner.invoke(app, ["solve", "--roster", str(r), "--task", "do it"])
    assert result.exit_code == 0, result.output
    assert seen["hitl_callback"] is None


def _roster(tmp_path) -> Path:
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text("- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8")
    return d


def _outcome(tmp):
    sd = Path(tmp) / "s"
    return SolveOutcome(kind="success", session_id="s", session_dir=sd,
                        snapshot_path=sd / "snap.json", manifest_path=sd / "m.json",
                        events=[], task_description="t", n_agents=1)


def _roster2(tmp_path):
    d = tmp_path / "r2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n", encoding="utf-8")
    return d


def _ctx2(tmp_path):
    c = tmp_path / "ctx2"
    c.mkdir(parents=True, exist_ok=True)
    (c / "f.txt").write_text("hi", encoding="utf-8")
    return c


def test_fetch_max_forwarded_to_solve_once(tmp_path, monkeypatch):
    from aaosa.core.sandbox import SandboxViolation  # noqa: F401 (ensure importable)
    captured = {}
    def fake(*a, **k):
        captured.update(k)
        return _outcome(tmp_path)
    monkeypatch.setattr(app_mod, "solve_once", fake)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster2(tmp_path)), "--task", "t",
        "--context-dir", str(_ctx2(tmp_path)), "--fetch-max", "1234",
    ])
    assert result.exit_code == 0, result.output
    assert captured["context_dir"] == _ctx2(tmp_path)
    assert captured["fetch_max"] == 1234


def test_sandbox_violation_exits_1(tmp_path, monkeypatch):
    from aaosa.core.sandbox import SandboxViolation
    def boom(*a, **k):
        raise SandboxViolation("sandbox root is not a directory: x")
    monkeypatch.setattr(app_mod, "solve_once", boom)
    result = runner.invoke(app, [
        "solve", "--roster", str(_roster2(tmp_path)), "--task", "t",
        "--context-dir", str(_ctx2(tmp_path)),
    ])
    assert result.exit_code == 1
    assert "sandbox" in result.output.lower()
