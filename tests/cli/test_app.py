from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_module
from aaosa.cli.app import app
from aaosa.cli.incident_runs import CampaignIndex, RunOutcome

runner = CliRunner()


def _fake_outcome(tmp_path: Path, kind: str = "success") -> RunOutcome:
    return RunOutcome(
        kind=kind,
        session_id="sess-1",
        session_dir=tmp_path / "sessions" / "sess-1",
        snapshot_path=tmp_path / "elo_snapshots" / "latest.json",
        events=[],
        task_description="incident task",
        n_agents=7,
    )


class TestRunCommand:
    def test_run_default_scenario_is_main(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(scenario, runs_root, client):
            captured["scenario"] = scenario
            captured["runs_root"] = runs_root
            return _fake_outcome(tmp_path)

        monkeypatch.setattr(app_module, "run_once", stub)
        result = runner.invoke(app, ["run", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["scenario"] == "main"
        assert captured["runs_root"] == tmp_path
        assert "success" in result.output

    def test_run_scenario_roster_gap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(scenario, runs_root, client):
            captured["scenario"] = scenario
            return _fake_outcome(tmp_path, kind="unassigned")

        monkeypatch.setattr(app_module, "run_once", stub)
        result = runner.invoke(
            app, ["run", "--scenario", "roster_gap", "--runs-root", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert captured["scenario"] == "roster_gap"

    def test_run_rejects_invalid_scenario(self):
        result = runner.invoke(app, ["run", "--scenario", "bogus"])
        assert result.exit_code == 2


class TestCampaignCommand:
    def test_n_is_required(self):
        result = runner.invoke(app, ["campaign"])
        assert result.exit_code == 2

    def test_n_zero_rejected(self):
        result = runner.invoke(app, ["campaign", "--n", "0"])
        assert result.exit_code == 2

    def test_guard_refuses_populated_store(self, tmp_path):
        (tmp_path / "sessions" / "2026-06-07T18-00-00-abcd1234").mkdir(parents=True)
        result = runner.invoke(app, ["campaign", "--n", "2", "--runs-root", str(tmp_path)])

        assert result.exit_code == 1
        assert str(tmp_path / "sessions") in result.output
        assert "--runs-root" in result.output

    def test_campaign_wires_run_campaign(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(n, scenario, runs_root, client, on_run=None):
            captured.update(n=n, scenario=scenario, runs_root=runs_root)
            return CampaignIndex(scenario=scenario, n_requested=n)

        monkeypatch.setattr(app_module, "run_campaign", stub)
        result = runner.invoke(app, ["campaign", "--n", "5", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["n"] == 5
        assert captured["scenario"] == "main"
        assert captured["runs_root"] == tmp_path


class _FakeServer:
    def __init__(self):
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs


class TestDashboardCommand:
    def test_defaults_are_config_defaults(self, monkeypatch):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard"])

        assert result.exit_code == 0
        assert captured["cfg"].port == 5001  # defaut DashboardConfig, inchange
        assert captured["cfg"].runs_root == Path("runs")
        assert server.kwargs == {"host": "127.0.0.1", "port": 5001, "debug": True}

    def test_port_override(self, monkeypatch):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard", "--port", "8123"])

        assert result.exit_code == 0
        assert captured["cfg"].port == 8123
        assert server.kwargs == {"host": "127.0.0.1", "port": 8123, "debug": True}

    def test_runs_root_override(self, monkeypatch, tmp_path):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["cfg"].runs_root == tmp_path
        assert captured["cfg"].port == 5001  # port par defaut preserve


class TestHealthCheckCommand:
    def test_wraps_run_demo_health_check_v3(self, monkeypatch):
        called = {"n": 0}

        def fake_health_check():
            called["n"] += 1

        monkeypatch.setattr(app_module, "run_demo_health_check_v3", fake_health_check)
        result = runner.invoke(app, ["health-check"])

        assert result.exit_code == 0
        assert called["n"] == 1
