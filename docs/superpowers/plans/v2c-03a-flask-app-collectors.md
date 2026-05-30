# V2c — Épique 03a — App Flask, cache & collectors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire l'infrastructure serveur du dashboard (factory `create_app`, config Pydantic, cache on-demand) et les 4 collectors d'agrégation (infra, agents, health checks, sessions), testables sur un `runs_root` fixture, sans aucune couche HTTP (réservée à l'Épique 03b).

**Architecture:** Couche `dashboard/` consommant la couche data `src/aaosa/`. Collectors = fonctions pures `(runs_root[, id]) -> ModèlePydantic`, chacune ne lisant que les fichiers nécessaires. `build_graph` (Épique 02) reste pur et intouché : les collectors le câblent. Cache mémorise les calculs immuables-par-id ; les vues d'ensemble se recalculent à chaque appel (reflètent les nouveaux runs sans redémarrage). Un lecteur de trace `load_trace` est ajouté côté data (inverse de `Tracer.flush`).

**Tech Stack:** Python 3.14, Pydantic 2.13, Flask 3.1, pytest 9.0.3. Imports absolus uniquement. `model_config = ConfigDict(extra="forbid")` sur tout modèle.

**Décisions de design (deep-dive cross-check 2026-05-30) :**
- **S1** — Jointure registry via l'endpoint `/api/agents` existant (join côté frontend). `build_graph` intouché, label de nœud = `agent_id`. ELO de l'overlay = courant (registry) + deltas du run (déjà dans `AgentDetail`). Conséquence 03a : le collector `Agents` expose liste (id+name) + détail (system_prompt + ELO courant + historique + activité).
- **S2** — Collectors renvoient du **Pydantic** (modèles existants réutilisés + nouveaux modèles d'agrégat dans `dashboard/`). La sérialisation (`by_alias=True` pour l'alias `from`, datetime) sera un helper unique en 03b ; **aucune gestion d'alias dans les collectors**.
- **S3** — Health check : le collector **synthétise un `SessionMeta`** depuis le `test_set.json` avant `build_graph` (sinon overlay Input vide). `winner_agent_id`/`outcome` du record synthétisé sont des placeholders **ignorés par `build_graph`** (il dérive des events).
- **S4** — Contrat `HealthChecks` : liste (champs top-level du report), détail (`report ⋈ test_set` par `task_id`, `graphable` ssi cas actif), `evaluator_spec` réutilisé tel quel, split train/test = axe `role`.
- **S5** — `load_trace` dans `src/aaosa/tracing/store.py` (inverse de `flush`). Collectors indépendants, partage limité à `load_trace`. `ExecutedEvent.llm_metadata` est nullable → skip les `None` dans l'agrégat infra.
- **Cache** — on-demand lazy (`get_or_compute`), pas de TTL, pas d'invalidation, pas de live mode (V1 statique). Live mode reporté post-V2/V3 ; ce design ne le bloque pas.
- **Config** — module `config.py` mais en modèle Pydantic à defaults (`runs_root`/`host`/`port`), pas de `config.json` obligatoire.

---

## Consignes projet d'exécution (à respecter pour toutes les tasks)

- **Discipline de commit :** l'implémenteur **ne commit pas**. Le commit d'une task n'a lieu qu'**après** que la spec-review ET la quality-review soient passées (cf. subagent-driven-development). La dernière étape de chaque task donne la commande exacte, à n'exécuter qu'une fois la feature validée par les reviews.
- **Économie de tests :** lancer les tests quand ils ont un intérêt. 03a est 100% logique (collectors, agrégation, cache) → les cycles TDD fail/pass sont pertinents et conservés. Pas de re-run gratuit de la suite complète en milieu de task ; une seule task de non-régression finale (Task 12).

---

## Store / contrat cible après ce plan

```
src/aaosa/tracing/store.py  += load_trace(path) -> list[ClaimEvent]    # inverse de Tracer.flush

dashboard/
  config.py        DashboardConfig (Pydantic, defaults)
  cache.py         Cache.get_or_compute(key, fn)
  app.py           create_app(config) -> Flask   (config + cache attachés ; aucune route data)
  collectors/
    __init__.py
    sessions.py    SessionList / SessionView          + list_sessions / session_detail
    health_checks.py  HealthCheckList / HealthCheckView / HealthCheckCaseView / CaseMetrics
                      + list_runs / run_detail / case_graph (+ _synth_meta)
    agents.py      AgentList / AgentDetailView / TagEloSeries / EloPoint / AgentActivity
                      + list_agents / agent_detail
    infra.py       InfraStats / LatencyStats / PassRatePoint  + collect
tests/dashboard/
  conftest.py      fixture runs_root (arborescence réelle, partagée avec 03b)
```

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/aaosa/tracing/store.py` | `load_trace` (désérialise JSONL → `list[ClaimEvent]`) | Modifier |
| `tests/tracing/test_store.py` | tests `load_trace` | Modifier |
| `dashboard/config.py` | `DashboardConfig` Pydantic | Créer |
| `dashboard/cache.py` | `Cache` on-demand | Créer |
| `dashboard/app.py` | factory `create_app` | Créer |
| `pyproject.toml` | dépendance Flask | Modifier |
| `tests/dashboard/conftest.py` | fixture `runs_root` | Créer |
| `dashboard/collectors/__init__.py` | package | Créer |
| `dashboard/collectors/sessions.py` | collector Tab 4 | Créer |
| `dashboard/collectors/health_checks.py` | collector Tab 3 | Créer |
| `dashboard/collectors/agents.py` | collector Tab 2 | Créer |
| `dashboard/collectors/infra.py` | collector Tab 1 | Créer |
| `tests/dashboard/test_config.py` · `test_cache.py` · `test_app.py` | infra | Créer |
| `tests/dashboard/test_collectors_*.py` | collectors | Créer |

**Commande de test (Windows, toujours le venv) :** `.venv\Scripts\python -m pytest <fichier> -v`

---

# PHASE 0 — Couche data : lecteur de trace

## Task 1: `load_trace` dans `store.py`

**Files:**
- Modify: `src/aaosa/tracing/store.py`
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Écrire les tests `load_trace`**

Ajouter à la fin de `tests/tracing/test_store.py` :

```python
class TestLoadTrace:
    def test_roundtrip(self, tmp_path):
        from aaosa.tracing.events import ExecutedEvent, Phase1FilteredEvent
        from aaosa.tracing.store import load_trace
        from aaosa.tracing.tracer import Tracer

        tracer = Tracer(session_id="s1")
        tracer.emit(Phase1FilteredEvent(session_id="s1", task_id="t1", agent_id="a1", passed=True, fit_score=0.9))
        tracer.emit(ExecutedEvent(session_id="s1", task_id="t1", agent_id="a1", output_summary="done", output_content="full"))
        path = tmp_path / "trace.jsonl"
        tracer.flush(path)

        events = load_trace(path)
        assert len(events) == 2
        assert events[0].type == "phase1_filtered"
        assert events[1].type == "executed"
        assert events[1].output_content == "full"

    def test_skips_blank_lines(self, tmp_path):
        from aaosa.tracing.store import load_trace

        path = tmp_path / "trace.jsonl"
        path.write_text(
            '{"type":"unassigned","session_id":"s1","task_id":"t1","reason":"x",'
            '"timestamp":"2026-05-30T10:00:00+00:00"}\n\n',
            encoding="utf-8",
        )
        events = load_trace(path)
        assert len(events) == 1
        assert events[0].reason == "x"
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py::TestLoadTrace -v`
Expected: FAIL — `ImportError: cannot import name 'load_trace'`.

- [ ] **Step 3: Implémenter `load_trace`**

Dans `src/aaosa/tracing/store.py`, ajouter `TypeAdapter` à l'import pydantic et importer `ClaimEvent` :

```python
from pydantic import BaseModel, ConfigDict, TypeAdapter
```

```python
from aaosa.tracing.events import ClaimEvent
```

Puis ajouter, après les imports (avant `new_session_id`) :

```python
_event_adapter = TypeAdapter(ClaimEvent)
```

Et en fin de fichier :

```python
def load_trace(path: Path) -> list[ClaimEvent]:
    """Lit un trace.jsonl en liste d'events. Inverse de Tracer.flush."""
    return [
        _event_adapter.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
```

> Cycle d'import : `events.py` importe `qa.judge` + `schemas.output` ; aucun n'importe `tracing.store`. Acyclique.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS (nouveaux + anciens).

- [ ] **Step 5: Commit (après spec-review + quality-review)**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(v2c): load_trace - lecteur JSONL inverse de Tracer.flush"
```

---

# PHASE 1 — Infra dashboard (config, cache, factory, fixture)

## Task 2: `dashboard/config.py`

**Files:**
- Create: `dashboard/config.py`
- Test: `tests/dashboard/test_config.py`

- [ ] **Step 1: Écrire les tests config**

Créer `tests/dashboard/test_config.py` :

```python
from pathlib import Path

import pytest

from dashboard.config import DashboardConfig


def test_defaults():
    c = DashboardConfig()
    assert c.runs_root == Path("runs")
    assert c.host == "127.0.0.1"
    assert c.port == 5000


def test_override():
    c = DashboardConfig(runs_root=Path("/tmp/x"), port=8080)
    assert c.runs_root == Path("/tmp/x")
    assert c.port == 8080


def test_extra_forbidden():
    with pytest.raises(Exception):
        DashboardConfig(unknown="x")
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.config'`.

- [ ] **Step 3: Créer `dashboard/config.py`**

```python
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class DashboardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs_root: Path = Path("runs")
    host: str = "127.0.0.1"
    port: int = 5000
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/config.py tests/dashboard/test_config.py
git commit -m "feat(v2c): DashboardConfig - config Pydantic a defaults"
```

---

## Task 3: `dashboard/cache.py`

**Files:**
- Create: `dashboard/cache.py`
- Test: `tests/dashboard/test_cache.py`

- [ ] **Step 1: Écrire les tests cache**

Créer `tests/dashboard/test_cache.py` :

```python
from dashboard.cache import Cache


def test_computes_once():
    calls = []
    cache = Cache()

    def fn():
        calls.append(1)
        return 42

    assert cache.get_or_compute("k", fn) == 42
    assert cache.get_or_compute("k", fn) == 42
    assert len(calls) == 1  # fn appelé une seule fois


def test_distinct_keys():
    cache = Cache()
    assert cache.get_or_compute("a", lambda: 1) == 1
    assert cache.get_or_compute("b", lambda: 2) == 2
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.cache'`.

- [ ] **Step 3: Créer `dashboard/cache.py`**

```python
import threading
from typing import Any, Callable


class Cache:
    """Cache on-demand : calcule au premier accès, mémorise. Pas de TTL, pas d'invalidation."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._data:
                self._data[key] = fn()
            return self._data[key]
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/cache.py tests/dashboard/test_cache.py
git commit -m "feat(v2c): Cache on-demand (get_or_compute, sans TTL)"
```

---

## Task 4: Dépendance Flask + factory `create_app`

**Files:**
- Modify: `pyproject.toml`
- Create: `dashboard/app.py`
- Test: `tests/dashboard/test_app.py`

- [ ] **Step 1: Ajouter Flask et installer**

Run (depuis la racine du repo) : `uv add "flask>=3.1"`
Expected: `pyproject.toml` voit `flask>=3.1` ajouté à `[project].dependencies`, et Flask installé dans `.venv`.

Vérifier : `.venv\Scripts\python -c "import flask; print(flask.__version__)"` → `3.1.x`.

- [ ] **Step 2: Écrire les tests factory**

Créer `tests/dashboard/test_app.py` :

```python
from dashboard.app import create_app
from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def test_create_app_instantiable(tmp_path):
    app = create_app(DashboardConfig(runs_root=tmp_path))
    assert app is not None
    assert app.config["AAOSA"].runs_root == tmp_path


def test_create_app_has_cache(tmp_path):
    app = create_app(DashboardConfig(runs_root=tmp_path))
    assert isinstance(app.config["CACHE"], Cache)


def test_create_app_default_config():
    app = create_app()
    assert app.config["AAOSA"].runs_root.name == "runs"
```

- [ ] **Step 3: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.app'`.

- [ ] **Step 4: Créer `dashboard/app.py`**

```python
from flask import Flask

from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def create_app(config: DashboardConfig | None = None) -> Flask:
    """Factory. Attache config + cache ; aucune route data (réservé Épique 03b)."""
    config = config or DashboardConfig()
    app = Flask(__name__)
    app.config["AAOSA"] = config
    app.config["CACHE"] = Cache()
    return app
```

- [ ] **Step 5: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_app.py -v`
Expected: PASS.

- [ ] **Step 6: Commit (après reviews)**

```bash
git add pyproject.toml uv.lock dashboard/app.py tests/dashboard/test_app.py
git commit -m "feat(v2c): create_app factory + dependance Flask"
```

---

## Task 5: Fixture `runs_root` partagée

**Files:**
- Create: `tests/dashboard/conftest.py`

> Cette fixture construit une arborescence `runs_root` réelle via les vrais modèles et fonctions de sauvegarde (garantit le match avec ce que le runtime écrit). Réutilisée par les tests de l'Épique 03b. Elle exerce : registry (4 agents demo), 2 snapshots ELO (historique), une session (1 task `qa_pass` + 1 task `unassigned`), un health check (1 cas actif `regression_guard` + 1 cas quarantaine `task_spec`).

- [ ] **Step 1: Créer `tests/dashboard/conftest.py`**

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot
from aaosa.qa.health_check import CaseResult, HealthCheckReport, save_health_check
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    DispatchedEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer


@pytest.fixture
def runs_root(tmp_path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    a0, a1 = DEMO_AGENTS[0], DEMO_AGENTS[1]
    t0, t1 = DEMO_TASKS[0], DEMO_TASKS[1]
    lm = LLMMetadata(model_name="gpt-4o-mini", tokens_in=120, tokens_out=80, latency_ms=350.0)

    # --- agents/registry.json ---
    save_agent_registry(DEMO_AGENTS, root / "agents" / "registry.json")

    # --- elo_snapshots : deux timestamps -> historique par tag ---
    snap_dir = root / "elo_snapshots"
    snap_dir.mkdir()
    base = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
    for i, ts in enumerate([base, base + timedelta(hours=1)]):
        snap = EloSnapshot(
            timestamp=ts,
            agents=[
                AgentEloSnapshot(
                    agent_name=a.name,
                    agent_id=a.id,
                    tags_with_elo={tag: elo + i * 3 for tag, elo in a.tags_with_elo.items()},
                )
                for a in DEMO_AGENTS
            ],
        )
        data = snap.model_dump_json(indent=2)
        (snap_dir / (ts.strftime("%Y-%m-%dT%H-%M-%S") + ".json")).write_text(data, encoding="utf-8")
        if i == 1:
            (snap_dir / "latest.json").write_text(data, encoding="utf-8")

    # --- session : t0 qa_pass (a0 gagne), t1 unassigned ---
    sid = "2026-05-30T10-00-00-aaaa"
    tracer = Tracer(session_id=sid)
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, passed=True, fit_score=0.9))
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t0.id, agent_id=a1.id, passed=False, fit_score=0.2))
    tracer.emit(Phase2ClaimedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, decision="claim", justification="mine"))
    tracer.emit(DispatchedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, reason="best fit"))
    tracer.emit(ExecutedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, output_summary="done", output_content="full output body", llm_metadata=lm))
    tracer.emit(QAEvaluatedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, success=True, score=0.85, reason="good", criteria_results={"non_empty": True}))
    tracer.emit(EloUpdatedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, deltas={list(t0.required_tags)[0]: 5}))
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t1.id, agent_id=a0.id, passed=False, fit_score=0.1))
    tracer.emit(UnassignedEvent(session_id=sid, task_id=t1.id, reason="no capable agent"))

    meta = SessionMeta(
        session_id=sid,
        started_at=base,
        ended_at=base + timedelta(minutes=2),
        tasks=[
            SessionTaskRecord(id=t0.id, description=t0.description, winner_agent_id=a0.id, outcome="qa_pass", required_tags=t0.required_tags),
            SessionTaskRecord(id=t1.id, description=t1.description, winner_agent_id=None, outcome="unassigned", required_tags=t1.required_tags),
        ],
        agent_ids=[a.id for a in DEMO_AGENTS],
    )
    save_session(tracer, meta, root)

    # --- health check : 1 cas actif (regression_guard/agent) + 1 quarantaine (fix_target/task_spec) ---
    hc_ts = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    test_set = TestSet(cases=[
        TestCase(task=t0, evaluator_spec=spec, origin="curated", role="regression_guard", attribution="agent"),
        TestCase(task=t1, evaluator_spec=spec, origin="runtime_failure", role="fix_target", attribution="task_spec"),
    ])
    qa = QAResult(task_id=t0.id, agent_id=a0.id, success=True, score=0.9, reason="ok", criteria_results={"non_empty": True})
    case_result = CaseResult(
        task_id=t0.id, role="regression_guard", n_runs=3, pass_count=2, pass_rate=2 / 3,
        unstable=False, qa_results=[qa, qa], qa_failures=[],
    )
    report = HealthCheckReport(
        timestamp=hc_ts, n_runs=3, total_cases=1, case_results=[case_result],
        fix_target_pass_rate=0.0, regression_guard_pass_rate=2 / 3,
        unstable_cases=[], unattributed=[], task_spec_quarantined=[t1.id], evaluator_quarantined=[],
    )
    hc_tracer = Tracer(session_id="hc-" + sid)
    hc_tracer.emit(Phase1FilteredEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, passed=True, fit_score=0.9))
    hc_tracer.emit(DispatchedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, reason="best fit"))
    hc_tracer.emit(ExecutedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, output_summary="done", output_content="hc body", llm_metadata=lm))
    hc_tracer.emit(QAEvaluatedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, success=True, score=0.9, reason="ok", criteria_results={"non_empty": True}))
    save_health_check(report, test_set, hc_tracer, root / "health_checks")

    return root
```

- [ ] **Step 2: Vérifier que la fixture se construit (smoke test temporaire)**

Ajouter temporairement dans `tests/dashboard/test_app.py` :

```python
def test_runs_root_fixture_builds(runs_root):
    assert (runs_root / "agents" / "registry.json").exists()
    assert (runs_root / "sessions").is_dir()
    assert (runs_root / "health_checks").is_dir()
    assert list((runs_root / "elo_snapshots").glob("*.json"))
```

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_app.py::test_runs_root_fixture_builds -v`
Expected: PASS. (Ce test sera retiré au profit des tests de collectors qui exercent réellement la fixture ; le laisser ne nuit pas — au choix du reviewer.)

- [ ] **Step 3: Commit (après reviews)**

```bash
git add tests/dashboard/conftest.py tests/dashboard/test_app.py
git commit -m "test(v2c): fixture runs_root partagee (registry/snapshots/session/health-check)"
```

---

# PHASE 2 — Collectors

## Task 6: Collector `Sessions` (Tab 4)

**Files:**
- Create: `dashboard/collectors/__init__.py`
- Create: `dashboard/collectors/sessions.py`
- Test: `tests/dashboard/test_collectors_sessions.py`

- [ ] **Step 1: Écrire les tests sessions**

Créer `tests/dashboard/test_collectors_sessions.py` :

```python
from dashboard.collectors.sessions import list_sessions, session_detail


def test_list_sessions(runs_root):
    result = list_sessions(runs_root)
    assert len(result.sessions) == 1
    s = result.sessions[0]
    assert s.task_count == 2
    assert s.agent_count == 4


def test_list_sessions_empty(tmp_path):
    assert list_sessions(tmp_path).sessions == []


def test_session_detail_graph(runs_root):
    sid = list_sessions(runs_root).sessions[0].session_id
    view = session_detail(runs_root, sid)
    assert view is not None
    assert len(view.graph.steps) == 2
    outcomes = {st.outcome for st in view.graph.steps}
    assert "qa_pass" in outcomes
    assert "unassigned" in outcomes


def test_session_detail_not_found(runs_root):
    assert session_detail(runs_root, "nope") is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.collectors'`.

- [ ] **Step 3: Créer le package collectors**

Créer `dashboard/collectors/__init__.py` (fichier vide).

- [ ] **Step 4: Créer `dashboard/collectors/sessions.py`**

```python
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.tracing.store import SessionMeta, load_trace
from dashboard.graph_model import GraphModel, build_graph


class SessionListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    task_count: int
    agent_count: int


class SessionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: list[SessionListItem]


class SessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SessionMeta
    graph: GraphModel


def _sessions_dir(runs_root: Path) -> Path:
    return runs_root / "sessions"


def _load_meta(session_dir: Path) -> SessionMeta:
    return SessionMeta.model_validate_json((session_dir / "meta.json").read_text(encoding="utf-8"))


def list_sessions(runs_root: Path) -> SessionList:
    sdir = _sessions_dir(runs_root)
    items: list[SessionListItem] = []
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            if not (d / "meta.json").exists():
                continue
            meta = _load_meta(d)
            items.append(SessionListItem(
                session_id=meta.session_id,
                started_at=meta.started_at,
                ended_at=meta.ended_at,
                task_count=len(meta.tasks),
                agent_count=len(meta.agent_ids),
            ))
    items.sort(key=lambda s: s.started_at, reverse=True)
    return SessionList(sessions=items)


def session_detail(runs_root: Path, session_id: str) -> SessionView | None:
    d = _sessions_dir(runs_root) / session_id
    if not (d / "meta.json").exists() or not (d / "trace.jsonl").exists():
        return None
    meta = _load_meta(d)
    graph = build_graph(load_trace(d / "trace.jsonl"), meta)
    return SessionView(meta=meta, graph=graph)
```

- [ ] **Step 5: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py -v`
Expected: PASS.

- [ ] **Step 6: Commit (après reviews)**

```bash
git add dashboard/collectors/__init__.py dashboard/collectors/sessions.py tests/dashboard/test_collectors_sessions.py
git commit -m "feat(v2c): collector Sessions (liste + detail + graphe via build_graph)"
```

---

## Task 7: Collector `HealthChecks` — liste

**Files:**
- Create: `dashboard/collectors/health_checks.py`
- Test: `tests/dashboard/test_collectors_health_checks.py`

- [ ] **Step 1: Écrire les tests liste**

Créer `tests/dashboard/test_collectors_health_checks.py` :

```python
from dashboard.collectors.health_checks import list_runs


def test_list_runs(runs_root):
    result = list_runs(runs_root)
    assert len(result.runs) == 1
    r = result.runs[0]
    assert r.total_cases == 1
    assert r.quarantined_count == 1
    assert abs(r.regression_guard_pass_rate - 2 / 3) < 1e-9


def test_list_runs_empty(tmp_path):
    assert list_runs(tmp_path).runs == []
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.collectors.health_checks'`.

- [ ] **Step 3: Créer `dashboard/collectors/health_checks.py` (modèles liste + `list_runs`)**

```python
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.qa.health_check import HealthCheckReport
from aaosa.qa.spec import EvaluatorSpec
from aaosa.qa.test_set import TestSet
from aaosa.tracing.store import SessionMeta, SessionTaskRecord, load_trace
from dashboard.graph_model import GraphModel, build_graph


class HealthCheckListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    timestamp: datetime
    n_runs: int
    total_cases: int
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_count: int
    quarantined_count: int


class HealthCheckList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: list[HealthCheckListItem]


def _hc_dir(runs_root: Path) -> Path:
    return runs_root / "health_checks"


def _load_report(run_dir: Path) -> HealthCheckReport:
    return HealthCheckReport.model_validate_json((run_dir / "report.json").read_text(encoding="utf-8"))


def list_runs(runs_root: Path) -> HealthCheckList:
    hdir = _hc_dir(runs_root)
    items: list[HealthCheckListItem] = []
    if hdir.exists():
        for d in sorted(hdir.iterdir()):
            if not (d / "report.json").exists():
                continue
            r = _load_report(d)
            quarantined = len(r.task_spec_quarantined) + len(r.evaluator_quarantined) + len(r.unattributed)
            items.append(HealthCheckListItem(
                id=d.name,
                timestamp=r.timestamp,
                n_runs=r.n_runs,
                total_cases=r.total_cases,
                fix_target_pass_rate=r.fix_target_pass_rate,
                regression_guard_pass_rate=r.regression_guard_pass_rate,
                unstable_count=len(r.unstable_cases),
                quarantined_count=quarantined,
            ))
    items.sort(key=lambda x: x.timestamp, reverse=True)
    return HealthCheckList(runs=items)
```

> Les imports `EvaluatorSpec`, `TestSet`, `SessionMeta`, `SessionTaskRecord`, `GraphModel`, `build_graph` servent aux Tasks 8-9 (détail + graphe) ; ils sont placés ici pour éviter de re-toucher l'en-tête.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/health_checks.py tests/dashboard/test_collectors_health_checks.py
git commit -m "feat(v2c): collector HealthChecks - liste des runs"
```

---

## Task 8: Collector `HealthChecks` — détail (join `report ⋈ test_set`)

**Files:**
- Modify: `dashboard/collectors/health_checks.py`
- Test: `tests/dashboard/test_collectors_health_checks.py`

- [ ] **Step 1: Écrire les tests détail**

Ajouter à `tests/dashboard/test_collectors_health_checks.py` :

```python
from dashboard.collectors.health_checks import run_detail


def test_run_detail_join(runs_root):
    rid = list_runs(runs_root).runs[0].id
    view = run_detail(runs_root, rid)
    assert view is not None
    assert len(view.cases) == 2

    active = [c for c in view.cases if c.graphable]
    quarantined = [c for c in view.cases if not c.graphable]

    assert len(active) == 1
    assert active[0].role == "regression_guard"
    assert active[0].result is not None
    assert active[0].result.pass_count == 2

    assert len(quarantined) == 1
    assert quarantined[0].attribution == "task_spec"
    assert quarantined[0].result is None
    assert quarantined[0].evaluator_spec.criteria[0].name == "non_empty"


def test_run_detail_not_found(runs_root):
    assert run_detail(runs_root, "nope") is None
```

> `list_runs` est déjà importé en haut du fichier (Task 7).

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py::test_run_detail_join -v`
Expected: FAIL — `ImportError: cannot import name 'run_detail'`.

- [ ] **Step 3: Ajouter les modèles détail + `run_detail`**

Dans `dashboard/collectors/health_checks.py`, ajouter après `HealthCheckList` :

```python
class CaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_rate: float
    pass_count: int
    n_runs: int
    unstable: bool


class HealthCheckCaseView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    description: str
    required_tags: dict[str, int]
    role: str
    attribution: str
    origin: str
    reference: str | None
    evaluator_spec: EvaluatorSpec
    graphable: bool
    result: CaseMetrics | None


class HealthCheckView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    timestamp: datetime
    n_runs: int
    total_cases: int
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_cases: list[str]
    task_spec_quarantined: list[str]
    evaluator_quarantined: list[str]
    unattributed: list[str]
    cases: list[HealthCheckCaseView]
```

Et ajouter les fonctions (après `list_runs`) :

```python
def _load_test_set(run_dir: Path) -> TestSet:
    return TestSet.model_validate_json((run_dir / "test_set.json").read_text(encoding="utf-8"))


def run_detail(runs_root: Path, run_id: str) -> HealthCheckView | None:
    d = _hc_dir(runs_root) / run_id
    if not (d / "report.json").exists() or not (d / "test_set.json").exists():
        return None
    report = _load_report(d)
    test_set = _load_test_set(d)
    by_task = {cr.task_id: cr for cr in report.case_results}
    cases: list[HealthCheckCaseView] = []
    for c in test_set.cases:
        cr = by_task.get(c.task.id)
        cases.append(HealthCheckCaseView(
            task_id=c.task.id,
            description=c.task.description,
            required_tags=c.task.required_tags,
            role=c.role,
            attribution=c.attribution,
            origin=c.origin,
            reference=c.reference,
            evaluator_spec=c.evaluator_spec,
            graphable=cr is not None,
            result=CaseMetrics(pass_rate=cr.pass_rate, pass_count=cr.pass_count, n_runs=cr.n_runs, unstable=cr.unstable) if cr is not None else None,
        ))
    return HealthCheckView(
        id=run_id,
        timestamp=report.timestamp,
        n_runs=report.n_runs,
        total_cases=report.total_cases,
        fix_target_pass_rate=report.fix_target_pass_rate,
        regression_guard_pass_rate=report.regression_guard_pass_rate,
        unstable_cases=report.unstable_cases,
        task_spec_quarantined=report.task_spec_quarantined,
        evaluator_quarantined=report.evaluator_quarantined,
        unattributed=report.unattributed,
        cases=cases,
    )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/health_checks.py tests/dashboard/test_collectors_health_checks.py
git commit -m "feat(v2c): collector HealthChecks - detail (join report x test_set, graphable)"
```

---

## Task 9: Collector `HealthChecks` — graphe par cas (`_synth_meta`)

**Files:**
- Modify: `dashboard/collectors/health_checks.py`
- Test: `tests/dashboard/test_collectors_health_checks.py`

- [ ] **Step 1: Écrire les tests graphe par cas**

Ajouter à `tests/dashboard/test_collectors_health_checks.py` :

```python
from dashboard.collectors.health_checks import case_graph


def test_case_graph_active(runs_root):
    rid = list_runs(runs_root).runs[0].id
    active = [c for c in run_detail(runs_root, rid).cases if c.graphable][0]
    graph = case_graph(runs_root, rid, active.task_id)
    assert graph is not None
    assert len(graph.steps) == 1
    step = graph.steps[0]
    assert step.outcome == "qa_pass"
    # _synth_meta remplit l'overlay Input depuis le TestSet (sinon vide)
    assert step.detail.input.description == active.description
    assert step.detail.input.required_tags == active.required_tags


def test_case_graph_quarantined_returns_none(runs_root):
    rid = list_runs(runs_root).runs[0].id
    quarantined = [c for c in run_detail(runs_root, rid).cases if not c.graphable][0]
    assert case_graph(runs_root, rid, quarantined.task_id) is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py::test_case_graph_active -v`
Expected: FAIL — `ImportError: cannot import name 'case_graph'`.

- [ ] **Step 3: Ajouter `_synth_meta` + `case_graph`**

Dans `dashboard/collectors/health_checks.py`, ajouter en fin de fichier :

```python
def _synth_meta(test_set: TestSet, report: HealthCheckReport, run_id: str) -> SessionMeta:
    """Synthétise un SessionMeta depuis le TestSet pour nourrir build_graph.

    winner_agent_id/outcome sont des placeholders ignorés par build_graph
    (il dérive winner/outcome des events) ; seuls description/required_tags servent.
    """
    return SessionMeta(
        session_id=run_id,
        started_at=report.timestamp,
        ended_at=report.timestamp,
        tasks=[
            SessionTaskRecord(
                id=c.task.id,
                description=c.task.description,
                required_tags=c.task.required_tags,
                winner_agent_id=None,
                outcome="no_qa",
            )
            for c in test_set.cases
        ],
        agent_ids=[],
    )


def case_graph(runs_root: Path, run_id: str, task_id: str) -> GraphModel | None:
    d = _hc_dir(runs_root) / run_id
    if not all((d / f).exists() for f in ("report.json", "test_set.json", "trace.jsonl")):
        return None
    report = _load_report(d)
    test_set = _load_test_set(d)
    events = [e for e in load_trace(d / "trace.jsonl") if e.task_id == task_id]
    if not events:
        return None  # cas non graphable (quarantaine ou absent de la trace)
    return build_graph(events, _synth_meta(test_set, report, run_id))
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/health_checks.py tests/dashboard/test_collectors_health_checks.py
git commit -m "feat(v2c): collector HealthChecks - graphe par cas (_synth_meta + build_graph)"
```

---

## Task 10: Collector `Agents` (Tab 2)

**Files:**
- Create: `dashboard/collectors/agents.py`
- Test: `tests/dashboard/test_collectors_agents.py`

- [ ] **Step 1: Écrire les tests agents**

Créer `tests/dashboard/test_collectors_agents.py` :

```python
from aaosa.demo.agents import DEMO_AGENTS
from dashboard.collectors.agents import agent_detail, list_agents


def test_list_agents(runs_root):
    result = list_agents(runs_root)
    assert len(result.agents) == len(DEMO_AGENTS)
    assert DEMO_AGENTS[0].name in {a.name for a in result.agents}


def test_list_agents_empty(tmp_path):
    assert list_agents(tmp_path).agents == []


def test_agent_detail(runs_root):
    aid = DEMO_AGENTS[0].id
    view = agent_detail(runs_root, aid)
    assert view is not None
    assert view.system_prompt
    # deux snapshots -> chaque tag a deux points
    assert view.elo_history
    assert all(len(s.points) == 2 for s in view.elo_history)
    # a0 a claim + win + success sur t0 dans la session fixture
    assert view.activity.claims >= 1
    assert view.activity.wins >= 1
    assert view.activity.successes >= 1


def test_agent_detail_not_found(runs_root):
    assert agent_detail(runs_root, "nope") is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.collectors.agents'`.

- [ ] **Step 3: Créer `dashboard/collectors/agents.py`**

```python
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.elo.persistence import EloSnapshot
from aaosa.tracing.events import DispatchedEvent, Phase2ClaimedEvent, QAEvaluatedEvent
from aaosa.tracing.store import AgentRegistry, load_trace


class AgentListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    tags_with_elo: dict[str, int]


class AgentList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentListItem]


class EloPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    elo: int


class TagEloSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    points: list[EloPoint]


class AgentActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: int
    wins: int
    successes: int
    failures: int


class AgentDetailView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    system_prompt: str
    tags_with_elo: dict[str, int]
    elo_history: list[TagEloSeries]
    activity: AgentActivity


def _load_registry(runs_root: Path) -> AgentRegistry | None:
    path = runs_root / "agents" / "registry.json"
    if not path.exists():
        return None
    return AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def list_agents(runs_root: Path) -> AgentList:
    reg = _load_registry(runs_root)
    if reg is None:
        return AgentList(agents=[])
    return AgentList(agents=[
        AgentListItem(agent_id=e.agent_id, name=e.name, tags_with_elo=e.tags_with_elo)
        for e in reg.agents
    ])


def _elo_history(runs_root: Path, agent_id: str) -> list[TagEloSeries]:
    snap_dir = runs_root / "elo_snapshots"
    if not snap_dir.exists():
        return []
    series: dict[str, list[EloPoint]] = {}
    for f in sorted(snap_dir.glob("*.json")):
        if f.name == "latest.json":
            continue
        snap = EloSnapshot.model_validate_json(f.read_text(encoding="utf-8"))
        for a in snap.agents:
            if a.agent_id != agent_id:
                continue
            for tag, elo in a.tags_with_elo.items():
                series.setdefault(tag, []).append(EloPoint(timestamp=snap.timestamp, elo=elo))
    return [TagEloSeries(tag=tag, points=pts) for tag, pts in sorted(series.items())]


def _activity(runs_root: Path, agent_id: str) -> AgentActivity:
    claims = wins = successes = failures = 0
    sdir = runs_root / "sessions"
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            trace = d / "trace.jsonl"
            if not trace.exists():
                continue
            for e in load_trace(trace):
                if isinstance(e, Phase2ClaimedEvent) and e.agent_id == agent_id and e.decision == "claim":
                    claims += 1
                elif isinstance(e, DispatchedEvent) and e.agent_id == agent_id:
                    wins += 1
                elif isinstance(e, QAEvaluatedEvent) and e.agent_id == agent_id:
                    if e.success:
                        successes += 1
                    else:
                        failures += 1
    return AgentActivity(claims=claims, wins=wins, successes=successes, failures=failures)


def agent_detail(runs_root: Path, agent_id: str) -> AgentDetailView | None:
    reg = _load_registry(runs_root)
    if reg is None:
        return None
    entry = next((e for e in reg.agents if e.agent_id == agent_id), None)
    if entry is None:
        return None
    return AgentDetailView(
        agent_id=entry.agent_id,
        name=entry.name,
        system_prompt=entry.system_prompt,
        tags_with_elo=entry.tags_with_elo,
        elo_history=_elo_history(runs_root, agent_id),
        activity=_activity(runs_root, agent_id),
    )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_agents.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/agents.py tests/dashboard/test_collectors_agents.py
git commit -m "feat(v2c): collector Agents (liste + detail : prompt, ELO courant, historique, activite)"
```

---

## Task 11: Collector `InfraStats` (Tab 1)

**Files:**
- Create: `dashboard/collectors/infra.py`
- Test: `tests/dashboard/test_collectors_infra.py`

- [ ] **Step 1: Écrire les tests infra**

Créer `tests/dashboard/test_collectors_infra.py` :

```python
from dashboard.collectors.infra import collect


def test_infra_counts(runs_root):
    stats = collect(runs_root)
    assert stats.session_count == 1
    assert stats.task_count == 2
    assert stats.run_count == 1            # un seul ExecutedEvent (t0)
    assert stats.agent_count == 4
    assert stats.qa_pass_rate == 1.0       # 1 QA event, success
    assert stats.total_tokens_in == 120
    assert stats.total_tokens_out == 80
    assert stats.latency.count == 1
    assert stats.latency.mean_ms == 350.0
    assert len(stats.pass_rate_over_time) == 1


def test_infra_empty(tmp_path):
    stats = collect(tmp_path)
    assert stats.session_count == 0
    assert stats.qa_pass_rate is None
    assert stats.latency.mean_ms is None
    assert stats.pass_rate_over_time == []
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_infra.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.collectors.infra'`.

- [ ] **Step 3: Créer `dashboard/collectors/infra.py`**

```python
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.tracing.events import ExecutedEvent, QAEvaluatedEvent
from aaosa.tracing.store import AgentRegistry, SessionMeta, load_trace


class LatencyStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    mean_ms: float | None
    min_ms: float | None
    max_ms: float | None


class PassRatePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    pass_rate: float


class InfraStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_count: int
    task_count: int
    agent_count: int
    run_count: int
    qa_pass_rate: float | None
    total_tokens_in: int
    total_tokens_out: int
    latency: LatencyStats
    pass_rate_over_time: list[PassRatePoint]


def collect(runs_root: Path) -> InfraStats:
    session_count = task_count = run_count = 0
    tokens_in = tokens_out = 0
    latencies: list[float] = []
    qa_total = qa_pass = 0
    pass_rate_over_time: list[PassRatePoint] = []
    agent_ids: set[str] = set()

    sdir = runs_root / "sessions"
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            meta_path, trace_path = d / "meta.json", d / "trace.jsonl"
            if not meta_path.exists() or not trace_path.exists():
                continue
            session_count += 1
            meta = SessionMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            task_count += len(meta.tasks)
            agent_ids.update(meta.agent_ids)

            s_qa_total = s_qa_pass = 0
            for e in load_trace(trace_path):
                if isinstance(e, ExecutedEvent):
                    run_count += 1
                    if e.llm_metadata is not None:  # nullable -> skip si absent (S5)
                        tokens_in += e.llm_metadata.tokens_in
                        tokens_out += e.llm_metadata.tokens_out
                        latencies.append(e.llm_metadata.latency_ms)
                elif isinstance(e, QAEvaluatedEvent):
                    s_qa_total += 1
                    if e.success:
                        s_qa_pass += 1
            qa_total += s_qa_total
            qa_pass += s_qa_pass
            if s_qa_total > 0:
                pass_rate_over_time.append(PassRatePoint(timestamp=meta.started_at, pass_rate=s_qa_pass / s_qa_total))

    pass_rate_over_time.sort(key=lambda p: p.timestamp)

    reg_path = runs_root / "agents" / "registry.json"
    if reg_path.exists():
        reg = AgentRegistry.model_validate_json(reg_path.read_text(encoding="utf-8"))
        agent_ids.update(e.agent_id for e in reg.agents)

    return InfraStats(
        session_count=session_count,
        task_count=task_count,
        agent_count=len(agent_ids),
        run_count=run_count,
        qa_pass_rate=(qa_pass / qa_total) if qa_total > 0 else None,
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        latency=LatencyStats(
            count=len(latencies),
            mean_ms=(sum(latencies) / len(latencies)) if latencies else None,
            min_ms=min(latencies) if latencies else None,
            max_ms=max(latencies) if latencies else None,
        ),
        pass_rate_over_time=pass_rate_over_time,
    )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_infra.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/infra.py tests/dashboard/test_collectors_infra.py
git commit -m "feat(v2c): collector InfraStats (agregat cross-session, llm_metadata nullable)"
```

---

# PHASE 3 — Non-régression

## Task 12: Suite complète + cycle d'import propre

**Files:** aucun (vérification)

- [ ] **Step 1: Lancer toute la suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (530 tests de l'Épique 02 + les nouveaux tests data/dashboard de ce plan), 0 échec.

- [ ] **Step 2: Vérifier l'absence de cycle d'import dashboard**

Run: `.venv\Scripts\python -c "import dashboard.app, dashboard.collectors.sessions, dashboard.collectors.health_checks, dashboard.collectors.agents, dashboard.collectors.infra; print('imports ok')"`
Expected: `imports ok`.

- [ ] **Step 3: Vérifier que `runs/` reste gitignoré et qu'aucun artefact runtime n'est suivi**

Run: `git status --short`
Expected: aucun fichier sous `runs/` listé ; seuls les fichiers du plan.

- [ ] **Step 4: Commit final éventuel (si une correction de non-régression a été nécessaire)**

```bash
git add -A
git commit -m "chore(v2c): non-regression epique 03a (collectors + cache + factory)"
```

> Si aucune correction n'a été nécessaire (toutes les tasks déjà commitées après reviews), ne rien committer ici.

---

## Self-review (effectuée à l'écriture)

**Couverture spec (Section 2 + épique 03a) :**
- `create_app(config)` factory → Task 4 ✓
- `config.py` → Task 2 ✓
- `cache.py` on-demand → Task 3 ✓
- Collector `InfraStats` (counts, latence, tokens, QA pass rate, pass rate dans le temps) → Task 11 ✓
- Collector `Agents` (prompt, ELO courant, historique ELO par tag, claim/win/success/fail) → Task 10 ✓
- Collector `HealthChecks` (liste, pass rates, unstable, quarantaine, TestSet, attribution, graphe par cas) → Tasks 7-9 ✓
- Collector `Sessions` (liste, meta + graphe) → Task 6 ✓
- Cache testé (2e accès ne recalcule pas) → Task 3 ✓
- Aucun endpoint HTTP → respecté (aucune route data dans `app.py`) ✓
- `runs_root` fixture partagé avec 03b → Task 5 ✓
- `load_trace` (seam 5) → Task 1 ✓

**Cohérence des types :** `runs_root: Path` partout ; `load_trace` renvoie `list[ClaimEvent]` consommé par tous les collectors ; `build_graph(events, SessionMeta | None)` appelé avec un `SessionMeta` réel (sessions) ou synthétisé (health checks) ; `EvaluatorSpec`/`SessionMeta`/`GraphModel`/`HealthCheckReport` réutilisés tels quels. Pas de placeholder.
