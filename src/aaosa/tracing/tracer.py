from pathlib import Path
from typing import IO

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


class StreamingTracer(Tracer):
    """Tracer qui, en plus d'accumuler en mémoire, append chaque event à un
    trace.jsonl ouvert (flush par emit) — la session est observable en live par
    un autre process qui poll le fichier. Le Tracer de base reste pur en-mémoire.

    Le handle doit être fermé (close()) avant que save_session ne réécrive le
    fichier (lock Windows). close() est idempotent.
    """

    def __init__(self, session_id: str, stream_path: Path | None) -> None:
        super().__init__(session_id)
        self._stream_path = stream_path
        self._handle: IO[str] | None = None
        if stream_path is not None:
            stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = stream_path.open("w", encoding="utf-8")

    def emit(self, event: ClaimEvent) -> None:
        super().emit(event)
        if self._handle is not None:
            self._handle.write(event.model_dump_json() + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
