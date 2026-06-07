import pytest

from aaosa.cli.incident_runs import (
    StoreNotEmptyError,
    ensure_empty_store,
    load_elo_into,
)
from aaosa.core.agent import Agent
from aaosa.elo.persistence import save_snapshot


def _agent(name: str, tags: dict[str, int] | None = None) -> Agent:
    return Agent(
        name=name,
        system_prompt="system prompt",
        tags_with_elo=tags if tags is not None else {"security": 50},
    )


class TestEnsureEmptyStore:
    def test_missing_root_ok(self, tmp_path):
        ensure_empty_store(tmp_path / "fresh")  # ne lève pas

    def test_empty_sessions_dir_ok(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        ensure_empty_store(tmp_path)  # ne lève pas

    def test_populated_sessions_refused(self, tmp_path):
        (tmp_path / "sessions" / "2026-06-07T18-00-00-abcd1234").mkdir(parents=True)
        with pytest.raises(StoreNotEmptyError) as exc_info:
            ensure_empty_store(tmp_path)
        # le message nomme le chemin peuplé et suggère un root frais
        assert str(tmp_path / "sessions") in str(exc_info.value)
        assert "--runs-root" in str(exc_info.value)

    def test_other_store_content_does_not_trigger(self, tmp_path):
        # agents/ et elo_snapshots/ seuls ne déclenchent pas le garde-fou
        (tmp_path / "agents").mkdir()
        (tmp_path / "elo_snapshots").mkdir()
        ensure_empty_store(tmp_path)  # ne lève pas


class TestLoadEloInto:
    def test_absent_snapshot_leaves_elo_intact(self, tmp_path):
        agent = _agent("log-analyst", {"security": 50, "forensics": 40})
        assert load_elo_into([agent], tmp_path) is False
        assert agent.tags_with_elo == {"security": 50, "forensics": 40}

    def test_roundtrip_load_apply_on_fresh_roster(self, tmp_path):
        donor = _agent("log-analyst", {"security": 72, "forensics": 61})
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir(parents=True)
        save_snapshot([donor], snap_dir)

        fresh = _agent("log-analyst", {"security": 50, "forensics": 40})
        assert load_elo_into([fresh], tmp_path) is True
        assert fresh.tags_with_elo == {"security": 72, "forensics": 61}

    def test_snapshot_name_absent_from_roster_is_ignored(self, tmp_path):
        # cas roster_gap : dpo-jurist dans le snapshot, absent du roster → pas d'erreur
        donor = _agent("dpo-jurist", {"gdpr": 80})
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir(parents=True)
        save_snapshot([donor], snap_dir)

        fresh = _agent("log-analyst", {"security": 50})
        assert load_elo_into([fresh], tmp_path) is True
        assert fresh.tags_with_elo == {"security": 50}
