"""Preflight : vérifie que chaque model demandé (agents + rôles système) est
disponible dans son provider AVANT le run. Échec opaque mid-run -> erreur claire.

Fonction pure : ne mute rien, n'écrit rien. Interroge chaque provider distinct une
seule fois (cache local), agrège tous les problèmes en un seul PreflightError.
"""

from __future__ import annotations

from aaosa.config.role_providers import RoleProvider, RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider, ProviderUnreachableError


class PreflightError(Exception):
    """≥1 model absent ou ≥1 provider injoignable, détecté avant le run."""


def _role_items(roles: RoleProviders) -> list[tuple[str, RoleProvider]]:
    """(nom, RoleProvider) pour les 7 rôles système, ordre stable."""
    return [
        ("divider", roles.divider),
        ("aggregator", roles.aggregator),
        ("tagger", roles.tagger),
        ("evaluator", roles.evaluator),
        ("diagnostic", roles.diagnostic),
        ("triage", roles.triage),
        ("task_spec", roles.task_spec),
    ]


def preflight_models(
    agents: list[Agent],
    roles: RoleProviders,
    registry: dict[str, LLMProvider],
    default_provider_name: str,
) -> None:
    """Lève PreflightError si un model demandé est absent ou un provider injoignable."""
    # 1. (provider_name, model_résolu, source) pour chaque consommateur LLM.
    reqs: list[tuple[str, str, str]] = []
    problems: list[str] = []

    for a in agents:
        pname = a.provider or default_provider_name
        if pname not in registry:
            problems.append(f"  - agent {a.name!r}: provider {pname!r} not in registry")
            continue
        model = a.model or registry[pname].default_model
        reqs.append((pname, model, f"agent {a.name!r}"))

    for role_name, rp in _role_items(roles):
        pname = rp.provider or default_provider_name
        if pname not in registry:
            problems.append(f"  - role {role_name!r}: provider {pname!r} not in registry")
            continue
        model = rp.model or registry[pname].default_model
        reqs.append((pname, model, f"role {role_name!r}"))

    # 2. Disponibilité : un appel par provider distinct.
    available: dict[str, set[str]] = {}
    unreachable: dict[str, str] = {}
    for pname in {r[0] for r in reqs}:
        try:
            available[pname] = registry[pname].available_models()
        except ProviderUnreachableError as exc:
            unreachable[pname] = str(exc)

    # 3. Agrégation des problèmes.
    for pname in sorted(unreachable):
        problems.append(f"  - provider {pname!r} injoignable: {unreachable[pname]}")
    for pname, model, source in reqs:
        if pname in unreachable:
            continue  # déjà signalé au niveau provider
        if model not in available[pname]:
            problems.append(f"  - {source}: model {model!r} absent du provider {pname!r}")

    if problems:
        raise PreflightError(
            "Preflight model availability failed:\n" + "\n".join(problems)
        )
