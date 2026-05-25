import pytest
from datetime import datetime
from pydantic import ValidationError
from aaosa.schemas.output import Output, LLMMetadata


VALID_METADATA = {
    "model_name": "gpt-4o",
    "tokens_in": 100,
    "tokens_out": 50,
    "latency_ms": 1234.5,
}


class TestLLMMetadata:
    """Tests for LLMMetadata nested model."""

    def test_llm_metadata_valid_creation(self):
        """Create LLMMetadata directly with all fields. Assert values are set correctly."""
        metadata = LLMMetadata(**VALID_METADATA)
        assert metadata.model_name == "gpt-4o"
        assert metadata.tokens_in == 100
        assert metadata.tokens_out == 50
        assert metadata.latency_ms == 1234.5

    def test_llm_metadata_tokens_must_be_int(self):
        """Pass tokens_in as string, expect ValidationError."""
        invalid_metadata = VALID_METADATA.copy()
        invalid_metadata["tokens_in"] = "fifty"
        with pytest.raises(ValidationError):
            LLMMetadata(**invalid_metadata)

    def test_llm_metadata_latency_must_be_float(self):
        """Pass latency_ms as string, expect ValidationError."""
        invalid_metadata = VALID_METADATA.copy()
        invalid_metadata["latency_ms"] = "fast"
        with pytest.raises(ValidationError):
            LLMMetadata(**invalid_metadata)


class TestOutput:
    """Tests for Output model."""

    def test_output_valid_creation(self):
        """Create a full valid Output with all fields including valid LLMMetadata."""
        output = Output(
            task_id="task-123",
            agent_id="agent-456",
            content="This is the LLM output.",
            llm_metadata=LLMMetadata(**VALID_METADATA),
        )
        assert output.task_id == "task-123"
        assert output.agent_id == "agent-456"
        assert output.content == "This is the LLM output."
        assert output.llm_metadata.model_name == "gpt-4o"
        assert isinstance(output.timestamp, datetime)

    def test_output_timestamp_auto_generated(self):
        """Create Output, assert timestamp is a datetime instance."""
        output = Output(
            task_id="task-789",
            agent_id="agent-101",
            content="Another output.",
            llm_metadata=LLMMetadata(**VALID_METADATA),
        )
        assert isinstance(output.timestamp, datetime)
        assert output.timestamp.tzinfo is not None  # Should be UTC

    def test_output_missing_task_id_raises(self):
        """Omit task_id, expect ValidationError."""
        with pytest.raises(ValidationError):
            Output(
                agent_id="agent-456",
                content="This is the LLM output.",
                llm_metadata=LLMMetadata(**VALID_METADATA),
            )

    def test_output_missing_agent_id_raises(self):
        """Omit agent_id, expect ValidationError."""
        with pytest.raises(ValidationError):
            Output(
                task_id="task-123",
                content="This is the LLM output.",
                llm_metadata=LLMMetadata(**VALID_METADATA),
            )

    def test_output_missing_content_raises(self):
        """Omit content, expect ValidationError."""
        with pytest.raises(ValidationError):
            Output(
                task_id="task-123",
                agent_id="agent-456",
                llm_metadata=LLMMetadata(**VALID_METADATA),
            )

    def test_output_missing_llm_metadata_raises(self):
        """Omit llm_metadata, expect ValidationError."""
        with pytest.raises(ValidationError):
            Output(
                task_id="task-123",
                agent_id="agent-456",
                content="This is the LLM output.",
            )
