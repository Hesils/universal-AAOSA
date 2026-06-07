from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_module
from aaosa.cli.app import app
from aaosa.cli.incident_runs import CampaignIndex, CampaignRunRecord, RunOutcome
from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot

runner = CliRunner()

_NOW = datetime.now(timezone.utc)


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

    def test_campaign_echoes_records_and_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())

        def stub(n, scenario, runs_root, client, on_run=None):
            records = [
                CampaignRunRecord(
                    i=1, session_id="sess-1", outcome="success",
                    typologies=["divided", "aggregated"],
                    started_at=_NOW, ended_at=_NOW,
                ),
                CampaignRunRecord(
                    i=2, session_id=None, outcome="error", typologies=[],
                    started_at=_NOW, ended_at=_NOW, error="boom",
                ),
                CampaignRunRecord(
                    i=3, session_id="sess-3", outcome="success",
                    typologies=["simple"],
                    started_at=_NOW, ended_at=_NOW,
                ),
            ]
            index = CampaignIndex(scenario=scenario, n_requested=n, runs=records)
            if on_run is not None:
                for record in records:
                    on_run(record)
            return index

        monkeypatch.setattr(app_module, "run_campaign", stub)
        result = runner.invoke(app, ["campaign", "--n", "3", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert "run 1/3: success ['divided', 'aggregated']" in result.output
        assert "run 2/3: error []" in result.output
        assert "2/3 success" in result.output


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


class TestReportCommand:
    def test_missing_index_exits_1_with_path(self, tmp_path):
        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 1
        assert "campaign_index.json" in result.output
        assert str(tmp_path) in result.output

    def _populate_store(self, tmp_path: Path) -> None:
        index = CampaignIndex(
            scenario="main",
            n_requested=1,
            runs=[
                CampaignRunRecord(
                    i=1, session_id="sess-1", outcome="success",
                    typologies=["divided"], started_at=_NOW, ended_at=_NOW,
                )
            ],
        )
        (tmp_path / "campaign_index.json").write_text(
            index.model_dump_json(indent=2), encoding="utf-8"
        )

    def test_nominal_writes_file_and_echoes(self, tmp_path):
        self._populate_store(tmp_path)

        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        report_path = tmp_path / "campaign_report.md"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "# Rapport de campagne" in content
        assert f"aaosa dashboard --runs-root {tmp_path}" in content
        assert "# Rapport de campagne" in result.output
        assert str(report_path) in result.output

    def test_snapshots_read_sorted_latest_excluded(self, tmp_path, monkeypatch):
        self._populate_store(tmp_path)
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir()
        # deux snapshots horodates + un latest.json (doit etre ignore :
        # meme regle que _elo_history du dashboard)
        for name, minute, elo in [
            ("2026-06-07T18-00-00.json", 0, 50),
            ("2026-06-07T18-05-00.json", 5, 60),
            ("latest.json", 5, 60),
        ]:
            snap = EloSnapshot(
                timestamp=_NOW + timedelta(minutes=minute),
                agents=[
                    AgentEloSnapshot(
                        agent_name="backend-dev",
                        agent_id="id-1",
                        tags_with_elo={"logs": elo},
                    )
                ],
            )
            (snap_dir / name).write_text(snap.model_dump_json(indent=2), encoding="utf-8")
        captured = {}
        real_build_report = app_module.build_report

        def spy(index, snapshots, runs_root=None):
            captured["n_snapshots"] = len(snapshots)
            return real_build_report(index, snapshots, runs_root=runs_root)

        monkeypatch.setattr(app_module, "build_report", spy)
        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["n_snapshots"] == 2  # latest.json exclu
        content = (tmp_path / "campaign_report.md").read_text(encoding="utf-8")
        assert "| backend-dev | logs | 50 | 60 | +10 |" in content
