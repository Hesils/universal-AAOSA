import pytest
from aaosa.elo.updater import EloUpdateResult, update_agent_elo
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_FLOOR, ELO_CEILING


def make_agent(tags: dict[str, int], name: str = "TestAgent") -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt="test")


def make_task(required: dict[str, int], acquirable: dict[str, int] | None = None) -> Task:
    return Task(
        description="test task",
        required_tags=required,
        acquirable_tags=acquirable or {},
    )


class TestUpdateAgentEloSuccess:
    def test_success_single_tag(self):
        """Succes, 1 required tag. Delta positif, agent mute."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        # compute_delta(50, 50, True) = round(5 * 50/50) = 5
        assert result.deltas == {"python": 5}
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 55}
        assert agent.tags_with_elo["python"] == 55

    def test_success_multiple_tags(self):
        """Succes, 2 required tags. Both updated."""
        agent = make_agent({"python": 50, "backend": 80})
        task = make_task({"python": 50, "backend": 30})
        result = update_agent_elo(agent, task, success=True)
        # python: round(5 * 50/50) = 5 -> 55
        # backend: round(5 * 30/80) = round(1.875) = 2 -> 82
        assert result.deltas["python"] == 5
        assert result.deltas["backend"] == 2
        assert agent.tags_with_elo["python"] == 55
        assert agent.tags_with_elo["backend"] == 82

    def test_success_ceiling_clamp(self):
        """Succes qui pousserait au-dessus de 95 -> clampe a 95."""
        agent = make_agent({"python": 92})
        task = make_task({"python": 92})
        result = update_agent_elo(agent, task, success=True)
        # delta = 5, 92+5 = 97 -> clamp to 95
        assert agent.tags_with_elo["python"] == ELO_CEILING
        assert result.elo_after["python"] == ELO_CEILING


class TestUpdateAgentEloFailure:
    def test_failure_single_tag(self):
        """Echec, 1 required tag. Delta negatif, agent mute."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=False)
        # compute_delta(50, 50, False) = round(-5 * 50/50) = -5
        assert result.deltas == {"python": -5}
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 45}
        assert agent.tags_with_elo["python"] == 45

    def test_failure_floor_clamp(self):
        """Echec qui pousserait en dessous de 1 -> clampe a 1."""
        agent = make_agent({"python": 3})
        task = make_task({"python": 1})
        result = update_agent_elo(agent, task, success=False)
        # delta = round(-5 * 3/1) = -15, clampe a -10. 3 + (-10) = -7 -> floor = 1
        assert agent.tags_with_elo["python"] == ELO_FLOOR
        assert result.elo_after["python"] == ELO_FLOOR


class TestUpdateAgentEloAcquisition:
    def test_success_acquires_new_tag(self):
        """Succes + acquirable tag absent -> acquisition au level requis."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=True)
        assert "docker" in agent.tags_with_elo
        assert agent.tags_with_elo["docker"] == 20
        assert result.acquired_tags == {"docker": 20}

    def test_success_existing_acquirable_tag_updated(self):
        """Succes + acquirable tag deja present -> update normal (pas acquisition)."""
        agent = make_agent({"python": 50, "docker": 30})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=True)
        # docker: compute_delta(30, 20, True) = round(5 * 20/30) = round(3.33) = 3
        assert result.acquired_tags == {}
        assert result.deltas["docker"] == 3
        assert agent.tags_with_elo["docker"] == 33

    def test_failure_no_acquisition(self):
        """Echec + acquirable tag absent -> PAS d'acquisition, PAS de penalite."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=False)
        assert "docker" not in agent.tags_with_elo
        assert result.acquired_tags == {}
        assert "docker" not in result.deltas

    def test_failure_existing_acquirable_penalized(self):
        """Echec + acquirable tag present -> penalite normale (meme formule que required)."""
        agent = make_agent({"python": 50, "docker": 30})
        task = make_task({"python": 50}, acquirable={"docker": 20})
        result = update_agent_elo(agent, task, success=False)
        # python (required): compute_delta(50, 50, False) = -5 -> 45
        # docker (acquirable, present): compute_delta(30, 20, False) = round(-5 * 30/20) = round(-7.5) = -8 -> 22
        assert result.deltas["python"] == -5
        assert result.deltas["docker"] == -8
        assert agent.tags_with_elo["python"] == 45
        assert agent.tags_with_elo["docker"] == 22

    def test_failure_existing_acquirable_floor_clamp(self):
        """Echec + acquirable tag present avec ELO tres bas -> clampe au floor global (1)."""
        agent = make_agent({"python": 50, "docker": 3})
        task = make_task({"python": 50}, acquirable={"docker": 1})
        result = update_agent_elo(agent, task, success=False)
        # docker: compute_delta(3, 1, False) = round(-5 * 3/1) = -15 -> clamp -10. 3 + (-10) = -7 -> floor = 1
        assert agent.tags_with_elo["docker"] == ELO_FLOOR


class TestUpdateAgentEloMetadata:
    def test_elo_before_is_snapshot_before_mutation(self):
        """elo_before doit etre une copie AVANT mutation."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.elo_before == {"python": 50}
        assert result.elo_after == {"python": 55}

    def test_result_ids_match(self):
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.agent_id == agent.id
        assert result.task_id == task.id
        assert result.success is True

    def test_elo_before_is_independent_copy(self):
        """elo_before ne doit pas etre affecte par la mutation."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        agent.tags_with_elo["python"] = 999
        assert result.elo_before == {"python": 50}

    def test_no_acquirable_tags_field_empty(self):
        """Quand pas d'acquirable tags, acquired_tags est vide."""
        agent = make_agent({"python": 50})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert result.acquired_tags == {}

    def test_untouched_tags_not_in_deltas(self):
        """Tags de l'agent non references par la task ne sont pas dans deltas."""
        agent = make_agent({"python": 50, "css": 80})
        task = make_task({"python": 50})
        result = update_agent_elo(agent, task, success=True)
        assert "css" not in result.deltas
        assert agent.tags_with_elo["css"] == 80
