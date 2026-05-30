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
