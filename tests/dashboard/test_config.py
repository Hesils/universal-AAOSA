from pathlib import Path

import pytest

from dashboard.config import DashboardConfig


def test_defaults():
    c = DashboardConfig()
    assert c.runs_root == Path("runs")
    assert c.host == "127.0.0.1"
    assert c.port == 5001  # 5000 réservé au dashboard AIOS


def test_override():
    c = DashboardConfig(runs_root=Path("/tmp/x"), port=8080)
    assert c.runs_root == Path("/tmp/x")
    assert c.port == 8080


def test_extra_forbidden():
    with pytest.raises(Exception):
        DashboardConfig(unknown="x")
