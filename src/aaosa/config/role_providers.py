from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RoleProvider(BaseModel):
    """Configuration pour un rôle LLM non-agent (divider, aggregator, etc.)."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None  # nom de provider (ollama|openai) ; None = défaut du run
    model: str | None = None  # None = modèle par défaut du provider


class RoleProviders(BaseModel):
    """Mapping de rôles LLM non-agents vers leurs configs provider/model."""

    model_config = ConfigDict(extra="forbid")

    divider: RoleProvider = Field(default_factory=RoleProvider)
    aggregator: RoleProvider = Field(default_factory=RoleProvider)
    tagger: RoleProvider = Field(default_factory=RoleProvider)
    evaluator: RoleProvider = Field(default_factory=RoleProvider)
    diagnostic: RoleProvider = Field(default_factory=RoleProvider)
    triage: RoleProvider = Field(default_factory=RoleProvider)
    task_spec: RoleProvider = Field(default_factory=RoleProvider)


def load_role_providers(path: Path | None) -> RoleProviders:
    """Charge un roles.yaml (mapping rôle -> {provider?, model?}).

    Comportement :
    - path=None → RoleProviders() vide (tous rôles RoleProvider()).
    - fichier absent + path explicite → ValueError.
    - YAML malformé → ValueError.
    - YAML non-mapping (liste, scalaire) → ValueError.
    - YAML vide (None après parse) → RoleProviders() vide.
    - rôle inconnu ou champ invalide → ValueError (extra="forbid" couvre ça).

    Args:
        path: Chemin vers roles.yaml, ou None pour comportement par défaut.

    Returns:
        RoleProviders peuplée selon le YAML.

    Raises:
        ValueError: Fichier absent, malformé, non-mapping, ou contient des rôles/champs invalides.
    """
    if path is None:
        return RoleProviders()

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Cannot read role providers config at {path}: {e}") from e

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"Malformed YAML in {path}: {e}") from e

    if data is None:
        return RoleProviders()

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping (dict) of roles in {path}, got {type(data).__name__}"
        )

    try:
        return RoleProviders(**data)
    except ValidationError as e:
        raise ValueError(f"Invalid role providers definition in {path}: {e}") from e
