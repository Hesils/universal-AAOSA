from dashboard.app import create_app
from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def test_create_app_instantiable(tmp_path):
    app = create_app(DashboardConfig(runs_root=tmp_path))
    assert app is not None
    assert app.config["AAOSA"].runs_root == tmp_path


def test_create_app_has_cache(tmp_path):
    app = create_app(DashboardConfig(runs_root=tmp_path))
    assert isinstance(app.config["CACHE"], Cache)


def test_create_app_default_config():
    app = create_app()
    assert app.config["AAOSA"].runs_root.name == "runs"


def test_runs_root_fixture_builds(runs_root):
    assert (runs_root / "agents" / "registry.json").exists()
    assert (runs_root / "sessions").is_dir()
    assert (runs_root / "health_checks").is_dir()
    assert list((runs_root / "elo_snapshots").glob("*.json"))
