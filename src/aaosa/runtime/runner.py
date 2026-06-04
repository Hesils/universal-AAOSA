from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.elo.updater import update_agent_elo
from aaosa.qa.protocol import QAEvaluator, QAFailure
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import (
    DividedSubTask,
    EloUpdatedEvent,
    ExecutedEvent,
    QAEvaluatedEvent,
    RosterGapEvent,
    TagAcquiredEvent,
    TagLostEvent,
    TaskDividedEvent,
)
from aaosa.tracing.tracer import Tracer

MAX_RECOVERY_DEPTH = 3


def _roster_gap(task: Task, agents: list[Agent]) -> set[str]:
    """Tags requis qu'AUCUN agent du roster ne porte. Compare la présence du tag,
    pas son niveau d'ELO (un ELO insuffisant n'est pas un trou de roster)."""
    roster = {tag for a in agents for tag in a.tags_with_elo}
    return set(task.required_tags) - roster


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

    # Frontière de containment : execute() et evaluate() font des appels LLM (boucle
    # d'outils, juge) qui peuvent lever. run_task ne propage jamais ces erreurs ; il
    # renvoie DispatchResult(execution_failed). Simple et divisé se dégradent pareil
    # (run_chain s'appuie sur ce contrat, il n'a plus son propre try).
    try:
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
            for tag, elo in elo_result.lost_tags.items():
                tracer.emit(TagLostEvent(
                    session_id=tracer.session_id,
                    task_id=task.id,
                    agent_id=winner.id,
                    tag=tag,
                    last_elo=elo,
                ))

        if qa_result.success:
            return output
        return QAFailure(
            task_id=task.id,
            agent_id=winner.id,
            output=output,
            qa_result=qa_result,
        )
    except Exception as exc:
        return DispatchResult(
            status="execution_failed",
            agent_id=None,
            reason=f"execution raised: {type(exc).__name__}: {exc}",
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


def run_chain(sub_tasks: list[Task], ctx: RunContext, depth: int) -> list[Output | DispatchResult | QAFailure]:
    """Exécute une liste de sous-tâches ordonnée par leur graphe de dépendances (Kahn).

    Recovery-aware (D1) : l'exécuteur par nœud est `run_with_recovery` (était `run_task`).
    Le reste est identique à A3 — required_outputs des deps réussies injectés, cascade
    dependency_failed, input non muté (model_copy)."""
    order = _topological_order(sub_tasks)
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
        result = run_with_recovery(task_to_run, ctx, depth)
        results.append(result)
        if isinstance(result, Output):
            outputs[task.id] = result

    return results


def build_sub_tasks(parent_task: Task, division: DivisionResult, ctx: RunContext) -> list[Task]:
    """Transforme les sous-specs structurelles du divider en Task taguées.

    Tague CHAQUE sous-tâche depuis sa propre description (pas d'héritage parent), pose la
    barre uniforme DEFAULT_REQUIRED_ELO, résout les deps indices→IDs, et émet le
    TaskDividedEvent (avec les vrais tags). Lève EmptyTaggingError si une sous-spec ne
    produit aucun tag (clean-crash géré par run_with_recovery)."""
    sub_tasks: list[Task] = []
    for i, spec in enumerate(division.sub_tasks):
        tags = ctx.tagger.tag(spec.description, ctx.agents, ctx.client)
        if not tags:
            raise EmptyTaggingError(spec.description)
        sub_tasks.append(Task(
            description=spec.description,
            required_tags={t: DEFAULT_REQUIRED_ELO for t in tags},
            parent_task_id=parent_task.id,
            order_index=i,
        ))
    for i, spec in enumerate(division.sub_tasks):
        sub_tasks[i].depends_on = [sub_tasks[j].id for j in spec.depends_on_indices]

    if ctx.tracer is not None:
        ctx.tracer.emit(TaskDividedEvent(
            session_id=ctx.tracer.session_id,
            task_id=parent_task.id,
            sub_tasks=[
                DividedSubTask(
                    id=st.id, description=st.description,
                    depends_on=list(st.depends_on), required_tags=dict(st.required_tags),
                )
                for st in sub_tasks
            ],
        ))
    return sub_tasks


def run_with_recovery(task: Task, ctx: RunContext, depth: int = 0) -> Output | DispatchResult | QAFailure:
    """Cœur récursif D1. Tente la tâche à plat ; ne divise que sur `unassigned`,
    récursivement (mutuellement récursif avec run_chain). `task` est TOUJOURS taguée."""
    missing = _roster_gap(task, ctx.agents)
    if missing:
        if ctx.tracer is not None:
            ctx.tracer.emit(RosterGapEvent(
                session_id=ctx.tracer.session_id,
                task_id=task.id,
                missing_tags=sorted(missing),
            ))
        return DispatchResult(
            status="roster_gap",
            agent_id=None,
            reason=f"no agent covers required tags: {sorted(missing)}",
        )

    result = run_task(task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)
    if not (isinstance(result, DispatchResult) and result.status == "unassigned"):
        return result

    if depth >= MAX_RECOVERY_DEPTH:
        return result

    try:
        division = ctx.divider.divide(task, ctx.client)
    except Exception:
        return DispatchResult(
            status="execution_failed",
            agent_id=None,
            reason="divider raised an exception",
        )
    if division.is_atomic:
        return result

    try:
        sub_tasks = build_sub_tasks(task, division, ctx)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed",
            agent_id=None,
            reason="tagging produced no tags",
        )

    sub_results = run_chain(sub_tasks, ctx, depth + 1)
    successful = [r for r in sub_results if isinstance(r, Output)]
    if not successful:
        return DispatchResult(
            status="unassigned",
            agent_id=None,
            reason="no sub-tasks recovered",
        )

    try:
        return ctx.aggregator.aggregate(task, successful, ctx.client, ctx.tracer)
    except Exception:
        return successful[-1]


def run_recovery(
    description: str,
    ctx: RunContext,
    pinned_tags: dict[str, int] | None = None,
) -> Output | DispatchResult | QAFailure:
    """Entrée publique D1 (remplace run_divided_task). Tague la racine SEULEMENT si le
    caller n'a pas épinglé de tags ; une racine déjà taguée n'est pas re-taguée (§2)."""
    if pinned_tags:
        task = Task(description=description, required_tags=pinned_tags)
    else:
        tags = ctx.tagger.tag(description, ctx.agents, ctx.client)
        if not tags:
            return DispatchResult(
                status="execution_failed",
                agent_id=None,
                reason="tagging produced no tags",
            )
        task = Task(description=description, required_tags={t: DEFAULT_REQUIRED_ELO for t in tags})
    return run_with_recovery(task, ctx, depth=0)
