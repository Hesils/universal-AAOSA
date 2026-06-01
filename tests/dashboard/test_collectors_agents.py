from aaosa.demo.agents import DEMO_AGENTS
from dashboard.collectors.agents import agent_detail, list_agents


def test_list_agents(runs_root):
    result = list_agents(runs_root)
    assert len(result.agents) == len(DEMO_AGENTS)
    assert DEMO_AGENTS[0].name in {a.name for a in result.agents}


def test_list_agents_empty(tmp_path):
    assert list_agents(tmp_path).agents == []


def test_agent_detail(runs_root):
    aid = DEMO_AGENTS[0].id
    view = agent_detail(runs_root, aid)
    assert view is not None
    assert view.system_prompt
    # deux snapshots -> chaque tag a deux points
    assert view.elo_history
    assert all(len(s.points) == 2 for s in view.elo_history)
    # a0 a claim + win + success sur t0 dans la session fixture
    assert view.activity.claims >= 1
    assert view.activity.wins >= 1
    assert view.activity.successes >= 1


def test_agent_detail_not_found(runs_root):
    assert agent_detail(runs_root, "nope") is None


def test_elo_history_matches_by_name_not_id(tmp_path):
    # Simule deux runs (process différents) : même agent_name, agent_id distincts.
    from datetime import datetime, timedelta, timezone

    from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot
    from aaosa.tracing.store import save_agent_registry

    root = tmp_path / "runs"
    root.mkdir()
    save_agent_registry(DEMO_AGENTS, root / "agents" / "registry.json")  # ids du run courant
    snap_dir = root / "elo_snapshots"
    snap_dir.mkdir()
    a0 = DEMO_AGENTS[0]
    base = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    for i, ts in enumerate([base, base + timedelta(hours=1)]):
        snap = EloSnapshot(
            timestamp=ts,
            agents=[AgentEloSnapshot(
                agent_name=a0.name,            # nom stable
                agent_id=f"stale-uuid-{i}",    # id != registry (run antérieur)
                tags_with_elo={"css": 90 + i},
            )],
        )
        (snap_dir / (ts.strftime("%Y-%m-%dT%H-%M-%S") + ".json")).write_text(
            snap.model_dump_json(), encoding="utf-8"
        )

    view = agent_detail(root, a0.id)
    assert view is not None
    css_series = next((s for s in view.elo_history if s.tag == "css"), None)
    assert css_series is not None and len(css_series.points) == 2  # matché par nom
