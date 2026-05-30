# V2c — Épique 03b — API REST + addendum data B1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exposer les 4 collectors (03a) et `build_graph` (02) en JSON via une couche HTTP Flask testée par `test_client`, après avoir figé l'identité des agents par run (B1) et capturé le `context` du task (addendum Épique 04) pour rendre les overlays fidèles au run réel.

**Architecture:** Un addendum **additif** à la couche data (`save_session`/`save_health_check` écrivent un `agents.json` par run, param optionnel — backward compat). Puis un helper de sérialisation unique (`model_dump(by_alias=True, mode="json")` + `Cache-Control: no-store`), et un `Blueprint("api")` de routes minces lisant `runs_root`/cache depuis `app.config`. Les collectors `sessions`/`health_checks` exposent en plus les agents du run.

**Tech Stack:** Python 3.14, Pydantic 2.13, Flask 3.1, pytest 9.0.3. Imports absolus uniquement. `model_config = ConfigDict(extra="forbid")` sur tout modèle.

**Décisions de design (deep-dive cross-check 2026-05-30 — spec `docs/superpowers/specs/2026-05-30-v2c-03b-rest-api-design.md`) :**
- **S1** — Helper `json_response(model)` = `Response(json.dumps(model.model_dump(by_alias=True, mode="json")), mimetype="application/json")` + `Cache-Control: no-store`. `by_alias` produit `from`/`to` des edges ; `mode="json"` gère datetime/Path. `error_response(msg)` = `{"error": msg}` + no-store. (Response + `json.dumps` plutôt que `jsonify` → testable sans app context.)
- **S2** — Un seul `Blueprint("api", url_prefix="/api")`, enregistré dans `create_app`. Routes lisent config/cache depuis `current_app.config`.
- **S3-A** — `/sessions/<id>` = meta + agents (**pas le graphe**) ; `/sessions/<id>/graph` = `GraphModel` nu. Symétrie avec `/health-checks/<id>/graph`.
- **S4-B** — `/health-checks/<id>/graph` sans `task_id` → premier cas graphable ; 404 si run absent / aucun cas graphable.
- **S5/B1** — `agent_id` régénéré à chaque instanciation → snapshot `agents.json` par run (modèle `AgentRegistry` réutilisé). Param `agents` **optionnel** (`None` = comportement 03a). Overlays joignent contre ce snapshot ; `/api/agents` reste le roster courant (Tab 2).
- **Addendum Épique 04 (Task 1B)** — `task.metadata["context"]` (input réel de l'agent, cf. `core/agent.py`) non capturé → `SessionTaskRecord.context` + `InputDetail.context` (optionnels, frères de B1), renseignés au constructeur dans `run_demo.py`. Overlay affiche le bloc Context si non vide.
- **S6** — 404 → corps JSON `{"error": ...}` + no-store, jamais nu.
- **Cache** — immuables-par-id mémorisés (détails, graphes) ; listes/infra recalculées (reflètent les nouveaux runs). Cohérent avec 03a.

---

## Consignes projet d'exécution (à respecter pour toutes les tasks)

- **Discipline de commit :** l'implémenteur **ne commit pas**. Le commit d'une task n'a lieu qu'**après** que la spec-review ET la quality-review soient passées (cf. subagent-driven-development). La dernière étape de chaque task donne la commande exacte, à n'exécuter qu'une fois la feature validée par les reviews.
- **Économie de tests :** Phases 0-1 sont 100% logique (persistance, sérialisation) → cycles TDD fail/pass conservés. Phase 2 (API) testée via `test_client`. Pas de re-run gratuit de la suite complète en milieu de task ; une seule task de non-régression finale (Task 11).

---

## Store / contrat cible après ce plan

```
src/aaosa/tracing/store.py
  _build_registry(agents) -> AgentRegistry        # factorisé depuis save_agent_registry
  save_session(tracer, meta, runs_root, agents=None)        # += agents.json si agents fourni
  SessionTaskRecord.context: str | None = None    # NOUVEAU (addendum Épique 04)
src/aaosa/qa/health_check.py
  save_health_check(report, test_set, tracer, directory, agents=None)   # += agents.json
dashboard/graph_model.py
  InputDetail.context: str | None = None          # NOUVEAU (addendum Épique 04)

runs_root/sessions/<id>/agents.json          # NOUVEAU
runs_root/health_checks/<ts>/agents.json     # NOUVEAU

dashboard/
  serialization.py   json_response / error_response          # NOUVEAU
  api.py             Blueprint("api") + 9 routes              # NOUVEAU
  app.py             create_app  += register_blueprint(api)
  collectors/sessions.py        SessionView += agents
  collectors/health_checks.py   HealthCheckView += agents
tests/dashboard/
  conftest.py        fixture runs_root : agents.json (session + HC)
  test_serialization.py · test_api.py                        # NOUVEAU
```

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/aaosa/tracing/store.py` | `_build_registry` + `save_session(..., agents)` + `SessionTaskRecord.context` | Modifier |
| `tests/tracing/test_store.py` | tests agents.json session | Modifier |
| `dashboard/graph_model.py` | `InputDetail.context` + `_build_step` (Task 1B) | Modifier |
| `tests/dashboard/test_graph_model.py` | test propagation context | Modifier |
| `src/aaosa/qa/health_check.py` | `save_health_check(..., agents)` | Modifier |
| `tests/qa/test_health_check.py` | tests agents.json HC | Modifier |
| `tests/dashboard/conftest.py` | fixture écrit les `agents.json` | Modifier |
| `dashboard/collectors/sessions.py` | `SessionView += agents` | Modifier |
| `tests/dashboard/test_collectors_sessions.py` | test agents | Modifier |
| `dashboard/collectors/health_checks.py` | `HealthCheckView += agents` | Modifier |
| `tests/dashboard/test_collectors_health_checks.py` | test agents | Modifier |
| `src/aaosa/demo/run_demo.py` · `run_health_check.py` | passent les agents (Task 6) ; `run_demo` renseigne aussi `context` (Task 1B) | Modifier |
| `dashboard/serialization.py` | helpers JSON | Créer |
| `tests/dashboard/test_serialization.py` | tests helpers | Créer |
| `dashboard/api.py` | blueprint + routes | Créer |
| `dashboard/app.py` | enregistre le blueprint | Modifier |
| `tests/dashboard/test_api.py` | tests `test_client` | Créer |

**Commande de test (Windows, toujours le venv) :** `.venv\Scripts\python -m pytest <fichier> -v`

---

# PHASE 0 — Addendum data B1 (snapshot agents par run)

## Task 1: `save_session(..., agents)` écrit `agents.json`

**Files:**
- Modify: `src/aaosa/tracing/store.py`
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Écrire les tests**

Ajouter à la fin de `tests/tracing/test_store.py` :

```python
class TestSaveSessionAgents:
    def _meta(self, sid):
        from datetime import datetime, timezone
        from aaosa.tracing.store import SessionMeta
        now = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
        return SessionMeta(session_id=sid, started_at=now, ended_at=now, tasks=[], agent_ids=[])

    def test_writes_agents_json_when_provided(self, tmp_path):
        from aaosa.demo.agents import DEMO_AGENTS
        from aaosa.tracing.store import AgentRegistry, save_session
        from aaosa.tracing.tracer import Tracer

        sid = "s-agents"
        tracer = Tracer(session_id=sid)
        save_session(tracer, self._meta(sid), tmp_path / "runs", agents=DEMO_AGENTS)

        path = tmp_path / "runs" / "sessions" / sid / "agents.json"
        assert path.exists()
        reg = AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        assert len(reg.agents) == len(DEMO_AGENTS)
        assert {e.agent_id for e in reg.agents} == {a.id for a in DEMO_AGENTS}
        assert all(e.system_prompt for e in reg.agents)

    def test_no_agents_json_when_omitted(self, tmp_path):
        from aaosa.tracing.store import save_session
        from aaosa.tracing.tracer import Tracer

        sid = "s-noagents"
        tracer = Tracer(session_id=sid)
        save_session(tracer, self._meta(sid), tmp_path / "runs")  # pas d'agents

        assert not (tmp_path / "runs" / "sessions" / sid / "agents.json").exists()
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py::TestSaveSessionAgents -v`
Expected: FAIL — `save_session() got an unexpected keyword argument 'agents'`.

- [ ] **Step 3: Factoriser `_build_registry` + ajouter le param `agents`**

Dans `src/aaosa/tracing/store.py`, remplacer `save_agent_registry` par une version factorisée et garder le comportement :

```python
def _build_registry(agents: list[Agent]) -> AgentRegistry:
    return AgentRegistry(
        agents=[
            AgentRegistryEntry(
                agent_id=a.id,
                name=a.name,
                system_prompt=a.system_prompt,
                tags_with_elo=dict(a.tags_with_elo),
            )
            for a in agents
        ]
    )


def save_agent_registry(agents: list[Agent], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_registry(agents).model_dump_json(indent=2), encoding="utf-8")
    return path
```

Puis modifier la signature et le corps de `save_session` :

```python
def save_session(
    tracer: Tracer,
    meta: SessionMeta,
    runs_root: Path,
    agents: list[Agent] | None = None,
) -> Path:
    if tracer.session_id != meta.session_id:
        raise ValueError(
            f"tracer.session_id ({tracer.session_id!r}) != meta.session_id ({meta.session_id!r})"
        )
    session_dir = runs_root / "sessions" / meta.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    tracer.flush(session_dir / "trace.jsonl")
    (session_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    if agents is not None:
        (session_dir / "agents.json").write_text(
            _build_registry(agents).model_dump_json(indent=2), encoding="utf-8"
        )
    return session_dir
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS (nouveaux + anciens, dont `save_agent_registry` inchangé fonctionnellement).

- [ ] **Step 5: Commit (après spec-review + quality-review)**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(v2c): save_session ecrit agents.json par run (B1, param optionnel)"
```

---

## Task 1B: Capture du `context` du task (addendum data — découverte deep-dive Épique 04)

> **Provenance :** deep-dive Épique 04 (spec `docs/superpowers/specs/2026-05-30-v2c-04-frontend-graph-design.md`). L'input réel de l'agent = `task.description + task.metadata["context"]` (`src/aaosa/core/agent.py::execute`), mais `SessionTaskRecord` ne persiste que `description` + `required_tags` → l'overlay Input/Agent masquerait une partie de ce que l'agent a reçu. **Frère de B1** : additif, optionnel, backward compat. La capture se fait dans le **constructeur de `SessionTaskRecord`** (`run_demo.py`), pas dans `save_session` (qui reçoit le `meta` déjà construit).

**Files:**
- Modify: `src/aaosa/tracing/store.py` (`SessionTaskRecord.context`)
- Modify: `dashboard/graph_model.py` (`InputDetail.context` + `_build_step`)
- Modify: `src/aaosa/demo/run_demo.py` (renseigne `context` depuis `task.metadata`)
- Test: `tests/dashboard/test_graph_model.py`

- [ ] **Step 1: Écrire les tests**

Ajouter à la classe de tests `StepDetail` de `tests/dashboard/test_graph_model.py` (mêmes helpers `p1`/`disp`/`ex`/`_meta`) :

```python
    def test_input_detail_carries_context(self):
        events = [p1("t1", "a", True, 0.9), disp("t1", "a", "fit"), ex("t1", "a", summary="s", content="c")]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS", winner_agent_id="a",
            outcome="no_qa", required_tags={"css": 60}, context="Fichier source: style.css ...",
        )])
        d = build_graph(events, sm).steps[0].detail
        assert d.input.context == "Fichier source: style.css ..."

    def test_input_detail_context_none_when_absent(self):
        events = [p1("t1", "a", True, 0.9), disp("t1", "a", "fit"), ex("t1", "a", summary="s", content="c")]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS", winner_agent_id="a",
            outcome="no_qa", required_tags={"css": 60},
        )])
        d = build_graph(events, sm).steps[0].detail
        assert d.input.context is None
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -k context -v`
Expected: FAIL — `SessionTaskRecord` rejette `context` (`extra="forbid"`) / `InputDetail` n'a pas d'attribut `context`.

- [ ] **Step 3: Ajouter le champ `context` (additif, optionnel)**

Dans `src/aaosa/tracing/store.py`, étendre `SessionTaskRecord` :

```python
class SessionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    winner_agent_id: str | None
    outcome: TaskOutcome
    required_tags: dict[str, int]
    context: str | None = None
```

Dans `dashboard/graph_model.py`, étendre `InputDetail` :

```python
class InputDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    description: str
    required_tags: dict[str, int]
    context: str | None = None
```

Toujours dans `dashboard/graph_model.py`, dans `_build_step`, renseigner `context` depuis le `meta_record` :

```python
    description = meta_record.description if meta_record is not None else task_id
    required_tags = dict(meta_record.required_tags) if meta_record is not None else {}
    context = meta_record.context if meta_record is not None else None
    input_detail = InputDetail(task_id=task_id, description=description, required_tags=required_tags, context=context)
```

Dans `src/aaosa/demo/run_demo.py`, renseigner `context` à la construction du `SessionTaskRecord` (≈ lignes 56-59) :

```python
        task_records.append(SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=winner_id, outcome=outcome,
            required_tags=task.required_tags,
            context=task.metadata.get("context") or None,
        ))
```

> `or None` normalise la chaîne vide (`metadata["context"] == ""`) en `None` → l'overlay masque le bloc Context comme attendu.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -v`
Expected: PASS (nouveaux + anciens — `InputDetail.context` optionnel ne casse aucune fixture existante).

- [ ] **Step 5: Commit (après spec-review + quality-review)**

```bash
git add src/aaosa/tracing/store.py dashboard/graph_model.py src/aaosa/demo/run_demo.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2c): capture task context dans SessionTaskRecord/InputDetail (addendum Epique 04)"
```

> Note : `run_demo.py` est aussi modifié en Task 6 (param `agents`). Si les deux tasks sont exécutées d'affilée, regrouper les deux changements `run_demo.py` en un seul passage est acceptable (au choix de l'implémenteur) — sinon committer séparément comme indiqué.

---

## Task 2: `save_health_check(..., agents)` écrit `agents.json`

**Files:**
- Modify: `src/aaosa/qa/health_check.py`
- Test: `tests/qa/test_health_check.py`

- [ ] **Step 1: Écrire les tests**

Ajouter à la fin de `tests/qa/test_health_check.py` :

```python
class TestSaveHealthCheckAgents:
    def _report(self):
        from datetime import datetime, timezone
        from aaosa.qa.health_check import HealthCheckReport
        return HealthCheckReport(
            timestamp=datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc),
            n_runs=1, total_cases=0, case_results=[],
            fix_target_pass_rate=0.0, regression_guard_pass_rate=0.0,
            unstable_cases=[], unattributed=[], task_spec_quarantined=[], evaluator_quarantined=[],
        )

    def test_writes_agents_json_when_provided(self, tmp_path):
        from aaosa.demo.agents import DEMO_AGENTS
        from aaosa.qa.health_check import save_health_check
        from aaosa.qa.test_set import TestSet
        from aaosa.tracing.store import AgentRegistry
        from aaosa.tracing.tracer import Tracer

        report = self._report()
        tracer = Tracer(session_id="hc-agents")
        target = save_health_check(report, TestSet(cases=[]), tracer, tmp_path / "hc", agents=DEMO_AGENTS)

        path = target / "agents.json"
        assert path.exists()
        reg = AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        assert {e.agent_id for e in reg.agents} == {a.id for a in DEMO_AGENTS}

    def test_no_agents_json_when_omitted(self, tmp_path):
        from aaosa.qa.health_check import save_health_check
        from aaosa.qa.test_set import TestSet
        from aaosa.tracing.tracer import Tracer

        report = self._report()
        tracer = Tracer(session_id="hc-noagents")
        target = save_health_check(report, TestSet(cases=[]), tracer, tmp_path / "hc")
        assert not (target / "agents.json").exists()
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_health_check.py::TestSaveHealthCheckAgents -v`
Expected: FAIL — `save_health_check() got an unexpected keyword argument 'agents'`.

- [ ] **Step 3: Ajouter le param `agents`**

Dans `src/aaosa/qa/health_check.py`, importer le helper et modifier `save_health_check` :

```python
from aaosa.tracing.store import _build_registry
```

```python
def save_health_check(
    report: HealthCheckReport,
    test_set: TestSet,
    tracer: Tracer,
    directory: Path,
    agents: list[Agent] | None = None,
) -> Path:
    ts = report.timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    target = directory / ts
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (target / "test_set.json").write_text(test_set.model_dump_json(indent=2), encoding="utf-8")
    tracer.flush(target / "trace.jsonl")
    if agents is not None:
        (target / "agents.json").write_text(
            _build_registry(agents).model_dump_json(indent=2), encoding="utf-8"
        )
    return target
```

> `Agent` est déjà importé dans `health_check.py` (ligne `from aaosa.core.agent import Agent`). L'import de `_build_registry` ne crée pas de cycle : `store.py` n'importe pas `qa.health_check`.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add src/aaosa/qa/health_check.py tests/qa/test_health_check.py
git commit -m "feat(v2c): save_health_check ecrit agents.json par run (B1, param optionnel)"
```

---

## Task 3: Fixture `runs_root` écrit les `agents.json`

**Files:**
- Modify: `tests/dashboard/conftest.py`

- [ ] **Step 1: Passer `agents=DEMO_AGENTS` aux deux sauvegardes**

Dans `tests/dashboard/conftest.py`, remplacer l'appel session :

```python
    save_session(tracer, meta, root)
```

par :

```python
    save_session(tracer, meta, root, agents=DEMO_AGENTS)
```

Et l'appel health check :

```python
    save_health_check(report, test_set, hc_tracer, root / "health_checks")
```

par :

```python
    save_health_check(report, test_set, hc_tracer, root / "health_checks", agents=DEMO_AGENTS)
```

- [ ] **Step 2: Vérifier que la fixture se construit toujours**

Ajouter temporairement dans `tests/dashboard/test_app.py` :

```python
def test_runs_root_has_agents_json(runs_root):
    assert (runs_root / "sessions").is_dir()
    session_dirs = [d for d in (runs_root / "sessions").iterdir() if d.is_dir()]
    assert (session_dirs[0] / "agents.json").exists()
    hc_dirs = [d for d in (runs_root / "health_checks").iterdir() if d.is_dir()]
    assert (hc_dirs[0] / "agents.json").exists()
```

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_app.py::test_runs_root_has_agents_json -v`
Expected: PASS. (Retirable au profit des tests collectors/API qui exercent réellement les agents ; au choix du reviewer.)

- [ ] **Step 3: Commit (après reviews)**

```bash
git add tests/dashboard/conftest.py tests/dashboard/test_app.py
git commit -m "test(v2c): fixture runs_root ecrit agents.json (session + health check)"
```

---

## Task 4: Collector `Sessions` expose `agents`

**Files:**
- Modify: `dashboard/collectors/sessions.py`
- Test: `tests/dashboard/test_collectors_sessions.py`

- [ ] **Step 1: Écrire le test**

Ajouter à `tests/dashboard/test_collectors_sessions.py` :

```python
from aaosa.demo.agents import DEMO_AGENTS


def test_session_detail_has_agents(runs_root):
    sid = list_sessions(runs_root).sessions[0].session_id
    view = session_detail(runs_root, sid)
    assert view is not None
    assert len(view.agents) == len(DEMO_AGENTS)
    assert all(a.system_prompt for a in view.agents)
    assert {a.agent_id for a in view.agents} == {a.id for a in DEMO_AGENTS}
```

> `list_sessions` et `session_detail` sont déjà importés en haut du fichier.

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py::test_session_detail_has_agents -v`
Expected: FAIL — `AttributeError: 'SessionView' object has no attribute 'agents'`.

- [ ] **Step 3: Ajouter `agents` à `SessionView`**

Dans `dashboard/collectors/sessions.py`, étendre l'import store et ajouter un loader :

```python
from aaosa.tracing.store import AgentRegistry, AgentRegistryEntry, SessionMeta, load_trace
```

Ajouter `agents` au modèle `SessionView` :

```python
class SessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SessionMeta
    agents: list[AgentRegistryEntry]
    graph: GraphModel
```

Ajouter un helper (après `_load_meta`) :

```python
def _load_agents(session_dir: Path) -> list[AgentRegistryEntry]:
    path = session_dir / "agents.json"
    if not path.exists():
        return []
    return AgentRegistry.model_validate_json(path.read_text(encoding="utf-8")).agents
```

Et peupler dans `session_detail` :

```python
def session_detail(runs_root: Path, session_id: str) -> SessionView | None:
    d = _sessions_dir(runs_root) / session_id
    if not (d / "meta.json").exists() or not (d / "trace.jsonl").exists():
        return None
    meta = _load_meta(d)
    graph = build_graph(load_trace(d / "trace.jsonl"), meta)
    return SessionView(meta=meta, agents=_load_agents(d), graph=graph)
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py -v`
Expected: PASS (nouveau + anciens, dont `test_session_detail_graph`).

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/sessions.py tests/dashboard/test_collectors_sessions.py
git commit -m "feat(v2c): collector Sessions expose les agents du run (B1)"
```

---

## Task 5: Collector `HealthChecks` expose `agents`

**Files:**
- Modify: `dashboard/collectors/health_checks.py`
- Test: `tests/dashboard/test_collectors_health_checks.py`

- [ ] **Step 1: Écrire le test**

Ajouter à `tests/dashboard/test_collectors_health_checks.py` :

```python
from aaosa.demo.agents import DEMO_AGENTS


def test_run_detail_has_agents(runs_root):
    rid = list_runs(runs_root).runs[0].id
    view = run_detail(runs_root, rid)
    assert view is not None
    assert len(view.agents) == len(DEMO_AGENTS)
    assert all(a.system_prompt for a in view.agents)
```

> `list_runs` et `run_detail` sont déjà importés en haut du fichier.

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py::test_run_detail_has_agents -v`
Expected: FAIL — `AttributeError: 'HealthCheckView' object has no attribute 'agents'`.

- [ ] **Step 3: Ajouter `agents` à `HealthCheckView`**

Dans `dashboard/collectors/health_checks.py`, étendre l'import store :

```python
from aaosa.tracing.store import AgentRegistry, AgentRegistryEntry, SessionMeta, SessionTaskRecord, load_trace
```

Ajouter `agents` au modèle `HealthCheckView` (en fin de la liste des champs) :

```python
    unattributed: list[str]
    cases: list[HealthCheckCaseView]
    agents: list[AgentRegistryEntry]
```

Ajouter un helper (après `_load_test_set`) :

```python
def _load_agents(run_dir: Path) -> list[AgentRegistryEntry]:
    path = run_dir / "agents.json"
    if not path.exists():
        return []
    return AgentRegistry.model_validate_json(path.read_text(encoding="utf-8")).agents
```

Et peupler le champ dans le `return HealthCheckView(...)` de `run_detail` (ajouter la ligne) :

```python
        unattributed=report.unattributed,
        cases=cases,
        agents=_load_agents(d),
    )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_health_checks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/collectors/health_checks.py tests/dashboard/test_collectors_health_checks.py
git commit -m "feat(v2c): collector HealthChecks expose les agents du run (B1)"
```

---

## Task 6: Démos passent les agents

**Files:**
- Modify: `src/aaosa/demo/run_demo.py`
- Modify: `src/aaosa/demo/run_health_check.py`

> Scripts de démo (non couverts par TDD). On passe `agents=DEMO_AGENTS` aux deux sauvegardes, vérification par smoke import.

- [ ] **Step 1: `run_demo.py`**

Remplacer l'appel `save_session(tracer, meta, runs_root)` par :

```python
    session_dir = save_session(tracer, meta, runs_root, agents=DEMO_AGENTS)
```

- [ ] **Step 2: `run_health_check.py`**

Remplacer l'appel `save_health_check(report, test_set, tracer, Path("runs") / "health_checks")` par :

```python
    target = save_health_check(report, test_set, tracer, Path("runs") / "health_checks", agents=DEMO_AGENTS)
```

- [ ] **Step 3: Smoke import (pas d'appel LLM)**

Run: `.venv\Scripts\python -c "import aaosa.demo.run_demo, aaosa.demo.run_health_check; print('demos import ok')"`
Expected: `demos import ok`.

- [ ] **Step 4: Commit (après reviews)**

```bash
git add src/aaosa/demo/run_demo.py src/aaosa/demo/run_health_check.py
git commit -m "feat(v2c): demos persistent agents.json par run (B1)"
```

---

# PHASE 1 — Sérialisation

## Task 7: `dashboard/serialization.py`

**Files:**
- Create: `dashboard/serialization.py`
- Test: `tests/dashboard/test_serialization.py`

- [ ] **Step 1: Écrire les tests**

Créer `tests/dashboard/test_serialization.py` :

```python
import json
from datetime import datetime, timezone

from dashboard.collectors.infra import PassRatePoint
from dashboard.graph_model import GraphEdge
from dashboard.serialization import error_response, json_response


def test_json_response_alias_and_header():
    resp = json_response(GraphEdge(from_node="a", to="b"))
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.headers["Cache-Control"] == "no-store"
    body = json.loads(resp.get_data(as_text=True))
    assert body == {"from": "a", "to": "b"}  # by_alias -> "from"


def test_json_response_datetime_iso():
    p = PassRatePoint(timestamp=datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc), pass_rate=0.5)
    body = json.loads(json_response(p).get_data(as_text=True))
    assert body["timestamp"].startswith("2026-05-30T10:00:00")


def test_json_response_status():
    resp = json_response(GraphEdge(from_node="a", to="b"), status=201)
    assert resp.status_code == 201


def test_error_response():
    resp = error_response("session x not found")
    assert resp.status_code == 404
    assert resp.headers["Cache-Control"] == "no-store"
    assert json.loads(resp.get_data(as_text=True)) == {"error": "session x not found"}
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_serialization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.serialization'`.

- [ ] **Step 3: Créer `dashboard/serialization.py`**

```python
import json

from flask import Response
from pydantic import BaseModel


def json_response(model: BaseModel, status: int = 200) -> Response:
    """Sérialise un modèle Pydantic en réponse JSON no-store.

    by_alias=True -> alias `from` des GraphEdge ; mode="json" -> datetime/Path JSON-safe.
    Response + json.dumps (pas jsonify) -> pas besoin d'app context.
    """
    body = json.dumps(model.model_dump(by_alias=True, mode="json"))
    resp = Response(body, status=status, mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def error_response(msg: str, status: int = 404) -> Response:
    resp = Response(json.dumps({"error": msg}), status=status, mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_serialization.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/serialization.py tests/dashboard/test_serialization.py
git commit -m "feat(v2c): helpers json_response / error_response (by_alias, no-store)"
```

---

# PHASE 2 — API (Blueprint + routes)

## Task 8: Blueprint + endpoints Infra & Agents + enregistrement

**Files:**
- Create: `dashboard/api.py`
- Modify: `dashboard/app.py`
- Test: `tests/dashboard/test_api.py`

- [ ] **Step 1: Écrire les tests**

Créer `tests/dashboard/test_api.py` :

```python
from aaosa.demo.agents import DEMO_AGENTS
from dashboard.app import create_app
from dashboard.config import DashboardConfig


def _client(runs_root):
    return create_app(DashboardConfig(runs_root=runs_root)).test_client()


def test_infra_endpoint(runs_root):
    r = _client(runs_root).get("/api/infra")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert r.get_json()["session_count"] == 1


def test_agents_list(runs_root):
    r = _client(runs_root).get("/api/agents")
    assert r.status_code == 200
    assert len(r.get_json()["agents"]) == len(DEMO_AGENTS)


def test_agent_detail(runs_root):
    r = _client(runs_root).get(f"/api/agents/{DEMO_AGENTS[0].id}")
    assert r.status_code == 200
    assert r.get_json()["system_prompt"]


def test_agent_detail_404(runs_root):
    r = _client(runs_root).get("/api/agents/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()
    assert r.headers["Cache-Control"] == "no-store"
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py -v`
Expected: FAIL — 404 sur `/api/infra` (aucune route enregistrée).

- [ ] **Step 3: Créer `dashboard/api.py` (blueprint + infra + agents)**

```python
from flask import Blueprint, current_app

from dashboard.collectors import agents as agents_collector
from dashboard.collectors import infra as infra_collector
from dashboard.serialization import error_response, json_response

api = Blueprint("api", __name__, url_prefix="/api")


def _runs_root():
    return current_app.config["AAOSA"].runs_root


def _cache():
    return current_app.config["CACHE"]


@api.get("/infra")
def get_infra():
    return json_response(infra_collector.collect(_runs_root()))


@api.get("/agents")
def get_agents():
    return json_response(agents_collector.list_agents(_runs_root()))


@api.get("/agents/<agent_id>")
def get_agent(agent_id):
    view = _cache().get_or_compute(
        f"agent:{agent_id}", lambda: agents_collector.agent_detail(_runs_root(), agent_id)
    )
    if view is None:
        return error_response(f"agent {agent_id} not found")
    return json_response(view)
```

- [ ] **Step 4: Enregistrer le blueprint dans `create_app`**

Dans `dashboard/app.py`, ajouter l'import et la ligne d'enregistrement :

```python
from flask import Flask

from dashboard.api import api
from dashboard.cache import Cache
from dashboard.config import DashboardConfig


def create_app(config: DashboardConfig | None = None) -> Flask:
    """Factory. Attache config + cache et enregistre l'API REST (Épique 03b)."""
    config = config or DashboardConfig()
    app = Flask(__name__)
    app.config["AAOSA"] = config
    app.config["CACHE"] = Cache()
    app.register_blueprint(api)
    return app
```

- [ ] **Step 5: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py tests/dashboard/test_app.py -v`
Expected: PASS (API + les tests factory existants restent verts).

- [ ] **Step 6: Commit (après reviews)**

```bash
git add dashboard/api.py dashboard/app.py tests/dashboard/test_api.py
git commit -m "feat(v2c): API blueprint + endpoints infra & agents (Cache-Control no-store)"
```

---

## Task 9: Endpoints Sessions (liste / détail meta+agents / graphe)

**Files:**
- Modify: `dashboard/api.py`
- Test: `tests/dashboard/test_api.py`

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/dashboard/test_api.py` :

```python
def test_sessions_list(runs_root):
    r = _client(runs_root).get("/api/sessions")
    assert r.status_code == 200
    assert len(r.get_json()["sessions"]) == 1


def test_session_detail_meta_agents_no_graph(runs_root):
    c = _client(runs_root)
    sid = c.get("/api/sessions").get_json()["sessions"][0]["session_id"]
    body = c.get(f"/api/sessions/{sid}").get_json()
    assert "graph" not in body          # S3-A : détail = meta + agents, pas le graphe
    assert body["meta"]["session_id"] == sid
    assert len(body["agents"]) == len(DEMO_AGENTS)


def test_session_graph_edges_use_alias(runs_root):
    c = _client(runs_root)
    sid = c.get("/api/sessions").get_json()["sessions"][0]["session_id"]
    r = c.get(f"/api/sessions/{sid}/graph")
    assert r.status_code == 200
    g = r.get_json()
    assert len(g["steps"]) == 2
    assert all(("from" in e and "to" in e) for e in g["edges"])  # by_alias


def test_session_detail_404(runs_root):
    r = _client(runs_root).get("/api/sessions/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_session_graph_404(runs_root):
    r = _client(runs_root).get("/api/sessions/nope/graph")
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py::test_session_detail_meta_agents_no_graph -v`
Expected: FAIL — 404 (routes sessions absentes).

- [ ] **Step 3: Ajouter les routes sessions à `dashboard/api.py`**

En tête de fichier, étendre les imports :

```python
from pydantic import BaseModel, ConfigDict

from aaosa.tracing.store import AgentRegistryEntry, SessionMeta
from dashboard.collectors import sessions as sessions_collector
```

Ajouter le modèle de réponse détail (projection meta+agents, S3-A) et les routes :

```python
class SessionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SessionMeta
    agents: list[AgentRegistryEntry]


def _session_view(session_id):
    return _cache().get_or_compute(
        f"session_view:{session_id}",
        lambda: sessions_collector.session_detail(_runs_root(), session_id),
    )


@api.get("/sessions")
def get_sessions():
    return json_response(sessions_collector.list_sessions(_runs_root()))


@api.get("/sessions/<session_id>")
def get_session(session_id):
    view = _session_view(session_id)
    if view is None:
        return error_response(f"session {session_id} not found")
    return json_response(SessionDetailResponse(meta=view.meta, agents=view.agents))


@api.get("/sessions/<session_id>/graph")
def get_session_graph(session_id):
    view = _session_view(session_id)
    if view is None:
        return error_response(f"session {session_id} not found")
    return json_response(view.graph)
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/api.py tests/dashboard/test_api.py
git commit -m "feat(v2c): API endpoints sessions (liste / detail meta+agents / graphe nu)"
```

---

## Task 10: Endpoints Health Checks (liste / détail / graphe avec défaut `task_id`)

**Files:**
- Modify: `dashboard/api.py`
- Test: `tests/dashboard/test_api.py`

- [ ] **Step 1: Écrire les tests**

Ajouter à `tests/dashboard/test_api.py` :

```python
def test_health_checks_list(runs_root):
    r = _client(runs_root).get("/api/health-checks")
    assert r.status_code == 200
    assert len(r.get_json()["runs"]) == 1


def test_health_check_detail_has_agents(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    body = c.get(f"/api/health-checks/{rid}").get_json()
    assert len(body["cases"]) == 2
    assert len(body["agents"]) == len(DEMO_AGENTS)


def test_health_check_graph_default_first_graphable(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    r = c.get(f"/api/health-checks/{rid}/graph")  # sans task_id -> 1er cas graphable (S4-B)
    assert r.status_code == 200
    assert len(r.get_json()["steps"]) == 1


def test_health_check_graph_explicit_task(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    detail = c.get(f"/api/health-checks/{rid}").get_json()
    graphable_tid = [cc["task_id"] for cc in detail["cases"] if cc["graphable"]][0]
    r = c.get(f"/api/health-checks/{rid}/graph?task_id={graphable_tid}")
    assert r.status_code == 200


def test_health_check_graph_quarantined_404(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    detail = c.get(f"/api/health-checks/{rid}").get_json()
    quarantined_tid = [cc["task_id"] for cc in detail["cases"] if not cc["graphable"]][0]
    r = c.get(f"/api/health-checks/{rid}/graph?task_id={quarantined_tid}")
    assert r.status_code == 404


def test_health_check_detail_404(runs_root):
    r = _client(runs_root).get("/api/health-checks/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py::test_health_checks_list -v`
Expected: FAIL — 404 (routes health-checks absentes).

- [ ] **Step 3: Ajouter les routes health-checks à `dashboard/api.py`**

En tête de fichier, étendre les imports :

```python
from flask import Blueprint, current_app, request
```

```python
from dashboard.collectors import health_checks as hc_collector
```

Ajouter les routes :

```python
def _hc_view(run_id):
    return _cache().get_or_compute(
        f"hc_view:{run_id}", lambda: hc_collector.run_detail(_runs_root(), run_id)
    )


@api.get("/health-checks")
def get_health_checks():
    return json_response(hc_collector.list_runs(_runs_root()))


@api.get("/health-checks/<run_id>")
def get_health_check(run_id):
    view = _hc_view(run_id)
    if view is None:
        return error_response(f"health check {run_id} not found")
    return json_response(view)


@api.get("/health-checks/<run_id>/graph")
def get_health_check_graph(run_id):
    view = _hc_view(run_id)
    if view is None:
        return error_response(f"health check {run_id} not found")
    task_id = request.args.get("task_id")
    if task_id is None:  # S4-B : défaut = premier cas graphable
        graphable = [c for c in view.cases if c.graphable]
        if not graphable:
            return error_response(f"health check {run_id} has no graphable case")
        task_id = graphable[0].task_id
    graph = _cache().get_or_compute(
        f"hc_graph:{run_id}:{task_id}",
        lambda: hc_collector.case_graph(_runs_root(), run_id, task_id),
    )
    if graph is None:
        return error_response(f"task {task_id} not graphable in run {run_id}")
    return json_response(graph)
```

> `request` est ajouté à l'import `flask` existant (Step 3 le montre). La ligne `from flask import Blueprint, current_app` de la Task 8 devient `from flask import Blueprint, current_app, request`.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (après reviews)**

```bash
git add dashboard/api.py tests/dashboard/test_api.py
git commit -m "feat(v2c): API endpoints health-checks (liste / detail / graphe avec defaut task_id)"
```

---

# PHASE 3 — Non-régression

## Task 11: Suite complète + cycle d'import propre

**Files:** aucun (vérification)

- [ ] **Step 1: Lancer toute la suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (557 tests de l'Épique 03a + les nouveaux tests data/serialization/api de ce plan), 0 échec.

- [ ] **Step 2: Vérifier l'absence de cycle d'import dashboard + data**

Run: `.venv\Scripts\python -c "import dashboard.app, dashboard.api, dashboard.serialization; import aaosa.qa.health_check, aaosa.tracing.store; print('imports ok')"`
Expected: `imports ok`.

- [ ] **Step 3: Vérifier qu'aucun artefact runtime n'est suivi**

Run: `git status --short`
Expected: aucun fichier sous `runs/` listé ; seuls les fichiers du plan.

- [ ] **Step 4: Commit final éventuel (si une correction de non-régression a été nécessaire)**

```bash
git add -A
git commit -m "chore(v2c): non-regression epique 03b (API REST + addendum data B1)"
```

> Si aucune correction n'a été nécessaire (toutes les tasks déjà commitées après reviews), ne rien committer ici.

---

## Self-review (effectuée à l'écriture)

**Couverture spec (`2026-05-30-v2c-03b-rest-api-design.md` + addendum Épique 04) :**
- Addendum Épique 04 (context) : `SessionTaskRecord.context` + `InputDetail.context` + `_build_step` + `run_demo` → Task 1B ✓ (optionnels, backward compat vérifiée par `test_input_detail_context_none_when_absent`).
- Addendum B1 : `save_session(..., agents)` → Task 1 ✓ ; `save_health_check(..., agents)` → Task 2 ✓ ; helper `_build_registry` factorisé → Task 1 ✓ ; démos → Task 6 ✓ ; fixture `agents.json` → Task 3 ✓ ; collectors exposent `agents` → Tasks 4-5 ✓ (backward compat : param optionnel `None`, vérifié Task 1/2 `test_no_agents_json_when_omitted`).
- S1 sérialisation (`by_alias`, datetime, no-store, `error_response`) → Task 7 ✓.
- S2 blueprint + enregistrement → Task 8 ✓.
- S3-A `/sessions/<id>` meta+agents sans graphe + `/sessions/<id>/graph` nu → Task 9 ✓ (test `test_session_detail_meta_agents_no_graph` assert `"graph" not in body`).
- S4-B `/health-checks/<id>/graph` défaut 1er cas graphable + 404 → Task 10 ✓.
- S6 404 `{"error": ...}` + no-store → Tasks 8-10 ✓.
- Cache immuables-par-id mémorisés / listes recalculées → Tasks 8-10 ✓ (`agent:`/`session_view:`/`hc_view:`/`hc_graph:` mémorisés ; `list_*`/`infra` recalculés).
- Critère de done « Cache-Control no-store sur succès ET 404 » → helper unique (Task 7) garantit les deux.

**Cohérence des types :** `runs_root: Path` partout ; `SessionView(meta, agents, graph)` (Task 4) consommé par `_session_view` (Task 9) qui projette en `SessionDetailResponse(meta, agents)` et expose `.graph` ; `HealthCheckView(..., agents)` (Task 5) renvoyé tel quel (Task 10) ; `case_graph(runs_root, run_id, task_id)` renvoie `GraphModel | None` (signature inchangée depuis 03a) ; `_build_registry` renvoie `AgentRegistry`, `.agents` est `list[AgentRegistryEntry]` réutilisé dans les deux collectors et la réponse session. Pas de placeholder.

**Note d'exécution :** le cache mémorise aussi les `None` (id absent) — acceptable en V1 statique (un id manquant reste manquant sans redémarrage). Documenté ici, pas un bug.
