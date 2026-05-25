import pytest
from datetime import datetime
from pydantic import ValidationError
from aaosa.schemas.task import Task


def test_task_valid_creation():
    """Test instantiation of Task with required fields."""
    task = Task(description="Fix bug", required_tags={"python": 50})
    assert task.description == "Fix bug"
    assert task.required_tags == {"python": 50}
    assert task.id is not None
    assert task.metadata == {}
    assert isinstance(task.timestamp, datetime)


def test_task_id_auto_generated():
    """Test that id is auto-generated when not provided."""
    task = Task(description="Fix bug", required_tags={"python": 50})
    assert isinstance(task.id, str)
    assert len(task.id) > 0


def test_task_timestamp_auto_generated():
    """Test that timestamp is auto-generated when not provided."""
    task = Task(description="Fix bug", required_tags={"python": 50})
    assert isinstance(task.timestamp, datetime)


def test_task_metadata_defaults_empty():
    """Test that metadata defaults to empty dict when not provided."""
    task = Task(description="Fix bug", required_tags={"python": 50})
    assert task.metadata == {}


def test_task_required_tags_empty_raises():
    """Test that empty required_tags raises ValidationError."""
    with pytest.raises(ValidationError):
        Task(description="Fix bug", required_tags={})


def test_task_required_tags_wrong_value_type_raises():
    """Test that non-int values in required_tags raises ValidationError."""
    with pytest.raises(ValidationError):
        Task(description="Fix bug", required_tags={"python": "high"})


def test_task_description_required():
    """Test that description is required and omitting it raises ValidationError."""
    with pytest.raises(ValidationError):
        Task(required_tags={"python": 50})


def test_task_required_tags_required():
    """Test that required_tags is required and omitting it raises ValidationError."""
    with pytest.raises(ValidationError):
        Task(description="Fix bug")
