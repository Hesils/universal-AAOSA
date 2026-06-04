from pathlib import Path

from pydantic import BaseModel, ConfigDict


class DashboardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs_root: Path = Path("runs")
    host: str = "127.0.0.1"
    port: int = 5001
