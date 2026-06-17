"""Helpers partagés des commandes `aaosa run` / `aaosa campaign`.

Zéro print, zéro dépendance Typer : le wiring console vit dans app.py
(les helpers restent testables sans capture de sortie).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.demo.incident.prompts import AGGREGATOR_PROMPT, DIVIDER_PROMPT, TAGGER_PROMPT
from aaosa.schemas.task import Task
from aaosa.demo.incident.scenarios import (
    build_data_leak_task,
    full_roster,
    roster_gap_roster,
)
from aaosa.elo.persistence import apply_snapshot, load_snapshot, save_snapshot
from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.runner import run_with_recovery
from aaosa.runtime.tagger import Tagger
from aaosa.schemas.output import Output
from aaosa.tracing.analysis import classify_run
from aaosa.tracing.events import ClaimEvent
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import StreamingTracer

_ROSTERS = {"main": full_roster, "roster_gap": roster_gap_roster}

RunKind = Literal["success", "qa_fail", "unassigned"]

# SessionMeta.outcome garde le comportement de run_incident.py (la trace est la
# vérité, le label meta est grossier — constat phase 2) ; qa_fail est juste plus
# honnête que l'écraser en unassigned.
_META_OUTCOME: dict[RunKind, str] = {
    "success": "divided",
    "qa_fail": "qa_fail",
    "unassigned": "unassigned",
}


class StoreNotEmptyError(Exception):
    """Garde-fou campagne : store déjà peuplé, jamais de cleanup auto."""

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        super().__init__(
            f"runs store already populated: {sessions_dir} contains sessions. "
            "Refusing to mix campaigns - pass a fresh --runs-root (no automatic cleanup)."
        )


def ensure_empty_store(runs_root: Path) -> None:
    """Lève StoreNotEmptyError si runs_root/sessions/ contient >=1 session."""
    sessions_dir = runs_root / "sessions"
    if sessions_dir.exists() and any(sessions_dir.iterdir()):
        raise StoreNotEmptyError(sessions_dir)


def load_elo_into(agents: list[Agent], runs_root: Path) -> bool:
    """Charge runs_root/elo_snapshots/latest.json s'il existe et l'applique par
    nom sur le roster (noms absents ignorés — comportement V2a, compatible
    roster_gap). Retourne False si absent : ELO YAML intacts."""
    path = runs_root / "elo_snapshots" / "latest.json"
    if not path.exists():
        return False
    apply_snapshot(agents, load_snapshot(path))
    return True


@dataclass(frozen=True)
class RunOutcome:
    """Résultat d'un run consommé par `aaosa run` (console) et `aaosa campaign` (index)."""

    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    events: list[ClaimEvent]
    task_description: str
    n_agents: int


@dataclass(frozen=True)
class _PersistedResult:
    """Sortie du scaffolding partagé : tout ce dont run_once/solve_once ont besoin."""
    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    tracer: "StreamingTracer"
    task: Task
    result: object  # Output | DispatchResult | QAFailure


def _persisted_run(
    agents: list[Agent],
    runs_root: Path,
    build_ctx: "Callable[[StreamingTracer], RunContext]",
    make_task: "Callable[[RunContext], Task]",
) -> _PersistedResult:
    """Scaffolding commun à run_once/solve_once : session + meta provisoire (live) +
    trace streamée + exécution contenue + finalisation + snapshot ELO mono-store.

    L'ordre place tracer/ctx avant make_task (solve tague via ctx.tagger ; le tagger
    n'émet aucun event -> le meta provisoire reste antérieur au run)."""
    session_id = new_session_id()
    started_at = datetime.now(timezone.utc)
    session_dir = runs_root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    tracer = StreamingTracer(session_id=session_id, stream_path=session_dir / "trace.jsonl")
    ctx = build_ctx(tracer)
    task = make_task(ctx)

    def _meta(status: str, ended_at: datetime, outcome: str) -> SessionMeta:
        return SessionMeta(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            tasks=[
                SessionTaskRecord(
                    id=task.id,
                    description=task.description,
                    winner_agent_id=None,
                    outcome=outcome,
                    required_tags=task.required_tags,
                    context=task.context,
                )
            ],
            agent_ids=[a.id for a in agents],
            status=status,
        )

    provisional = _meta("running", started_at, "divided")
    (session_dir / "meta.json").write_text(provisional.model_dump_json(indent=2), encoding="utf-8")
    save_agent_registry(agents, session_dir / "agents.json")

    try:
        result = run_with_recovery(task, ctx)
    except Exception:
        (session_dir / "meta.json").write_text(
            _meta("complete", datetime.now(timezone.utc), "unassigned").model_dump_json(indent=2),
            encoding="utf-8",
        )
        raise
    finally:
        tracer.close()

    kind = _result_kind(result)
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = _meta("complete", datetime.now(timezone.utc), _META_OUTCOME[kind])
    session_dir = save_session(tracer, meta, runs_root, agents=agents)

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = save_snapshot(agents, snapshot_dir)

    return _PersistedResult(
        kind=kind, session_id=session_id, session_dir=session_dir,
        snapshot_path=snapshot_path, tracer=tracer, task=task, result=result,
    )


def _result_kind(result: Output | DispatchResult | QAFailure) -> RunKind:
    """Mappe le retour de run_with_recovery sur le vocabulaire d'index.

    Un échec QA non récupéré remonte en DispatchResult(status="qa_failed")
    (_route_diagnostic ne laisse jamais échapper un QAFailure) ; l'arm QAFailure
    reste en défense de l'annotation de run_with_recovery.
    """
    if isinstance(result, Output):
        return "success"
    if isinstance(result, QAFailure):
        return "qa_fail"
    if result.status == "qa_failed":
        return "qa_fail"
    return "unassigned"


def run_once(scenario: str, runs_root: Path, provider: LLMProvider) -> RunOutcome:
    """Un run incident complet, observable en live. Consomme le scaffolding partagé
    `_persisted_run` (identique à l'inline d'origine ; prompts/évaluateur incident)."""
    agents = _ROSTERS[scenario]()
    load_elo_into(agents, runs_root)

    def build_ctx(tracer: StreamingTracer) -> RunContext:
        return RunContext(
            agents=agents,
            provider=provider,
            divider=TaskDivider(system_prompt=DIVIDER_PROMPT),
            aggregator=TaskAggregator(system_prompt=AGGREGATOR_PROMPT),
            tagger=Tagger(system_prompt=TAGGER_PROMPT),
            tracer=tracer,
            evaluator=AdaptiveSpecEvaluator(provider),
        )

    pr = _persisted_run(agents, runs_root, build_ctx, make_task=lambda ctx: build_data_leak_task())
    return RunOutcome(
        kind=pr.kind,
        session_id=pr.session_id,
        session_dir=pr.session_dir,
        snapshot_path=pr.snapshot_path,
        events=list(pr.tracer.events),
        task_description=pr.task.description,
        n_agents=len(agents),
    )


class CampaignRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    i: int
    session_id: str | None
    outcome: Literal["success", "qa_fail", "unassigned", "error"]
    typologies: list[str]
    started_at: datetime
    ended_at: datetime
    error: str | None = None


class CampaignIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str
    n_requested: int
    runs: list[CampaignRunRecord] = Field(default_factory=list)


def run_campaign(
    n: int,
    scenario: str,
    runs_root: Path,
    provider: LLMProvider | None,
    on_run: Callable[[CampaignRunRecord], None] | None = None,
) -> CampaignIndex:
    """N runs séquentiels, ELO chaîné par les snapshots (run_once recharge
    latest.json à chaque itération). Index réécrit après CHAQUE run (crash-safe :
    un Ctrl-C ne perd que le run en cours). Une exception d'un run n'avorte pas
    la campagne (entrée error, la boucle continue) ; KeyboardInterrupt passe."""
    index = CampaignIndex(scenario=scenario, n_requested=n)
    runs_root.mkdir(parents=True, exist_ok=True)
    index_path = runs_root / "campaign_index.json"

    for i in range(1, n + 1):
        started_at = datetime.now(timezone.utc)
        try:
            outcome = run_once(scenario, runs_root, provider)
            record = CampaignRunRecord(
                i=i,
                session_id=outcome.session_id,
                outcome=outcome.kind,
                typologies=classify_run(outcome.events),
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
            )
        except Exception as exc:  # containment — jamais KeyboardInterrupt
            record = CampaignRunRecord(
                i=i,
                session_id=None,
                outcome="error",
                typologies=[],
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                error=str(exc)[:200],
            )
        index.runs.append(record)
        index_path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        if on_run is not None:
            on_run(record)

    return index
