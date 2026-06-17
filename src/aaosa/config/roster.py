"""Chargement de rosters (dossiers agents.yaml + tools.py optionnel).

Convention tools.py : un symbole TOOL_REGISTRY: dict[str, ToolDef] (pas d'auto-scan).
Importé via importlib (exécution de code au load — hypothèse rosters de confiance, erd).
Registres cloisonnés par roster ; collision de noms d'agents = erreur dure (clé ELO = name).
"""

import importlib.util
from pathlib import Path

from aaosa.config.loader import load_agents
from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef


def _load_tool_registry(directory: Path) -> dict[str, ToolDef] | None:
    """Importe directory/tools.py et retourne son TOOL_REGISTRY, ou None si absent."""
    tools_path = directory / "tools.py"
    if not tools_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"_roster_tools_{directory.name}", tools_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load tools.py at {tools_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = getattr(module, "TOOL_REGISTRY", None)
    if registry is None:
        raise ValueError(f"tools.py at {tools_path} must expose a TOOL_REGISTRY dict[str, ToolDef]")
    if not isinstance(registry, dict) or not all(
        isinstance(k, str) and isinstance(v, ToolDef) for k, v in registry.items()
    ):
        raise ValueError(f"TOOL_REGISTRY in {tools_path} must be a dict[str, ToolDef]")
    return registry


def load_roster(directory: Path) -> list[Agent]:
    """Charge UN roster : agents.yaml résolu contre le TOOL_REGISTRY de son tools.py."""
    directory = Path(directory)
    agents_path = directory / "agents.yaml"
    if not agents_path.exists():
        raise ValueError(f"Roster {directory} is missing agents.yaml")
    registry = _load_tool_registry(directory)
    return load_agents(agents_path, registry)


def load_rosters(directories: list[Path]) -> list[Agent]:
    """Charge N rosters et fusionne. Collision de noms d'agents -> ValueError."""
    if not directories:
        raise ValueError("load_rosters requires at least one roster directory")
    merged: list[Agent] = []
    seen: dict[str, Path] = {}
    for d in directories:
        d = Path(d)
        for agent in load_roster(d):
            if agent.name in seen:
                raise ValueError(
                    f"Agent name collision: {agent.name!r} in {d} "
                    f"already loaded from {seen[agent.name]}"
                )
            seen[agent.name] = d
            merged.append(agent)
    return merged
