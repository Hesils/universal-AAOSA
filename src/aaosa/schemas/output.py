from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict


class LLMMetadata(BaseModel):
    """Metadata about an LLM invocation."""

    model_config = ConfigDict(strict=True)

    model_name: str
    tokens_in: int
    tokens_out: int
    latency_ms: float


class Output(BaseModel):
    """Output from an agent processing a task."""

    task_id: str
    agent_id: str
    content: str
    llm_metadata: LLMMetadata
    timestamp: datetime = None

    def __init__(self, **data):
        if 'timestamp' not in data or data['timestamp'] is None:
            data['timestamp'] = datetime.now(timezone.utc)
        super().__init__(**data)
