"""Construction du registre de providers d'un run `solve`.

Noms distincts = {default_provider} ∪ {a.provider for a in agents if a.provider}
                 ∪ {rp.provider for rp in roles.* if rp.provider} (si roles fourni).
create_provider lève déjà sur un nom != ollama|openai. Le registre câblé dans
RunContext.provider_registry active la résolution provider-par-agent (déjà codée
dans run_task). Défaut projet = ollama (gratuit).
"""

from __future__ import annotations

from aaosa.config.role_providers import RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.llm_client import create_provider
from aaosa.runtime.providers import LLMProvider


def resolve_provider(
    name: str | None,
    registry: dict[str, LLMProvider] | None,
    default: LLMProvider,
) -> LLMProvider:
    """Résout un nom de provider en LLMProvider via le registre.

    name falsy ou registre absent -> default.
    Nom absent du registre -> default (pas d'erreur).
    """
    if name and registry:
        return registry.get(name, default)
    return default


def build_provider_registry(
    agents: list[Agent],
    default_provider: str = "ollama",
    roles: RoleProviders | None = None,
) -> tuple[LLMProvider, dict[str, LLMProvider]]:
    """Retourne (provider_par_défaut_du_run, registry_par_nom).

    Scanne les agents ET, si fourni, les 7 champs de RoleProviders pour collecter
    tous les noms de provider distincts nécessaires au run.
    """
    names = {default_provider}
    names.update(a.provider for a in agents if a.provider)
    if roles is not None:
        names.update(
            rp.provider
            for rp in (
                roles.divider,
                roles.aggregator,
                roles.tagger,
                roles.evaluator,
                roles.diagnostic,
                roles.triage,
                roles.task_spec,
            )
            if rp.provider
        )
    registry = {name: create_provider(name) for name in sorted(names)}
    return registry[default_provider], registry
