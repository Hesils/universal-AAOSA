"""RunContext — dépendances statiques d'un run de récupération (D1, spec §8).

Évite de threader agents/provider/divider/aggregator/tagger/tracer/evaluator dans chaque
appel récursif. Seul `depth` reste threadé explicitement. Frozen : aucune mutation en
cours de run.
"""

from dataclasses import dataclass

from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
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
