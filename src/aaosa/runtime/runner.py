from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.elo.updater import update_agent_elo
from aaosa.qa.diagnostic import DiagnosticResult, FailureContext, diagnose_failure
from aaosa.qa.protocol import QAEvaluator, QAFailure
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
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


def _sinks(sub_tasks: list[Task], outputs_by_id: dict[str, Output]) -> list[Output]:
    """Sinks du sous-DAG des frères réussis : un réussi non consommé par un réussi.

    Un sink est un résultat terminal « lâche » qui doit être fusionné ; un réussi
    consommé par un réussi est déjà replié dans son consommateur (required_outputs).
    Ordre = ordre de sub_tasks (ordre du divider). Pur, pas d'appel LLM."""
    succeeded = set(outputs_by_id)
    consumed = {
        dep
        for t in sub_tasks if t.id in succeeded
        for dep in t.depends_on if dep in succeeded
    }
    return [outputs_by_id[t.id] for t in sub_tasks if t.id in succeeded and t.id not in consumed]


def run_chain(
    sub_tasks: list[Task],
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None = None,
) -> dict[str, Output]:
    """Exécute des sous-tâches ordonnées par leur DAG de dépendances (Kahn) et renvoie
    les outputs RÉUSSIS indexés par id de tâche (ordre d'insertion = ordre topologique).

    Recovery-aware (D1) : l'exécuteur par nœud est `run_with_recovery`. required_outputs
    des deps réussies injectés, input non muté (model_copy). chained_context (D3) est
    transmis tel quel à chaque nœud (déjà augmenté du parent par l'appelant). Les échecs
    ne sont pas dans le retour (déjà contenus/tracés à l'exécution) ; un dépendant dont
    une dep manque est simplement sauté. Interne à la récursion : seul `run_with_recovery`
    l'appelle (D2)."""
    order = _topological_order(sub_tasks)
    outputs: dict[str, Output] = {}

    for task in order:
        unmet = [dep for dep in task.depends_on if dep not in outputs]
        if unmet:
            continue
        resolved = [outputs[dep] for dep in task.depends_on]
        task_to_run = task.model_copy(update={"required_outputs": resolved})
        result = run_with_recovery(
            task_to_run, ctx, depth, chained_context=chained_context
        )
        if isinstance(result, Output):
            outputs[task.id] = result

    return outputs


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
            context=spec.context,
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


def _divide_and_recover(
    task: Task,
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None,
    failure_context: FailureContext | None,
    atomic_fallback: Output | DispatchResult | QAFailure,
) -> Output | DispatchResult | QAFailure:
    """Divise `task`, exécute le sous-DAG (run_chain), agrège les sinks (D2).

    Partagé par la route D1 (unassigned, failure_context=None) et la route D3
    task_spec (failure_context renseigné). `atomic_fallback` est renvoyé si le
    divider juge la tâche atomique ou si aucune sous-tâche n'aboutit."""
    if depth >= MAX_RECOVERY_DEPTH:
        return atomic_fallback

    try:
        division = ctx.divider.divide(
            task, ctx.client,
            chained_context=chained_context,
            failure_context=failure_context,
        )
    except Exception:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="divider raised an exception",
        )
    if division.is_atomic:
        return atomic_fallback

    try:
        sub_tasks = build_sub_tasks(task, division, ctx)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="tagging produced no tags",
        )

    child_context = (chained_context or []) + [task]
    outputs_by_id = run_chain(sub_tasks, ctx, depth + 1, chained_context=child_context)
    if not outputs_by_id:
        return DispatchResult(
            status="unassigned", agent_id=None,
            reason="no sub-tasks recovered",
        )

    sinks = _sinks(sub_tasks, outputs_by_id)
    if len(sinks) == 1:
        return sinks[0]   # court-circuit : un seul résultat terminal, rien à synthétiser

    try:
        return ctx.aggregator.aggregate(task, sinks, ctx.client, ctx.tracer)
    except Exception:
        return sinks[-1]


def _qa_failed(task: Task, attribution: str, consignes_tried: bool) -> DispatchResult:
    return DispatchResult(
        status="qa_failed", agent_id=None,
        reason=f"qa failed (attribution={attribution})",
        attribution=attribution, consignes_tried=consignes_tried,
    )


def _retry_with_consignes(
    task: Task,
    consignes: str | None,
    ctx: RunContext,
    attribution: str,
) -> "Output | DispatchResult | QAFailure":
    """Retry agent UNE fois, consignes injectées dans task.context. Output → succès ;
    sinon DispatchResult(qa_failed, consignes_tried=True)."""
    if consignes:
        base = task.context or ""
        new_context = f"{base}\n\n# Consignes de correction\n{consignes}".strip()
        retry_task = task.model_copy(update={"context": new_context})
    else:
        retry_task = task
    result = run_task(retry_task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)
    if isinstance(result, Output):
        return result
    return _qa_failed(task, attribution=attribution, consignes_tried=True)


def _route_diagnostic(
    task: Task,
    failure: "QAFailure",
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None,
) -> "Output | DispatchResult | QAFailure":
    diagnostic = diagnose_failure(task, failure.output, failure.qa_result, ctx.client)
    if diagnostic is None:
        return _qa_failed(task, attribution="unattributed", consignes_tried=False)

    if diagnostic.attribution == "agent":
        return _retry_with_consignes(task, diagnostic.consignes, ctx, attribution="agent")

    if diagnostic.attribution == "evaluator":
        fc = FailureContext(
            failed_output=failure.output,
            qa_result=failure.qa_result,
            diagnostic_reason=diagnostic.reason,
        )
        new_evaluator = AdaptiveSpecEvaluator(ctx.client, failure_context=fc)
        qa2 = new_evaluator.evaluate(task, failure.output)
        if qa2.success:
            return failure.output   # l'output original passe avec la spec régénérée
        return _retry_with_consignes(task, diagnostic.consignes, ctx, attribution="evaluator")

    if diagnostic.attribution == "task_spec":
        failure_ctx = FailureContext(
            failed_output=failure.output,
            qa_result=failure.qa_result,
            diagnostic_reason=diagnostic.reason,
        )
        return _divide_and_recover(
            task, ctx, depth, chained_context,
            failure_context=failure_ctx,
            atomic_fallback=_qa_failed(task, attribution="task_spec", consignes_tried=False),
        )

    return _qa_failed(task, attribution="unattributed", consignes_tried=False)


def run_with_recovery(
    task: Task,
    ctx: RunContext,
    depth: int = 0,
    chained_context: list[Task] | None = None,
    failure_context: FailureContext | None = None,
) -> Output | DispatchResult | QAFailure:
    """Cœur récursif D1+D3. Tente la tâche à plat ; divise sur `unassigned` (D1) ou
    sur diagnostic `task_spec` (D3) ; route les autres qa_fail (D3). `task` est
    TOUJOURS taguée."""
    missing = _roster_gap(task, ctx.agents)
    if missing:
        if ctx.tracer is not None:
            ctx.tracer.emit(RosterGapEvent(
                session_id=ctx.tracer.session_id,
                task_id=task.id,
                missing_tags=sorted(missing),
            ))
        return DispatchResult(
            status="roster_gap", agent_id=None,
            reason=f"no agent covers required tags: {sorted(missing)}",
        )

    result = run_task(task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)

    if isinstance(result, DispatchResult) and result.status == "unassigned":
        return _divide_and_recover(
            task, ctx, depth, chained_context,
            failure_context=None, atomic_fallback=result,
        )

    if isinstance(result, QAFailure):
        return _route_diagnostic(task, result, ctx, depth, chained_context)

    return result


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
