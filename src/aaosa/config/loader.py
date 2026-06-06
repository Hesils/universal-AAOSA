from pathlib import Path

import yaml
from pydantic import ValidationError

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef


def load_agents(path: Path, tool_registry: dict[str, ToolDef] | None = None) -> list[Agent]:
    """Charge une liste d'agents depuis un fichier YAML.

    Chaque entrée YAML doit avoir : name, tags_with_elo, system_prompt.
    Champ optionnel tools (liste de noms, list[str]) : résolu en list[ToolDef]
    via tool_registry. Le champ id est généré automatiquement (default_factory
    uuid4). Lève ValueError si le fichier est absent, malformé, invalide
    Pydantic, ou si un tool déclaré ne peut pas être résolu.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read agents config at {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML in {path}: {e}") from e

    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"Expected a YAML list of agents in {path}, got {type(data).__name__}")

    agents: list[Agent] = []
    for entry in data:
        if isinstance(entry, dict) and "tools" in entry:
            entry = {**entry}  # ne pas muter la structure YAML parsée
            entry["tools"] = _resolve_tools(entry.pop("tools"), tool_registry, entry.get("name"), path)
        try:
            agents.append(Agent(**entry))
        except (ValidationError, TypeError) as e:
            raise ValueError(f"Invalid agent definition in {path}: {e}") from e
    return agents


def _resolve_tools(
    names: object,
    registry: dict[str, ToolDef] | None,
    agent_name: object,
    path: Path,
) -> list[ToolDef]:
    """Résout les noms de tools d'une entrée YAML en ToolDef via le registry."""
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"Agent {agent_name!r} in {path}: 'tools' must be a list of strings")
    if len(names) != len(set(names)):
        raise ValueError(f"Agent {agent_name!r} in {path}: duplicate tool names in 'tools'")
    if not names:
        return []
    if registry is None:
        raise ValueError(
            f"Agent {agent_name!r} in {path} declares tools but no tool_registry was provided"
        )
    missing = [n for n in names if n not in registry]
    if missing:
        raise ValueError(
            f"Agent {agent_name!r} in {path}: unknown tool(s) {missing}; "
            f"available: {sorted(registry)}"
        )
    return [registry[n] for n in names]
