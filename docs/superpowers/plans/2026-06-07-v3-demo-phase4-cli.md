# V3 — Démo phase 4 : CLI `aaosa` (Typer) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer les scripts jetables (`run_incident.py`, `run_demo_v3.py`) par un CLI Typer projet-wide `aaosa` (`run` · `campaign` · `dashboard` · `health-check`), trancher le ticket divider/topologie (prompt réécrit), et outiller la phase 5 (`classify_run` + `campaign_index.json` crash-safe + ELO chaîné).

**Architecture:** Package `src/aaosa/cli/` — `app.py` (wiring Typer fin, seul endroit qui printe) + `incident_runs.py` (helpers purs sans print ni Typer : `run_once`, `run_campaign`, garde-fou, ELO). Prompts dans `demo/incident/prompts.py` (single home). Classification dans `tracing/analysis.py` (opère sur events, réutilisable dashboard). Zéro changement runtime (`runner.py`/`store.py` intouchés).

**Tech Stack:** Python 3.14, Typer (dernière stable via `uv add`), Pydantic 2.13, pytest 9 (`typer.testing.CliRunner` pour le parsing).

**Spec:** `docs/superpowers/specs/2026-06-07-v3-demo-phase4-cli-design.md`

**Écarts assumés vs spec (validés à la review du plan) :**
1. `outcome` d'index : la spec liste `success`/`unassigned`/`error`, mais `run_with_recovery` peut aussi retourner `QAFailure` (`runner.py:404-438`). Le plan ajoute **`qa_fail`** comme 4e valeur d'index (plus honnête que de l'écraser en `unassigned`).
2. `pyproject.toml` : `packages = ["src/aaosa", "dashboard"]` — sans ça, le console script `aaosa` ne peut pas importer `dashboard` (l'install editable n'expose que `src/aaosa` ; `python -m dashboard` ne marchait que grâce au CWD).
3. `ensure_empty_store` lève `StoreNotEmptyError` (exception dédiée, pas `typer.Exit`) — `app.py` la convertit en `typer.Exit(code=1)`. Cohérent §7 (« les helpers ne printent pas »).
4. `RunOutcome.n_agents` : porte la taille du roster pour l'en-tête console (le helper ne printe pas, `app.py` a besoin de l'info).
5. `aaosa dashboard --runs-root` (la spec ne prévoit que `--port`) : expose le champ existant `DashboardConfig.runs_root` — nécessaire au DoD pour rendre les sessions de la mini-campagne (root frais exigé par le garde-fou), et cohérent avec `run`/`campaign`.

---

## File Structure

```
src/aaosa/cli/__init__.py            # CRÉÉ (vide)
src/aaosa/cli/app.py                 # CRÉÉ — Typer app : run · campaign · dashboard · health-check
src/aaosa/cli/incident_runs.py       # CRÉÉ — run_once · run_campaign · ensure_empty_store · load_elo_into · modèles index
src/aaosa/demo/incident/prompts.py   # CRÉÉ — DIVIDER_PROMPT (réécrit) · AGGREGATOR_PROMPT · TAGGER_PROMPT
src/aaosa/tracing/analysis.py        # MODIFIÉ — + classify_run
pyproject.toml                       # MODIFIÉ — + typer · [project.scripts] · packages dashboard
uv.lock                              # MODIFIÉ — commité dans le même mouvement (leçon phase 2)

src/aaosa/demo/incident/run_incident.py  # SUPPRIMÉ (remplacé par le CLI — destin déclaré phase 3)
src/aaosa/demo/run_demo_v3.py            # SUPPRIMÉ (subsumé par la démo incident, contredit la thèse D1)
tests/demo/test_run_demo_v3.py           # SUPPRIMÉ

tests/tracing/test_analysis.py       # MODIFIÉ — + TestClassifyRun
tests/demo/incident/test_prompts.py  # CRÉÉ — verrous du ticket divider
tests/cli/__init__.py                # CRÉÉ (vide)
tests/cli/test_incident_runs.py      # CRÉÉ
tests/cli/test_app.py                # CRÉÉ
```

Imports absolus uniquement. Timestamps : `datetime.now(timezone.utc)`. `extra="forbid"` sur les nouveaux modèles Pydantic.

---

### Task 1: `classify_run` (`tracing/analysis.py`)

Fonction pure : `Sequence[ClaimEvent] -> list[str]`, labels de typologie dans un ordre canonique fixe. Consommée par `run_campaign` (Task 5), réutilisable par le dashboard plus tard.

**Files:**
- Modify: `src/aaosa/tracing/analysis.py`
- Test: `tests/tracing/test_analysis.py` (le fichier existe — ajouter imports + classe à la fin)

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter aux imports existants de `tests/tracing/test_analysis.py` :

```python
from aaosa.tracing.analysis import classify_run, detect_overclaims, detect_underclaims
from aaosa.tracing.events import (
    DiagnosedEvent,
    DividedSubTask,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
```

(`detect_overclaims`/`detect_underclaims`, `Phase1FilteredEvent`/`Phase2ClaimedEvent` sont déjà importés — ne garder qu'une ligne d'import par module, fusionner.)

Ajouter à la fin du fichier :

```python
def _divided(task_id: str, sub_ids: list[str]) -> TaskDividedEvent:
    return TaskDividedEvent(
        session_id="sess1",
        task_id=task_id,
        sub_tasks=[DividedSubTask(id=i, description=f"sub {i}") for i in sub_ids],
    )


def _gap() -> RosterGapEvent:
    return RosterGapEvent(session_id="sess1", task_id="task1", missing_tags=["gdpr"])


def _diag(attribution: str) -> DiagnosedEvent:
    return DiagnosedEvent(
        session_id="sess1", task_id="task1", attribution=attribution, reason="r"
    )


def _agg() -> TaskAggregatedEvent:
    return TaskAggregatedEvent(
        session_id="sess1",
        task_id="task1",
        sub_task_ids=["s1", "s2"],
        output_summary="merged",
        output_content="merged content",
    )


class TestClassifyRun:
    """Typologies détectées depuis la trace, ordre canonique fixe (spec phase 4 §5)."""

    def test_empty_trace_is_simple(self):
        assert classify_run([]) == ["simple"]

    def test_claiming_events_alone_are_simple(self):
        p1 = Phase1FilteredEvent(
            session_id="sess1", task_id="task1", agent_id="a1",
            passed=True, fit_score=1.0,
        )
        assert classify_run([p1]) == ["simple"]

    def test_divided(self):
        assert classify_run([_divided("root", ["s1", "s2"])]) == ["divided"]

    def test_recursion_when_division_is_nested(self):
        # s1 est une sous-tâche de root ET le parent d'une autre division → D1 récursif
        events = [_divided("root", ["s1", "s2"]), _divided("s1", ["s1a", "s1b"])]
        assert classify_run(events) == ["divided", "recursion"]

    def test_sibling_divisions_are_not_recursion(self):
        events = [_divided("root-a", ["x"]), _divided("root-b", ["y"])]
        assert classify_run(events) == ["divided"]

    def test_roster_gap(self):
        assert classify_run([_gap()]) == ["simple", "roster_gap"]

    def test_diagnosed_one_label_per_distinct_attribution(self):
        # task_spec émis avant agent, agent en double → ordre canonique, dédupliqué
        events = [_diag("task_spec"), _diag("agent"), _diag("agent")]
        assert classify_run(events) == ["simple", "diagnosed:agent", "diagnosed:task_spec"]

    def test_aggregated(self):
        events = [_divided("root", ["s1", "s2"]), _agg()]
        assert classify_run(events) == ["divided", "aggregated"]

    def test_full_combination_canonical_order(self):
        # Events volontairement mélangés : l'ordre des labels ne dépend pas de la trace
        events = [
            _agg(),
            _diag("unattributed"),
            _gap(),
            _divided("root", ["s1", "s2"]),
            _divided("s1", ["s1a"]),
            _diag("evaluator"),
        ]
        assert classify_run(events) == [
            "divided",
            "recursion",
            "roster_gap",
            "diagnosed:evaluator",
            "diagnosed:unattributed",
            "aggregated",
        ]
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_analysis.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_run'`

- [ ] **Step 3: Implémenter `classify_run`**

Dans `src/aaosa/tracing/analysis.py`, remplacer la ligne d'import et ajouter la fonction à la fin :

```python
from collections.abc import Sequence

from aaosa.tracing.events import (
    ClaimEvent,
    DiagnosedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
```

```python
_DIAGNOSED_ORDER = ("agent", "evaluator", "task_spec", "unattributed")


def classify_run(events: Sequence[ClaimEvent]) -> list[str]:
    """Typologies d'un run détectées depuis la trace, ordre canonique fixe.

    `simple` et `divided` sont mutuellement exclusifs ; les autres labels se
    cumulent. `aggregated` = agrégation réelle uniquement (le court-circuit
    1-sink n'émet pas de TaskAggregatedEvent, règle D2). Fonction pure sans I/O.
    """
    divided = [e for e in events if isinstance(e, TaskDividedEvent)]
    labels = ["divided" if divided else "simple"]

    sub_ids = {st.id for e in divided for st in e.sub_tasks}
    if any(e.task_id in sub_ids for e in divided):
        labels.append("recursion")

    if any(isinstance(e, RosterGapEvent) for e in events):
        labels.append("roster_gap")

    seen = {e.attribution for e in events if isinstance(e, DiagnosedEvent)}
    labels.extend(f"diagnosed:{a}" for a in _DIAGNOSED_ORDER if a in seen)

    if any(isinstance(e, TaskAggregatedEvent) for e in events):
        labels.append("aggregated")

    return labels
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_analysis.py -v`
Expected: PASS (tests existants + 9 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/analysis.py tests/tracing/test_analysis.py
git commit -m "feat(tracing): classify_run - typologies d'un run depuis la trace (phase 4)"
```

---

### Task 2: Prompts incident (`demo/incident/prompts.py`) — ticket divider tranché

Single home des 3 prompts système. Aggregator et tagger migrent **tels quels** depuis `run_incident.py` ; divider **réécrit** (spec §6) : disparition de « include a final synthesis sub-task » et de « ordered ». Tests = verrous de la décision (pattern du verrou gap-detection tagger, `f6ac272`).

**Files:**
- Create: `src/aaosa/demo/incident/prompts.py`
- Test: `tests/demo/incident/test_prompts.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/demo/incident/test_prompts.py` :

```python
from aaosa.demo.incident.prompts import AGGREGATOR_PROMPT, DIVIDER_PROMPT, TAGGER_PROMPT


class TestDividerPromptTopologyDecision:
    """Verrous du ticket divider/topologie (2026-06-07) : le divider décide
    librement la topologie — aucune découpe hardcodée dans le prompt."""

    def test_no_forced_synthesis_subtask(self):
        # « include a final synthesis sub-task » garantissait un sink unique
        # → court-circuit D2 systématique, aggregator code mort
        assert "synthesis" not in DIVIDER_PROMPT.lower()

    def test_no_ordered_constraint(self):
        # « ordered » poussait vers le strictement séquentiel (chaîne pure = 1 sink)
        assert "ordered" not in DIVIDER_PROMPT.lower()

    def test_dependencies_only_when_genuinely_needed(self):
        assert "only when" in DIVIDER_PROMPT


def test_all_prompts_non_empty():
    for prompt in (DIVIDER_PROMPT, AGGREGATOR_PROMPT, TAGGER_PROMPT):
        assert prompt.strip()
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/demo/incident/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.demo.incident.prompts'`

- [ ] **Step 3: Créer `prompts.py`**

Créer `src/aaosa/demo/incident/prompts.py` :

```python
"""Prompts système de la démo incident — single home (consommés par le CLI).

DIVIDER_PROMPT réécrit le 2026-06-07 (ticket divider/topologie) : retrait de
« include a final synthesis sub-task » (garantissait un consommateur terminal
unique → court-circuit D2 systématique) et de « ordered » (poussait vers le
strictement séquentiel). Le divider décide librement la topologie → des découpes
auront ≥2 sinks → l'aggregator D2 devient démontrable.
"""

DIVIDER_PROMPT = (
    "You are a task decomposer. Break the task into the minimal set of "
    "sub-tasks needed to fully resolve it. Express a dependency between two "
    "sub-tasks only when one genuinely needs the other's output. Prefer few, "
    "well-scoped sub-tasks."
)

AGGREGATOR_PROMPT = (
    "You are a synthesizer. Merge the sub-task results into one coherent, complete "
    "answer to the original incident."
)

TAGGER_PROMPT = (
    "You assign capability tags to a task description. Use the roster vocabulary "
    "when it fits; name a real capability even if absent. Return at least one tag."
)
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `.venv\Scripts\python -m pytest tests/demo/incident/test_prompts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/demo/incident/prompts.py tests/demo/incident/test_prompts.py
git commit -m "feat(demo): prompts incident single-home, divider reecrit (ticket topologie tranche)"
```

---

### Task 3: Infra CLI — typer, entry point, packages, squelette `aaosa.cli`

Pas de TDD ici (config + squelette sans logique). `uv.lock` commité dans le même mouvement que l'ajout de typer (leçon phase 2 : désync lock).

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (généré)
- Create: `src/aaosa/cli/__init__.py`
- Create: `src/aaosa/cli/app.py` (squelette — les commandes arrivent en Task 6)

- [ ] **Step 1: Ajouter typer**

Run: `uv add typer`
Expected: typer (dernière stable) ajouté à `[project.dependencies]` de `pyproject.toml`, `uv.lock` mis à jour, venv synchronisé.

- [ ] **Step 2: Entry point + packages dashboard**

Dans `pyproject.toml`, ajouter la section scripts après `[project.optional-dependencies]` :

```toml
[project.scripts]
aaosa = "aaosa.cli.app:app"
```

et modifier la cible wheel (le console script doit pouvoir importer `dashboard` — l'install editable n'expose que les packages déclarés) :

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/aaosa", "dashboard"]
```

- [ ] **Step 3: Créer le squelette du package**

Créer `src/aaosa/cli/__init__.py` (vide).

Créer `src/aaosa/cli/app.py` :

```python
"""CLI projet-wide `aaosa` — entrée unique des points d'exécution du projet.

Wiring console fin uniquement : la logique run/campaign vit dans
`aaosa.cli.incident_runs` (helpers purs, sans print).
"""

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Réinstaller et vérifier le console script**

Run: `uv sync --all-extras`
Run: `.venv\Scripts\aaosa --help`
Expected: usage Typer affiché (aucune commande encore), exit code 0.

Run: `.venv\Scripts\python -c "import dashboard.app; print('dashboard importable')"`
Expected: `dashboard importable`

- [ ] **Step 5: Suite complète (non-régression installation)**

Run: `.venv\Scripts\python -m pytest tests/ -q`
Expected: PASS (926+ tests — aucun test ne touche encore au CLI)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/aaosa/cli/__init__.py src/aaosa/cli/app.py
git commit -m "feat(cli): infra Typer - dependance, entry point aaosa, package dashboard expose"
```

---

### Task 4: Helpers `incident_runs.py` — garde-fou, ELO, `run_once`

`ensure_empty_store` et `load_elo_into` en TDD. `run_once` = wiring pur (migration de `run_incident.py` + ELO load + prompts importés) — **pas de test unitaire dédié, conformément à la spec §8** (le DoD réel Task 8 le couvre ; il orchestre des appels LLM, le stubber reviendrait à tester du mock). Aucun print, aucune dépendance Typer dans ce module.

**Files:**
- Create: `src/aaosa/cli/incident_runs.py`
- Test: `tests/cli/__init__.py` (vide), `tests/cli/test_incident_runs.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/cli/__init__.py` (vide), puis `tests/cli/test_incident_runs.py` :

```python
import pytest

from aaosa.cli.incident_runs import (
    StoreNotEmptyError,
    ensure_empty_store,
    load_elo_into,
)
from aaosa.core.agent import Agent
from aaosa.elo.persistence import save_snapshot


def _agent(name: str, tags: dict[str, int] | None = None) -> Agent:
    return Agent(
        name=name,
        system_prompt="system prompt",
        tags_with_elo=tags if tags is not None else {"security": 50},
    )


class TestEnsureEmptyStore:
    def test_missing_root_ok(self, tmp_path):
        ensure_empty_store(tmp_path / "fresh")  # ne lève pas

    def test_empty_sessions_dir_ok(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        ensure_empty_store(tmp_path)  # ne lève pas

    def test_populated_sessions_refused(self, tmp_path):
        (tmp_path / "sessions" / "2026-06-07T18-00-00-abcd1234").mkdir(parents=True)
        with pytest.raises(StoreNotEmptyError) as exc_info:
            ensure_empty_store(tmp_path)
        # le message nomme le chemin peuplé et suggère un root frais
        assert str(tmp_path / "sessions") in str(exc_info.value)
        assert "--runs-root" in str(exc_info.value)

    def test_other_store_content_does_not_trigger(self, tmp_path):
        # agents/ et elo_snapshots/ seuls ne déclenchent pas le garde-fou
        (tmp_path / "agents").mkdir()
        (tmp_path / "elo_snapshots").mkdir()
        ensure_empty_store(tmp_path)  # ne lève pas


class TestLoadEloInto:
    def test_absent_snapshot_leaves_elo_intact(self, tmp_path):
        agent = _agent("log-analyst", {"security": 50, "forensics": 40})
        assert load_elo_into([agent], tmp_path) is False
        assert agent.tags_with_elo == {"security": 50, "forensics": 40}

    def test_roundtrip_load_apply_on_fresh_roster(self, tmp_path):
        donor = _agent("log-analyst", {"security": 72, "forensics": 61})
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir(parents=True)
        save_snapshot([donor], snap_dir)

        fresh = _agent("log-analyst", {"security": 50, "forensics": 40})
        assert load_elo_into([fresh], tmp_path) is True
        assert fresh.tags_with_elo == {"security": 72, "forensics": 61}

    def test_snapshot_name_absent_from_roster_is_ignored(self, tmp_path):
        # cas roster_gap : dpo-jurist dans le snapshot, absent du roster → pas d'erreur
        donor = _agent("dpo-jurist", {"gdpr": 80})
        snap_dir = tmp_path / "elo_snapshots"
        snap_dir.mkdir(parents=True)
        save_snapshot([donor], snap_dir)

        fresh = _agent("log-analyst", {"security": 50})
        assert load_elo_into([fresh], tmp_path) is True
        assert fresh.tags_with_elo == {"security": 50}
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.cli.incident_runs'`

- [ ] **Step 3: Implémenter `incident_runs.py` (helpers + `run_once`)**

Créer `src/aaosa/cli/incident_runs.py` :

```python
"""Helpers partagés des commandes `aaosa run` / `aaosa campaign`.

Zéro print, zéro dépendance Typer : le wiring console vit dans app.py
(les helpers restent testables sans capture de sortie).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import OpenAI

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
    if isinstance(result, Output):
        kind: RunKind = "success"
    elif isinstance(result, QAFailure):
        kind = "qa_fail"
    else:
        kind = "unassigned"

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
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/incident_runs.py tests/cli/__init__.py tests/cli/test_incident_runs.py
git commit -m "feat(cli): incident_runs - garde-fou store, ELO load-by-name, run_once"
```

---

### Task 5: `run_campaign` + index crash-safe (`incident_runs.py`)

Boucle N runs séquentiels dans le même process. `run_once` appelé comme global de module (monkeypatchable). Index réécrit après **chaque** run (un Ctrl-C — `KeyboardInterrupt`, hors `except Exception` — ne perd que le run en cours). Containment : une exception d'un run → entrée `error`, la boucle continue.

**Files:**
- Modify: `src/aaosa/cli/incident_runs.py`
- Test: `tests/cli/test_incident_runs.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/cli/test_incident_runs.py` — compléter les imports :

```python
from pathlib import Path

from aaosa.cli import incident_runs
from aaosa.cli.incident_runs import (
    CampaignIndex,
    RunOutcome,
    StoreNotEmptyError,
    ensure_empty_store,
    load_elo_into,
    run_campaign,
)
from aaosa.tracing.events import DividedSubTask, TaskDividedEvent
```

et la classe :

```python
def _fake_outcome(i: int, tmp_path: Path, kind: str = "success", events=None) -> RunOutcome:
    return RunOutcome(
        kind=kind,
        session_id=f"sess-{i}",
        session_dir=tmp_path / "sessions" / f"sess-{i}",
        snapshot_path=tmp_path / "elo_snapshots" / "latest.json",
        events=list(events or []),
        task_description="incident task",
        n_agents=7,
    )


class TestRunCampaign:
    def test_runs_n_iterations_sequentially(self, tmp_path, monkeypatch):
        calls = []

        def stub(scenario, runs_root, client):
            calls.append((scenario, runs_root))
            return _fake_outcome(len(calls), tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert calls == [("main", tmp_path)] * 3
        assert index.scenario == "main"
        assert index.n_requested == 3
        assert [r.i for r in index.runs] == [1, 2, 3]
        assert [r.session_id for r in index.runs] == ["sess-1", "sess-2", "sess-3"]
        assert all(r.outcome == "success" for r in index.runs)

    def test_index_written_after_each_run(self, tmp_path, monkeypatch):
        # crash-safe : au début du run k, l'index sur disque contient k-1 entrées
        index_path = tmp_path / "campaign_index.json"
        runs_on_disk_at_start = []

        def stub(scenario, runs_root, client):
            if index_path.exists():
                on_disk = CampaignIndex.model_validate_json(
                    index_path.read_text(encoding="utf-8")
                )
                runs_on_disk_at_start.append(len(on_disk.runs))
            else:
                runs_on_disk_at_start.append(0)
            return _fake_outcome(len(runs_on_disk_at_start), tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert runs_on_disk_at_start == [0, 1, 2]
        on_disk = CampaignIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        assert on_disk == index

    def test_exception_recorded_as_error_and_loop_continues(self, tmp_path, monkeypatch):
        counter = {"n": 0}

        def stub(scenario, runs_root, client):
            counter["n"] += 1
            if counter["n"] == 2:
                raise RuntimeError("boom: tool loop exceeded")
            return _fake_outcome(counter["n"], tmp_path)

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(3, "main", tmp_path, client=None)

        assert [r.outcome for r in index.runs] == ["success", "error", "success"]
        assert index.runs[1].session_id is None
        assert "boom" in index.runs[1].error
        assert index.runs[1].typologies == []

    def test_typologies_come_from_classify_run(self, tmp_path, monkeypatch):
        divided_event = TaskDividedEvent(
            session_id="s",
            task_id="root",
            sub_tasks=[DividedSubTask(id="s1", description="sub")],
        )

        def stub(scenario, runs_root, client):
            return _fake_outcome(1, tmp_path, events=[divided_event])

        monkeypatch.setattr(incident_runs, "run_once", stub)
        index = run_campaign(1, "main", tmp_path, client=None)

        assert index.runs[0].typologies == ["divided"]

    def test_on_run_callback_called_per_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            incident_runs,
            "run_once",
            lambda scenario, runs_root, client: _fake_outcome(1, tmp_path),
        )
        seen = []
        run_campaign(2, "main", tmp_path, client=None, on_run=lambda rec: seen.append(rec.i))
        assert seen == [1, 2]

    def test_qa_fail_outcome_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            incident_runs,
            "run_once",
            lambda scenario, runs_root, client: _fake_outcome(1, tmp_path, kind="qa_fail"),
        )
        index = run_campaign(1, "main", tmp_path, client=None)
        assert index.runs[0].outcome == "qa_fail"
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py -v`
Expected: FAIL — `ImportError: cannot import name 'CampaignIndex'`

- [ ] **Step 3: Implémenter les modèles d'index et `run_campaign`**

Dans `src/aaosa/cli/incident_runs.py`, compléter les imports :

```python
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from aaosa.tracing.analysis import classify_run
```

et ajouter à la fin du module :

```python
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
    client: OpenAI | None,
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
            outcome = run_once(scenario, runs_root, client)
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
```

Note : `run_once(...)` est résolu comme global de module à l'appel — c'est ce qui rend le monkeypatch `setattr(incident_runs, "run_once", stub)` effectif.

- [ ] **Step 4: Vérifier que tout passe**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/incident_runs.py tests/cli/test_incident_runs.py
git commit -m "feat(cli): run_campaign - N runs sequentiels, index crash-safe, containment par run"
```

---

### Task 6: `app.py` — les 4 commandes Typer

Wiring fin : parse → délègue aux helpers → echo. Tests `CliRunner` sur stubs (zéro LLM). Le garde-fou s'affiche sur stdout (assertable via `result.output` quelle que soit la version de click).

**Files:**
- Modify: `src/aaosa/cli/app.py`
- Test: `tests/cli/test_app.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/cli/test_app.py` :

```python
from pathlib import Path

from typer.testing import CliRunner

import aaosa.cli.app as app_module
from aaosa.cli.app import app
from aaosa.cli.incident_runs import CampaignIndex, RunOutcome

runner = CliRunner()


def _fake_outcome(tmp_path: Path, kind: str = "success") -> RunOutcome:
    return RunOutcome(
        kind=kind,
        session_id="sess-1",
        session_dir=tmp_path / "sessions" / "sess-1",
        snapshot_path=tmp_path / "elo_snapshots" / "latest.json",
        events=[],
        task_description="incident task",
        n_agents=7,
    )


class TestRunCommand:
    def test_run_default_scenario_is_main(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(scenario, runs_root, client):
            captured["scenario"] = scenario
            captured["runs_root"] = runs_root
            return _fake_outcome(tmp_path)

        monkeypatch.setattr(app_module, "run_once", stub)
        result = runner.invoke(app, ["run", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["scenario"] == "main"
        assert captured["runs_root"] == tmp_path
        assert "success" in result.output

    def test_run_scenario_roster_gap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(scenario, runs_root, client):
            captured["scenario"] = scenario
            return _fake_outcome(tmp_path, kind="unassigned")

        monkeypatch.setattr(app_module, "run_once", stub)
        result = runner.invoke(
            app, ["run", "--scenario", "roster_gap", "--runs-root", str(tmp_path)]
        )

        assert result.exit_code == 0
        assert captured["scenario"] == "roster_gap"

    def test_run_rejects_invalid_scenario(self):
        result = runner.invoke(app, ["run", "--scenario", "bogus"])
        assert result.exit_code == 2


class TestCampaignCommand:
    def test_n_is_required(self):
        result = runner.invoke(app, ["campaign"])
        assert result.exit_code == 2

    def test_guard_refuses_populated_store(self, tmp_path):
        (tmp_path / "sessions" / "2026-06-07T18-00-00-abcd1234").mkdir(parents=True)
        result = runner.invoke(app, ["campaign", "--n", "2", "--runs-root", str(tmp_path)])

        assert result.exit_code == 1
        assert str(tmp_path / "sessions") in result.output
        assert "--runs-root" in result.output

    def test_campaign_wires_run_campaign(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_module, "create_client", lambda: object())
        captured = {}

        def stub(n, scenario, runs_root, client, on_run=None):
            captured.update(n=n, scenario=scenario, runs_root=runs_root)
            return CampaignIndex(scenario=scenario, n_requested=n)

        monkeypatch.setattr(app_module, "run_campaign", stub)
        result = runner.invoke(app, ["campaign", "--n", "5", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["n"] == 5
        assert captured["scenario"] == "main"
        assert captured["runs_root"] == tmp_path


class _FakeServer:
    def __init__(self):
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs


class TestDashboardCommand:
    def test_defaults_are_config_defaults(self, monkeypatch):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard"])

        assert result.exit_code == 0
        assert captured["cfg"].port == 5001  # défaut DashboardConfig, inchangé
        assert captured["cfg"].runs_root == Path("runs")
        assert server.kwargs == {"host": "127.0.0.1", "port": 5001, "debug": True}

    def test_port_override(self, monkeypatch):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard", "--port", "8123"])

        assert result.exit_code == 0
        assert captured["cfg"].port == 8123
        assert server.kwargs == {"host": "127.0.0.1", "port": 8123, "debug": True}

    def test_runs_root_override(self, monkeypatch, tmp_path):
        server = _FakeServer()
        captured = {}

        def fake_create_app(cfg):
            captured["cfg"] = cfg
            return server

        monkeypatch.setattr(app_module, "create_app", fake_create_app)
        result = runner.invoke(app, ["dashboard", "--runs-root", str(tmp_path)])

        assert result.exit_code == 0
        assert captured["cfg"].runs_root == tmp_path
        assert captured["cfg"].port == 5001  # port par défaut préservé


class TestHealthCheckCommand:
    def test_wraps_run_demo_health_check_v3(self, monkeypatch):
        called = {"n": 0}

        def fake_health_check():
            called["n"] += 1

        monkeypatch.setattr(app_module, "run_demo_health_check_v3", fake_health_check)
        result = runner.invoke(app, ["health-check"])

        assert result.exit_code == 0
        assert called["n"] == 1
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/cli/test_app.py -v`
Expected: FAIL — `Error: No such command 'run'` (exit code 2 partout, les asserts `exit_code == 0` échouent ; `test_run_rejects_invalid_scenario` et `test_n_is_required` peuvent passer par accident, c'est attendu)

- [ ] **Step 3: Implémenter les 4 commandes**

Remplacer entièrement `src/aaosa/cli/app.py` :

```python
"""CLI projet-wide `aaosa` — entrée unique des points d'exécution du projet.

Wiring console fin uniquement : la logique run/campaign vit dans
`aaosa.cli.incident_runs` (helpers purs, sans print).
"""

from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv

from aaosa.cli.incident_runs import (
    StoreNotEmptyError,
    ensure_empty_store,
    run_campaign,
    run_once,
)
from aaosa.demo.run_health_check_v3 import run_demo_health_check_v3
from aaosa.runtime.llm_client import create_client
from aaosa.tracing.formatter import print_timeline
from dashboard.app import create_app
from dashboard.config import DashboardConfig

app = typer.Typer(no_args_is_help=True, add_completion=False)


class Scenario(str, Enum):
    main = "main"
    roster_gap = "roster_gap"


@app.command()
def run(
    scenario: Scenario = typer.Option(Scenario.main, "--scenario"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Un run incident : claiming -> récupération D1/D3 -> persistance (ELO chaîné)."""
    load_dotenv()
    client = create_client()
    outcome = run_once(scenario.value, runs_root, client)

    typer.echo(
        f"=== AAOSA incident — scenario: {scenario.value} ({outcome.n_agents} agents) ===\n"
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
    n: int = typer.Option(..., "--n", help="Nombre de runs (obligatoire — coût LLM)"),
    scenario: Scenario = typer.Option(Scenario.main, "--scenario"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """N runs séquentiels, ELO chaîné, index crash-safe. Refuse un store peuplé."""
    try:
        ensure_empty_store(runs_root)
    except StoreNotEmptyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    load_dotenv()
    client = create_client()
    typer.echo(f"=== AAOSA campaign — scenario: {scenario.value}, n={n} ===")

    def _echo_run(record) -> None:
        typer.echo(f"run {record.i}/{n}: {record.outcome} {record.typologies}")

    index = run_campaign(n, scenario.value, runs_root, client, on_run=_echo_run)
    successes = sum(1 for r in index.runs if r.outcome == "success")
    typer.echo(f"\n{successes}/{n} success — index: {runs_root / 'campaign_index.json'}")


@app.command()
def dashboard(
    port: int | None = typer.Option(None, "--port"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Dashboard d'observabilité (serveur dev Flask, équivalent `python -m dashboard`)."""
    cfg = (
        DashboardConfig(runs_root=runs_root)
        if port is None
        else DashboardConfig(runs_root=runs_root, port=port)
    )
    create_app(cfg).run(host=cfg.host, port=cfg.port, debug=True)


@app.command(name="health-check")
def health_check() -> None:
    """Boucle auto-amélioration B2 -> B3 -> re-triage sur le roster software (intact)."""
    load_dotenv()
    run_demo_health_check_v3()


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Vérifier que tout passe**

Run: `.venv\Scripts\python -m pytest tests/cli/ -v`
Expected: PASS (10 tests app + 13 tests incident_runs)

- [ ] **Step 5: Smoke du console script**

Run: `.venv\Scripts\aaosa --help`
Expected: les 4 commandes listées (`run`, `campaign`, `dashboard`, `health-check`).

Run: `.venv\Scripts\aaosa campaign --runs-root nonexistent`
Expected: erreur « Missing option '--n' », exit code 2.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): aaosa run/campaign/dashboard/health-check - wiring Typer sur les helpers"
```

---

### Task 7: Suppressions — `run_demo_v3.py`, `run_incident.py`

Destins déclarés (phase 3 pour `run_incident.py`, spec phase 4 pour `run_demo_v3.py`). `tests/demo/test_run_demo_v3.py` ne couvre rien d'unique (un test d'attributs de Task + un `callable()`). `run_incident.py` n'a aucun test. `demo/tasks.py` et `run_health_check_v3.py` restent (consommés par le health check + fixtures dashboard).

**Files:**
- Delete: `src/aaosa/demo/run_demo_v3.py`
- Delete: `tests/demo/test_run_demo_v3.py`
- Delete: `src/aaosa/demo/incident/run_incident.py`

- [ ] **Step 1: Supprimer les trois fichiers**

```bash
git rm src/aaosa/demo/run_demo_v3.py tests/demo/test_run_demo_v3.py src/aaosa/demo/incident/run_incident.py
```

- [ ] **Step 2: Vérifier qu'aucune référence code ne subsiste**

Run: `Grep pattern="run_demo_v3|run_incident" path="src" + path="tests" + path="dashboard"` (ou `rg "run_demo_v3|run_incident" src tests dashboard`)
Expected: zéro occurrence dans `src/`, `tests/`, `dashboard/` (les occurrences dans `docs/` et `CLAUDE.md` sont traitées en Task 8).

- [ ] **Step 3: Suite complète**

Run: `.venv\Scripts\python -m pytest tests/ -q`
Expected: PASS — ~960 tests (926 au départ − 2 supprimés + 9 classify_run + 4 prompts + 13 incident_runs + 10 app ; le test conditionnel de trace réelle peut skipper hors master, comportement connu).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(demo): suppression run_demo_v3 + run_incident (remplaces par le CLI aaosa)"
```

---

### Task 8: DoD réel (checkpoint humain) + tickets backlog + CLAUDE.md

**STOP — checkpoint humain.** Cette task exécute des runs LLM réels (gpt-4o-mini, `OPENAI_API_KEY` dans `.env`) et requiert le sign-off de Quentin. Coût : ~7 runs complets (~2 runs unitaires + mini-campagne n=5).

**Files:**
- Modify: `docs/backlog/2026-06-07-divider-topologie-aggregator.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `aaosa run --scenario main`**

Run: `.venv\Scripts\aaosa run --scenario main`
Expected: la tâche RÉUSSIT (`-> success`, QA PASS dans la timeline) — chemin simple ou divisé, peu importe : il émerge. Session persistée sous `runs/sessions/`.

- [ ] **Step 2: `aaosa run --scenario roster_gap`**

Run: `.venv\Scripts\aaosa run --scenario roster_gap`
Expected: `RosterGapEvent` dans la trace (`-> unassigned`, `missing_tags` contient `gdpr`).

- [ ] **Step 3: Mini-campagne réelle sur un root frais**

Run: `.venv\Scripts\aaosa campaign --n 5 --runs-root runs_campaign_p4`
Expected: 5 runs séquentiels, index `runs_campaign_p4/campaign_index.json` complet (5 entrées, typologies remplies), snapshots ELO successifs distincts (l'ELO se chaîne — comparer 2 snapshots horodatés).

- [ ] **Step 4: Garde-fou vérifié sur le même root**

Run: `.venv\Scripts\aaosa campaign --n 5 --runs-root runs_campaign_p4`
Expected: refus explicite (exit code 1), message nommant `runs_campaign_p4\sessions` et suggérant un `--runs-root` frais. Aucun run lancé.

- [ ] **Step 5: Observation aggregator (critère du ticket divider)**

Run: `rg -l "task_aggregated" runs_campaign_p4/sessions` (chercher `TaskAggregatedEvent` dans les traces de la campagne + les runs des Steps 1-2)
Expected: ≥1 occurrence → ticket validé (vérifier aussi le nœud AGGREGATOR au dashboard, Step 6). **Zéro occurrence = constat documenté dans le ticket, la N=20 de phase 5 tranche — on n'inverse pas la décision.**

- [ ] **Step 6: Dashboard + health check**

Run: `.venv\Scripts\aaosa dashboard --runs-root runs_campaign_p4` → ouvrir http://127.0.0.1:5001 — les 5 sessions de la campagne rendent (nœud AGGREGATOR visible si Step 5 positif).
Run: `.venv\Scripts\aaosa dashboard` → les sessions des Steps 1-2 rendent sur le store par défaut `runs/` (non-régression).
Run: `.venv\Scripts\aaosa health-check`
Expected: les deux stores rendent au dashboard ; health check déroule B2 → B3 → re-triage sans erreur.

- [ ] **Step 7: Mettre à jour le ticket divider**

Dans `docs/backlog/2026-06-07-divider-topologie-aggregator.md` :
- Section « Options discutées » → marquer la décision : **« Retirer la consigne synthèse » tranché le 2026-06-07** (spec phase 4 §6), prompt réécrit dans `src/aaosa/demo/incident/prompts.py`, verrous `tests/demo/incident/test_prompts.py`.
- Section « Critères d'acceptation » → cocher avec le résultat d'observation du Step 5 (nombre de `TaskAggregatedEvent` observés sur n=5+2 runs, ou constat zéro documenté).
- Section « Question ouverte associée » → noter : **QA-aggregator re-déferré explicitement en D5** (spec phase 4 §2) — la campagne phase 5 fournit fréquence + qualité perçue pour trancher.
- Corriger les pointeurs : les prompts vivent désormais dans `prompts.py` (plus `run_incident.py`/`run_demo_v3.py`, supprimés).

- [ ] **Step 8: Mettre à jour CLAUDE.md**

- Bloc « État courant » : ajouter le paragraphe phase 4 (CLI `aaosa`, 4 commandes, `classify_run`, index campagne, ELO chaîné, ticket divider tranché + résultat d'observation, compte de tests post-suite).
- Arbre « Architecture » : ajouter `cli/ app.py · incident_runs.py  # phase 4` ; sous `demo/` : `incident/prompts.py`, retirer `run_demo_v3.py` et `run_incident.py` ; noter `run_health_check_v3.py` (wrappé par `aaosa health-check`).
- « Stack et commandes » : remplacer « Lancer la démo : `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` » par `aaosa run [--scenario main|roster_gap]` · `aaosa campaign --n N --runs-root <frais>` · `aaosa dashboard` · `aaosa health-check` ; « Lancer le dashboard » mentionne `aaosa dashboard` comme équivalent.

- [ ] **Step 9: Commit final**

```bash
git add docs/backlog/2026-06-07-divider-topologie-aggregator.md CLAUDE.md
git commit -m "docs: phase 4 CLI livree - DoD reel valide, ticket divider clos, CLAUDE.md a jour"
```

---

## Self-review (faite à l'écriture du plan)

- **Couverture spec** : §3 layout → Tasks 3-7 · §4.1 run → Tasks 4+6 · §4.2 campaign (garde-fou, containment, index crash-safe, `--n` obligatoire) → Tasks 4-6 · §4.3 dashboard → Task 6 · §4.4 health-check → Task 6 · §5 classify_run → Task 1 · §6 prompts/ticket → Task 2 (+ Step 5 Task 8) · §7 helpers → Tasks 4-5 · §8 TDD+DoD → tout + Task 8.
- **Types cohérents** : `RunOutcome` (kind/session_id/session_dir/snapshot_path/events/task_description/n_agents) identique Tasks 4/5/6 ; `run_campaign(n, scenario, runs_root, client, on_run)` identique Tasks 5/6 ; `StoreNotEmptyError(sessions_dir)` identique Tasks 4/6.
- **Écarts spec** : 4 écarts listés en tête de plan, à valider avec Quentin avant exécution.
