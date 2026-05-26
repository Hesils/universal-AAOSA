import pytest
from datetime import datetime, timezone, timedelta

from aaosa.tracing.events import (
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
)
from aaosa.tracing.formatter import format_timeline, print_timeline


class TestFormatTimelinePhase1Filtered:
    """Test formatting Phase1FilteredEvent."""

    def test_phase1_filtered_passed(self):
        """Phase1FilteredEvent with passed=True should include fit score."""
        event = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_a",
            passed=True,
            fit_score=0.85,
            timestamp=datetime(2026, 5, 25, 10, 30, 45, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:45] PHASE1 agent_a -> passed (fit=0.85)" in result

    def test_phase1_filtered_not_passed(self):
        """Phase1FilteredEvent with passed=False should show 'filtered'."""
        event = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_b",
            passed=False,
            fit_score=0.3,
            timestamp=datetime(2026, 5, 25, 10, 30, 45, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:30:45] PHASE1 agent_b -> filtered" in result


class TestFormatTimelinePhase2Claimed:
    """Test formatting Phase2ClaimedEvent."""

    def test_phase2_claimed_short_justification(self):
        """Phase2ClaimedEvent with justification <= 50 chars should not truncate."""
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_c",
            decision="claim",
            justification="I have the skills",
            timestamp=datetime(2026, 5, 25, 10, 31, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:31:00] PHASE2 agent_c -> claim (I have the skills)" in result

    def test_phase2_claimed_long_justification(self):
        """Phase2ClaimedEvent with justification > 50 chars should truncate with ..."""
        long_justification = "A" * 51
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_d",
            decision="claim",
            justification=long_justification,
            timestamp=datetime(2026, 5, 25, 10, 31, 30, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:31:30] PHASE2 agent_d -> claim (AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...)" in result

    def test_phase2_claimed_no_claim_decision(self):
        """Phase2ClaimedEvent with decision='no_claim' should format correctly."""
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_e",
            decision="no_claim",
            justification="Not qualified",
            timestamp=datetime(2026, 5, 25, 10, 32, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:32:00] PHASE2 agent_e -> no_claim (Not qualified)" in result

    def test_phase2_claimed_exactly_50_chars(self):
        """Justification with exactly 50 chars should not be truncated."""
        just_50 = "A" * 50
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_f",
            decision="claim",
            justification=just_50,
            timestamp=datetime(2026, 5, 25, 10, 32, 30, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert f"({just_50})" in result
        assert "..." not in result


class TestFormatTimelineDispatched:
    """Test formatting DispatchedEvent."""

    def test_dispatched_event(self):
        """DispatchedEvent should format agent and reason."""
        event = DispatchedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_g",
            reason="only claimer",
            timestamp=datetime(2026, 5, 25, 10, 33, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:33:00] DISPATCH -> agent_g (only claimer)" in result


class TestFormatTimelineExecuted:
    """Test formatting ExecutedEvent."""

    def test_executed_short_output(self):
        """ExecutedEvent with output_summary <= 60 chars should not truncate."""
        event = ExecutedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_h",
            output_summary="Task completed successfully",
            timestamp=datetime(2026, 5, 25, 10, 33, 30, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:33:30] EXECUTED -> agent_h (Task completed successfully)" in result

    def test_executed_long_output(self):
        """ExecutedEvent with output_summary > 60 chars should truncate with ..."""
        long_output = "A" * 61
        event = ExecutedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_i",
            output_summary=long_output,
            timestamp=datetime(2026, 5, 25, 10, 34, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:34:00] EXECUTED -> agent_i (AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA...)" in result

    def test_executed_exactly_60_chars(self):
        """Output_summary with exactly 60 chars should not be truncated."""
        just_60 = "A" * 60
        event = ExecutedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_j",
            output_summary=just_60,
            timestamp=datetime(2026, 5, 25, 10, 34, 30, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert f"({just_60})" in result
        assert "..." not in result


class TestFormatTimelineUnassigned:
    """Test formatting UnassignedEvent."""

    def test_unassigned_event(self):
        """UnassignedEvent should format reason."""
        event = UnassignedEvent(
            session_id="s1",
            task_id="t1",
            reason="no agents claimed",
            timestamp=datetime(2026, 5, 25, 10, 35, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "[10:35:00] UNASSIGNED -> no agents claimed" in result


class TestFormatTimelineSorting:
    """Test that events are sorted by timestamp."""

    def test_events_out_of_order_sorted_correctly(self):
        """Events provided out of order should be sorted by timestamp."""
        e1 = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=0.9,
            timestamp=datetime(2026, 5, 25, 10, 30, 30, tzinfo=timezone.utc),
        )
        e2 = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a2",
            passed=False,
            fit_score=0.2,
            timestamp=datetime(2026, 5, 25, 10, 30, 0, tzinfo=timezone.utc),
        )
        e3 = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a3",
            passed=True,
            fit_score=0.8,
            timestamp=datetime(2026, 5, 25, 10, 31, 0, tzinfo=timezone.utc),
        )
        # Provide in non-chronological order: e1, e3, e2
        result = format_timeline([e1, e3, e2])
        lines = result.split("\n")
        assert len(lines) == 3
        # Should be sorted: e2 (10:30:00), e1 (10:30:30), e3 (10:31:00)
        assert "10:30:00" in lines[0]
        assert "10:30:30" in lines[1]
        assert "10:31:00" in lines[2]


class TestFormatTimelineEmpty:
    """Test formatting empty event list."""

    def test_empty_events_returns_empty_string(self):
        """format_timeline([]) should return empty string."""
        result = format_timeline([])
        assert result == ""

    def test_phase2_empty_justification_no_crash(self):
        """Phase2ClaimedEvent with justification='' should format without error."""
        event = Phase2ClaimedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_x",
            decision="claim",
            justification="",
            timestamp=datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "PHASE2 agent_x -> claim ()" in result

    def test_executed_empty_output_summary_no_crash(self):
        """ExecutedEvent with output_summary='' should format without error."""
        event = ExecutedEvent(
            session_id="s1",
            task_id="t1",
            agent_id="agent_y",
            output_summary="",
            timestamp=datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
        )
        result = format_timeline([event])
        assert "EXECUTED -> agent_y ()" in result


class TestFormatTimelineMixed:
    """Test formatting mixed event types."""

    def test_mixed_event_types_formatted_correctly(self):
        """A mix of all event types should format correctly."""
        events = [
            Phase1FilteredEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                passed=True,
                fit_score=0.9,
                timestamp=datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
            ),
            Phase2ClaimedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                decision="claim",
                justification="Ready",
                timestamp=datetime(2026, 5, 25, 10, 0, 1, tzinfo=timezone.utc),
            ),
            DispatchedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                reason="best scorer",
                timestamp=datetime(2026, 5, 25, 10, 0, 2, tzinfo=timezone.utc),
            ),
            ExecutedEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                output_summary="Done",
                timestamp=datetime(2026, 5, 25, 10, 0, 3, tzinfo=timezone.utc),
            ),
        ]
        result = format_timeline(events)
        lines = result.split("\n")
        assert len(lines) == 4
        assert "PHASE1" in lines[0]
        assert "PHASE2" in lines[1]
        assert "DISPATCH" in lines[2]
        assert "EXECUTED" in lines[3]


class TestPrintTimeline:
    """Test print_timeline convenience wrapper."""

    def test_print_timeline_prints_to_stdout(self, capsys):
        """print_timeline should print format_timeline output to stdout."""
        event = Phase1FilteredEvent(
            session_id="s1",
            task_id="t1",
            agent_id="a1",
            passed=True,
            fit_score=0.85,
            timestamp=datetime(2026, 5, 25, 10, 30, 45, tzinfo=timezone.utc),
        )
        print_timeline([event])
        captured = capsys.readouterr()
        assert "[10:30:45] PHASE1 a1 -> passed (fit=0.85)" in captured.out

    def test_print_timeline_empty_list(self, capsys):
        """print_timeline([]) should print empty line."""
        print_timeline([])
        captured = capsys.readouterr()
        assert captured.out == "\n"  # print() adds a newline

    def test_print_timeline_multiple_events(self, capsys):
        """print_timeline with multiple events should print all lines."""
        events = [
            Phase1FilteredEvent(
                session_id="s1",
                task_id="t1",
                agent_id="a1",
                passed=True,
                fit_score=0.9,
                timestamp=datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
            ),
            UnassignedEvent(
                session_id="s1",
                task_id="t1",
                reason="test reason",
                timestamp=datetime(2026, 5, 25, 10, 0, 1, tzinfo=timezone.utc),
            ),
        ]
        print_timeline(events)
        captured = capsys.readouterr()
        assert "PHASE1" in captured.out
        assert "UNASSIGNED" in captured.out
