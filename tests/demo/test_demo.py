import pytest
from aaosa.schemas.task import Task
from aaosa.demo.tasks import (
    DEMO_TASKS,
    TASK_FIX_CSS_HOVER,
    TASK_WRITE_PYTHON_TESTS,
    TASK_SECURITY_AUDIT,
    TASK_OPTIMIZE_SQL,
)


class TestDemoTasksList:
    """Tests for DEMO_TASKS list structure and size."""

    def test_demo_tasks_list_length(self):
        """DEMO_TASKS should contain at least 6 tasks."""
        assert len(DEMO_TASKS) >= 6


class TestAllDemoTasksBasics:
    """Tests for basic properties of all tasks in DEMO_TASKS."""

    def test_all_demo_tasks_are_task_instances(self):
        """Every task in DEMO_TASKS should be a Task instance."""
        for task in DEMO_TASKS:
            assert isinstance(task, Task)

    def test_all_demo_tasks_have_non_empty_required_tags(self):
        """Every task should have at least one required tag."""
        for task in DEMO_TASKS:
            assert len(task.required_tags) >= 1

    def test_all_demo_tasks_have_description(self):
        """Every task should have a non-empty description string."""
        for task in DEMO_TASKS:
            assert isinstance(task.description, str)
            assert len(task.description) > 0

    def test_all_demo_tasks_have_unique_ids(self):
        """All task IDs in DEMO_TASKS should be unique."""
        ids = [task.id for task in DEMO_TASKS]
        assert len(ids) == len(set(ids))

    def test_tag_elo_values_are_valid_integers(self):
        """All tag ELO values should be integers in range [1, 100]."""
        for task in DEMO_TASKS:
            for value in task.required_tags.values():
                assert isinstance(value, int)
                assert 1 <= value <= 100


class TestSingleClaimTask:
    """Tests for single-claim task (TASK_FIX_CSS_HOVER)."""

    def test_single_claim_task_has_css_tag(self):
        """TASK_FIX_CSS_HOVER should have css tag with ELO >= 60."""
        assert "css" in TASK_FIX_CSS_HOVER.required_tags
        assert TASK_FIX_CSS_HOVER.required_tags["css"] >= 60


class TestMultiClaimTask:
    """Tests for multi-claim task (TASK_WRITE_PYTHON_TESTS)."""

    def test_multi_claim_task_has_multiple_tags(self):
        """TASK_WRITE_PYTHON_TESTS should have at least 2 required tags."""
        assert len(TASK_WRITE_PYTHON_TESTS.required_tags) >= 2


class TestNoClaimTask:
    """Tests for no-claim task with high ELO (TASK_SECURITY_AUDIT)."""

    def test_no_claim_task_has_high_elo(self):
        """TASK_SECURITY_AUDIT should have at least one tag with ELO >= 75."""
        assert max(TASK_SECURITY_AUDIT.required_tags.values()) >= 75


class TestUnderClaimTask:
    """Tests for under-claim task with low ELO (TASK_OPTIMIZE_SQL)."""

    def test_under_claim_task_has_low_elo(self):
        """TASK_OPTIMIZE_SQL should have all tags with ELO <= 50."""
        assert all(v <= 50 for v in TASK_OPTIMIZE_SQL.required_tags.values())
