"""Helpers partagés des commandes `aaosa run` / `aaosa campaign`.

Zéro print, zéro dépendance Typer : le wiring console vit dans app.py
(les helpers restent testables sans capture de sortie).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.demo.incident.prompts import AGGREGATOR_PROMPT, DIVIDER_PROMPT, TAGGER_PROMPT
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
from aaosa.runtime.runner import run_with_recovery
from aaosa.runtime.tagger import Tagger
from aaosa.schemas.output import Output
from aaosa.tracing.events import ClaimEvent
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer

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


def run_once(scenario: str, runs_root: Path, client: OpenAI) -> RunOutcome:
    """Un run incident complet : roster frais + ELO appliqué -> run_with_recovery
    (jamais de division forcée, thèse D1) -> persistance (registry, session,
    snapshot). Mécanique migrée de run_incident.py (phase 3, supprimé)."""
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    agents = _ROSTERS[scenario]()
    load_elo_into(agents, runs_root)

    ctx = RunContext(
        agents=agents,
        client=client,
        divider=TaskDivider(system_prompt=DIVIDER_PROMPT),
        aggregator=TaskAggregator(system_prompt=AGGREGATOR_PROMPT),
        tagger=Tagger(system_prompt=TAGGER_PROMPT),
        tracer=tracer,
        evaluator=AdaptiveSpecEvaluator(client),
    )

    task = build_data_leak_task()
    result = run_with_recovery(task, ctx)
    kind = _result_kind(result)

    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=[
            SessionTaskRecord(
                id=task.id,
                description=task.description,
                winner_agent_id=None,
                outcome=_META_OUTCOME[kind],
                required_tags=task.required_tags,
                context=task.context,
            )
        ],
        agent_ids=[a.id for a in agents],
    )
    session_dir = save_session(tracer, meta, runs_root, agents=agents)

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = save_snapshot(agents, snapshot_dir)

    return RunOutcome(
        kind=kind,
        session_id=session_id,
        session_dir=session_dir,
        snapshot_path=snapshot_path,
        events=list(tracer.events),
        task_description=task.description,
        n_agents=len(agents),
    )
