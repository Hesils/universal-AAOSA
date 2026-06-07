"""Tests des scénarios incident — données pures, zéro runtime."""

from aaosa.demo.incident.agents import INCIDENT_AGENTS
from aaosa.demo.incident.scenarios import (
    build_data_leak_task,
    full_roster,
    roster_gap_roster,
)
from aaosa.schemas.task import Task


class TestDataLeakTask:
    def test_task_well_formed(self):
        task = build_data_leak_task()
        assert isinstance(task, Task)
        assert task.required_tags == {"security": 70, "gdpr": 70, "communication": 65}
        assert task.context and task.context.strip()

    def test_fresh_task_each_call(self):
        assert build_data_leak_task().id != build_data_leak_task().id


class TestRosters:
    def test_full_roster_has_seven(self):
        roster = full_roster()
        assert len(roster) == 7
        assert set(a.name for a in roster) == set(a.name for a in INCIDENT_AGENTS)

    def test_full_roster_is_a_copy(self):
        roster = full_roster()
        assert roster is not INCIDENT_AGENTS
        roster.clear()
        assert len(INCIDENT_AGENTS) == 7

    def test_roster_gap_drops_only_dpo_jurist(self):
        gap = roster_gap_roster()
        assert len(gap) == 6
        assert "dpo-jurist" not in {a.name for a in gap}
        assert {a.name for a in full_roster()} - {a.name for a in gap} == {"dpo-jurist"}
