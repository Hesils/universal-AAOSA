"""Sandbox (v1m) — isolation FS par run + plancher de non-destruction.

Unique porte d'accès FS pour les tools d'agent (Monde B). Path jail : aucun
chemin ne sort de `root`. Plancher de non-destruction : `writable=False` par
défaut -> toute écriture lève SandboxViolation (enforce par construction, pas
une consigne au prompt). Doctrine reprise de night-guard-destructive-floor.
"""

from dataclasses import dataclass
from pathlib import Path


class SandboxViolation(Exception):
    """Accès hors racine, ou écriture sur une sandbox read-only."""


@dataclass(frozen=True)
class Sandbox:
    root: Path
    writable: bool = False

    @classmethod
    def for_reading(cls, root: Path) -> "Sandbox":
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise SandboxViolation(f"sandbox root is not a directory: {root}")
        return cls(root=resolved, writable=False)

    def resolve(self, rel_path: str) -> Path:
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(f"path escapes sandbox root: {rel_path!r}")
        return candidate

    def read_text(self, rel_path: str) -> str:
        return self.resolve(rel_path).read_text(encoding="utf-8")

    def write_text(self, rel_path: str, data: str) -> None:
        if not self.writable:
            raise SandboxViolation("sandbox is read-only: writes are disabled")
        target = self.resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
