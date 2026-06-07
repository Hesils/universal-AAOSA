from datetime import datetime, timedelta, timezone
from pathlib import Path

from aaosa.cli.incident_runs import CampaignIndex, CampaignRunRecord
from aaosa.cli.report import build_report
from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot

_T0 = datetime(2026, 6, 7, 18, 0, 0, tzinfo=timezone.utc)


def _record(
    i: int,
    outcome: str = "success",
    typologies: list[str] | None = None,
    error: str | None = None,
    duration_s: float = 30.0,
) -> CampaignRunRecord:
    started = _T0 + timedelta(minutes=i)
    return CampaignRunRecord(
        i=i,
        session_id=None if outcome == "error" else f"sess-{i}",
        outcome=outcome,
        typologies=typologies if typologies is not None else ["divided"],
        started_at=started,
        ended_at=started + timedelta(seconds=duration_s),
        error=error,
    )


def _index(records: list[CampaignRunRecord], n_requested: int = 20) -> CampaignIndex:
    return CampaignIndex(scenario="main", n_requested=n_requested, runs=records)


def _snapshot(minute: int, elos: dict[str, dict[str, int]]) -> EloSnapshot:
    return EloSnapshot(
        timestamp=_T0 + timedelta(minutes=minute),
        agents=[
            AgentEloSnapshot(agent_name=name, agent_id=f"id-{name}", tags_with_elo=tags)
            for name, tags in elos.items()
        ],
    )


class TestHeader:
    def test_scenario_and_counts(self):
        text = build_report(_index([_record(1), _record(2)], n_requested=20), [])
        assert "`main`" in text
        assert "Runs demandés : 20" in text
        assert "Runs exécutés : 2" in text

    def test_period_from_first_start_to_last_end(self):
        text = build_report(_index([_record(1), _record(2)]), [])
        assert "2026-06-07T18:01:00+00:00" in text  # started_at du run 1
        assert "2026-06-07T18:02:30+00:00" in text  # ended_at du run 2

    def test_empty_runs_render_dash_period(self):
        text = build_report(_index([], n_requested=20), [])
        assert "Période : —" in text


class TestOutcomes:
    def test_counts_and_percentages_in_fixed_order(self):
        records = [
            _record(1, outcome="success"),
            _record(2, outcome="success"),
            _record(3, outcome="qa_fail"),
            _record(4, outcome="error", typologies=[], error="boom"),
        ]
        text = build_report(_index(records), [])
        assert "- success : 2/4 (50%)" in text
        assert "- qa_fail : 1/4 (25%)" in text
        assert "- unassigned : 0/4 (0%)" in text
        assert "- error : 1/4 (25%)" in text
        # ordre fixe : success avant qa_fail avant unassigned avant error
        assert text.index("- success :") < text.index("- qa_fail :")
        assert text.index("- qa_fail :") < text.index("- unassigned :")
        assert text.index("- unassigned :") < text.index("- error :")


class TestTypologies:
    def test_counts_zeros_included_canonical_order(self):
        records = [
            _record(1, typologies=["divided", "recursion"]),
            _record(2, typologies=["divided", "aggregated"]),
            _record(3, typologies=["simple"]),
        ]
        text = build_report(_index(records), [])
        assert "- simple : 1" in text
        assert "- divided : 2" in text
        assert "- recursion : 1" in text
        assert "- roster_gap : 0" in text
        assert "- diagnosed:agent : 0" in text
        assert "- aggregated : 1" in text
        # ordre canonique classify_run : simple < divided < recursion <
        # roster_gap < diagnosed:* < aggregated
        assert text.index("- simple :") < text.index("- divided :")
        assert text.index("- recursion :") < text.index("- roster_gap :")
        assert text.index("- diagnosed:agent :") < text.index("- diagnosed:evaluator :")
        assert text.index("- diagnosed:evaluator :") < text.index("- diagnosed:task_spec :")
        assert text.index("- diagnosed:task_spec :") < text.index("- diagnosed:unattributed :")
        assert text.index("- diagnosed:unattributed :") < text.index("- aggregated :")


class TestAggregatorObservation:
    def test_zero_states_criterion_not_met(self):
        text = build_report(_index([_record(1)]), [])
        assert "## Observation aggregator" in text
        assert "**0/1 runs avec `TaskAggregatedEvent` réel.**" in text
        assert "Critère du ticket divider non atteint" in text

    def test_nonzero_counts_aggregated_runs(self):
        records = [
            _record(1, typologies=["divided", "aggregated"]),
            _record(2, typologies=["divided"]),
        ]
        text = build_report(_index(records), [])
        assert "**1/2 runs avec `TaskAggregatedEvent` réel.**" in text
        assert "Critère du ticket divider non atteint" not in text


class TestRunsTable:
    def test_nominal_row(self):
        text = build_report(_index([_record(1, duration_s=42.5)]), [])
        assert "| 1 | sess-1 | success | divided | 42.5s |" in text

    def test_error_row_renders_dashes_and_error_note(self):
        records = [_record(1, outcome="error", typologies=[], error="boom failure")]
        text = build_report(_index(records), [])
        assert "| 1 | — | error | — |" in text
        assert "run 1 error : boom failure" in text

    def test_no_error_note_without_errors(self):
        # NB : ne pas asserter sur "error :" tout court — la section Outcomes
        # contient toujours une ligne "- error : 0/..." ; la note d'erreur par
        # run a la forme "run <i> error :".
        text = build_report(_index([_record(1)]), [])
        assert "run 1 error :" not in text


class TestEloDelta:
    def test_zero_snapshots_degraded(self):
        text = build_report(_index([_record(1)]), [])
        assert "_Delta indisponible (moins de 2 snapshots)._" in text

    def test_one_snapshot_degraded(self):
        snaps = [_snapshot(0, {"backend-dev": {"logs": 50}})]
        text = build_report(_index([_record(1)]), snaps)
        assert "_Delta indisponible (moins de 2 snapshots)._" in text

    def test_delta_first_to_last_sorted_by_agent_then_tag(self):
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}, "sre": {"infra": 60}}),
            _snapshot(1, {"backend-dev": {"logs": 55}, "sre": {"infra": 58}}),
            _snapshot(2, {"backend-dev": {"logs": 70}, "sre": {"infra": 64}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | logs | 50 | 70 | +20 |" in text
        assert "| sre | infra | 60 | 64 | +4 |" in text
        assert text.index("backend-dev") < text.index("| sre |")

    def test_snapshots_sorted_by_timestamp_not_input_order(self):
        snaps = [
            _snapshot(2, {"backend-dev": {"logs": 70}}),
            _snapshot(0, {"backend-dev": {"logs": 50}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | logs | 50 | 70 | +20 |" in text

    def test_tag_absent_from_first_snapshot_renders_nouveau(self):
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}}),
            _snapshot(1, {"backend-dev": {"logs": 52, "code": 51}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | code | — | 51 | nouveau |" in text


class TestReplaySection:
    def test_runs_root_in_replay_command(self):
        text = build_report(_index([_record(1)]), [], runs_root=Path("runs_campaign_n20"))
        assert "aaosa dashboard --runs-root runs_campaign_n20" in text

    def test_without_runs_root_placeholder(self):
        text = build_report(_index([_record(1)]), [])
        assert "aaosa dashboard --runs-root <runs-root>" in text


class TestDeterminismAndSections:
    def test_same_input_same_output(self):
        records = [_record(1), _record(2, outcome="error", typologies=[], error="x")]
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}}),
            _snapshot(1, {"backend-dev": {"logs": 55}}),
        ]
        assert build_report(_index(records), snaps) == build_report(_index(records), snaps)

    def test_all_seven_sections_present(self):
        text = build_report(_index([_record(1)]), [])
        assert "# Rapport de campagne" in text          # 1. en-tête
        assert "## Outcomes" in text                     # 2.
        assert "## Typologies" in text                   # 3.
        assert "## Observation aggregator" in text       # 4.
        assert "## Runs" in text                         # 5.
        assert "## Delta ELO" in text                    # 6.
        assert "## Rejeu" in text                        # 7.
