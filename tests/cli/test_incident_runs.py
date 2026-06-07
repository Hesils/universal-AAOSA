from pathlib import Path

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.cli import incident_runs
from aaosa.cli.incident_runs import (
    CampaignIndex,
    RunOutcome,
    StoreNotEmptyError,
    _result_kind,
    ensure_empty_store,
    load_elo_into,
    run_campaign,
)
from aaosa.core.agent import Agent
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.tracing.events import DividedSubTask, TaskDividedEvent


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


class TestResultKind:
    """Mapping retour run_with_recovery -> vocabulaire d'index (review T4) :
    un échec QA non récupéré arrive en DispatchResult(status="qa_failed")."""

    def _output(self) -> Output:
        return Output(
            task_id="t1", agent_id="a1", content="done",
            llm_metadata=LLMMetadata(
                model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0
            ),
        )

    def test_output_is_success(self):
        assert _result_kind(self._output()) == "success"

    def test_dispatch_qa_failed_is_qa_fail(self):
        result = DispatchResult(status="qa_failed", agent_id=None, reason="qa")
        assert _result_kind(result) == "qa_fail"

    def test_qa_failure_is_qa_fail(self):
        output = self._output()
        failure = QAFailure(
            task_id="t1", agent_id="a1", output=output,
            qa_result=QAResult(
                task_id="t1", agent_id="a1", success=False, score=0.2,
                reason="too short", criteria_results={"non_empty": True},
            ),
        )
        assert _result_kind(failure) == "qa_fail"

    def test_dispatch_unassigned_is_unassigned(self):
        result = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        assert _result_kind(result) == "unassigned"

    def test_dispatch_roster_gap_is_unassigned(self):
        result = DispatchResult(status="roster_gap", agent_id=None, reason="gap")
        assert _result_kind(result) == "unassigned"


def _fake_outcome(i: int, tmp_path: Path, kind: str = "success", events=None) -> RunOutcome:
    return RunOutcome(
        kind=kind,
        session_id=f"sess-{i}",
        session_dir=tmp_path / "sessions" / f"sess-{i}",
        snapshot_path=tmp_path / "elo_snapshots" / "latest.json",
        events=list(events or []),
        task_description="incident task",
        n_agents=7,
    )


class TestRunCampaign:
    def test_runs_n_iterations_sequentially(self, tmp_path, monkeypatch):
        calls = []

        def stub(scenario, runs_root, client):
            calls.append((scenario, runs_root))
            return _fake_outcome(len(calls), tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert calls == [("main", tmp_path)] * 3
        assert index.scenario == "main"
        assert index.n_requested == 3
        assert [r.i for r in index.runs] == [1, 2, 3]
        assert [r.session_id for r in index.runs] == ["sess-1", "sess-2", "sess-3"]
        assert all(r.outcome == "success" for r in index.runs)

    def test_index_written_after_each_run(self, tmp_path, monkeypatch):
        # crash-safe : au début du run k, l'index sur disque contient k-1 entrées
        index_path = tmp_path / "campaign_index.json"
        runs_on_disk_at_start = []

        def stub(scenario, runs_root, client):
            if index_path.exists():
                on_disk = CampaignIndex.model_validate_json(
                    index_path.read_text(encoding="utf-8")
                )
                runs_on_disk_at_start.append(len(on_disk.runs))
            else:
                runs_on_disk_at_start.append(0)
            return _fake_outcome(len(runs_on_disk_at_start), tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert runs_on_disk_at_start == [0, 1, 2]
        on_disk = CampaignIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        assert on_disk == index

    def test_exception_recorded_as_error_and_loop_continues(self, tmp_path, monkeypatch):
        counter = {"n": 0}

        def stub(scenario, runs_root, client):
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("boom: tool loop exceeded")
            return _fake_outcome(counter["n"], tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert [r.outcome for r in index.runs] == ["success", "error", "success"]
        assert index.runs[1].session_id is None
        assert "boom" in index.runs[1].error
        assert index.runs[1].typologies == []

    def test_typologies_come_from_classify_run(self, tmp_path, monkeypatch):
        divided_event = TaskDividedEvent(
            session_id="s",
            task_id="root",
            sub_tasks=[DividedSubTask(id="s1", description="sub")],
        )

        def stub(scenario, runs_root, client):
            return _fake_outcome(1, tmp_path, events=[divided_event])

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(1, "main", tmp_path, client=None)

        assert index.runs[0].typologies == ["divided"]

    def test_on_run_callback_called_per_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            incident_runs,
            "run_once",
            lambda scenario, runs_root, client: _fake_outcome(1, tmp_path),
        )
        seen = []
        run_campaign(2, "main", tmp_path, client=None, on_run=lambda rec: seen.append(rec.i))
        assert seen == [1, 2]

    def test_qa_fail_outcome_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            incident_runs,
            "run_once",
            lambda scenario, runs_root, client: _fake_outcome(1, tmp_path, kind="qa_fail"),
        )
        index = run_campaign(1, "main", tmp_path, client=None)
        assert index.runs[0].outcome == "qa_fail"
