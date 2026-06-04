import pytest
from aaosa.claiming.scoring import passes_filter, fit_score
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task


def make_agent(tags: dict) -> Agent:
    """Helper to create an Agent with the given tags_with_elo."""
    return Agent(name="TestAgent", tags_with_elo=tags, system_prompt=".")


# ============================================================================
# passes_filter tests (11 tests)
# ============================================================================

def test_passes_filter_required_tag_sufficient_elo():
    """Agent has required tag with sufficient ELO."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"python": 50})
    assert passes_filter(agent, task) is True


def test_passes_filter_required_tag_exact_threshold():
    """Agent meets exact ELO threshold (>= not >)."""
    agent = make_agent({"python": 50})
    task = Task(description="Test", required_tags={"python": 50})
    assert passes_filter(agent, task) is True


def test_passes_filter_required_tag_elo_below():
    """Agent ELO below required threshold fails."""
    agent = make_agent({"python": 49})
    task = Task(description="Test", required_tags={"python": 50})
    assert passes_filter(agent, task) is False


def test_passes_filter_required_tag_missing():
    """Required tag with high ELO missing from agent fails."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"css": 50})
    assert passes_filter(agent, task) is False


def test_passes_filter_acquirable_tag_missing_passes():
    """Acquirable tag missing from agent passes (only required_tags are checked)."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"python": 50}, acquirable_tags={"docker": 10})
    assert passes_filter(agent, task) is True


def test_passes_filter_acquirable_tag_only_missing_passes():
    """Task with only acquirable tag missing from agent passes."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"python": 50}, acquirable_tags={"tag_new": 20})
    assert passes_filter(agent, task) is True


def test_passes_filter_multiple_required_all_pass():
    """Multiple required tags, all with sufficient ELO."""
    agent = make_agent({"python": 80, "backend": 60})
    task = Task(description="Test", required_tags={"python": 50, "backend": 40})
    assert passes_filter(agent, task) is True


def test_passes_filter_multiple_required_one_elo_below():
    """One required tag has insufficient ELO."""
    agent = make_agent({"python": 80, "backend": 30})
    task = Task(description="Test", required_tags={"python": 50, "backend": 40})
    assert passes_filter(agent, task) is False


def test_passes_filter_multiple_required_one_missing():
    """One required tag (ELO > 25) missing from agent."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"python": 50, "backend": 40})
    assert passes_filter(agent, task) is False


def test_passes_filter_acquirable_agent_has_low_elo_passes():
    """Acquirable tag not checked by passes_filter regardless of agent ELO."""
    agent = make_agent({"python": 80, "docker": 5})
    task = Task(description="Test", required_tags={"python": 50}, acquirable_tags={"docker": 20})
    assert passes_filter(agent, task) is True


def test_passes_filter_returns_bool():
    """passes_filter returns a bool."""
    agent = make_agent({"python": 80})
    task = Task(description="Test", required_tags={"python": 50})
    result = passes_filter(agent, task)
    assert isinstance(result, bool)


# ============================================================================
# fit_score tests (7 tests)
# ============================================================================

def test_fit_score_single_tag_exact():
    """Single tag, agent ELO matches required ELO → 1.0."""
    agent = make_agent({"python": 50})
    task = Task(description="Test", required_tags={"python": 50})
    assert fit_score(agent, task) == 1.0


def test_fit_score_single_tag_double():
    """Single tag, agent ELO double required ELO → 2.0."""
    agent = make_agent({"python": 100})
    task = Task(description="Test", required_tags={"python": 50})
    assert fit_score(agent, task) == 2.0


def test_fit_score_multiple_tags_weighted():
    """Multiple tags with weighted calculation."""
    agent = make_agent({"python": 80, "backend": 60})
    task = Task(description="Test", required_tags={"python": 40, "backend": 60})
    # (80 + 60) / (40 + 60) = 140 / 100 = 1.4
    assert fit_score(agent, task) == 1.4


def test_fit_score_acquirable_tag_missing_no_penalty():
    """Acquirable tag the agent lacks is ignored: vrai bonus pur, aucune penalite (Gap 2).

    Lacking the acquirable tag doit donner le meme score qu'une tache sans ce tag.
    """
    agent = make_agent({"python": 60})
    with_acq = Task(description="Test", required_tags={"python": 50}, acquirable_tags={"docker": 10})
    without_acq = Task(description="Test", required_tags={"python": 50})
    # docker absent de l'agent -> non compte -> 60 / 50 = 1.2, identique a la tache sans docker
    assert fit_score(agent, with_acq) == 1.2
    assert fit_score(agent, with_acq) == fit_score(agent, without_acq)


def test_fit_score_acquirable_tag_present_improves():
    """Acquirable tag present in agent improves score."""
    agent = make_agent({"python": 60, "docker": 15})
    task = Task(description="Test", required_tags={"python": 50}, acquirable_tags={"docker": 10})
    # (60 + 15) / (50 + 10) = 75 / 60 = 1.25
    assert fit_score(agent, task) == 1.25


def test_fit_score_returns_float():
    """fit_score returns a float."""
    agent = make_agent({"python": 50})
    task = Task(description="Test", required_tags={"python": 50})
    result = fit_score(agent, task)
    assert isinstance(result, float)


def test_fit_score_all_required_no_acquirable_gte_1():
    """Agent meeting all required tags has fit_score >= 1.0."""
    agent = make_agent({"python": 80, "backend": 60})
    task = Task(description="Test", required_tags={"python": 50, "backend": 40})
    # (80 + 60) / (50 + 40) = 140 / 90 ≈ 1.556
    assert fit_score(agent, task) >= 1.0
