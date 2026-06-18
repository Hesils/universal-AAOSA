"""Helper pur de `aaosa solve` (zéro print, zéro Typer).

Parallèle à incident_runs.run_once : tâche LIBRE + N rosters injectés + provider_registry
câblé (défaut ollama) + prompts génériques + manifest dérivé de la trace. Partage le
scaffolding session/meta/tracer/snapshot via incident_runs._persisted_run.
"""

from dataclasses import dataclass, replace
from pathlib import Path

from aaosa.cli.incident_runs import RunKind, _persisted_run, load_elo_into
from aaosa.config.role_providers import load_role_providers
from aaosa.config.roster import load_rosters
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime import default_prompts
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.manifest import build_manifest
from aaosa.runtime.provider_registry import build_provider_registry, resolve_provider
from aaosa.runtime.runner import build_root_task
from aaosa.runtime.tagger import Tagger
from aaosa.tracing.events import ClaimEvent


@dataclass(frozen=True)
class SolveOutcome:
    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    manifest_path: Path
    events: list[ClaimEvent]
    task_description: str
    n_agents: int


def solve_once(
    roster_dirs: list[Path],
    task_text: str,
    context: str | None,
    runs_root: Path,
    provider_name: str = "ollama",
    roles_path: Path | None = None,
) -> SolveOutcome:
    """Résout une tâche libre avec N rosters injectés. Lève EmptyTaggingError si la
    tâche ne produit aucun tag (le caller CLI traduit en Exit 1).

    roles_path : chemin vers un roles.yaml (provider/model par rôle système). None →
    RoleProviders vide → comportement identique à avant (rétrocompat stricte).
    """
    agents = load_rosters(roster_dirs)
    roles = load_role_providers(roles_path)  # ValueError si fichier absent/malformé
    provider, registry = build_provider_registry(agents, provider_name, roles=roles)
    load_elo_into(agents, runs_root)

    # Résoudre le provider/model de l'évaluateur via les rôles.
    # roles.evaluator.provider=None (défaut) -> resolve_provider retourne provider (défaut du run).
    eprov = resolve_provider(roles.evaluator.provider, registry, provider)
    emodel = roles.evaluator.model

    # pre_ctx (tracer=None) pour taguer la racine AVANT toute création de session :
    # un échec de tagging ne doit pas laisser de session demi-écrite. build_root_task
    # n'utilise que tagger/agents/provider, jamais le tracer.
    pre_ctx = RunContext(
        agents=agents,
        provider=provider,
        divider=TaskDivider(system_prompt=default_prompts.DIVIDER_PROMPT),
        aggregator=TaskAggregator(system_prompt=default_prompts.AGGREGATOR_PROMPT),
        tagger=Tagger(system_prompt=default_prompts.TAGGER_PROMPT),
        tracer=None,
        evaluator=AdaptiveSpecEvaluator(eprov, model=emodel),
        provider_registry=registry,
        roles=roles,
    )
    task = build_root_task(task_text, pre_ctx, context=context)  # peut lever EmptyTaggingError

    pr = _persisted_run(
        agents,
        runs_root,
        build_ctx=lambda tracer: replace(pre_ctx, tracer=tracer),
        make_task=lambda ctx: task,
    )

    manifest = build_manifest(list(pr.tracer.events), pr.result, "trace.jsonl")
    manifest_path = pr.session_dir / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    return SolveOutcome(
        kind=pr.kind,
        session_id=pr.session_id,
        session_dir=pr.session_dir,
        snapshot_path=pr.snapshot_path,
        manifest_path=manifest_path,
        events=list(pr.tracer.events),
        task_description=pr.task.description,
        n_agents=len(agents),
    )
