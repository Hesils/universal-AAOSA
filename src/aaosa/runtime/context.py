"""RunContext — dépendances statiques d'un run de récupération (D1, spec §8).

Évite de threader agents/client/divider/aggregator/tagger/tracer/evaluator dans chaque
appel récursif. Seul `depth` reste threadé explicitement. Frozen : aucune mutation en
cours de run.
"""

from dataclasses import dataclass

from openai import OpenAI

from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger
from aaosa.tracing.tracer import Tracer


@dataclass(frozen=True)
class RunContext:
    agents: list[Agent]
    client: OpenAI
    divider: TaskDivider
    aggregator: TaskAggregator
    tagger: Tagger
    tracer: Tracer | None = None
    evaluator: QAEvaluator | None = None
