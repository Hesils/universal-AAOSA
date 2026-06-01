from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field


class LLMMetadata(BaseModel):
    model_config = ConfigDict(strict=True)

    model_name: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    tool_calls_count: int = 0    # A5 — cumulé sur toute la boucle tool-use


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    content: str
    llm_metadata: LLMMetadata
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
