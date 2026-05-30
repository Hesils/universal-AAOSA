import threading
from typing import Any, Callable


class Cache:
    """Cache on-demand : calcule au premier accès, mémorise. Pas de TTL, pas d'invalidation."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._data:
                self._data[key] = fn()
            return self._data[key]
