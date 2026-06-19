# tests/cli/test_app_solve_roles.py
"""Tests TDD pour l'option --roles du CLI `aaosa solve` (Task 7 — u9l)."""
import textwrap
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_mod
from aaosa.cli.app import app
from aaosa.cli.solve_runs import SolveOutcome

runner = CliRunner()


def _fake_outcome(tmp_path: Path) -> SolveOutcome:
    sd = tmp_path / "sessions" / "s1"
    return SolveOutcome(
        kind="success", session_id="s1", session_dir=sd,
        snapshot_path=sd / "snap.json", manifest_path=sd / "manifest.json",
        events=[], task_description="do it", n_agents=1,
    )


def _roster(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agents.yaml").write_text(
        "- name: a\n  tags_with_elo: {x: 1500}\n  system_prompt: p\n",
        encoding="utf-8",
    )
    return d


def _roles_file(tmp_path: Path) -> Path:
    p = tmp_path / "roles.yaml"
    p.write_text(
        textwrap.dedent("""\
            evaluator:
              provider: openai
              model: gpt-4o
        """),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Test 1 : --roles est transmis à solve_once comme roles_path.
# ---------------------------------------------------------------------------

def test_solve_cli_roles_option_forwarded_to_solve_once(tmp_path, monkeypatch):
    """--roles <file> doit être transmis à solve_once(roles_path=...)."""
    captured = {}

    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        captured["roles_path"] = roles_path
        return _fake_outcome(tmp_path)

    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    r = _roster(tmp_path)
    roles = _roles_file(tmp_path)

    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "do it",
        "--roles", str(roles),
        "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert captured["roles_path"] == roles


# ---------------------------------------------------------------------------
# Test 2 : sans --roles, roles_path=None est transmis (rétrocompat).
# ---------------------------------------------------------------------------

def test_solve_cli_no_roles_option_passes_none(tmp_path, monkeypatch):
    """Sans --roles, roles_path doit être None (comportement inchangé)."""
    captured = {}

    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        captured["roles_path"] = roles_path
        return _fake_outcome(tmp_path)

    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "do it",
        "--runs-root", str(tmp_path / "runs"),
    ])
    assert result.exit_code == 0, result.output
    assert captured["roles_path"] is None


# ---------------------------------------------------------------------------
# Test 3 : --roles avec un fichier inexistant -> ValueError -> exit 1.
# ---------------------------------------------------------------------------

def test_solve_cli_invalid_roles_file_exits_1(tmp_path, monkeypatch):
    """Un roles file introuvable doit faire sortir avec code 1 via ValueError."""
    def fake_solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama",
                        roles_path=None, hitl_callback=None, **kwargs):
        raise ValueError(f"Cannot read role providers config at {roles_path}: ...")

    monkeypatch.setattr(app_mod, "solve_once", fake_solve_once)

    r = _roster(tmp_path)
    result = runner.invoke(app, [
        "solve", "--roster", str(r), "--task", "do it",
        "--roles", str(tmp_path / "nonexistent.yaml"),
    ])
    assert result.exit_code == 1
