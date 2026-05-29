# V2c — Épique 01 — Couche data & persistance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persister sur disque tout ce dont le dashboard V2c a besoin (traces de session, métadonnées de session, registry d'agents, rapports de health check, métadonnées LLM par exécution) sans casser les 471 tests existants.

**Architecture:** Un store fichier sous une racine configurable `runs_root/` (défaut `runs/`). Nouveau module `tracing/store.py` (identité agents + métadonnées de session + flush de session). `ExecutedEvent` enrichi d'un `llm_metadata` optionnel (rétrocompat). `save_health_check` ajouté à `qa/health_check.py`. Les deux demos flushent réellement au lieu de seulement `print`.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9.0.3. Imports absolus uniquement. Timestamps UTC via `datetime.now(timezone.utc)`.

**Décisions de design (deep-dive 2026-05-29) :**
- `session_id` = `new_session_id()` → `"%Y-%m-%dT%H-%M-%S"` + `-` + `uuid4().hex[:4]` (triable, lisible, collision-safe).
- Health check **persiste sa trace** : `run_health_check` a déjà un param `tracer` ; on le thread depuis la demo et `save_health_check(report, test_set, tracer, directory)` écrit `trace.jsonl`.
- `SessionMeta` est **caller-built** : la boucle demo collecte les outcomes et construit le `SessionMeta`, `save_session` l'écrit tel quel (pas de reconstruction depuis les events).
- `SessionTaskRecord.outcome` ∈ `Literal["qa_pass", "qa_fail", "unassigned", "no_qa"]` (`no_qa` = run sans evaluator). `winner_agent_id=None` si `unassigned`.
- Les snapshots ELO migrent sous `runs_root/elo_snapshots/` (convention de store de la spec ; lu par le collector Agents en Épique 03a).
- `registry` duplique `tags_with_elo` au moment de l'enregistrement (identité figée) ; l'**historique** ELO reste dans `elo_snapshots/` (hors scope de cette épique).

---

## Store layout cible

```
runs/
  agents/registry.json                  # NOUVEAU (AgentRegistry)
  elo_snapshots/<ts>.json + latest.json # migré depuis ./elo_snapshots
  sessions/<session_id>/
      trace.jsonl                       # flush du Tracer (existe, jamais appelé)
      meta.json                         # NOUVEAU (SessionMeta)
  health_checks/<ts>/
      report.json                       # NOUVEAU (HealthCheckReport)
      test_set.json                     # snapshot du TestSet utilisé
      trace.jsonl                       # trace du run health check
```

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/aaosa/tracing/events.py` | `ExecutedEvent` gagne `llm_metadata: LLMMetadata \| None = None` | Modifier |
| `src/aaosa/runtime/runner.py` | `run_task` passe `output.llm_metadata` dans l'`ExecutedEvent` | Modifier |
| `src/aaosa/tracing/store.py` | `new_session_id`, `AgentRegistryEntry`/`AgentRegistry`/`save_agent_registry`, `SessionTaskRecord`/`SessionMeta`/`save_session` | Créer |
| `src/aaosa/qa/health_check.py` | `save_health_check(report, test_set, tracer, directory)` | Modifier |
| `src/aaosa/demo/run_demo.py` | flush registry + session sous `runs/` | Modifier |
| `src/aaosa/demo/run_health_check.py` | tracer threadé + flush health check sous `runs/` | Modifier |
| `tests/tracing/test_events_v2.py` | tests `llm_metadata` | Modifier |
| `tests/runtime/test_runner.py` | assertion `llm_metadata` propagé | Modifier |
| `tests/tracing/test_store.py` | tests du nouveau store | Créer |
| `tests/qa/test_health_check.py` | tests `save_health_check` | Modifier |
| `tests/demo/test_demo.py` | maj persistance + monkeypatch | Modifier |
| `tests/demo/test_demo_health_check.py` | maj persistance + monkeypatch | Modifier |

---

## Task 1: `ExecutedEvent.llm_metadata` optionnel + wiring runner

**Files:**
- Modify: `src/aaosa/tracing/events.py:1-4` (import) et `:34-37` (`ExecutedEvent`)
- Modify: `src/aaosa/runtime/runner.py:36-42` (émission `ExecutedEvent`)
- Test: `tests/tracing/test_events_v2.py`, `tests/runtime/test_runner.py`

- [ ] **Step 1: Écrire les tests `llm_metadata` (events)**

Ajouter à la fin de `tests/tracing/test_events_v2.py` :

```python
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import ExecutedEvent


class TestExecutedEventLLMMetadata:
    def test_defaults_to_none(self):
        """Rétrocompat : ExecutedEvent sans llm_metadata reste valide, défaut None."""
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
        )
        assert e.llm_metadata is None

    def test_carries_llm_metadata(self):
        meta = LLMMetadata(
            model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0,
        )
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done", llm_metadata=meta,
        )
        assert e.llm_metadata is not None
        assert e.llm_metadata.tokens_in == 10

    def test_json_roundtrip_with_metadata(self):
        meta = LLMMetadata(
            model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0,
        )
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done", llm_metadata=meta,
        )
        e2 = ExecutedEvent.model_validate_json(e.model_dump_json())
        assert e2.llm_metadata is not None
        assert e2.llm_metadata.model_name == "gpt-4o-mini"
        assert e2.llm_metadata.latency_ms == 42.0
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py::TestExecutedEventLLMMetadata -v`
Expected: FAIL — `ExecutedEvent() got an unexpected keyword argument 'llm_metadata'` (extra=forbid).

- [ ] **Step 3: Ajouter le champ optionnel**

Dans `src/aaosa/tracing/events.py`, ajouter l'import après les imports existants (haut du fichier) :

```python
from aaosa.schemas.output import LLMMetadata
```

Puis modifier `ExecutedEvent` :

```python
class ExecutedEvent(_BaseEvent):
    type: Literal["executed"] = "executed"
    agent_id: str
    output_summary: str
    llm_metadata: LLMMetadata | None = None
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v`
Expected: PASS (nouveaux + anciens).

- [ ] **Step 5: Écrire le test de propagation runner**

Ajouter à `tests/runtime/test_runner.py` (après `test_run_task_tracer_receives_executed_event`) :

```python
def test_run_task_executed_event_carries_llm_metadata():
    """L'ExecutedEvent émis porte le llm_metadata de l'Output."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            run_task(task, [agent], MagicMock(), tracer=tracer)

    executed = [e for e in tracer.events if isinstance(e, ExecutedEvent)]
    assert len(executed) == 1
    assert executed[0].llm_metadata == output.llm_metadata
```

- [ ] **Step 6: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py::test_run_task_executed_event_carries_llm_metadata -v`
Expected: FAIL — `assert None == LLMMetadata(...)` (runner ne passe pas encore le metadata).

- [ ] **Step 7: Wirer le runner**

Dans `src/aaosa/runtime/runner.py`, modifier l'émission de l'`ExecutedEvent` (lignes 37-42) :

```python
    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
            llm_metadata=output.llm_metadata,
        ))
```

- [ ] **Step 8: Lancer les tests runner**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/aaosa/tracing/events.py src/aaosa/runtime/runner.py tests/tracing/test_events_v2.py tests/runtime/test_runner.py
git commit -m "feat(v2c): ExecutedEvent.llm_metadata optionnel + wiring runner"
```

---

## Task 2: `store.py` — `new_session_id` + registry d'agents

**Files:**
- Create: `src/aaosa/tracing/store.py`
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Écrire les tests registry + session_id**

Créer `tests/tracing/test_store.py` :

```python
from pathlib import Path

from aaosa.core.agent import Agent
from aaosa.tracing.store import (
    AgentRegistry,
    AgentRegistryEntry,
    new_session_id,
    save_agent_registry,
)


def make_agent(name: str, tags: dict[str, int]) -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt=f"prompt for {name}")


class TestNewSessionId:
    def test_is_unique(self):
        ids = {new_session_id() for _ in range(50)}
        assert len(ids) == 50

    def test_is_sortable_string(self):
        sid = new_session_id()
        assert isinstance(sid, str)
        # forme: 2026-05-29T14-30-00-ab12
        assert sid[:4].isdigit()
        assert "T" in sid


class TestSaveAgentRegistry:
    def test_writes_file(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        path = save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert (tmp_path / "agents").is_dir()

    def test_roundtrip(self, tmp_path):
        agents = [
            make_agent("Frontend", {"css": 80, "javascript": 70}),
            make_agent("Backend", {"python": 90}),
        ]
        path = save_agent_registry(agents, tmp_path / "registry.json")
        reg = AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        assert len(reg.agents) == 2
        fe = next(e for e in reg.agents if e.name == "Frontend")
        assert fe.tags_with_elo == {"css": 80, "javascript": 70}
        assert fe.system_prompt == "prompt for Frontend"
        assert fe.agent_id == agents[0].id

    def test_entry_rejects_extra_field(self):
        import pytest
        with pytest.raises(Exception):
            AgentRegistryEntry(
                agent_id="1", name="X", system_prompt="p",
                tags_with_elo={"a": 1}, bogus="bad",
            )
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.tracing.store'`.

- [ ] **Step 3: Créer `store.py` (partie registry)**

Créer `src/aaosa/tracing/store.py` :

```python
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent


def new_session_id() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S") + "-" + uuid.uuid4().hex[:4]


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    system_prompt: str
    tags_with_elo: dict[str, int]


class AgentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentRegistryEntry]


def save_agent_registry(agents: list[Agent], path: Path) -> Path:
    registry = AgentRegistry(
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(v2c): store.py - new_session_id + registry d'agents"
```

---

## Task 3: `store.py` — `SessionMeta` + `save_session`

**Files:**
- Modify: `src/aaosa/tracing/store.py`
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Écrire les tests SessionMeta + save_session**

Ajouter à `tests/tracing/test_store.py` :

```python
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter

from aaosa.tracing.events import ClaimEvent, ExecutedEvent
from aaosa.tracing.store import SessionMeta, SessionTaskRecord, save_session
from aaosa.tracing.tracer import Tracer


def make_meta(session_id: str) -> SessionMeta:
    now = datetime.now(timezone.utc)
    return SessionMeta(
        session_id=session_id,
        started_at=now,
        ended_at=now,
        tasks=[
            SessionTaskRecord(
                id="t1", description="do a thing",
                winner_agent_id="a1", outcome="qa_pass",
            ),
            SessionTaskRecord(
                id="t2", description="impossible",
                winner_agent_id=None, outcome="unassigned",
            ),
        ],
        agent_ids=["a1", "a2"],
    )


class TestSessionTaskRecord:
    def test_outcome_rejects_unknown_value(self):
        with pytest.raises(Exception):
            SessionTaskRecord(
                id="t1", description="x",
                winner_agent_id="a1", outcome="weird",
            )

    def test_unassigned_allows_none_winner(self):
        rec = SessionTaskRecord(
            id="t1", description="x", winner_agent_id=None, outcome="unassigned",
        )
        assert rec.winner_agent_id is None


class TestSaveSession:
    def test_writes_trace_and_meta(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id, task_id="t1",
            agent_id="a1", output_summary="done",
        ))
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        assert (session_dir / "trace.jsonl").exists()
        assert (session_dir / "meta.json").exists()

    def test_session_dir_path(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        assert session_dir == tmp_path / "sessions" / "2026-05-29T10-00-00-ab12"

    def test_meta_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        loaded = SessionMeta.model_validate_json(
            (session_dir / "meta.json").read_text(encoding="utf-8")
        )
        assert loaded.session_id == meta.session_id
        assert len(loaded.tasks) == 2
        assert loaded.tasks[1].outcome == "unassigned"
        assert loaded.agent_ids == ["a1", "a2"]

    def test_trace_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id, task_id="t1",
            agent_id="a1", output_summary="done",
        ))
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        adapter = TypeAdapter(ClaimEvent)
        lines = (session_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        events = [adapter.validate_json(line) for line in lines if line.strip()]
        assert len(events) == 1
        assert isinstance(events[0], ExecutedEvent)

    def test_session_id_mismatch_raises(self, tmp_path):
        tracer = Tracer(session_id="sid-A")
        meta = make_meta("sid-B")
        with pytest.raises(ValueError, match="session_id"):
            save_session(tracer, meta, tmp_path)
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -k "Session or save_session" -v`
Expected: FAIL — `ImportError: cannot import name 'SessionMeta'`.

- [ ] **Step 3: Étendre `store.py`**

Ajouter à `src/aaosa/tracing/store.py`. D'abord compléter l'import `typing` en haut :

```python
from typing import Literal
```

Et l'import du Tracer (après l'import `Agent`) :

```python
from aaosa.tracing.tracer import Tracer
```

Puis ajouter en fin de fichier :

```python
TaskOutcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa"]


class SessionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    winner_agent_id: str | None
    outcome: TaskOutcome


class SessionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    tasks: list[SessionTaskRecord]
    agent_ids: list[str]


def save_session(tracer: Tracer, meta: SessionMeta, runs_root: Path) -> Path:
    if tracer.session_id != meta.session_id:
        raise ValueError(
            f"tracer.session_id ({tracer.session_id!r}) != meta.session_id ({meta.session_id!r})"
        )
    session_dir = runs_root / "sessions" / meta.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    tracer.flush(session_dir / "trace.jsonl")
    (session_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return session_dir
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS (registry + session).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/store.py tests/tracing/test_store.py
git commit -m "feat(v2c): store.py - SessionMeta + save_session"
```

---

## Task 4: `save_health_check`

**Files:**
- Modify: `src/aaosa/qa/health_check.py:1-14` (imports) + nouvelle fonction
- Test: `tests/qa/test_health_check.py`

- [ ] **Step 1: Écrire les tests `save_health_check`**

Ajouter à `tests/qa/test_health_check.py` (en réutilisant les imports existants du fichier ; ajouter ceux ci-dessous s'ils manquent) :

```python
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from aaosa.qa.health_check import HealthCheckReport, save_health_check
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.schemas.task import Task
from aaosa.tracing.events import ClaimEvent, QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer


def _empty_report() -> HealthCheckReport:
    return HealthCheckReport(
        timestamp=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc),
        n_runs=3, total_cases=0, case_results=[],
        fix_target_pass_rate=0.0, regression_guard_pass_rate=0.0,
        unstable_cases=[], unattributed=[],
        task_spec_quarantined=[], evaluator_quarantined=[],
    )


def _demo_test_set() -> TestSet:
    task = Task(description="t", required_tags={"python": 50})
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    return TestSet(cases=[TestCase(
        task=task, evaluator_spec=spec, origin="curated",
        role="regression_guard", attribution="agent",
    )])


class TestSaveHealthCheck:
    def test_writes_three_files(self, tmp_path):
        tracer = Tracer(session_id="hc-1")
        target = save_health_check(_empty_report(), _demo_test_set(), tracer, tmp_path)
        assert (target / "report.json").exists()
        assert (target / "test_set.json").exists()
        assert (target / "trace.jsonl").exists()

    def test_dir_named_from_report_timestamp(self, tmp_path):
        tracer = Tracer(session_id="hc-1")
        target = save_health_check(_empty_report(), _demo_test_set(), tracer, tmp_path)
        assert target == tmp_path / "2026-05-29T10-00-00"

    def test_report_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="hc-1")
        target = save_health_check(_empty_report(), _demo_test_set(), tracer, tmp_path)
        loaded = HealthCheckReport.model_validate_json(
            (target / "report.json").read_text(encoding="utf-8")
        )
        assert loaded.n_runs == 3

    def test_test_set_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="hc-1")
        target = save_health_check(_empty_report(), _demo_test_set(), tracer, tmp_path)
        loaded = TestSet.model_validate_json(
            (target / "test_set.json").read_text(encoding="utf-8")
        )
        assert len(loaded.cases) == 1

    def test_trace_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="hc-1")
        tracer.emit(QAEvaluatedEvent(
            session_id="hc-1", task_id="t1", agent_id="a1",
            success=True, score=1.0, reason="ok",
        ))
        target = save_health_check(_empty_report(), _demo_test_set(), tracer, tmp_path)
        adapter = TypeAdapter(ClaimEvent)
        lines = (target / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        events = [adapter.validate_json(line) for line in lines if line.strip()]
        assert len(events) == 1
        assert isinstance(events[0], QAEvaluatedEvent)
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_health_check.py::TestSaveHealthCheck -v`
Expected: FAIL — `ImportError: cannot import name 'save_health_check'`.

- [ ] **Step 3: Implémenter `save_health_check`**

Dans `src/aaosa/qa/health_check.py`, ajouter `Path` à l'import `pathlib` en haut du fichier :

```python
from pathlib import Path
```

(`Tracer` et `TestSet` sont déjà importés.) Puis ajouter en fin de fichier :

```python
def save_health_check(
    report: HealthCheckReport,
    test_set: TestSet,
    tracer: Tracer,
    directory: Path,
) -> Path:
    ts = report.timestamp.strftime("%Y-%m-%dT%H-%M-%S")
    target = directory / ts
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (target / "test_set.json").write_text(test_set.model_dump_json(indent=2), encoding="utf-8")
    tracer.flush(target / "trace.jsonl")
    return target
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v`
Expected: PASS (anciens + nouveaux).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/health_check.py tests/qa/test_health_check.py
git commit -m "feat(v2c): save_health_check (report + test_set + trace)"
```

---

## Task 5: Les demos flushent réellement sous `runs/`

**Files:**
- Modify: `src/aaosa/demo/run_demo.py`
- Modify: `src/aaosa/demo/run_health_check.py`
- Test: `tests/demo/test_demo.py`, `tests/demo/test_demo_health_check.py`

- [ ] **Step 1: Réécrire `run_demo.py`**

Remplacer le contenu de `src/aaosa/demo/run_demo.py` par :

```python
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.claiming.dispatch import DispatchResult
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.adaptive import build_adaptive_spec
from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec_evaluator import from_spec
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    print("=== AAOSA Demo V2b ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}
    task_records: list[SessionTaskRecord] = []

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        spec = build_adaptive_spec(task)
        evaluator = from_spec(spec, client=client)
        judge_note = " (+judge)" if spec.judge else ""
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: PASS){judge_note}")
            outcome, winner_id = "qa_pass", result.agent_id
        elif isinstance(result, QAFailure):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: FAIL - {result.qa_result.reason})")
            outcome, winner_id = "qa_fail", result.agent_id
        else:
            print(f"  -> Unassigned")
            outcome, winner_id = "unassigned", None
        task_records.append(SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=winner_id, outcome=outcome,
        ))
        print()

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== Persistence ===")
    save_agent_registry(DEMO_AGENTS, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=task_records,
        agent_ids=[a.id for a in DEMO_AGENTS],
    )
    session_dir = save_session(tracer, meta, runs_root)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(DEMO_AGENTS, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    run_demo()
```

- [ ] **Step 2: Réécrire `run_health_check.py` (tracer + flush)**

Dans `src/aaosa/demo/run_health_check.py`, mettre à jour les imports (ajouter `Path`, `Tracer`, `new_session_id`, `save_health_check`) :

```python
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import (
    TASK_BUILD_DASHBOARD_UI,
    TASK_FIX_CSS_HOVER,
    TASK_OPTIMIZE_SQL,
    TASK_REFACTOR_REST_API,
    TASK_SECURITY_AUDIT,
    TASK_WRITE_PYTHON_TESTS,
)
from aaosa.qa.health_check import run_health_check, save_health_check
from aaosa.qa.lifecycle import graduate
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet, active_cases
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.tracing.store import new_session_id
from aaosa.tracing.tracer import Tracer
```

Puis dans `run_demo_health_check()`, remplacer la ligne `report = run_health_check(DEMO_AGENTS, test_set, client, n_runs=3)` par :

```python
    tracer = Tracer(session_id=new_session_id())
    print(f"Lancement health check (n_runs=3)...\n")
    report = run_health_check(DEMO_AGENTS, test_set, client, n_runs=3, tracer=tracer)
```

(supprimer l'ancienne ligne `print("Lancement health check...")` dupliquée). Et à la toute fin de la fonction, après le bloc `graduate()`, ajouter :

```python
    target = save_health_check(report, test_set, tracer, Path("runs") / "health_checks")
    print(f"\nHealth check saved to {target}")
```

- [ ] **Step 3: Mettre à jour les tests demo V2b (run_demo)**

Dans `tests/demo/test_demo.py`, classe `TestDemoV2b`, les deux tests monkeypatchent `run_task` et `save_snapshot`. Ajouter le monkeypatch des nouvelles fonctions de persistance dans **chaque** test (`test_runs_without_crash` et `test_handles_qa_failure`), juste après la ligne `monkeypatch.setattr(demo_module, "save_snapshot", ...)` :

```python
        monkeypatch.setattr(demo_module, "save_agent_registry", lambda *a, **k: None)
        monkeypatch.setattr(demo_module, "save_session", lambda *a, **k: tmp_path / "sessions")
```

- [ ] **Step 4: Mettre à jour `test_demo_creates_snapshot`**

Dans `tests/demo/test_demo.py`, `TestDemoV2.test_demo_creates_snapshot` : la demo écrit désormais sous `runs/elo_snapshots`. Remplacer le corps après les `monkeypatch.setattr` par :

```python
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        monkeypatch.chdir(tmp_path)

        run_demo()

        assert (tmp_path / "runs" / "elo_snapshots" / "latest.json").exists()
```

(supprimer les lignes `snapshot_dir = tmp_path / "elo_snapshots"` et `snapshot_dir.mkdir()` : la demo crée le dossier elle-même.)

Pour `test_demo_runs_without_error` et `test_demo_handles_qa_failure`, supprimer la ligne `(tmp_path / "elo_snapshots").mkdir()` (la demo mkdir `runs/elo_snapshots` toute seule ; `monkeypatch.chdir(tmp_path)` reste).

- [ ] **Step 5: Mettre à jour les tests demo health check**

Dans `tests/demo/test_demo_health_check.py`, classe `TestRunDemoHealthCheck`, ajouter dans **chaque** test (`test_runs_without_crash`, `test_report_shows_all_quarantine_buckets`) le monkeypatch de `save_health_check`, juste après le `monkeypatch.setattr(hc_demo_module, "run_task", ...)` :

```python
        monkeypatch.setattr(hc_demo_module, "save_health_check", lambda *a, **k: None)
```

- [ ] **Step 6: Lancer les tests demo**

Run: `.venv\Scripts\python -m pytest tests/demo/test_demo.py tests/demo/test_demo_health_check.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/aaosa/demo/run_demo.py src/aaosa/demo/run_health_check.py tests/demo/test_demo.py tests/demo/test_demo_health_check.py
git commit -m "feat(v2c): demos flushent registry + session + health check sous runs/"
```

---

## Task 6: Vérification non-régression complète

**Files:** aucun (vérification).

- [ ] **Step 1: Lancer la suite complète**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS. Compte attendu : 471 (existants) + nouveaux tests de cette épique (≈ 3 events + 1 runner + ~11 store + ~5 health check) ≈ 491 verts, 0 échec.

- [ ] **Step 2: Vérifier que `runs/` est gitignored**

Run: `git status --porcelain runs/`
Expected: aucune sortie (le dossier `runs/` ne doit pas apparaître). Si `runs/` apparaît, ajouter `runs/` à `.gitignore` et committer ce changement seul :

```bash
git add .gitignore
git commit -m "chore(v2c): gitignore runs/"
```

- [ ] **Step 3: Smoke test manuel optionnel (nécessite `.env` avec `OPENAI_API_KEY`)**

Run: `.venv\Scripts\python src\aaosa\demo\run_demo.py`
Expected: la console affiche `Session saved to runs\sessions\<session_id>` et `ELO snapshot saved to runs\elo_snapshots\...`. Vérifier que `runs/sessions/<id>/trace.jsonl`, `runs/sessions/<id>/meta.json` et `runs/agents/registry.json` existent et contiennent du JSON valide.

---

## Self-Review

**Spec coverage (Section 1 + critères de done de l'épique) :**
- `ExecutedEvent.llm_metadata` optionnel, fixtures intactes → Task 1 (test `test_defaults_to_none`).
- `store.py` registry + `SessionMeta` + `save_session`, roundtrip JSON → Tasks 2-3.
- `save_health_check` report + test_set + trace dans `health_checks/<ts>/` → Task 4.
- Les deux demos flushent réellement sur `runs/` → Task 5.
- Suite complète verte → Task 6.
- Question deep-dive `LLMMetadata` (forme existante) → réutilisée telle quelle, Task 1.
- Question deep-dive `session_id`/timestamps → `new_session_id` (Task 2) + `started_at`/`ended_at` posés caller-side dans `run_demo` (Task 5).
- Question deep-dive format `trace.jsonl` → `Tracer.flush` réutilisé dans `save_session` (Task 3) et `save_health_check` (Task 4).
- Question deep-dive `tags_with_elo` registry vs ELO → registry duplique le dict (Task 2) ; historique via `elo_snapshots/` (hors scope, migré sous `runs/`).

**Placeholder scan :** aucun TODO/TBD ; tout le code est complet.

**Type consistency :** `SessionMeta`/`SessionTaskRecord`/`save_session`/`new_session_id`/`save_agent_registry`/`AgentRegistry`/`AgentRegistryEntry`/`save_health_check` portent les mêmes signatures entre définitions (Tasks 2-4) et usages (Task 5) et tests. `outcome` ∈ `{qa_pass, qa_fail, unassigned, no_qa}` cohérent partout. `save_session(tracer, meta, runs_root)` et `save_health_check(report, test_set, tracer, directory)` identiques entre déclaration et appels demo.
