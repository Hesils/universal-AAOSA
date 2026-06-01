from pathlib import Path

import yaml
from pydantic import ValidationError

from aaosa.core.agent import Agent


def load_agents(path: Path) -> list[Agent]:
    """Charge une liste d'agents depuis un fichier YAML.

    Chaque entrée YAML doit avoir : name, tags_with_elo, system_prompt.
    Le champ id est généré automatiquement (default_factory uuid4).
    Lève ValueError si le fichier est absent, malformé, ou invalide Pydantic.
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

    try:
        return [Agent(**entry) for entry in data]
    except (ValidationError, TypeError) as e:
        raise ValueError(f"Invalid agent definition in {path}: {e}") from e
