"""Rapport de campagne markdown — fonction pure sur l'index + snapshots ELO.

Zéro print, zéro I/O : le wiring (lecture fichiers, écriture, echo) vit dans
app.py, même contrat de testabilité que incident_runs.py.
"""

from pathlib import Path

from aaosa.cli.incident_runs import CampaignIndex, CampaignRunRecord
from aaosa.elo.persistence import EloSnapshot

_OUTCOME_ORDER = ("success", "qa_fail", "unassigned", "error")

# Ordre canonique des labels classify_run (tracing/analysis.py, _DIAGNOSED_ORDER
# inclus) — le rapport suit le même ordre, zéros inclus (observation explicite).
_TYPOLOGY_ORDER = (
    "simple",
    "divided",
    "recursion",
    "roster_gap",
    "diagnosed:agent",
    "diagnosed:evaluator",
    "diagnosed:task_spec",
    "diagnosed:unattributed",
    "aggregated",
)


def _duration(record: CampaignRunRecord) -> str:
    return f"{(record.ended_at - record.started_at).total_seconds():.1f}s"


def _header(index: CampaignIndex) -> list[str]:
    runs = index.runs
    period = (
        f"{runs[0].started_at.isoformat()} → {runs[-1].ended_at.isoformat()}"
        if runs
        else "—"
    )
    return [
        f"# Rapport de campagne — scénario `{index.scenario}`",
        "",
        f"- Runs demandés : {index.n_requested}",
        f"- Runs exécutés : {len(runs)}",
        f"- Période : {period}",
    ]


def _outcomes(index: CampaignIndex) -> list[str]:
    total = len(index.runs)
    lines = ["", "## Outcomes", ""]
    for outcome in _OUTCOME_ORDER:
        count = sum(1 for r in index.runs if r.outcome == outcome)
        pct = 100 * count / total if total else 0.0
        lines.append(f"- {outcome} : {count}/{total} ({pct:.0f}%)")
    return lines


def _typologies(index: CampaignIndex) -> list[str]:
    lines = ["", "## Typologies", ""]
    for label in _TYPOLOGY_ORDER:
        count = sum(1 for r in index.runs if label in r.typologies)
        lines.append(f"- {label} : {count}")
    return lines


def _aggregator_observation(index: CampaignIndex) -> list[str]:
    total = len(index.runs)
    count = sum(1 for r in index.runs if "aggregated" in r.typologies)
    lines = [
        "",
        "## Observation aggregator (ticket divider)",
        "",
        f"**{count}/{total} runs avec `TaskAggregatedEvent` réel.**",
    ]
    if count == 0:
        lines.append(
            "Critère du ticket divider non atteint sur cette campagne "
            "(aucun fan-in agrégé — cf. docs/backlog/2026-06-07-divider-topologie-aggregator.md)."
        )
    return lines


def _runs_table(index: CampaignIndex) -> list[str]:
    lines = [
        "",
        "## Runs",
        "",
        "| i | session | outcome | typologies | durée |",
        "|---|---------|---------|------------|-------|",
    ]
    for r in index.runs:
        session = r.session_id or "—"
        typologies = ", ".join(r.typologies) if r.typologies else "—"
        lines.append(
            f"| {r.i} | {session} | {r.outcome} | {typologies} | {_duration(r)} |"
        )
    errors = [r for r in index.runs if r.error]
    if errors:
        lines.append("")
        lines.extend(f"- run {r.i} error : {r.error}" for r in errors)
    return lines


def _elo_delta(snapshots: list[EloSnapshot]) -> list[str]:
    lines = ["", "## Delta ELO (premier → dernier snapshot)", ""]
    ordered = sorted(snapshots, key=lambda s: s.timestamp)
    if len(ordered) < 2:
        lines.append("_Delta indisponible (moins de 2 snapshots)._")
        return lines
    first = {a.agent_name: a.tags_with_elo for a in ordered[0].agents}
    last = {a.agent_name: a.tags_with_elo for a in ordered[-1].agents}
    lines.append("| agent | tag | départ | arrivée | delta |")
    lines.append("|-------|-----|--------|---------|-------|")
    # Seuls les agents/tags du dernier snapshot sont rendus — un agent/tag
    # disparu en cours de campagne sort de la table (cas inatteignable aujourd'hui).
    for name in sorted(last):
        first_tags = first.get(name, {})
        for tag in sorted(last[name]):
            end = last[name][tag]
            start = first_tags.get(tag)
            if start is None:
                lines.append(f"| {name} | {tag} | — | {end} | nouveau |")
            else:
                lines.append(f"| {name} | {tag} | {start} | {end} | {end - start:+d} |")
    return lines


def _replay(runs_root: Path | None) -> list[str]:
    root = str(runs_root) if runs_root is not None else "<runs-root>"
    return [
        "",
        "## Rejeu",
        "",
        f"- Dashboard (sessions + courbes ELO complètes) : `aaosa dashboard --runs-root {root}`",
        "",
    ]


def build_report(
    index: CampaignIndex,
    snapshots: list[EloSnapshot],
    runs_root: Path | None = None,
) -> str:
    """Rapport markdown complet d'une campagne. Pure : même input → même output."""
    lines = (
        _header(index)
        + _outcomes(index)
        + _typologies(index)
        + _aggregator_observation(index)
        + _runs_table(index)
        + _elo_delta(snapshots)
        + _replay(runs_root)
    )
    return "\n".join(lines)
