"""TaskAggregator — synthétise les outputs des sous-tâches via LLM (A4).

Contrairement à l'« Integrator » V2c (collecteur passif), l'Aggregateur est un
composant actif : il produit un Output réel via un appel LLM. Ce n'est pas un
agent AAOSA — l'Output porte le sentinel agent_id="aggregator".
"""

import time

from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import TaskAggregatedEvent
from aaosa.tracing.tracer import Tracer

AGGREGATOR_AGENT_ID = "aggregator"


class TaskAggregator:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_aggregate_prompt(self, parent_task: Task, sub_outputs: list[Output]) -> str:
        parts = [
            f"Original task: {parent_task.description}",
            "",
            "The results below are complementary: each covers a distinct part of the "
            "original task. They are peers, not a sequence.",
            "",
            "Complementary results:",
        ]
        for i, out in enumerate(sub_outputs, start=1):
            if i > 1:
                parts.append("---")
            parts.append(f"[result {i}]: {out.content}")
        parts.append("")
        parts.append("Produce a single coherent response that covers all of them.")
        return "\n".join(parts)

    def aggregate(
        self,
        parent_task: Task,
        sub_outputs: list[Output],
        provider: LLMProvider,
        tracer: Tracer | None = None,
        model: str | None = None,
    ) -> Output:
        """LLM call → Output synthétisant les sub_outputs.

        Output.task_id = parent_task.id, Output.agent_id = "aggregator".
        """
        prompt = self._build_aggregate_prompt(parent_task, sub_outputs)
        start = time.monotonic()
        response = provider.complete(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=model,
        )
        latency_ms = (time.monotonic() - start) * 1000
        output = Output(
            task_id=parent_task.id,
            agent_id=AGGREGATOR_AGENT_ID,
            content=response.choices[0].message.content or "",
            llm_metadata=LLMMetadata(
                model_name=response.model,
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens,
                latency_ms=latency_ms,
            ),
        )

        if tracer is not None:
            tracer.emit(TaskAggregatedEvent(
                session_id=tracer.session_id,
                task_id=parent_task.id,
                sub_task_ids=[o.task_id for o in sub_outputs],
                output_summary=output.content[:100],
                output_content=output.content,
                llm_metadata=output.llm_metadata,
            ))
        return output
