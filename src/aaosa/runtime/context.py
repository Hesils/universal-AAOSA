"""RunContext — dépendances statiques d'un run de récupération (D1, spec §8).

Évite de threader agents/provider/divider/aggregator/tagger/tracer/evaluator dans chaque
appel récursif. Seul `depth` reste threadé explicitement. Frozen : aucune mutation en
cours de run.
"""

from dataclasses import dataclass, field

from aaosa.config.role_providers import RoleProviders
from aaosa.core.agent import Agent
from aaosa.core.hitl import HITLCallback
from aaosa.core.sandbox import Sandbox
from aaosa.qa.protocol import QAEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.provider_registry import resolve_provider
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.tagger import Tagger
from aaosa.tracing.tracer import Tracer


@dataclass(frozen=True)
class RunContext:
    agents: list[Agent]
    provider: LLMProvider
    divider: TaskDivider
    aggregator: TaskAggregator
    tagger: Tagger
    tracer: Tracer | None = None
    evaluator: QAEvaluator | None = None
    provider_registry: "dict[str, LLMProvider] | None" = None
    hitl_callback: "HITLCallback | None" = None
    sandbox: "Sandbox | None" = None        # v1m — racine FS jalée du run
    roles: RoleProviders = field(default_factory=RoleProviders)

    def resolve_role(self, name: str) -> "tuple[LLMProvider, str | None]":
        """(provider effectif, model) pour un rôle, via resolve_provider + le registre.

        Rôle sans provider/model -> (provider défaut du run, None) = comportement actuel.
        """
        rp = getattr(self.roles, name)
        return resolve_provider(rp.provider, self.provider_registry, self.provider), rp.model
