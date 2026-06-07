# V3 — Démo phase 5 : campagne N=20 + curation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer `aaosa report` (rapport de campagne markdown, TDD), exécuter la campagne réelle N=20, trancher le ticket aggregator au checkpoint humain, et curer les exhibits dans `runs_demo/` versionné + `docs/demo/exhibits.md`.

**Architecture:** `build_report(index, snapshots, runs_root=None) -> str` — fonction pure dans `src/aaosa/cli/report.py` (zéro print, zéro I/O, même contrat que `incident_runs.py`) ; le wiring (lecture `campaign_index.json` + snapshots, écriture `campaign_report.md`, echo) vit dans `app.py`. Tasks 3-5 = exécution réelle + curation avec checkpoints humains (zéro changement runtime, lignes rouges : zéro seed, aucun bouton tourné avant l'observation).

**Tech Stack:** Python 3.14, Typer 0.26.7, Pydantic 2.13 (`CampaignIndex`/`CampaignRunRecord`/`EloSnapshot` existants), pytest 9 (`CliRunner`), gpt-4o-mini pour la campagne réelle.

**Spec:** `docs/superpowers/specs/2026-06-07-v3-demo-phase5-campagne-curation-design.md`

**Écart spec assumé (à valider à la review)** : `build_report` prend un 3e paramètre optionnel `runs_root: Path | None = None` — la spec fixe la signature `(index, snapshots) -> str` mais exige aussi (§4.7) une commande de rejeu « prête à copier » qui nécessite le chemin. Paramètre additif, fonction toujours pure (un `Path` est une donnée), `None` → placeholder `<runs-root>`.

**Conventions projet (rappel pour l'exécutant)** :
- Toujours le venv : `.venv\Scripts\python -m pytest <fichier> -v` (jamais le Python système).
- Imports absolus uniquement (`from aaosa.cli.report import build_report`).
- Les helpers ne printent jamais — seul `app.py` echo.
- Strings echo/CLI sans accents (convention `app.py` existante) ; le contenu markdown du rapport et des docs peut porter des accents.

---

### Task 1: `build_report` — fonction pure (TDD)

**Files:**
- Create: `src/aaosa/cli/report.py`
- Create: `tests/cli/test_report.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/cli/test_report.py` avec ce contenu complet :

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aaosa.cli.incident_runs import CampaignIndex, CampaignRunRecord
from aaosa.cli.report import build_report
from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot

_T0 = datetime(2026, 6, 7, 18, 0, 0, tzinfo=timezone.utc)


def _record(
    i: int,
    outcome: str = "success",
    typologies: list[str] | None = None,
    error: str | None = None,
    duration_s: float = 30.0,
) -> CampaignRunRecord:
    started = _T0 + timedelta(minutes=i)
    return CampaignRunRecord(
        i=i,
        session_id=None if outcome == "error" else f"sess-{i}",
        outcome=outcome,
        typologies=typologies if typologies is not None else ["divided"],
        started_at=started,
        ended_at=started + timedelta(seconds=duration_s),
        error=error,
    )


def _index(records: list[CampaignRunRecord], n_requested: int = 20) -> CampaignIndex:
    return CampaignIndex(scenario="main", n_requested=n_requested, runs=records)


def _snapshot(minute: int, elos: dict[str, dict[str, int]]) -> EloSnapshot:
    return EloSnapshot(
        timestamp=_T0 + timedelta(minutes=minute),
        agents=[
            AgentEloSnapshot(agent_name=name, agent_id=f"id-{name}", tags_with_elo=tags)
            for name, tags in elos.items()
        ],
    )


class TestHeader:
    def test_scenario_and_counts(self):
        text = build_report(_index([_record(1), _record(2)], n_requested=20), [])
        assert "`main`" in text
        assert "Runs demandés : 20" in text
        assert "Runs exécutés : 2" in text

    def test_period_from_first_start_to_last_end(self):
        text = build_report(_index([_record(1), _record(2)]), [])
        assert "2026-06-07T18:01:00+00:00" in text  # started_at du run 1
        assert "2026-06-07T18:02:30+00:00" in text  # ended_at du run 2

    def test_empty_runs_render_dash_period(self):
        text = build_report(_index([], n_requested=20), [])
        assert "Période : —" in text


class TestOutcomes:
    def test_counts_and_percentages_in_fixed_order(self):
        records = [
            _record(1, outcome="success"),
            _record(2, outcome="success"),
            _record(3, outcome="qa_fail"),
            _record(4, outcome="error", typologies=[], error="boom"),
        ]
        text = build_report(_index(records), [])
        assert "- success : 2/4 (50%)" in text
        assert "- qa_fail : 1/4 (25%)" in text
        assert "- unassigned : 0/4 (0%)" in text
        assert "- error : 1/4 (25%)" in text
        # ordre fixe : success avant qa_fail avant unassigned avant error
        assert text.index("- success :") < text.index("- qa_fail :")
        assert text.index("- qa_fail :") < text.index("- unassigned :")
        assert text.index("- unassigned :") < text.index("- error :")


class TestTypologies:
    def test_counts_zeros_included_canonical_order(self):
        records = [
            _record(1, typologies=["divided", "recursion"]),
            _record(2, typologies=["divided", "aggregated"]),
            _record(3, typologies=["simple"]),
        ]
        text = build_report(_index(records), [])
        assert "- simple : 1" in text
        assert "- divided : 2" in text
        assert "- recursion : 1" in text
        assert "- roster_gap : 0" in text
        assert "- diagnosed:agent : 0" in text
        assert "- aggregated : 1" in text
        # ordre canonique classify_run : simple < divided < recursion <
        # roster_gap < diagnosed:* < aggregated
        assert text.index("- simple :") < text.index("- divided :")
        assert text.index("- recursion :") < text.index("- roster_gap :")
        assert text.index("- diagnosed:agent :") < text.index("- diagnosed:evaluator :")
        assert text.index("- diagnosed:evaluator :") < text.index("- diagnosed:task_spec :")
        assert text.index("- diagnosed:task_spec :") < text.index("- diagnosed:unattributed :")
        assert text.index("- diagnosed:unattributed :") < text.index("- aggregated :")


class TestAggregatorObservation:
    def test_zero_states_criterion_not_met(self):
        text = build_report(_index([_record(1)]), [])
        assert "## Observation aggregator" in text
        assert "**0/1 runs avec `TaskAggregatedEvent` réel.**" in text
        assert "Critère du ticket divider non atteint" in text

    def test_nonzero_counts_aggregated_runs(self):
        records = [
            _record(1, typologies=["divided", "aggregated"]),
            _record(2, typologies=["divided"]),
        ]
        text = build_report(_index(records), [])
        assert "**1/2 runs avec `TaskAggregatedEvent` réel.**" in text
        assert "Critère du ticket divider non atteint" not in text


class TestRunsTable:
    def test_nominal_row(self):
        text = build_report(_index([_record(1, duration_s=42.5)]), [])
        assert "| 1 | sess-1 | success | divided | 42.5s |" in text

    def test_error_row_renders_dashes_and_error_note(self):
        records = [_record(1, outcome="error", typologies=[], error="boom failure")]
        text = build_report(_index(records), [])
        assert "| 1 | — | error | — |" in text
        assert "run 1 error : boom failure" in text

    def test_no_error_note_without_errors(self):
        # NB : ne pas asserter sur "error :" tout court — la section Outcomes
        # contient toujours une ligne "- error : 0/..." ; la note d'erreur par
        # run a la forme "run <i> error :".
        text = build_report(_index([_record(1)]), [])
        assert "run 1 error :" not in text


class TestEloDelta:
    def test_zero_snapshots_degraded(self):
        text = build_report(_index([_record(1)]), [])
        assert "_Delta indisponible (moins de 2 snapshots)._" in text

    def test_one_snapshot_degraded(self):
        snaps = [_snapshot(0, {"backend-dev": {"logs": 50}})]
        text = build_report(_index([_record(1)]), snaps)
        assert "_Delta indisponible (moins de 2 snapshots)._" in text

    def test_delta_first_to_last_sorted_by_agent_then_tag(self):
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}, "sre": {"infra": 60}}),
            _snapshot(1, {"backend-dev": {"logs": 55}, "sre": {"infra": 58}}),
            _snapshot(2, {"backend-dev": {"logs": 70}, "sre": {"infra": 64}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | logs | 50 | 70 | +20 |" in text
        assert "| sre | infra | 60 | 64 | +4 |" in text
        assert text.index("backend-dev") < text.index("| sre |")

    def test_snapshots_sorted_by_timestamp_not_input_order(self):
        snaps = [
            _snapshot(2, {"backend-dev": {"logs": 70}}),
            _snapshot(0, {"backend-dev": {"logs": 50}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | logs | 50 | 70 | +20 |" in text

    def test_tag_absent_from_first_snapshot_renders_nouveau(self):
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}}),
            _snapshot(1, {"backend-dev": {"logs": 52, "code": 51}}),
        ]
        text = build_report(_index([_record(1)]), snaps)
        assert "| backend-dev | code | — | 51 | nouveau |" in text


class TestReplaySection:
    def test_runs_root_in_replay_command(self):
        text = build_report(_index([_record(1)]), [], runs_root=Path("runs_campaign_n20"))
        assert "aaosa dashboard --runs-root runs_campaign_n20" in text

    def test_without_runs_root_placeholder(self):
        text = build_report(_index([_record(1)]), [])
        assert "aaosa dashboard --runs-root <runs-root>" in text


class TestDeterminismAndSections:
    def test_same_input_same_output(self):
        records = [_record(1), _record(2, outcome="error", typologies=[], error="x")]
        snaps = [
            _snapshot(0, {"backend-dev": {"logs": 50}}),
            _snapshot(1, {"backend-dev": {"logs": 55}}),
        ]
        assert build_report(_index(records), snaps) == build_report(_index(records), snaps)

    def test_all_seven_sections_present(self):
        text = build_report(_index([_record(1)]), [])
        assert "# Rapport de campagne" in text          # 1. en-tête
        assert "## Outcomes" in text                     # 2.
        assert "## Typologies" in text                   # 3.
        assert "## Observation aggregator" in text       # 4.
        assert "## Runs" in text                         # 5.
        assert "## Delta ELO" in text                    # 6.
        assert "## Rejeu" in text                        # 7.
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_report.py -v`
Expected: ERREUR de collection — `ModuleNotFoundError: No module named 'aaosa.cli.report'`

- [ ] **Step 3: Implémenter `build_report`**

Créer `src/aaosa/cli/report.py` avec ce contenu complet :

```python
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
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_report.py -v`
Expected: tous PASS (19 tests)

- [ ] **Step 5: Vérifier la non-régression de la suite CLI**

Run: `.venv\Scripts\python -m pytest tests/cli -v`
Expected: tous PASS (les tests existants de `test_app.py` et `test_incident_runs.py` inchangés)

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/report.py tests/cli/test_report.py
git commit -m "feat(cli): build_report - rapport de campagne markdown pur (7 sections, observation aggregator)"
```

---

### Task 2: commande `aaosa report` (wiring Typer, TDD)

**Files:**
- Modify: `src/aaosa/cli/app.py` (imports lignes 13-23 + nouvelle commande après `campaign`, ligne ~83)
- Modify: `tests/cli/test_app.py` (nouvelle classe `TestReportCommand` en fin de fichier)

- [ ] **Step 1: Écrire les tests qui échouent**

Compléter les imports en tête de `tests/cli/test_app.py` (`timedelta` rejoint l'import datetime existant ; nouvel import elo) :

```python
from datetime import datetime, timedelta, timezone

from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot
```

Puis ajouter en fin de fichier :

```python
class TestReportCommand:
    def test_missing_index_exits_1_with_path(self, tmp_path):
        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 1
        assert "campaign_index.json" in result.output
        assert str(tmp_path) in result.output

    def _populate_store(self, tmp_path: Path) -> None:
        index = CampaignIndex(
            scenario="main",
            n_requested=1,
            runs=[
                CampaignRunRecord(
                    i=1, session_id="sess-1", outcome="success",
                    typologies=["divided"], started_at=_NOW, ended_at=_NOW,
                )
            ],
        )
        (tmp_path / "campaign_index.json").write_text(
            index.model_dump_json(indent=2), encoding="utf-8"
        )

    def test_nominal_writes_file_and_echoes(self, tmp_path):
        self._populate_store(tmp_path)

        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        report_path = tmp_path / "campaign_report.md"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "# Rapport de campagne" in content
        assert f"aaosa dashboard --runs-root {tmp_path}" in content
        assert "# Rapport de campagne" in result.output
        assert str(report_path) in result.output

    def test_snapshots_read_sorted_latest_excluded(self, tmp_path, monkeypatch):
        self._populate_store(tmp_path)
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir()
        # deux snapshots horodatés + un latest.json (doit être ignoré :
        # même règle que _elo_history du dashboard)
        for name, minute, elo in [
            ("2026-06-07T18-00-00.json", 0, 50),
            ("2026-06-07T18-05-00.json", 5, 60),
            ("latest.json", 5, 60),
        ]:
            snap = EloSnapshot(
                timestamp=_NOW + timedelta(minutes=minute),
                agents=[
                    AgentEloSnapshot(
                        agent_name="backend-dev",
                        agent_id="id-1",
                        tags_with_elo={"logs": elo},
                    )
                ],
            )
            (snap_dir / name).write_text(snap.model_dump_json(indent=2), encoding="utf-8")
        captured = {}
        real_build_report = app_module.build_report

        def spy(index, snapshots, runs_root=None):
            captured["n_snapshots"] = len(snapshots)
            return real_build_report(index, snapshots, runs_root=runs_root)

        monkeypatch.setattr(app_module, "build_report", spy)
        result = runner.invoke(app, ["report", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["n_snapshots"] == 2  # latest.json exclu
        content = (tmp_path / "campaign_report.md").read_text(encoding="utf-8")
        assert "| backend-dev | logs | 50 | 60 | +10 |" in content
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app.py::TestReportCommand -v`
Expected: FAIL — `report` n'existe pas (`exit_code == 2`, usage error) et `app_module.build_report` absent (`AttributeError`)

- [ ] **Step 3: Implémenter la commande**

Dans `src/aaosa/cli/app.py` :

(a) Ajouter aux imports (bloc `from aaosa.cli.incident_runs import ...`, ligne 13) :

```python
from aaosa.cli.incident_runs import (
    CampaignIndex,
    StoreNotEmptyError,
    ensure_empty_store,
    run_campaign,
    run_once,
)
from aaosa.cli.report import build_report
from aaosa.elo.persistence import load_snapshot
```

(b) Ajouter la commande après `campaign` (avant `dashboard`) :

```python
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
            if f.name == "latest.json":  # même règle que _elo_history (dashboard)
                continue
            snapshots.append(load_snapshot(f))

    text = build_report(index, snapshots, runs_root=runs_root)
    out_path = runs_root / "campaign_report.md"
    out_path.write_text(text, encoding="utf-8")
    typer.echo(text)
    typer.echo(f"Report written to {out_path}")
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app.py -v`
Expected: tous PASS (existants + 3 nouveaux `TestReportCommand`)

- [ ] **Step 5: Suite complète**

Run: `.venv\Scripts\python -m pytest`
Expected: tous PASS (968 existants + 22 nouveaux = ~990, 1 skip conditionnel possible sur master)

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): aaosa report - ecrit campaign_report.md + echo (index requis, latest.json exclu)"
```

---

### Task 3: campagne réelle N=20 + rapport — CHECKPOINT HUMAIN

**Files:** aucun changement de code. Produit : `runs_campaign_n20/` (gitignoré par `runs_campaign*/`) peuplé de 20 sessions + index + rapport.

**Pré-requis** : `.env` avec `OPENAI_API_KEY` à la racine. Lignes rouges : température, prompts, tâche-mère = EXACTEMENT l'état du repo (aucun bouton tourné avant l'observation).

- [ ] **Step 1: Vérifier que le root de campagne n'existe pas**

Run (PowerShell): `Test-Path runs_campaign_n20`
Expected: `False`. Si `True` → STOP, demander à Quentin (jamais de cleanup auto — ligne rouge).

- [ ] **Step 2: Lancer la campagne N=20**

Run: `.venv\Scripts\aaosa campaign --n 20 --scenario main --runs-root runs_campaign_n20`
Expected: echo `run i/20: <outcome> [typologies]` pour i=1..20, puis `X/20 success - index: runs_campaign_n20\campaign_index.json`. Durée attendue : 30-90 min (≈2-4 min/run divisé observés en phase 4). Pas de `latest.json` préexistant → départ ELO YAML (décision spec §2).

- [ ] **Step 3: Vérifier l'index complet**

Run: `.venv\Scripts\python -c "import json; idx = json.load(open('runs_campaign_n20/campaign_index.json', encoding='utf-8')); print(len(idx['runs']), 'runs'); print({r['outcome'] for r in idx['runs']})"`
Expected: `20 runs` + l'ensemble des outcomes observés.

- [ ] **Step 4: Générer le rapport**

Run: `.venv\Scripts\aaosa report --runs-root runs_campaign_n20`
Expected: rapport markdown complet en console + `Report written to runs_campaign_n20\campaign_report.md`. Spot-check : la table « Runs » a 20 lignes, la section « Observation aggregator » donne un count explicite, le delta ELO est rempli (20 snapshots).

- [ ] **Step 5: CHECKPOINT — dépouillement avec Quentin**

Présenter le rapport. À trancher ensemble (rien n'est pré-committé, spec §6) :

1. **Ticket aggregator** : ≥1 `aggregated` → critère atteint, ticket clos. 0/20 → choisir entre les 3 options consignées au ticket (tâche-mère moins séquentielle · température divider · assumer « filet pour les vrais fan-ins ») — décision loggée, toute retouche = chantier séparé hors phase 5.
2. **Sélection des exhibits** (3-5 sessions, une par typologie exhibée) pour la Task 4 : noter les session_ids retenus + ce que chacun montre. Récolte D3/D4 (`diagnosed:*`) et `recursion` examinée ; absence = documentée, jamais comblée par seed (ligne rouge).

NE PAS passer à la Task 4 sans ce checkpoint.

---

### Task 4: curation — `runs_demo/` versionné + `docs/demo/exhibits.md` — CHECKPOINT HUMAIN

**Files:**
- Create: `runs_demo/` (sessions sélectionnées + registry + snapshots + index + rapport — versionné, aucun pattern `.gitignore` ne le couvre, vérifié)
- Create: `docs/demo/exhibits.md`

**Entrée** : les session_ids sélectionnés au checkpoint Task 3 (notés `<SID-1>`, `<SID-2>`, … ci-dessous — valeurs réelles connues au checkpoint uniquement).

- [ ] **Step 1: Peupler `runs_demo/` depuis le store de campagne**

Run (PowerShell, un `Copy-Item` par session sélectionnée) :

```powershell
New-Item -ItemType Directory -Force runs_demo\sessions
Copy-Item -Recurse runs_campaign_n20\sessions\<SID-1> runs_demo\sessions\
Copy-Item -Recurse runs_campaign_n20\sessions\<SID-2> runs_demo\sessions\
# ... une ligne par session retenue
Copy-Item -Recurse runs_campaign_n20\agents runs_demo\agents
Copy-Item -Recurse runs_campaign_n20\elo_snapshots runs_demo\elo_snapshots
Copy-Item runs_campaign_n20\campaign_index.json runs_demo\
Copy-Item runs_campaign_n20\campaign_report.md runs_demo\
```

Les 20 snapshots sont copiés en entier (les courbes « le roster après 20 incidents » ont besoin de toute la série, spec §7) ; `latest.json` inclus (inoffensif, le dashboard l'ignore).

- [ ] **Step 2: Exhibit roster_gap (si retenu) — run unitaire dans un root jetable**

Le scénario roster_gap est systématique (pas besoin de campagne), mais NE PAS le lancer dans `runs_campaign_n20/` ni `runs_demo/` : `run_once` sauverait le registry du roster à 6 agents par-dessus celui à 7 (perte des modals dpo-jurist au dashboard).

```powershell
.venv\Scripts\aaosa run --scenario roster_gap --runs-root runs_rg_staging
Copy-Item -Recurse runs_rg_staging\sessions\* runs_demo\sessions\
Remove-Item -Recurse -Force runs_rg_staging -Confirm:$false
```

(La session porte son propre `agents.json` — le tab Sessions du dashboard rend cross-roster sans toucher au registry.)

- [ ] **Step 3: Vérifier le rendu dashboard du store curé**

Run: `.venv\Scripts\aaosa dashboard --runs-root runs_demo --port 5005`
Vérifier au navigateur (http://127.0.0.1:5005) : tab Sessions liste les exhibits et chaque graphe se rejoue ; tab Agents montre les courbes ELO sur 20 snapshots. C'est le test du chemin « clone frais » (DoD §8.5).

- [ ] **Step 4: Écrire `docs/demo/exhibits.md`**

Structure imposée (contenu réel rempli depuis le checkpoint Task 3) :

```markdown
# Démo AAOSA — Exhibits curés (campagne N=20 du 2026-06-XX)

Sélection de runs 100 % naturels (zéro seed — ligne rouge du cadrage démo) issus
de la campagne `runs_campaign_n20` (gpt-4o-mini, temp 0, départ ELO YAML).
Données brutes : `runs_demo/campaign_index.json` · rapport : `runs_demo/campaign_report.md`.

## Rejeu (clone frais)

    .venv\Scripts\aaosa dashboard --runs-root runs_demo

Tab Sessions = les exhibits ci-dessous · tab Agents = courbes ELO « le roster après 20 incidents ».

## Exhibits

### <SID-1> — divided + success
<2-3 phrases : ce que le run montre, orienté narration démo — ex. claiming
compétitif 3 domaines, récupération D1, 5 sous-tâches QA PASS.>

### <SID-2> — roster_gap
<2-3 phrases — RosterGapEvent [gdpr] dès la racine, 0 appel agent : le système
nomme le trou de roster au lieu d'halluciner une réponse.>

### <SID-n> — <typologie>
<...>

## Typologies non observées sur N=20

<Liste honnête des typologies absentes de la campagne (ex. diagnosed:*,
aggregated) — non observées naturellement, jamais provoquées (curation ≠ seeding).
Relancer des campagnes plus tard est non bloquant (brainstorm Q14).>

## Curation — provenance

Copie manuelle depuis `runs_campaign_n20/` (sessions sélectionnées + registry +
20 snapshots ELO + index + rapport), exhibit roster_gap depuis un run unitaire
en root jetable. Commandes consignées dans le plan phase 5.
```

- [ ] **Step 5: CHECKPOINT — rejeu navigateur des 3 typologies avec Quentin**

Sign-off requis (DoD §8.4) : divided-success + roster_gap + 1 typologie curée selon récolte (recursion / diagnosed / aggregated), chacune déroulée au navigateur depuis `runs_demo/`. NE PAS committer avant le sign-off.

- [ ] **Step 6: Commit du store curé + doc**

```bash
git add runs_demo/ docs/demo/exhibits.md
git commit -m "feat(demo): runs_demo/ store cure versionne + exhibits.md - campagne N=20, rejeu clone frais"
```

---

### Task 5: clôture — ticket, CLAUDE.md

**Files:**
- Modify: `docs/backlog/2026-06-07-divider-topologie-aggregator.md` (section « Décision et résultat d'observation » + critères d'acceptation)
- Modify: `CLAUDE.md` (bloc « État courant » + arbre architecture + commandes)

- [ ] **Step 1: Mettre à jour le ticket divider**

Dans `docs/backlog/2026-06-07-divider-topologie-aggregator.md` :
- Cocher ou amender le critère `- [ ] Si « retirer » : observer ≥1 run réel avec TaskAggregatedEvent...` selon le résultat N=20 (≥1 → coché + session_id ; 0 → constat N=20 documenté + décision du checkpoint Task 3 consignée avec sa justification).
- Ajouter une section datée « Résultat N=20 (phase 5) » : count `aggregated`, lecture (chaînes pures encore ? topologies observées), décision prise et prochaine étape éventuelle (chantier séparé, hors phase 5).

- [ ] **Step 2: Mettre à jour CLAUDE.md**

Trois edits (valeurs réelles connues à l'exécution) :
1. Bloc état courant : ajouter le paragraphe « **V3 — démo phase 5 : campagne N=20 + curation — <N> tests total** (2026-06-XX) : `aaosa report` (`build_report` pur 7 sections, observation aggregator explicite) · campagne N=20 réelle (X/20 success, typologies, résultat aggregator + décision) · `runs_demo/` versionné + `docs/demo/exhibits.md` (rejeu clone frais) · ticket divider <clos|tranché : option choisie>. »
2. Arbre architecture : dans le bloc `cli/`, ajouter `report.py (build_report pur)` et la commande `report` dans la liste `app.py` ; ajouter `runs_demo/` et `docs/demo/` dans l'arborescence racine.
3. Section « Stack et commandes » : ajouter `aaosa report [--runs-root]` à la liste CLI.

- [ ] **Step 3: Suite complète (garde-fou final)**

Run: `.venv\Scripts\python -m pytest`
Expected: tous PASS (même count que Task 2 Step 5 — les Tasks 3-5 n'ont pas touché au code).

- [ ] **Step 4: Commit**

```bash
git add docs/backlog/2026-06-07-divider-topologie-aggregator.md CLAUDE.md
git commit -m "docs: phase 5 livree - campagne N=20 depouillee, ticket divider mis a jour, CLAUDE.md"
```

---

## Self-review du plan (faite à l'écriture)

- **Couverture spec** : §4 rapport → Tasks 1-2 · §5 campagne → Task 3 · §6 checkpoint aggregator → Task 3 Step 5 · §7 curation → Task 4 · §8 TDD+DoD → Tasks 1-2 (TDD) + Tasks 3-5 (DoD 1-6 ; DoD 5 = Task 4 Step 3) · §9 limites → consignes inline (zéro cleanup, zéro seed, root jetable roster_gap).
- **Placeholders** : `<SID-n>`, `<N>`, `2026-06-XX` sont des **données de runtime** (connues au checkpoint Task 3 / à l'exécution), pas des trous de design — chaque étape dit d'où vient la valeur.
- **Cohérence de types** : `build_report(index: CampaignIndex, snapshots: list[EloSnapshot], runs_root: Path | None = None)` identique en Task 1 (def), Task 2 (import + spy 3 params) ; `_TYPOLOGY_ORDER` aligné sur `_DIAGNOSED_ORDER = (agent, evaluator, task_spec, unattributed)` vérifié dans `analysis.py:68` — les tests `TestTypologies` assertent ce même ordre.
- **Piège évité** : exhibit roster_gap jamais lancé dans un store à conserver (écrasement registry 7→6 agents) — root jetable + copie de session.
