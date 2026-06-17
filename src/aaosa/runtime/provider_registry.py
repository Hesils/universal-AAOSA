"""Construction du registre de providers d'un run `solve`.

Noms distincts = {default_provider} ∪ {a.provider for a in agents if a.provider}.
create_provider lève déjà sur un nom != ollama|openai. Le registre câblé dans
RunContext.provider_registry active la résolution provider-par-agent (déjà codée
dans run_task). Défaut projet = ollama (gratuit).
"""

from aaosa.core.agent import Agent
from aaosa.runtime.llm_client import create_provider
from aaosa.runtime.providers import LLMProvider


def build_provider_registry(
    agents: list[Agent], default_provider: str = "ollama"
) -> tuple[LLMProvider, dict[str, LLMProvider]]:
    """Retourne (provider_par_défaut_du_run, registry_par_nom)."""
    names = {default_provider}
    names.update(a.provider for a in agents if a.provider)
    registry = {name: create_provider(name) for name in sorted(names)}
    return registry[default_provider], registry
