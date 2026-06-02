from typing import TYPE_CHECKING

from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.elo.updater import update_agent_elo
from aaosa.qa.protocol import QAEvaluator, QAFailure
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import ExecutedEvent, QAEvaluatedEvent, EloUpdatedEvent, TagAcquiredEvent
from aaosa.tracing.tracer import Tracer

if TYPE_CHECKING:
    from aaosa.runtime.aggregator import TaskAggregator
    from aaosa.runtime.divider import TaskDivider


def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> Output | DispatchResult | QAFailure:
    candidates = filter_candidates(task, agents, tracer)
    fit_scores = {agent.id: score for agent, score in candidates}
    claims = run_phase2(task, candidates, client, tracer)

    candidate_agents = [agent for agent, _ in candidates]
    result = dispatch(claims, task, candidate_agents, fit_scores, tracer)

    if result.status == "unassigned":
        return result

    agent_map = {agent.id: agent for agent in candidate_agents}
    winner = agent_map[result.agent_id]
    output = winner.execute(task, client, tracer)

    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
            output_content=output.content,
            llm_metadata=output.llm_metadata,
        ))

    if evaluator is None:
        return output

    qa_result = evaluator.evaluate(task, output)

    if tracer is not None:
        tracer.emit(QAEvaluatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            success=qa_result.success,
            score=qa_result.score,
            reason=qa_result.reason,
            criteria_results=qa_result.criteria_results,
            judge=qa_result.judge,
            spec=qa_result.spec_used,
        ))

    elo_result = update_agent_elo(winner, task, success=qa_result.success)

    if tracer is not None:
        tracer.emit(EloUpdatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            deltas=elo_result.deltas,
        ))
        for tag, elo in elo_result.acquired_tags.items():
            tracer.emit(TagAcquiredEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=winner.id,
                tag=tag,
                initial_elo=elo,
            ))

    if qa_result.success:
        return output
    return QAFailure(
        task_id=task.id,
        agent_id=winner.id,
        output=output,
        qa_result=qa_result,
    )


def _topological_order(tasks: list[Task]) -> list[Task]:
    """Tri topologique (Kahn) selon depends_on, en préservant l'ordre d'entrée
    pour les tâches de même rang. Lève ValueError sur cycle ou dépendance inconnue."""
    task_by_id = {t.id: t for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in task_by_id:
                raise ValueError(f"unknown dependency id: {dep!r}")

    in_degree = {t.id: 0 for t in tasks}
    adjacency: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            adjacency[dep].append(t.id)
            in_degree[t.id] += 1

    queue = [t for t in tasks if in_degree[t.id] == 0]
    order: list[Task] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt_id in adjacency[current.id]:
            in_degree[nxt_id] -= 1
            if in_degree[nxt_id] == 0:
                queue.append(task_by_id[nxt_id])

    if len(order) != len(tasks):
        raise ValueError("cycle detected in task dependencies")
    return order


def run_chain(
    tasks: list[Task],
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> list[Output | DispatchResult | QAFailure]:
    """Exécute une liste de sous-tâches ordonnée par leur graphe de dépendances.

    Chaque tâche reçoit dans `required_outputs` uniquement les outputs réussis des
    tâches déclarées dans son `depends_on`. Une tâche dont une dépendance n'a pas
    produit d'output réussi est marquée `DispatchResult(status="dependency_failed")`
    sans être exécutée. L'input n'est pas muté (copie via model_copy).
    """
    order = _topological_order(tasks)
    outputs: dict[str, Output] = {}
    results: list[Output | DispatchResult | QAFailure] = []

    for task in order:
        unmet = [dep for dep in task.depends_on if dep not in outputs]
        if unmet:
            results.append(DispatchResult(
                status="dependency_failed",
                agent_id=None,
                reason=f"unresolved dependencies: {unmet}",
            ))
            continue

        resolved = [outputs[dep] for dep in task.depends_on]
        task_to_run = task.model_copy(update={"required_outputs": resolved})
        result = run_task(task_to_run, agents, client, tracer, evaluator)
        results.append(result)
        if isinstance(result, Output):
            outputs[task.id] = result

    return results


def run_divided_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    divider: "TaskDivider",
    aggregator: "TaskAggregator",
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> Output | DispatchResult:
    """Divise une tâche, exécute la chaîne de sous-tâches, puis agrège.

    Stratégie B (LLM Aggregator) primaire. Fallback C : si aggregate() lève une
    exception, retourne le dernier Output réussi de la chaîne (qui peut être une
    sous-tâche de synthèse si le divider en a inclus une). Aucun output réussi →
    DispatchResult(status="unassigned").
    """
    sub_tasks = divider.divide(task, agents, client, tracer)
    sub_results = run_chain(sub_tasks, agents, client, tracer, evaluator)
    successful = [r for r in sub_results if isinstance(r, Output)]

    if not successful:
        return DispatchResult(
            status="unassigned",
            agent_id=None,
            reason="no sub-tasks succeeded",
        )

    try:
        return aggregator.aggregate(task, successful, client, tracer)
    except Exception:
        return successful[-1]  # fallback C : dernier output réussi
