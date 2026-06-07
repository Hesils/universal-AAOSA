"""CLI projet-wide `aaosa` — entree unique des points d'execution du projet.

Wiring console fin uniquement : la logique run/campaign vit dans
`aaosa.cli.incident_runs` (helpers purs, sans print).
"""

from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv

from aaosa.cli.incident_runs import (
    CampaignIndex,
    StoreNotEmptyError,
    ensure_empty_store,
    run_campaign,
    run_once,
)
from aaosa.cli.report import build_report
from aaosa.elo.persistence import load_snapshot
from aaosa.demo.run_health_check_v3 import run_demo_health_check_v3
from aaosa.runtime.llm_client import create_client
from aaosa.tracing.formatter import print_timeline
from dashboard.app import create_app
from dashboard.config import DashboardConfig

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Runtime multi-agents AAOSA - CLI projet-wide."""


class Scenario(str, Enum):
    main = "main"
    roster_gap = "roster_gap"


@app.command()
def run(
    scenario: Scenario = typer.Option(Scenario.main, "--scenario"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Un run incident : claiming -> recuperation D1/D3 -> persistance (ELO chaine)."""
    load_dotenv()
    client = create_client()
    outcome = run_once(scenario.value, runs_root, client)

    typer.echo(
        f"=== AAOSA incident - scenario: {scenario.value} ({outcome.n_agents} agents) ===\n"
    )
    typer.echo(f"Input: {outcome.task_description}\n")
    typer.echo(f"  -> {outcome.kind}\n")
    typer.echo("=== Timeline ===")
    print_timeline(outcome.events)
    typer.echo("\n=== Persistence ===")
    typer.echo(f"Session saved to {outcome.session_dir}")
    typer.echo(f"ELO snapshot saved to {outcome.snapshot_path}")


@app.command()
def campaign(
    n: int = typer.Option(..., "--n", min=1, help="Nombre de runs (obligatoire - cout LLM)"),
    scenario: Scenario = typer.Option(Scenario.main, "--scenario"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """N runs sequentiels, ELO chaine, index crash-safe. Refuse un store peuple."""
    try:
        ensure_empty_store(runs_root)
    except StoreNotEmptyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    load_dotenv()
    client = create_client()
    typer.echo(f"=== AAOSA campaign - scenario: {scenario.value}, n={n} ===")

    def _echo_run(record) -> None:
        typer.echo(f"run {record.i}/{n}: {record.outcome} {record.typologies}")

    index = run_campaign(n, scenario.value, runs_root, client, on_run=_echo_run)
    successes = sum(1 for r in index.runs if r.outcome == "success")
    typer.echo(f"\n{successes}/{n} success - index: {runs_root / 'campaign_index.json'}")


@app.command()
def report(
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Rapport de campagne markdown depuis campaign_index.json + snapshots ELO."""
    index_path = runs_root / "campaign_index.json"
    if not index_path.exists():
        typer.echo(
            f"campaign_index.json not found in {runs_root} - "
            f"run `aaosa campaign --runs-root {runs_root}` first (expected: {index_path})"
        )
        raise typer.Exit(code=1)

    index = CampaignIndex.model_validate_json(index_path.read_text(encoding="utf-8"))

    snapshots = []
    snap_dir = runs_root / "elo_snapshots"
    if snap_dir.exists():
        for f in sorted(snap_dir.glob("*.json")):
            if f.name == "latest.json":  # meme regle que _elo_history (dashboard)
                continue
            snapshots.append(load_snapshot(f))

    text = build_report(index, snapshots, runs_root=runs_root)
    out_path = runs_root / "campaign_report.md"
    out_path.write_text(text, encoding="utf-8")
    typer.echo(text)
    typer.echo(f"Report written to {out_path}")


@app.command()
def dashboard(
    port: int | None = typer.Option(None, "--port"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Dashboard d'observabilite (serveur dev Flask, equivalent `python -m dashboard`)."""
    cfg = (
        DashboardConfig(runs_root=runs_root)
        if port is None
        else DashboardConfig(runs_root=runs_root, port=port)
    )
    create_app(cfg).run(host=cfg.host, port=cfg.port, debug=True)


@app.command(name="health-check")
def health_check() -> None:
    """Boucle auto-amelioration B2 -> B3 -> re-triage sur le roster software (intact)."""
    load_dotenv()
    run_demo_health_check_v3()


if __name__ == "__main__":
    app()
