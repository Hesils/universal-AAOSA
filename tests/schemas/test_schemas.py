"""Edge case tests for AAOSA schemas."""

import pytest
from datetime import datetime
from pydantic import ValidationError
from aaosa.schemas.task import Task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata


class TestTaskEdgeCases:
    """Edge case tests for Task schema."""

    def test_task_id_is_uuid_format(self):
        """Create a Task, verify task.id has len 36 and contains exactly 4 tirets."""
        task = Task(description="Fix bug", required_tags={"python": 50})
        assert len(task.id) == 36
        assert task.id.count("-") == 4

    def test_task_two_instances_have_different_ids(self):
        """Two Task with same args have different ids."""
        task1 = Task(description="Fix bug", required_tags={"python": 50})
        task2 = Task(description="Fix bug", required_tags={"python": 50})
        assert task1.id != task2.id

    def test_task_timestamp_is_timezone_aware(self):
        """task.timestamp.tzinfo is not None."""
        task = Task(description="Fix bug", required_tags={"python": 50})
        assert task.timestamp.tzinfo is not None

    def test_task_metadata_accepts_nested_dict(self):
        """metadata={'key': {'nested': True}} should not raise."""
        task = Task(
            description="Fix bug",
            required_tags={"python": 50},
            metadata={"key": {"nested": True}}
        )
        assert task.metadata == {"key": {"nested": True}}

    def test_task_extra_fields_forbidden(self):
        """Passing unknown kwarg (priority='high') raises ValidationError."""
        with pytest.raises(ValidationError):
            Task(
                description="Fix bug",
                required_tags={"python": 50},
                priority="high"
            )

    def test_task_required_tags_multiple_tags(self):
        """Dict with 3 tags is valid."""
        task = Task(
            description="Fix bug",
            required_tags={"python": 50, "ml": 30, "devops": 20}
        )
        assert len(task.required_tags) == 3
        assert task.required_tags["python"] == 50
        assert task.required_tags["ml"] == 30
        assert task.required_tags["devops"] == 20


class TestClaimEdgeCases:
    """Edge case tests for Claim schema."""

    def test_claim_timestamp_is_timezone_aware(self):
        """claim.timestamp.tzinfo is not None."""
        claim = Claim(
            agent_id="agent-1",
            task_id="task-1",
            decision="claim",
            justification="Testing"
        )
        assert claim.timestamp.tzinfo is not None


class TestOutputEdgeCases:
    """Edge case tests for Output schema."""

    def test_output_extra_fields_forbidden(self):
        """Passing unknown kwarg on Output raises ValidationError."""
        valid_metadata = LLMMetadata(
            model_name="gpt-4o",
            tokens_in=100,
            tokens_out=50,
            latency_ms=1234.5
        )
        with pytest.raises(ValidationError):
            Output(
                task_id="task-123",
                agent_id="agent-456",
                content="Test output",
                llm_metadata=valid_metadata,
                unknown_field="value"
            )


class TestLLMMetadataEdgeCases:
    """Edge case tests for LLMMetadata schema."""

    def test_llm_metadata_missing_model_name_raises(self):
        """Omitting model_name raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMMetadata(
                tokens_in=100,
                tokens_out=50,
                latency_ms=1234.5
            )

    def test_llm_metadata_negative_tokens_in_passes(self):
        """tokens_in=-1 is valid (no min constraint in schema)."""
        metadata = LLMMetadata(
            model_name="gpt-4o",
            tokens_in=-1,
            tokens_out=50,
            latency_ms=1234.5
        )
        assert metadata.tokens_in == -1
