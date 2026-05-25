from pathlib import Path

from aaosa.tracing.events import ClaimEvent


class Tracer:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.events: list[ClaimEvent] = []

    def emit(self, event: ClaimEvent) -> None:
        self.events.append(event)

    def flush(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            for event in self.events:
                f.write(event.model_dump_json() + "\n")
