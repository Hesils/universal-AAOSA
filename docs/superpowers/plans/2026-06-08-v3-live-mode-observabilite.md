# Live mode observabilité (ex-B7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regarder un run `aaosa run` se construire en direct dans le dashboard — l'arbre émergent se révèle jalon par jalon pendant l'exécution, via poll du store fichier (pas de SSE).

**Architecture:** Découplage par filesystem. Le run (process A) écrit sa trace au fil de l'eau (`StreamingTracer`) et marque sa session `status="running"` dans `meta.json`, finalisée en `"complete"` à la fin. Le dashboard (process B) poll le store : il recalcule `build_graph` à chaque requête pour les sessions `running` (cache bypassé), met en cache à partir de `complete`. `build_graph` est inchangé (déjà tolérant aux traces partielles). Le frontend poll graphe + liste, avance la frontière de révélation et suit la caméra.

**Tech Stack:** Python 3.14, Pydantic 2.13, Flask, OpenAI SDK ; frontend vanilla JS/SVG (`dashboard/static/js/`). Tests pytest. Backend en TDD ; frontend via skill `impeccable` + validation navigateur.

**Source de vérité :** `docs/superpowers/specs/2026-06-08-v3-live-mode-observabilite-design.md`. Ne pas re-décider le cadrage (4 décisions tranchées : poll partiel, persistance incrémentale par défaut, surface = arbre `/impeccable`, pilotage UI hors scope).

**Rétrocompat verrouillée (à ne jamais casser) :**
- `Tracer` base inchangé — `StreamingTracer` est une sous-classe additive.
- `SessionMeta.status` est un champ **additif defaulté** `"complete"` (les 16 `meta.json` de `runs_demo/` et toutes les fixtures parsent inchangés malgré `extra="forbid"`).
- `build_graph` : **signature inchangée**, code inchangé (on ajoute seulement des tests).
- `save_session` : idempotent (réécrit `trace.jsonl` à l'identique depuis la mémoire).
- `runs_demo/` rejoue identique : `aaosa dashboard --runs-root runs_demo`.

**État de départ :** 992 tests (991 passed + 1 skip). Branche `feat/v3-live-mode`.

---

## File Structure

**Modifiés (backend, TDD) :**
- `src/aaosa/tracing/store.py` — `SessionMeta.status` (additif) · `load_trace_partial` (lecture tolérante).
- `src/aaosa/tracing/tracer.py` — `StreamingTracer` (sous-classe write-through).
- `src/aaosa/cli/incident_runs.py` — `run_once` restructuré (meta provisoire `running` → finalisation `complete` + `StreamingTracer`).
- `dashboard/collectors/sessions.py` — `SessionListItem.status` · `SessionView` porte déjà `meta.status` · `session_status` helper · `session_detail` utilise `load_trace_partial`.
- `dashboard/api.py` — `_session_view` status-gated (cache bypass si `running`).

**Inchangés (vérifiés tolérants, on ajoute des tests) :**
- `dashboard/graph_model.py` — `build_graph` tolère déjà trace partielle / INPUT-seul / meta provisoire.

**Frontend (skill `impeccable` uniquement, Tasks 8-9) :**
- `dashboard/static/js/tabs/sessions.js` · `graph.js` · `camera.js` · `modal.js` + CSS.

---

## Task 1: `SessionMeta.status` — champ additif defaulté

**Files:**
- Modify: `src/aaosa/tracing/store.py:66-72` (classe `SessionMeta`)
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/tracing/test_store.py` :

```python
from aaosa.tracing.store import SessionMeta


def _meta_kwargs():
    from datetime import datetime, timezone
    now = datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)
    return dict(
        session_id="s1",
        started_at=now,
        ended_at=now,
        tasks=[],
        agent_ids=["a1"],
    )


def test_session_meta_status_defaults_to_complete():
    # rétrocompat : un meta sans le champ status est valide et vaut "complete"
    meta = SessionMeta(**_meta_kwargs())
    assert meta.status == "complete"


def test_session_meta_status_running_accepted():
    meta = SessionMeta(**_meta_kwargs(), status="running")
    assert meta.status == "running"


def test_session_meta_legacy_json_without_status_parses():
    # un meta.json d'avant ce champ (extra="forbid") doit parser et défaulter
    import json
    legacy = json.dumps({
        "session_id": "s1",
        "started_at": "2026-06-08T10:00:00+00:00",
        "ended_at": "2026-06-08T10:00:00+00:00",
        "tasks": [],
        "agent_ids": ["a1"],
    })
    meta = SessionMeta.model_validate_json(legacy)
    assert meta.status == "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -k status -v`
Expected: FAIL — `AttributeError: 'SessionMeta' object has no attribute 'status'` (les 2 premiers) ; le 3e passe déjà mais n'asserte `status` qu'après le champ ajouté.

- [ ] **Step 3: Add the field**

Dans `src/aaosa/tracing/store.py`, classe `SessionMeta`, ajouter le champ après `agent_ids` :

```python
class SessionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    tasks: list[SessionTaskRecord]
    agent_ids: list[str]
    status: Literal["running", "complete"] = "complete"
```

`Literal` est déjà importé (ligne 4 : `from typing import Literal`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS (anciens + nouveaux).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(store): SessionMeta.status additif defaulte complete (live mode)"
```

---

## Task 2: `load_trace_partial` — lecture tolérante d'une trace en cours d'écriture

**Files:**
- Modify: `src/aaosa/tracing/store.py:96-102` (après `load_trace`)
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/tracing/test_store.py` :

```python
from aaosa.tracing.store import load_trace_partial
from aaosa.tracing.events import UnassignedEvent


def _line(task_id: str) -> str:
    return UnassignedEvent(session_id="s", task_id=task_id, reason="x").model_dump_json()


def test_load_trace_partial_reads_all_valid_lines(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(_line("t0") + "\n" + _line("t1") + "\n", encoding="utf-8")
    events = load_trace_partial(path)
    assert [e.task_id for e in events] == ["t0", "t1"]


def test_load_trace_partial_tolerates_truncated_last_line(tmp_path):
    # append concurrent surpris mi-écriture : la dernière ligne est tronquée
    path = tmp_path / "trace.jsonl"
    good = _line("t0")
    truncated = _line("t1")[:15]  # JSON incomplet
    path.write_text(good + "\n" + truncated, encoding="utf-8")
    events = load_trace_partial(path)
    assert [e.task_id for e in events] == ["t0"]  # préfixe valide rendu, ligne cassée ignorée


def test_load_trace_partial_empty_file(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    assert load_trace_partial(path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -k partial -v`
Expected: FAIL — `ImportError: cannot import name 'load_trace_partial'`.

- [ ] **Step 3: Implement `load_trace_partial`**

Dans `src/aaosa/tracing/store.py`, ajouter après `load_trace` :

```python
def load_trace_partial(path: Path) -> list[ClaimEvent]:
    """Comme load_trace, mais tolère une dernière ligne tronquée (append concurrent
    surpris mi-écriture par un poll live). Les lignes valides du préfixe sont rendues ;
    une ligne JSON incomplète est ignorée (rattrapée au tick de poll suivant)."""
    out: list[ClaimEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(_event_adapter.validate_json(line))
        except ValueError:
            break  # ligne tronquée = fin du préfixe valide
    return out
```

Note : `break` (pas `continue`) — une ligne tronquée ne peut être que la dernière (l'écriture est append-only séquentielle) ; s'arrêter évite d'avaler une ligne future qui paraîtrait valide.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -k partial -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(store): load_trace_partial tolere une derniere ligne tronquee (live poll)"
```

---

## Task 3: `StreamingTracer` — write-through append par event

**Files:**
- Modify: `src/aaosa/tracing/tracer.py` (ajout sous-classe)
- Test: `tests/tracing/test_streaming_tracer.py` (créer)

- [ ] **Step 1: Write the failing tests**

Créer `tests/tracing/test_streaming_tracer.py` :

```python
from aaosa.tracing.events import UnassignedEvent
from aaosa.tracing.store import load_trace_partial
from aaosa.tracing.tracer import StreamingTracer, Tracer


def _ev(task_id: str) -> UnassignedEvent:
    return UnassignedEvent(session_id="s", task_id=task_id, reason="x")


def test_streaming_tracer_is_a_tracer():
    t = StreamingTracer(session_id="s", stream_path=None)  # path None autorisé pour le typage ?
    assert isinstance(t, Tracer)


def test_emit_appends_line_readable_before_close(tmp_path):
    path = tmp_path / "trace.jsonl"
    t = StreamingTracer(session_id="s", stream_path=path)
    t.emit(_ev("t0"))
    # lisible MI-STREAM, avant close()/flush final
    events = load_trace_partial(path)
    assert [e.task_id for e in events] == ["t0"]
    t.emit(_ev("t1"))
    assert [e.task_id for e in load_trace_partial(path)] == ["t0", "t1"]
    t.close()


def test_emit_still_accumulates_in_memory(tmp_path):
    t = StreamingTracer(session_id="s", stream_path=tmp_path / "trace.jsonl")
    t.emit(_ev("t0"))
    t.emit(_ev("t1"))
    assert [e.task_id for e in t.events] == ["t0", "t1"]
    t.close()


def test_close_releases_handle_allows_rewrite(tmp_path):
    # après close(), un flush "w" sur le même fichier ne lève pas (lock Windows libéré)
    path = tmp_path / "trace.jsonl"
    t = StreamingTracer(session_id="s", stream_path=path)
    t.emit(_ev("t0"))
    t.close()
    t.flush(path)  # réécriture idempotente, ne doit pas lever
    assert [e.task_id for e in load_trace_partial(path)] == ["t0"]


def test_close_is_idempotent(tmp_path):
    t = StreamingTracer(session_id="s", stream_path=tmp_path / "trace.jsonl")
    t.close()
    t.close()  # second close ne lève pas
```

(Retirer `test_streaming_tracer_is_a_tracer`'s commentaire ambigu : on teste juste l'héritage.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_streaming_tracer.py -v`
Expected: FAIL — `ImportError: cannot import name 'StreamingTracer'`.

- [ ] **Step 3: Implement `StreamingTracer`**

Dans `src/aaosa/tracing/tracer.py`, ajouter la sous-classe (le `Tracer` de base reste **inchangé**) :

```python
class StreamingTracer(Tracer):
    """Tracer qui, en plus d'accumuler en mémoire, append chaque event à un
    trace.jsonl ouvert (flush par emit) — la session est observable en live par
    un autre process qui poll le fichier. Le Tracer de base reste pur en-mémoire.

    Le handle doit être fermé (close()) avant que save_session ne réécrive le
    fichier (lock Windows). close() est idempotent.
    """

    def __init__(self, session_id: str, stream_path: Path | None) -> None:
        super().__init__(session_id)
        self._stream_path = stream_path
        self._handle = None
        if stream_path is not None:
            stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = stream_path.open("w", encoding="utf-8")

    def emit(self, event: ClaimEvent) -> None:
        super().emit(event)
        if self._handle is not None:
            self._handle.write(event.model_dump_json() + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_streaming_tracer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full tracer/store suite (non-régression)**

Run: `.venv\Scripts\python -m pytest tests/tracing/ -v`
Expected: PASS (anciens tracer/store + nouveaux).

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/tracing/tracer.py tests/tracing/test_streaming_tracer.py
git commit -m "feat(tracer): StreamingTracer write-through append par event (live mode)"
```

---

## Task 4: `run_once` restructuré — meta provisoire `running` → finalisation `complete`

**Files:**
- Modify: `src/aaosa/cli/incident_runs.py:116-172` (`run_once`)
- Test: `tests/cli/test_incident_runs.py`

**Contexte :** `run_once` n'est pas unit-testé directement aujourd'hui (seulement via `run_campaign` avec `run_once` stubbé). On le restructure ; on teste en monkeypatchant `run_with_recovery` pour inspecter l'état disque au moment exact de l'exécution. Aucun appel LLM réel (les constructeurs `TaskDivider`/`TaskAggregator`/`Tagger`/`AdaptiveSpecEvaluator(None)` n'appellent pas le LLM ; `full_roster()` est pur ; `load_elo_into` sur root vide retourne False).

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/cli/test_incident_runs.py` :

```python
from aaosa.cli.incident_runs import run_once
from aaosa.tracing.store import SessionMeta


class TestRunOnceLive:
    def _output_for(self, task):
        from aaosa.schemas.output import LLMMetadata, Output
        return Output(
            task_id=task.id, agent_id="log-analyst", content="done",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )

    def test_provisional_meta_running_written_before_exec(self, tmp_path, monkeypatch):
        captured = {}

        def fake_recovery(task, ctx):
            sdir = next((tmp_path / "sessions").iterdir())
            meta = SessionMeta.model_validate_json(
                (sdir / "meta.json").read_text(encoding="utf-8")
            )
            captured["status_during"] = meta.status
            captured["trace_exists_during"] = (sdir / "trace.jsonl").exists()
            captured["desc_during"] = meta.tasks[0].description
            return self._output_for(task)

        monkeypatch.setattr(incident_runs, "run_with_recovery", fake_recovery)
        outcome = run_once("main", tmp_path, client=None)

        # pendant l'exécution : meta visible, status running, trace ouverte, vraie description
        assert captured["status_during"] == "running"
        assert captured["trace_exists_during"] is True
        assert captured["desc_during"]  # non vide = vraie description de tâche

    def test_meta_finalized_complete_after_exec(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            incident_runs, "run_with_recovery",
            lambda task, ctx: self._output_for(task),
        )
        outcome = run_once("main", tmp_path, client=None)
        final = SessionMeta.model_validate_json(
            (outcome.session_dir / "meta.json").read_text(encoding="utf-8")
        )
        assert final.status == "complete"
        assert final.ended_at >= final.started_at

    def test_trace_persisted_and_reloadable_after_run(self, tmp_path, monkeypatch):
        from aaosa.tracing.store import load_trace
        monkeypatch.setattr(
            incident_runs, "run_with_recovery",
            lambda task, ctx: self._output_for(task),
        )
        outcome = run_once("main", tmp_path, client=None)
        # save_session a réécrit la trace à l'identique après close() — relisible
        events = load_trace(outcome.session_dir / "trace.jsonl")
        assert isinstance(events, list)  # pas de crash de relecture (handle fermé)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py::TestRunOnceLive -v`
Expected: FAIL — `test_provisional_meta_running_written_before_exec` : `StopIteration` (aucune session écrite avant `run_with_recovery`) ; les autres peuvent passer accidentellement → c'est le premier test qui pilote la restructuration.

- [ ] **Step 3: Restructurer `run_once`**

Remplacer le corps de `run_once` (`src/aaosa/cli/incident_runs.py`) par :

```python
def run_once(scenario: str, runs_root: Path, client: OpenAI) -> RunOutcome:
    """Un run incident complet, observable en live : crée la session + meta
    provisoire (status="running") AVANT exécution, streame la trace au fil de
    l'eau (StreamingTracer), finalise (status="complete", ended_at, outcome) APRÈS.
    Mécanique migrée de run_incident.py (phase 3) + persistance incrémentale (live mode)."""
    session_id = new_session_id()
    started_at = datetime.now(timezone.utc)
    session_dir = runs_root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    agents = _ROSTERS[scenario]()
    load_elo_into(agents, runs_root)
    task = build_data_leak_task()

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

    # 1) meta provisoire + trace streamée -> session visible dès le démarrage
    provisional = _meta("running", started_at, "divided")
    (session_dir / "meta.json").write_text(
        provisional.model_dump_json(indent=2), encoding="utf-8"
    )
    tracer = StreamingTracer(session_id=session_id, stream_path=session_dir / "trace.jsonl")

    ctx = RunContext(
        agents=agents,
        client=client,
        divider=TaskDivider(system_prompt=DIVIDER_PROMPT),
        aggregator=TaskAggregator(system_prompt=AGGREGATOR_PROMPT),
        tagger=Tagger(system_prompt=TAGGER_PROMPT),
        tracer=tracer,
        evaluator=AdaptiveSpecEvaluator(client),
    )

    # 2) exécution -> events streamés incrémentalement
    try:
        result = run_with_recovery(task, ctx)
    finally:
        tracer.close()  # libère le handle (lock Windows) avant réécriture
    kind = _result_kind(result)

    # 3) finalisation : meta complete + persistance normale (save_session idempotent)
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = _meta("complete", datetime.now(timezone.utc), _META_OUTCOME[kind])
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

Mettre à jour l'import en tête de fichier : remplacer
`from aaosa.tracing.tracer import Tracer`
par
`from aaosa.tracing.tracer import StreamingTracer`
(le `Tracer` nu n'est plus utilisé dans ce module — vérifier qu'aucune autre référence ne subsiste).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/cli/test_incident_runs.py -v`
Expected: PASS — `TestRunOnceLive` (3) + tous les `TestRunCampaign` existants (non-régression : `run_campaign` appelle `run_once` qui garde la même signature et le même `RunOutcome`).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/cli/incident_runs.py tests/cli/test_incident_runs.py
git commit -m "feat(cli): run_once persistance incrementale - meta running->complete + StreamingTracer (live mode)"
```

---

## Task 5: Backend dashboard live-aware — `status` exposé + cache status-gated

**Files:**
- Modify: `dashboard/collectors/sessions.py` (`SessionListItem.status`, `session_status` helper, `session_detail` via `load_trace_partial`)
- Modify: `dashboard/api.py:48-52` (`_session_view` status-gated)
- Test: `tests/dashboard/test_collectors_sessions.py`, `tests/dashboard/test_api.py`

- [ ] **Step 1: Write the failing collector tests**

Ajouter dans `tests/dashboard/test_collectors_sessions.py` :

```python
from dashboard.collectors.sessions import list_sessions, session_status


def test_list_sessions_exposes_status_complete_by_default(runs_root):
    # la session du fixture n'a pas de status explicite -> "complete"
    items = list_sessions(runs_root).sessions
    assert all(s.status == "complete" for s in items)


def test_session_status_helper_reads_meta(runs_root):
    sid = list_sessions(runs_root).sessions[0].session_id
    assert session_status(runs_root, sid) == "complete"


def test_session_status_missing_session_is_none(runs_root):
    assert session_status(runs_root, "does-not-exist") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py -k "status" -v`
Expected: FAIL — `AttributeError: 'SessionListItem' object has no attribute 'status'` et `ImportError: cannot import name 'session_status'`.

- [ ] **Step 3: Update the sessions collector**

Dans `dashboard/collectors/sessions.py` :

(a) Ajouter `status` à `SessionListItem` :

```python
class SessionListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    task_count: int
    agent_count: int
    status: str
```

(b) Le peupler dans `list_sessions` (dans la construction de `SessionListItem`) :

```python
            items.append(SessionListItem(
                session_id=meta.session_id,
                started_at=meta.started_at,
                ended_at=meta.ended_at,
                task_count=len(meta.tasks),
                agent_count=len(meta.agent_ids),
                status=meta.status,
            ))
```

(c) Ajouter le helper `session_status` (lecture meta seule, bon marché pour le gating) après `_load_agents` :

```python
def session_status(runs_root: Path, session_id: str) -> str | None:
    """Statut d'une session ("running"/"complete") sans charger la trace ni
    construire le graphe. None si la session (ou son meta.json) n'existe pas."""
    d = _sessions_dir(runs_root) / session_id
    if not (d / "meta.json").exists():
        return None
    return _load_meta(d).status
```

(d) `session_detail` lit la trace en mode tolérant (une session `running` peut être surprise mi-écriture) — remplacer l'import et l'appel :

Import en tête : `from aaosa.tracing.store import (... load_trace ...)` → ajouter `load_trace_partial` :
```python
from aaosa.tracing.store import AgentRegistry, AgentRegistryEntry, SessionMeta, load_trace_partial
```
Et dans `session_detail` :
```python
    graph = build_graph(load_trace_partial(d / "trace.jsonl"), meta)
```
(`load_trace` n'est plus utilisé dans ce module — retirer de l'import s'il y figurait seul.)

- [ ] **Step 4: Run collector tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py -v`
Expected: PASS (anciens + 3 nouveaux).

- [ ] **Step 5: Write the failing api/cache tests**

Ajouter dans `tests/dashboard/test_api.py` un helper de construction de session + les tests de gating. Le fixture `runs_root` existant fournit déjà une session `complete` ; on en fabrique d'autres à la main pour piloter le statut.

```python
from datetime import datetime, timezone
from pathlib import Path

from aaosa.tracing.events import UnassignedEvent
from aaosa.tracing.store import SessionMeta, SessionTaskRecord


def _write_session(root: Path, sid: str, status: str, task_ids: list[str]) -> Path:
    sdir = root / "sessions" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)
    lines = [
        UnassignedEvent(session_id=sid, task_id=tid, reason="x").model_dump_json()
        for tid in task_ids
    ]
    (sdir / "trace.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    meta = SessionMeta(
        session_id=sid, started_at=now, ended_at=now, status=status,
        tasks=[SessionTaskRecord(id=task_ids[0], description="root task",
                                 winner_agent_id=None, outcome="unassigned",
                                 required_tags={})] if task_ids else [],
        agent_ids=["a1"],
    )
    (sdir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return sdir


def test_sessions_list_includes_status(runs_root):
    r = _client(runs_root).get("/api/sessions")
    assert r.status_code == 200
    assert all("status" in s for s in r.get_json()["sessions"])


def test_running_session_graph_not_cached_reflects_growth(runs_root):
    # une session running est recalculée à chaque requête : ajouter un event
    # entre deux GET doit changer le graphe
    sdir = _write_session(runs_root, "2026-06-08T11-00-00-live", "running", ["root"])
    c = _client(runs_root)
    g1 = c.get("/api/sessions/2026-06-08T11-00-00-live/graph").get_json()
    n1 = len(g1["steps"])
    # append un event (nouvelle tâche) -> trace grandit
    with (sdir / "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(UnassignedEvent(session_id="2026-06-08T11-00-00-live", task_id="t2", reason="y").model_dump_json() + "\n")
    g2 = c.get("/api/sessions/2026-06-08T11-00-00-live/graph").get_json()
    assert len(g2["steps"]) >= n1  # recalcul frais, pas de cache figé
    assert g2 != g1


def test_complete_session_graph_is_cached(runs_root):
    # une session complete est mise en cache : muter la trace sur disque ne change
    # plus le graphe servi (cache figé au 1er accès)
    sdir = _write_session(runs_root, "2026-06-08T11-30-00-done", "complete", ["root"])
    c = _client(runs_root)
    g1 = c.get("/api/sessions/2026-06-08T11-30-00-done/graph").get_json()
    with (sdir / "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(UnassignedEvent(session_id="2026-06-08T11-30-00-done", task_id="t2", reason="y").model_dump_json() + "\n")
    g2 = c.get("/api/sessions/2026-06-08T11-30-00-done/graph").get_json()
    assert g2 == g1  # cache : inchangé malgré la mutation disque
```

- [ ] **Step 6: Run api tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py -k "status or running or complete" -v`
Expected: FAIL — `test_running_session_graph_not_cached_reflects_growth` échoue (le graphe est mis en cache au 1er GET, le 2e GET ne reflète pas la croissance) ; `test_sessions_list_includes_status` passe déjà (Task 5 collector). C'est le test running qui pilote le gating.

- [ ] **Step 7: Status-gate the cache in `api.py`**

Dans `dashboard/api.py`, remplacer `_session_view` :

```python
def _session_view(session_id):
    runs_root = _runs_root()
    if sessions_collector.session_status(runs_root, session_id) == "running":
        # session live : recalcul frais à chaque requête (pas de cache figé)
        return sessions_collector.session_detail(runs_root, session_id)
    return _cache().get_or_compute(
        f"session_view:{session_id}",
        lambda: sessions_collector.session_detail(runs_root, session_id),
    )
```

(`sessions_collector` est déjà importé ligne 8.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_api.py tests/dashboard/test_collectors_sessions.py -v`
Expected: PASS (anciens + nouveaux).

- [ ] **Step 9: Commit**

```bash
git add dashboard/collectors/sessions.py dashboard/api.py tests/dashboard/test_api.py tests/dashboard/test_collectors_sessions.py
git commit -m "feat(dashboard): status expose + cache status-gated (recalcul live, cache si complete)"
```

---

## Task 6: `build_graph` — tests explicites trace partielle / INPUT-seul / meta provisoire

**Files:**
- Test: `tests/dashboard/test_graph_model.py` (ajout uniquement — `build_graph` reste **inchangé**)

**But :** verrouiller par des tests que `build_graph` rend un graphe valide croissant sur une trace incomplète (le live l'alimente avec une trace qui grandit). On vérifie la tolérance déjà présente (fallback racine ligne 640, garde trace vide ligne 639, garde « pas de DIAG sans passe » ligne 388).

- [ ] **Step 1: Write the tests**

Ajouter dans `tests/dashboard/test_graph_model.py` :

```python
from datetime import datetime, timezone

from aaosa.tracing.events import DispatchedEvent, Phase1FilteredEvent
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import build_graph


def _provisional_meta(task_id: str) -> SessionMeta:
    now = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)
    return SessionMeta(
        session_id="live", started_at=now, ended_at=now, status="running",
        tasks=[SessionTaskRecord(id=task_id, description="root incident",
                                 winner_agent_id=None, outcome="divided",
                                 required_tags={"security": 50})],
        agent_ids=["a1"],
    )


def test_build_graph_input_only_no_events(_=None):
    # trace vide + meta provisoire -> graphe INPUT-seul, pas de crash
    g = build_graph([], _provisional_meta("root"))
    assert g.steps[0].milestone_type == "input"
    assert g.steps[0].detail.description == "root incident"


def test_build_graph_partial_trace_phase1_only():
    # début de run : phase1 émise, rien d'autre -> graphe valide croissant
    meta = _provisional_meta("root")
    events = [
        Phase1FilteredEvent(session_id="live", task_id="root", agent_id="a1", passed=True, fit_score=0.8),
    ]
    g = build_graph(events, meta)
    assert g.steps[0].milestone_type == "input"
    assert len(g.steps) >= 1  # pas de crash, graphe partiel rendu


def test_build_graph_growing_trace_adds_steps():
    # un event supplémentaire produit au moins autant d'étapes (graphe cumulatif)
    meta = _provisional_meta("root")
    base = [Phase1FilteredEvent(session_id="live", task_id="root", agent_id="a1", passed=True, fit_score=0.8)]
    grown = base + [DispatchedEvent(session_id="live", task_id="root", agent_id="a1", reason="best fit")]
    assert len(build_graph(grown, meta).steps) >= len(build_graph(base, meta).steps)
```

Note : `test_build_graph_input_only_no_events` prend un paramètre factice `_` seulement si le runner exige une signature ; sinon le retirer. Vérifier l'attribut exact du détail INPUT (`description`) dans `test_graph_model.py` existant et l'aligner si le nom diffère.

- [ ] **Step 2: Run tests to verify they pass (comportement déjà présent)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -k "input_only or partial or growing" -v`
Expected: PASS — si un test échoue, c'est un **vrai trou de tolérance** : déboguer `build_graph` (skill `systematic-debugging`) avant de continuer, ne pas affaiblir le test. Aligner d'abord les noms d'attributs (`milestone_type`, `detail.description`) sur le modèle réel si AttributeError.

- [ ] **Step 3: Commit**

```bash
git add tests/dashboard/test_graph_model.py
git commit -m "test(graph): build_graph tolere trace partielle / INPUT-seul / meta provisoire (live mode)"
```

---

## Task 7: Non-régression backend complète + rejeu `runs_demo/`

**Files:** aucun (vérification).

- [ ] **Step 1: Run the full test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tous verts. Départ = 992 (991 passed + 1 skip) ; attendu après Tasks 1-6 ≈ 992 + ~17 nouveaux tests. Aucun test existant cassé.

- [ ] **Step 2: Vérifier le rejeu du store curé (rétrocompat `runs_demo/`)**

Lancer le dashboard sur le store versionné et confirmer qu'il charge sans erreur (les 16 `meta.json` sans `status` doivent défaulter `complete`) :

Run: `.venv\Scripts\aaosa dashboard --runs-root runs_demo --port 5057`
Puis dans un autre terminal : `curl -s http://127.0.0.1:5057/api/sessions`
Expected: liste JSON des 4 exhibits, chacun avec `"status": "complete"`. Arrêter le serveur (Ctrl-C).

- [ ] **Step 3: Commit (si un ajustement a été nécessaire)**

Pas de commit si rien n'a changé. Sinon committer le correctif avec un message ciblé.

---

## Task 8: Frontend live — boucle de poll, badge LIVE, révélation pilotée par events

> **DÉPENDANCE FORTE — skill `impeccable` obligatoire.** Toute modification de
> `dashboard/static/js/` (sessions.js, graph.js, camera.js, modal.js) + CSS passe par
> le skill `impeccable`. **Ne pas charger `impeccable` avant cette task. Ne pas coder
> le frontend à la main.** Le backend (Tasks 1-7) doit être vert avant de commencer.

**Files (à modifier via `impeccable`) :**
- `dashboard/static/js/tabs/sessions.js` — auto-refresh liste + ouverture live.
- `dashboard/static/js/graph.js` — frontière de révélation pilotée par l'arrivée d'events.
- `dashboard/static/js/camera.js` — follow sur le jalon neuf.
- `dashboard/static/js/modal.js` — (au besoin) pas de changement de contrat attendu.
- CSS associée — badge `● LIVE`.

**Contrat backend disponible (déjà livré, ne pas re-négocier) :**
- `GET /api/sessions` → `sessions[]` chacun avec `status: "running" | "complete"`, triés `started_at` desc (running en tête).
- `GET /api/sessions/<id>` → `meta.status`.
- `GET /api/sessions/<id>/graph` → `GraphModel` (recalculé frais tant que `running`, cache dès `complete`). Le graphe **grandit** d'un poll à l'autre.

**Exigences fonctionnelles (cadrage spec §4, tranché) :**
1. **Liste auto-refresh** ~2-3 s : une session `running` porte un badge `● LIVE` en tête.
2. **Vue live** : ouvrir une session `running` → poll graphe ~750 ms → rebuild → **avancer la frontière de révélation au dernier jalon** (réutiliser le mécanisme scrubber/reveal existant — c'est le scrubber piloté par l'arrivée d'events, pas par la souris) + **camera follow** sur le jalon neuf.
3. **Settle** : `status → complete` → un dernier fetch, **arrêt du poll**, la session redevient une vue statique scrubbable normale. Transition invisible.
4. **Non-régression** : ouvrir une session `complete` directement = comportement actuel exact (aucun poll, scrubber manuel).

- [ ] **Step 1: Invoquer le skill `impeccable`**

Charger `impeccable` avec ce contexte : surface = l'arbre émergent du Sessions tab (`graph.js`/`camera.js`), objectif = boucle live (poll + révélation auto + camera follow + badge LIVE + settle), contrat backend ci-dessus, exigences §4. Insister : réutiliser le mécanisme scrubber/reveal existant (ne pas réinventer la révélation), respecter le colorway crest→fire et l'esthétique « wireframe instrument » en place.

- [ ] **Step 2: Implémenter le frontend live sous la conduite d'`impeccable`**

Suivre le workflow `impeccable` (l'arbre de décision du skill prime). Découper a minima :
- liste auto-refresh + badge LIVE (sessions.js + CSS),
- boucle de poll graphe + arrêt sur `complete` (sessions.js),
- révélation pilotée par events (graph.js, via le scrubber existant),
- camera follow sur le jalon neuf (camera.js).

- [ ] **Step 3: Pas de commit ici** — le commit frontend est groupé après la validation navigateur (Task 9), conformément à la norme projet (frontend validé navigateur, hors TDD auto).

---

## Task 9: Validation navigateur end-to-end (flux démo réel)

**Files:** aucun nouveau code (sauf correctifs frontend issus de la validation).

**Prérequis :** `.env` avec `OPENAI_API_KEY` valide. Deux terminaux.

- [ ] **Step 1: Lancer le dashboard sur un store frais**

Terminal A :
```bash
.venv\Scripts\aaosa dashboard --runs-root runs_live_check --port 5058
```
Ouvrir http://127.0.0.1:5058, onglet Sessions. La liste est vide (ou montre les runs précédents si root réutilisé — préférer un root neuf).

- [ ] **Step 2: Lancer un run en parallèle et observer le live**

Terminal B :
```bash
.venv\Scripts\aaosa run --scenario main --runs-root runs_live_check
```
Checklist navigateur (le run dure ~30-90 s sur gpt-4o-mini) :
- [ ] La session apparaît dans la liste **dès le démarrage** avec le badge `● LIVE`, en tête.
- [ ] À l'ouverture de la session live, l'arbre se **révèle jalon par jalon** (INPUT → claiming → division → agents → QA → agrégation/sortie) sans rafraîchir manuellement.
- [ ] La **caméra suit** le jalon neuf (pas besoin de pan manuel).
- [ ] À la fin du run, le badge LIVE disparaît (`status → complete`), le poll s'arrête, la session reste **scrubbable** normalement (scrubber manuel fonctionne).

- [ ] **Step 3: Non-régression sur une session complete**

- [ ] Ouvrir une session `complete` (ex. depuis `runs_demo/` via un 2e dashboard, ou une session terminée du run ci-dessus) : aucun poll réseau (vérifier l'onglet Network ~silencieux), scrubber manuel identique à aujourd'hui.
- [ ] Onglet Health : non-régression (graphe health inchangé).

- [ ] **Step 4: Sign-off Quentin**

Présenter le flux live à Quentin (capture ou démo en direct). Obtenir le sign-off explicite avant de committer. Si réserves → boucler via `impeccable` (Task 8) puis re-valider.

- [ ] **Step 5: Commit du frontend live**

```bash
git add dashboard/static/js/ dashboard/static/css/
git commit -m "feat(dashboard): live mode frontend - badge LIVE, revelation pilotee par events, camera follow (impeccable)"
```

---

## Task 10: Clôture

- [ ] **Step 1: Suite complète une dernière fois**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tous verts.

- [ ] **Step 2: Mettre à jour `CLAUDE.md`**

Ajouter une entrée d'état « V3 — live mode observabilité (ex-B7) » : `StreamingTracer`, `SessionMeta.status` additif, `load_trace_partial`, `run_once` persistance incrémentale par défaut, cache status-gated, frontend live via `impeccable`, total tests, sign-off. Mettre à jour l'arbre `src/aaosa/tracing/` et `dashboard/` si pertinent.

- [ ] **Step 3: Décider l'intégration de branche**

Invoquer le skill `superpowers:finishing-a-development-branch` (merge local vers `master` selon la norme projet — master non pushé, demander à Quentin) ou PR selon préférence.

- [ ] **Step 4: Commit doc**

```bash
git add CLAUDE.md
git commit -m "docs: live mode observabilite livre (ex-B7)"
```

---

## Self-Review (effectuée à l'écriture)

**Couverture spec :**
- §1 découplage filesystem → architecture + Task 4 (run écrit) + Task 5 (dashboard poll). ✓
- §2 persistance incrémentale : `StreamingTracer` → Task 3 ; `SessionMeta.status` → Task 1 ; `run_once` restructuré → Task 4 ; campaign hérite (même `run_once`) → couvert par non-régression Task 4/7. ✓
- §3 backend live-aware : cache status-gated → Task 5 ; `load_trace_partial` → Task 2 (impl) + Task 5 (branché dans `session_detail`) ; `status` exposé list+detail → Task 5 ; `build_graph` inchangé + tests → Task 6. ✓
- §4 frontend → Tasks 8-9 (impeccable + validation navigateur). ✓
- §5 tests & rétrocompat → chaque task TDD backend ; rejeu `runs_demo/` → Task 7. ✓

**Placeholders :** aucun TODO/TBD ; tout step code porte son code. Tasks 8-9 délèguent à `impeccable` (sous-skill légitime, pas un placeholder) avec contrat backend explicite et exigences §4.

**Cohérence des types/noms :** `SessionMeta.status` (Literal running/complete) introduit Task 1, consommé Tasks 4/5/6 ; `load_trace_partial` introduit Task 2, consommé Tasks 3 (test)/5 ; `StreamingTracer(session_id, stream_path)` + `.close()` introduit Task 3, consommé Task 4 ; `session_status(runs_root, session_id)` introduit Task 5 collector, consommé Task 5 api. Cohérent.

**Point de vigilance d'exécution :** Task 6 — aligner les noms d'attributs des steps (`milestone_type`, `detail.description`) sur le modèle `GraphStep` réel de `test_graph_model.py` existant avant de figer les asserts (les tests doivent passer sans modifier `build_graph` ; un échec = vrai trou de tolérance à déboguer, pas à contourner).
