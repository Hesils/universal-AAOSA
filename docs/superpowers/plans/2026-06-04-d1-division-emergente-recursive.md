# D1 — Division émergente récursive (comme récupération) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer la division de tâches d'une phase obligatoire en amont (`run_divided_task`) en un mécanisme de récupération récursif : on tente la tâche à plat, on ne divise que sur échec de claiming (`unassigned`), récursivement.

**Architecture:** Un `Tagger` (nouveau, LLM) tague chaque tâche depuis sa propre description ; le `TaskDivider` devient purement structurel (descriptions + dépendances + verdict d'atomicité, zéro tag) ; un couple mutuellement récursif `run_with_recovery ⇄ run_chain` porte la récursion (profondeur-d'abord) ; un `RunContext` frozen transporte les dépendances statiques. Garde-fou `roster_gap` (tag requis absent de tout le roster → on ne divise pas, on remonte un event). Barre d'ELO uniforme `DEFAULT_REQUIRED_ELO = 30`. `run_task` reste strictement intact (rétrocompat V1/V2).

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38, pytest 9 / pytest-asyncio. Tests offline via mocks `SimpleNamespace` (jamais d'appel réseau hors test « real LLM » explicitement marqué).

**Spec source:** `docs/superpowers/specs/2026-06-04-d1-division-emergente-recursive-design.md`

**Commande de test:** `.venv\Scripts\python -m pytest <chemin> -v` (toujours le venv, jamais Python système).

---

## File Structure

**Créés :**
- `src/aaosa/runtime/tagger.py` — `Tagger` (LLM description → ensemble de tags ≥1), `TagSet`, `EmptyTaggingError`.
- `src/aaosa/runtime/context.py` — `RunContext` (dataclass frozen, dépendances statiques du run).
- `tests/runtime/test_tagger.py`, `tests/runtime/test_context.py`, `tests/runtime/test_run_with_recovery.py`.

**Modifiés :**
- `src/aaosa/schemas/elo.py` — `DEFAULT_REQUIRED_ELO` (barre uniforme).
- `src/aaosa/tracing/events.py` — `RosterGapEvent` + ajout à l'union `ClaimEvent`.
- `src/aaosa/claiming/dispatch.py` — statut `"roster_gap"` dans le `Literal`.
- `src/aaosa/runtime/divider.py` — `DivisionResult` (`is_atomic` + specs structurelles), `divide()` → `DivisionResult`, prompt, suppression `TagSpec`.
- `src/aaosa/runtime/runner.py` — `MAX_RECOVERY_DEPTH`, `_roster_gap`, `build_sub_tasks`, `run_with_recovery`, `run_recovery`, migration `run_chain`, suppression `run_divided_task`.
- `src/aaosa/demo/run_demo.py`, `src/aaosa/demo/run_demo_v3.py` — migration vers `run_recovery` + `RunContext` + `Tagger`.
- `tests/runtime/test_task_divider.py`, `tests/runtime/test_run_chain.py`, `tests/demo/test_demo.py`, `tests/demo/test_run_demo_v3.py` — adaptation.

**Supprimés :**
- `src/aaosa/runtime/runner.py::run_divided_task` (fonction) et `tests/runtime/test_run_divided_task.py` (fichier).

**Hors périmètre (suivis, cf. spec §9) :** rendu dashboard des traces récursives + du `RosterGapEvent` (`dashboard/graph_model.py` inchangé — il consomme `TaskDividedEvent` dont la forme `DividedSubTask` ne change pas), `qa_fail` (D3), forme de l'agrégateur en arbre (D2), exécution parallèle.

---

## Task 1: Constantes (barre uniforme + cap de récursion)

**Files:**
- Modify: `src/aaosa/schemas/elo.py`
- Test: `tests/schemas/test_elo.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/schemas/test_elo.py` :

```python
def test_default_required_elo_is_competent_floor():
    from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO, ELO_COMPETENT_MIN
    assert DEFAULT_REQUIRED_ELO == ELO_COMPETENT_MIN == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/schemas/test_elo.py::test_default_required_elo_is_competent_floor -v`
Expected: FAIL (`ImportError: cannot import name 'DEFAULT_REQUIRED_ELO'`).

- [ ] **Step 3: Add the constant**

Dans `src/aaosa/schemas/elo.py`, après la ligne `ELO_ACQUIRABLE_THRESHOLD = ELO_BASIC_MAX` :

```python
# V3 (D1) — barre d'ELO uniforme posée par le runner sur chaque tag produit par le
# tagger. « Qualifié, pas expert » = borne basse du palier COMPETENT. Ancrée à la
# constante, pas un nombre magique.
DEFAULT_REQUIRED_ELO = ELO_COMPETENT_MIN  # 30
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/schemas/test_elo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/schemas/elo.py tests/schemas/test_elo.py
git commit -m "feat(d1): DEFAULT_REQUIRED_ELO barre uniforme (= ELO_COMPETENT_MIN)"
```

`MAX_RECOVERY_DEPTH` sera ajouté dans `runner.py` à la Task 7 (près de son usage, comme `MAX_TOOL_ROUNDS` dans `core/tool.py`).

---

## Task 2: `RosterGapEvent`

**Files:**
- Modify: `src/aaosa/tracing/events.py`
- Test: `tests/tracing/test_events_v2.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/tracing/test_events_v2.py` :

```python
def test_roster_gap_event_fields_and_discriminator():
    from aaosa.tracing.events import RosterGapEvent
    e = RosterGapEvent(session_id="s", task_id="t", missing_tags=["quantum"])
    assert e.type == "roster_gap"
    assert e.missing_tags == ["quantum"]


def test_roster_gap_event_in_claim_event_union():
    from pydantic import TypeAdapter
    from aaosa.tracing.events import ClaimEvent, RosterGapEvent
    e = RosterGapEvent(session_id="s", task_id="t", missing_tags=["x"])
    dumped = e.model_dump()
    restored = TypeAdapter(ClaimEvent).validate_python(dumped)
    assert isinstance(restored, RosterGapEvent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -k roster_gap -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Add the event**

Dans `src/aaosa/tracing/events.py`, après `class TagLostEvent(...)` :

```python
class RosterGapEvent(_BaseEvent):
    type: Literal["roster_gap"] = "roster_gap"
    missing_tags: list[str]  # tags requis qu'aucun agent du roster ne couvre
```

Puis l'ajouter à l'union `ClaimEvent` (dans le `Union[...]`, à côté de `TagLostEvent`) :

```python
        TagLostEvent,
        RosterGapEvent,
        ToolCalledEvent,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -k roster_gap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/events.py tests/tracing/test_events_v2.py
git commit -m "feat(d1): RosterGapEvent (tags non couverts par le roster)"
```

---

## Task 3: Statut `roster_gap` sur `DispatchResult`

**Files:**
- Modify: `src/aaosa/claiming/dispatch.py:25`
- Test: `tests/claiming/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/claiming/test_dispatch.py` :

```python
def test_dispatch_result_accepts_roster_gap_status():
    from aaosa.claiming.dispatch import DispatchResult
    r = DispatchResult(status="roster_gap", agent_id=None, reason="no agent covers: ['quantum']")
    assert r.status == "roster_gap"
    assert r.agent_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/claiming/test_dispatch.py::test_dispatch_result_accepts_roster_gap_status -v`
Expected: FAIL (`ValidationError`: `status` n'accepte pas `"roster_gap"`).

- [ ] **Step 3: Extend the Literal**

Dans `src/aaosa/claiming/dispatch.py`, ligne 25, remplacer :

```python
    status: Literal["assigned", "unassigned", "dependency_failed", "execution_failed"]
```

par :

```python
    status: Literal["assigned", "unassigned", "dependency_failed", "execution_failed", "roster_gap"]
```

Le validateur `agent_id_matches_status` traite déjà tout statut `!= "assigned"` comme `agent_id is None` — rien d'autre à changer.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/claiming/test_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/claiming/dispatch.py tests/claiming/test_dispatch.py
git commit -m "feat(d1): statut DispatchResult roster_gap"
```

---

## Task 4: `Tagger` (description → ensemble de tags, ≥1 garanti)

**Files:**
- Create: `src/aaosa/runtime/tagger.py`
- Test: `tests/runtime/test_tagger.py`

Modèle calqué sur `TaskDivider` (`runtime/divider.py`) : prompt avec le vocabulaire du roster comme référence, structured output Pydantic.

- [ ] **Step 1: Write the failing tests**

Créer `tests/runtime/test_tagger.py` :

```python
from types import SimpleNamespace

from aaosa.core.agent import Agent
from aaosa.runtime.tagger import TagSet, Tagger


def make_agent(name="A", **tags) -> Agent:
    return Agent(name=name, tags_with_elo=tags or {"python": 80}, system_prompt="x")


def _client_returning(tagset: TagSet | None):
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=tagset))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def test_tag_returns_set_of_tags():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(TagSet(tags=["python", "sql"]))
    tags = tagger.tag("optimize a query", [make_agent()], client)
    assert tags == {"python", "sql"}


def test_tag_dedups_and_strips():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(TagSet(tags=[" python ", "python", "sql"]))
    assert tagger.tag("x", [make_agent()], client) == {"python", "sql"}


def test_tag_returns_empty_set_when_parse_is_none():
    tagger = Tagger(system_prompt="tag it")
    client = _client_returning(None)
    assert tagger.tag("x", [make_agent()], client) == set()


def test_tag_returns_empty_set_when_llm_raises():
    tagger = Tagger(system_prompt="tag it")
    def boom(**kw):
        raise RuntimeError("network")
    client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=boom)))
    )
    assert tagger.tag("x", [make_agent()], client) == set()


def test_tagset_requires_at_least_one_tag():
    import pytest
    with pytest.raises(Exception):
        TagSet(tags=[])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_tagger.py -v`
Expected: FAIL (`ModuleNotFoundError: aaosa.runtime.tagger`).

- [ ] **Step 3: Implement the tagger**

Créer `src/aaosa/runtime/tagger.py` :

```python
"""Tagger — assigne à une description l'ensemble de tags requis (D1).

LLM, provenance-agnostique : tague chaque (sous-)tâche depuis sa PROPRE description,
sans héritage parent. Ne pose PAS l'ELO (barre uniforme posée par le runner). Voit le
vocabulaire du roster comme référence mais nomme une capacité même si absente — c'est ce
qui permet au garde-fou roster_gap d'exister (cf. spec §5).
"""

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from aaosa.core.agent import Agent


class TagSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=1)  # >=1 garanti au niveau du schéma LLM


class EmptyTaggingError(Exception):
    """Levée quand le tagger ne produit aucun tag pour une description."""


class Tagger:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_prompt(self, description: str, agents: list[Agent]) -> str:
        vocab = sorted({t for a in agents for t in a.tags_with_elo})
        return (
            "Available agent tags (reference vocabulary — not exhaustive):\n"
            f"  {', '.join(vocab)}\n\n"
            "Name the capabilities (tags) this task requires to be done well.\n"
            "Prefer the vocabulary above when it fits, but name a real capability even\n"
            "if it is absent from the roster — do not force-fit. Return at least one tag.\n\n"
            f"Task: {description}"
        )

    def tag(self, description: str, agents: list[Agent], client: OpenAI) -> set[str]:
        prompt = self._build_prompt(description, agents)
        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format=TagSet,
            )
            parsed = response.choices[0].message.parsed
        except Exception:
            parsed = None
        if parsed is None:
            return set()
        return {t.strip() for t in parsed.tags if t.strip()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_tagger.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/tagger.py tests/runtime/test_tagger.py
git commit -m "feat(d1): Tagger (description -> ensemble de tags, >=1 garanti)"
```

---

## Task 5: `RunContext` (dépendances statiques du run)

**Files:**
- Create: `src/aaosa/runtime/context.py`
- Test: `tests/runtime/test_context.py`

- [ ] **Step 1: Write the failing tests**

Créer `tests/runtime/test_context.py` :

```python
import dataclasses

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger


def _ctx() -> RunContext:
    return RunContext(
        agents=[Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")],
        client=object(),
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
    )


def test_runcontext_holds_dependencies():
    ctx = _ctx()
    assert ctx.tracer is None
    assert ctx.evaluator is None
    assert ctx.agents[0].name == "A"


def test_runcontext_is_frozen():
    ctx = _ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.client = object()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_context.py -v`
Expected: FAIL (`ModuleNotFoundError: aaosa.runtime.context`).

- [ ] **Step 3: Implement RunContext**

Créer `src/aaosa/runtime/context.py` :

```python
"""RunContext — dépendances statiques d'un run de récupération (D1, spec §8).

Évite de threader agents/client/divider/aggregator/tagger/tracer/evaluator dans chaque
appel récursif. Seul `depth` reste threadé explicitement. Frozen : aucune mutation en
cours de run.
"""

from dataclasses import dataclass

from openai import OpenAI

from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger
from aaosa.tracing.tracer import Tracer


@dataclass(frozen=True)
class RunContext:
    agents: list[Agent]
    client: OpenAI
    divider: TaskDivider
    aggregator: TaskAggregator
    tagger: Tagger
    tracer: Tracer | None = None
    evaluator: QAEvaluator | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_context.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/context.py tests/runtime/test_context.py
git commit -m "feat(d1): RunContext (deps statiques du run, frozen)"
```

---

## Task 6: Helper pur `_roster_gap`

**Files:**
- Modify: `src/aaosa/runtime/runner.py`
- Test: `tests/runtime/test_runner.py`

Helper pur (logique d'ensembles), indépendant de la récursion. Ajouté tôt car testable isolément.

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/runtime/test_runner.py` :

```python
def test_roster_gap_detects_missing_tags():
    from aaosa.core.agent import Agent
    from aaosa.runtime.runner import _roster_gap
    from aaosa.schemas.task import Task

    agents = [Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")]
    task = Task(description="t", required_tags={"python": 30, "quantum": 30})
    assert _roster_gap(task, agents) == {"quantum"}


def test_roster_gap_empty_when_all_covered():
    from aaosa.core.agent import Agent
    from aaosa.runtime.runner import _roster_gap
    from aaosa.schemas.task import Task

    agents = [
        Agent(name="A", tags_with_elo={"python": 5}, system_prompt="x"),
        Agent(name="B", tags_with_elo={"sql": 5}, system_prompt="x"),
    ]
    task = Task(description="t", required_tags={"python": 30, "sql": 30})
    # présence du tag dans le roster suffit — l'ELO insuffisant n'est PAS un roster_gap
    assert _roster_gap(task, agents) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py -k roster_gap -v`
Expected: FAIL (`ImportError: cannot import name '_roster_gap'`).

- [ ] **Step 3: Implement the helper**

Dans `src/aaosa/runtime/runner.py`, après les imports (avant `def run_task`), ajouter :

```python
def _roster_gap(task: Task, agents: list[Agent]) -> set[str]:
    """Tags requis qu'AUCUN agent du roster ne porte. Compare la présence du tag,
    pas son niveau d'ELO (un ELO insuffisant n'est pas un trou de roster)."""
    roster = {tag for a in agents for tag in a.tags_with_elo}
    return set(task.required_tags) - roster
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py -k roster_gap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_runner.py
git commit -m "feat(d1): helper pur _roster_gap"
```

---

## Task 7: Cœur de récupération (divider structurel + récursion + migration)

> **Pourquoi un seul gros task :** changer le type de retour de `divide()` (list[Task] → `DivisionResult` structurel) casse `run_divided_task`, et la migration de la signature de `run_chain` (exécuteur `run_task` → `run_with_recovery`) est incompatible avec l'ancien `run_chain`. Ces changements sont **couplés** : les isoler créerait des états rouges intermédiaires. On les fait ensemble, un seul commit vert à la fin. Les étapes restent bite-sized.

**Files:**
- Modify: `src/aaosa/runtime/divider.py`
- Modify: `src/aaosa/runtime/runner.py`
- Modify: `src/aaosa/demo/run_demo.py`, `src/aaosa/demo/run_demo_v3.py`
- Rewrite: `tests/runtime/test_task_divider.py`
- Create: `tests/runtime/test_run_with_recovery.py`
- Modify: `tests/runtime/test_run_chain.py`, `tests/demo/test_demo.py`, `tests/demo/test_run_demo_v3.py`
- Delete: `tests/runtime/test_run_divided_task.py`

### 7a — Divider structurel

- [ ] **Step 1: Rewrite the divider tests**

Remplacer **tout** le contenu de `tests/runtime/test_task_divider.py` par :

```python
from types import SimpleNamespace

import pytest

from aaosa.runtime.divider import DivisionResult, SubTaskSpec, TaskDivider


def _client_returning(division_result):
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=division_result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


class TestDivisionResult:
    def test_non_atomic_requires_subtasks(self):
        with pytest.raises(ValueError, match="non-atomic"):
            DivisionResult(is_atomic=False, sub_tasks=[])

    def test_atomic_forbids_subtasks(self):
        with pytest.raises(ValueError, match="atomic"):
            DivisionResult(is_atomic=True, sub_tasks=[SubTaskSpec(description="x")])

    def test_atomic_ok_with_no_subtasks(self):
        d = DivisionResult(is_atomic=True, sub_tasks=[])
        assert d.is_atomic is True

    def test_subtaskspec_has_no_tags(self):
        # le divider est purement structurel : description + dépendances, pas de tags
        spec = SubTaskSpec(description="x", depends_on_indices=[0])
        assert not hasattr(spec, "required_tags")


class TestTaskDivider:
    def test_divide_returns_division_result(self):
        from aaosa.schemas.task import Task
        result = DivisionResult(sub_tasks=[
            SubTaskSpec(description="a"),
            SubTaskSpec(description="b", depends_on_indices=[0]),
        ])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(result))
        assert isinstance(out, DivisionResult)
        assert [s.description for s in out.sub_tasks] == ["a", "b"]
        assert out.sub_tasks[1].depends_on_indices == [0]

    def test_divide_passes_through_atomic_verdict(self):
        from aaosa.schemas.task import Task
        result = DivisionResult(is_atomic=True, sub_tasks=[])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(result))
        assert out.is_atomic is True

    def test_divide_raises_on_none_parsed(self):
        from aaosa.schemas.task import Task
        divider = TaskDivider(system_prompt="split")
        with pytest.raises(ValueError, match="no parsed"):
            divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(None))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_divider.py -v`
Expected: FAIL (`is_atomic` inconnu, `SubTaskSpec` exige encore `required_tags`, `divide` signature/retour).

- [ ] **Step 3: Refactor `divider.py`**

Dans `src/aaosa/runtime/divider.py` : supprimer la classe `TagSpec`. Remplacer `SubTaskSpec`, `DivisionResult`, `_build_divide_prompt` et `divide` par :

```python
class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    depends_on_indices: list[int] = Field(default_factory=list)  # indices 0-based dans sub_tasks


class DivisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_atomic: bool = False
    sub_tasks: list[SubTaskSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def atomic_xor_subtasks(self) -> "DivisionResult":
        if self.is_atomic and self.sub_tasks:
            raise ValueError("atomic division cannot have sub_tasks")
        if not self.is_atomic and not self.sub_tasks:
            raise ValueError("non-atomic division must have sub_tasks")
        return self


class TaskDivider:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_divide_prompt(self, task: Task) -> str:
        return (
            "If the task is atomic (a single capability, not usefully decomposable),\n"
            "set is_atomic=true and return no sub-tasks.\n"
            "Otherwise set is_atomic=false and decompose it into ordered sub-tasks, each\n"
            "a description plus dependencies (0-based indices into your sub_tasks list).\n"
            "Do NOT assign tags — only describe the work and its ordering.\n\n"
            f"Task: {task.description}"
        )

    def divide(self, task: Task, client: OpenAI) -> "DivisionResult":
        """LLM call → DivisionResult (structurel, sans tags). Ne construit pas de Task,
        ne résout pas les deps, n'émet aucun event — c'est le runner (build_sub_tasks)."""
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(task)},
            ],
            response_format=DivisionResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
```

Supprimer les imports devenus inutiles dans `divider.py` : `Agent`, `DividedSubTask`, `TaskDividedEvent`, `Tracer` (vérifier qu'ils ne servent plus ; garder `Task`, `OpenAI`, et `BaseModel, ConfigDict, Field, model_validator`).

- [ ] **Step 4: Run divider tests**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_divider.py -v`
Expected: PASS. (Le reste de la suite est cassé temporairement — on continue dans le même task.)

### 7b — Runner : suppression de l'ancien chemin, ajout du cœur récursif

- [ ] **Step 5: Delete the obsolete test file**

```bash
git rm tests/runtime/test_run_divided_task.py
```

- [ ] **Step 6: Rewrite `runner.py` runtime imports + constant**

Dans `src/aaosa/runtime/runner.py`, remplacer le bloc d'imports du haut par :

```python
from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.elo.updater import update_agent_elo
from aaosa.qa.protocol import QAEvaluator, QAFailure
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import (
    DividedSubTask,
    EloUpdatedEvent,
    ExecutedEvent,
    QAEvaluatedEvent,
    RosterGapEvent,
    TagAcquiredEvent,
    TagLostEvent,
    TaskDividedEvent,
)
from aaosa.tracing.tracer import Tracer

MAX_RECOVERY_DEPTH = 3  # tâche → sous → sous-sous ; relevable si les runs réels le justifient
```

> Note : on retire le bloc `if TYPE_CHECKING: ... TaskAggregator / TaskDivider` (ils transitaient par `run_divided_task`, supprimé). `RunContext` les porte maintenant.

`run_task` (lignes 21-115) et `_topological_order` (118-146) restent **inchangés**.

- [ ] **Step 7: Replace `run_chain` and delete `run_divided_task`**

Dans `src/aaosa/runtime/runner.py`, remplacer la fonction `run_chain` actuelle ET supprimer entièrement `run_divided_task`, par le bloc suivant :

```python
def run_chain(sub_tasks: list[Task], ctx: RunContext, depth: int) -> list[Output | DispatchResult | QAFailure]:
    """Exécute une liste de sous-tâches ordonnée par leur graphe de dépendances (Kahn).

    Recovery-aware (D1) : l'exécuteur par nœud est `run_with_recovery` (était `run_task`).
    Le reste est identique à A3 — required_outputs des deps réussies injectés, cascade
    dependency_failed, input non muté (model_copy)."""
    order = _topological_order(sub_tasks)
    outputs: dict[str, Output] = {}
    results: list[Output | DispatchResult | QAFailure] = []

    for task in order:
        unmet = [dep for dep in task.depends_on if dep not in outputs]
        if unmet:
            results.append(DispatchResult(
                status="dependency_failed",
                agent_id=None,
                reason=f"unresolved dependencies: {unmet}",
            ))
            continue
        resolved = [outputs[dep] for dep in task.depends_on]
        task_to_run = task.model_copy(update={"required_outputs": resolved})
        result = run_with_recovery(task_to_run, ctx, depth)
        results.append(result)
        if isinstance(result, Output):
            outputs[task.id] = result

    return results
```

- [ ] **Step 8: Add `build_sub_tasks`, `run_with_recovery`, `run_recovery`**

Toujours dans `src/aaosa/runtime/runner.py`, à la fin du fichier :

```python
def build_sub_tasks(parent_task: Task, division: DivisionResult, ctx: RunContext) -> list[Task]:
    """Transforme les sous-specs structurelles du divider en Task taguées.

    Tague CHAQUE sous-tâche depuis sa propre description (pas d'héritage parent), pose la
    barre uniforme DEFAULT_REQUIRED_ELO, résout les deps indices→IDs, et émet le
    TaskDividedEvent (avec les vrais tags). Lève EmptyTaggingError si une sous-spec ne
    produit aucun tag (clean-crash géré par run_with_recovery)."""
    sub_tasks: list[Task] = []
    for i, spec in enumerate(division.sub_tasks):
        tags = ctx.tagger.tag(spec.description, ctx.agents, ctx.client)
        if not tags:
            raise EmptyTaggingError(spec.description)
        sub_tasks.append(Task(
            description=spec.description,
            required_tags={t: DEFAULT_REQUIRED_ELO for t in tags},
            parent_task_id=parent_task.id,
            order_index=i,
        ))
    for i, spec in enumerate(division.sub_tasks):
        sub_tasks[i].depends_on = [sub_tasks[j].id for j in spec.depends_on_indices]

    if ctx.tracer is not None:
        ctx.tracer.emit(TaskDividedEvent(
            session_id=ctx.tracer.session_id,
            task_id=parent_task.id,
            sub_tasks=[
                DividedSubTask(
                    id=st.id, description=st.description,
                    depends_on=list(st.depends_on), required_tags=dict(st.required_tags),
                )
                for st in sub_tasks
            ],
        ))
    return sub_tasks


def run_with_recovery(task: Task, ctx: RunContext, depth: int = 0) -> Output | DispatchResult | QAFailure:
    """Cœur récursif D1. Tente la tâche à plat ; ne divise que sur `unassigned`,
    récursivement (mutuellement récursif avec run_chain). `task` est TOUJOURS taguée."""
    missing = _roster_gap(task, ctx.agents)
    if missing:
        if ctx.tracer is not None:
            ctx.tracer.emit(RosterGapEvent(
                session_id=ctx.tracer.session_id,
                task_id=task.id,
                missing_tags=sorted(missing),
            ))
        return DispatchResult(
            status="roster_gap",
            agent_id=None,
            reason=f"no agent covers required tags: {sorted(missing)}",
        )

    result = run_task(task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)
    if not (isinstance(result, DispatchResult) and result.status == "unassigned"):
        return result  # Output / QAFailure / execution_failed / dependency_failed : terminaux

    if depth >= MAX_RECOVERY_DEPTH:
        return result

    division = ctx.divider.divide(task, ctx.client)
    if division.is_atomic:
        return result  # cul-de-sac réel : unassigned remonté

    try:
        sub_tasks = build_sub_tasks(task, division, ctx)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed",
            agent_id=None,
            reason="tagging produced no tags",
        )

    sub_results = run_chain(sub_tasks, ctx, depth + 1)
    successful = [r for r in sub_results if isinstance(r, Output)]
    if not successful:
        return DispatchResult(
            status="unassigned",
            agent_id=None,
            reason="no sub-tasks recovered",
        )

    try:
        return ctx.aggregator.aggregate(task, successful, ctx.client, ctx.tracer)
    except Exception:
        return successful[-1]  # fallback C : dernier output réussi


def run_recovery(
    description: str,
    ctx: RunContext,
    pinned_tags: dict[str, int] | None = None,
) -> Output | DispatchResult | QAFailure:
    """Entrée publique D1 (remplace run_divided_task). Tague la racine SEULEMENT si le
    caller n'a pas épinglé de tags ; une racine déjà taguée n'est pas re-taguée (§2)."""
    if pinned_tags:
        task = Task(description=description, required_tags=pinned_tags)
    else:
        tags = ctx.tagger.tag(description, ctx.agents, ctx.client)
        if not tags:
            return DispatchResult(
                status="execution_failed",
                agent_id=None,
                reason="tagging produced no tags",
            )
        task = Task(description=description, required_tags={t: DEFAULT_REQUIRED_ELO for t in tags})
    return run_with_recovery(task, ctx, depth=0)
```

### 7c — Tests du cœur récursif

- [ ] **Step 9: Write `test_run_with_recovery.py`**

Créer `tests/runtime/test_run_with_recovery.py` :

```python
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks, run_recovery, run_with_recovery
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import RosterGapEvent, TaskDividedEvent
from aaosa.tracing.tracer import Tracer


def make_agent(name="A", **tags) -> Agent:
    return Agent(name=name, tags_with_elo=tags or {"python": 80}, system_prompt="x")


def make_output(task_id="t", content="c") -> Output:
    return Output(
        task_id=task_id, agent_id="x", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class _FakeTagger:
    def __init__(self, mapping=None, default=("python",)):
        self.mapping = mapping or {}
        self.default = set(default)

    def tag(self, description, agents, client):
        return set(self.mapping.get(description, self.default))


class _StaticDivider:
    def __init__(self, division):
        self.division = division

    def divide(self, task, client):
        return self.division


class _RecordingAggregator:
    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        return make_output(parent_task.id, "agg")


class _ExplodingAggregator:
    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        raise RuntimeError("boom")


def _ctx(divider, tagger=None, aggregator=None, tracer=None, agents=None):
    return RunContext(
        agents=agents or [make_agent()],
        client=object(),
        divider=divider,
        aggregator=aggregator or _RecordingAggregator(),
        tagger=tagger or _FakeTagger(),
        tracer=tracer,
    )


def _two_subtask_division():
    return DivisionResult(sub_tasks=[
        SubTaskSpec(description="s1"),
        SubTaskSpec(description="s2", depends_on_indices=[0]),
    ])


class TestRunWithRecovery:
    def test_flat_success_no_division(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")) as rt:
            result = run_with_recovery(task, ctx)
        assert isinstance(result, Output)
        rt.assert_called_once()

    def test_unassigned_triggers_division_then_aggregates(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
                result = run_with_recovery(task, ctx)
        assert isinstance(result, Output)
        assert result.content == "agg"

    def test_atomic_verdict_is_dead_end(self):
        ctx = _ctx(_StaticDivider(DivisionResult(is_atomic=True, sub_tasks=[])))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain") as rc:
                result = run_with_recovery(task, ctx)
        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"
        rc.assert_not_called()

    def test_depth_cap_stops_recursion(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain") as rc:
                result = run_with_recovery(task, ctx, depth=3)
        assert result.status == "unassigned"
        rc.assert_not_called()

    def test_roster_gap_short_circuits_and_emits_event(self):
        tracer = Tracer(session_id="s")
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tracer=tracer,
                   agents=[make_agent(python=80)])
        task = Task(description="t", required_tags={"python": 30, "quantum": 30})
        with patch("aaosa.runtime.runner.run_task") as rt:
            result = run_with_recovery(task, ctx)
        assert result.status == "roster_gap"
        rt.assert_not_called()
        assert any(isinstance(e, RosterGapEvent) and e.missing_tags == ["quantum"] for e in tracer.events)

    def test_no_successful_subtasks_returns_unassigned(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[unassigned, unassigned]):
                result = run_with_recovery(task, ctx)
        assert result.status == "unassigned"
        assert result.reason == "no sub-tasks recovered"

    def test_aggregator_exception_falls_back_to_last_output(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), aggregator=_ExplodingAggregator())
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
                result = run_with_recovery(task, ctx)
        assert result.task_id == "s2"

    def test_empty_tagging_is_clean_crash(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            result = run_with_recovery(task, ctx)
        assert result.status == "execution_failed"
        assert result.reason == "tagging produced no tags"


class TestBuildSubTasks:
    def test_tags_each_subtask_with_uniform_elo_and_resolves_deps(self):
        from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO
        ctx = _ctx(_StaticDivider(_two_subtask_division()),
                   tagger=_FakeTagger(mapping={"s1": ("python",), "s2": ("sql",)}))
        parent = Task(description="t", required_tags={"python": 30})
        subs = build_sub_tasks(parent, _two_subtask_division(), ctx)
        assert subs[0].required_tags == {"python": DEFAULT_REQUIRED_ELO}
        assert subs[1].required_tags == {"sql": DEFAULT_REQUIRED_ELO}
        assert subs[1].depends_on == [subs[0].id]
        assert all(s.parent_task_id == parent.id for s in subs)

    def test_emits_task_divided_event_with_real_tags(self):
        tracer = Tracer(session_id="s")
        ctx = _ctx(_StaticDivider(_two_subtask_division()),
                   tagger=_FakeTagger(mapping={"s1": ("python",), "s2": ("sql",)}), tracer=tracer)
        parent = Task(description="t", required_tags={"python": 30})
        build_sub_tasks(parent, _two_subtask_division(), ctx)
        events = [e for e in tracer.events if isinstance(e, TaskDividedEvent)]
        assert len(events) == 1
        assert events[0].sub_tasks[0].required_tags == {"python": 30}

    def test_raises_empty_tagging_error_on_empty(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        parent = Task(description="t", required_tags={"python": 30})
        with pytest.raises(EmptyTaggingError):
            build_sub_tasks(parent, _two_subtask_division(), ctx)


class TestRunRecovery:
    def test_pinned_tags_skip_tagger(self):
        called = {"tag": False}

        class _SpyTagger(_FakeTagger):
            def tag(self, description, agents, client):
                called["tag"] = True
                return {"python"}

        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_SpyTagger())
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")):
            run_recovery("t", ctx, pinned_tags={"python": 70})
        assert called["tag"] is False

    def test_unpinned_root_is_tagged(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=("python",)))
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")) as rt:
            run_recovery("do a python thing", ctx)
        # run_task a reçu une Task taguée par le tagger
        passed_task = rt.call_args.args[0]
        assert "python" in passed_task.required_tags

    def test_unpinned_root_empty_tagging_clean_crash(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        result = run_recovery("t", ctx)
        assert result.status == "execution_failed"
```

- [ ] **Step 10: Run the recovery tests**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery.py -v`
Expected: PASS (toutes). Si rouge, corriger l'implémentation 7b avant de continuer.

- [ ] **Step 11: Migrate `test_run_chain.py` to the ctx signature**

Dans `tests/runtime/test_run_chain.py`, le `run_chain` est maintenant `run_chain(sub_tasks, ctx, depth)` et appelle `run_with_recovery` par nœud. Adapter : remplacer chaque appel `run_chain([...], [a], MagicMock())` par `run_chain([...], _ctx_for_chain([a]), 1)`, et patcher `aaosa.runtime.runner.run_with_recovery` (au lieu de `run_task`) là où les tests stubbaient l'exécution par nœud.

Ajouter en tête du fichier ce helper, et l'utiliser :

```python
from aaosa.runtime.context import RunContext
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger


def _ctx_for_chain(agents):
    return RunContext(
        agents=agents, client=MagicMock(),
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
    )
```

Pour les tests qui vérifient le tri Kahn / la cascade `dependency_failed` : patcher `aaosa.runtime.runner.run_with_recovery` avec un side_effect qui renvoie un `Output` par tâche réussie (exactement comme l'ancien stub de `run_task`). Exemple de conversion d'un test existant :

```python
def test_chain_executes_in_topological_order():
    a = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")
    t1 = Task(description="t1", required_tags={"python": 30})
    t2 = Task(description="t2", required_tags={"python": 30}, depends_on=[t1.id])

    seen = []

    def fake_rwr(task, ctx, depth):
        seen.append(task.description)
        return Output(task_id=task.id, agent_id="x", content="ok",
                      llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))

    with patch("aaosa.runtime.runner.run_with_recovery", side_effect=fake_rwr):
        run_chain([t2, t1], _ctx_for_chain([a]), 1)  # unordered input
    assert seen == ["t1", "t2"]
```

Appliquer la même conversion (patch `run_with_recovery`, signature `(sub_tasks, ctx, depth)`) à **tous** les tests du fichier. Conserver les assertions sur l'ordre Kahn, `dependency_failed`, et le threading des `required_outputs` (inchangés).

- [ ] **Step 12: Run the chain tests**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_chain.py -v`
Expected: PASS.

### 7d — Migration des démos

- [ ] **Step 13: Migrate `run_demo_v3.py`**

Dans `src/aaosa/demo/run_demo_v3.py` :

Remplacer l'import `from aaosa.runtime.divider import TaskDivider` (ligne 16) par :

```python
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger
```

Après la construction de `aggregator` (vers ligne 75), ajouter le tagger + le contexte, et remplacer le bloc d'appel `run_divided_task` (lignes 81-84) :

```python
    tagger = Tagger(system_prompt=(
        "You assign capability tags to a task description. Use the roster vocabulary "
        "when it fits; name a real capability even if absent. Return at least one tag."
    ))
    ctx = RunContext(
        agents=agents, client=client, divider=divider, aggregator=aggregator,
        tagger=tagger, tracer=tracer, evaluator=evaluator,
    )

    print("=== AAOSA Demo V3 — flat-first, division as recovery ===\n")
    print(f"Input: {task.description}\n")

    from aaosa.runtime.runner import run_recovery
    result = run_recovery(task.description, ctx, pinned_tags=task.required_tags)
    outcome = "divided" if isinstance(result, Output) else "unassigned"
    print(f"  -> {outcome}\n")
```

(On épingle les tags de la tâche d'incident pour rester compatible avec le roster de démo ; la racine n'est donc pas re-taguée. Si aucun agent ne claime à plat, la récupération divise — comportement D1 attendu.)

- [ ] **Step 14: Migrate `run_demo.py`**

Dans `src/aaosa/demo/run_demo.py` :

Remplacer l'import ligne 15 `from aaosa.runtime.runner import run_divided_task, run_task` par :

```python
from aaosa.runtime.context import RunContext
from aaosa.runtime.runner import run_recovery, run_task
from aaosa.runtime.tagger import Tagger
```

Remplacer le bloc divisé (lignes 84-86) :

```python
    divided_result = run_divided_task(
        divided_task, DEMO_AGENTS, client, divider, aggregator, tracer=tracer
    )
```

par :

```python
    tagger = Tagger(system_prompt=(
        "You assign capability tags to a task description. Use the roster vocabulary "
        "when it fits; name a real capability even if absent. Return at least one tag."
    ))
    ctx = RunContext(
        agents=DEMO_AGENTS, client=client, divider=divider, aggregator=aggregator,
        tagger=tagger, tracer=tracer,
    )
    divided_result = run_recovery(
        divided_task.description, ctx, pinned_tags=divided_task.required_tags
    )
```

- [ ] **Step 15: Migrate the demo tests (`test_demo.py`)**

Dans `tests/demo/test_demo.py` :

Renommer le stub et repointer les monkeypatches. Remplacer `_fake_run_divided_task` (lignes 209-216) par :

```python
def _fake_run_recovery(description, ctx, pinned_tags=None):
    """Stub le run de récupération D1 pour garder les tests démo offline."""
    return Output(
        task_id="divided",
        agent_id="aggregator",
        content="Aggregated synthesis covering the divided task" + "x" * 40,
        llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
    )
```

Puis remplacer **toutes** les occurrences de :
`monkeypatch.setattr("aaosa.demo.run_demo.run_divided_task", _fake_run_divided_task)`
par :
`monkeypatch.setattr("aaosa.demo.run_demo.run_recovery", _fake_run_recovery)`

et (dans `TestDemoV2b`) les deux :
`monkeypatch.setattr(demo_module, "run_divided_task", _fake_run_divided_task)`
par :
`monkeypatch.setattr(demo_module, "run_recovery", _fake_run_recovery)`

- [ ] **Step 16: Migrate `test_run_demo_v3.py`**

Lire `tests/demo/test_run_demo_v3.py` et repérer tout monkeypatch de `run_divided_task` sur `aaosa.demo.run_demo_v3` ; le remplacer par un stub `run_recovery(description, ctx, pinned_tags=None)` de même forme que `_fake_run_recovery` ci-dessus (renvoyer un `Output` avec `agent_id="aggregator"`). Si le test patche `run_task` ou les `save_*`, les conserver tels quels.

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_demo_v3.py -v`
Expected: PASS (après adaptation).

### 7e — Suite complète verte + commit unique

- [ ] **Step 17: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert. Le compte total diminue des tests `run_divided_task` supprimés et augmente des tests `test_run_with_recovery` / `test_tagger` / `test_context` ajoutés. Corriger tout résidu (imports orphelins de `run_divided_task`, `TagSpec`, `TYPE_CHECKING`).

- [ ] **Step 18: Commit**

```bash
git add -A
git commit -m "feat(d1): division emergente recursive (tagger + run_with_recovery + roster_gap)

- divider purement structurel (DivisionResult.is_atomic, sous-specs sans tags)
- run_recovery/run_with_recovery (mutuellement recursif avec run_chain)
- build_sub_tasks (tague chaque sous-tache, barre uniforme, TaskDividedEvent)
- garde-fou roster_gap + RosterGapEvent ; clean-crash execution_failed sur tag vide
- run_chain recovery-aware ; suppression run_divided_task ; migration demos
- run_task strictement intact (retrocompat V1/V2)"
```

---

## Task 8: Smoke test LLM réel (manuel, hors CI)

**Files:**
- Test: `tests/runtime/test_run_with_recovery_llm.py` (marqué pour exclusion CI)

Valide le chemin end-to-end avec un vrai client : une tâche large échoue à plat puis se récupère par division. Ne tourne **pas** en CI (réseau + `OPENAI_API_KEY`).

- [ ] **Step 1: Write the gated test**

Créer `tests/runtime/test_run_with_recovery_llm.py` :

```python
import os

import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="set RUN_LLM_TESTS=1 to run real-LLM smoke tests"
)


def test_broad_task_recovers_by_division():
    load_dotenv()
    from aaosa.demo.agents import DEMO_AGENTS
    from aaosa.demo.tools import attach_tools
    from aaosa.runtime.aggregator import TaskAggregator
    from aaosa.runtime.context import RunContext
    from aaosa.runtime.divider import TaskDivider
    from aaosa.runtime.llm_client import create_client
    from aaosa.runtime.runner import run_recovery
    from aaosa.runtime.tagger import Tagger
    from aaosa.schemas.output import Output
    from aaosa.tracing.events import TaskDividedEvent
    from aaosa.tracing.tracer import Tracer

    client = create_client()
    agents = list(DEMO_AGENTS)
    attach_tools(agents)
    tracer = Tracer(session_id="llm-smoke")
    ctx = RunContext(
        agents=agents, client=client,
        divider=TaskDivider(system_prompt="Decompose only if the task bundles several capabilities; else mark atomic."),
        aggregator=TaskAggregator(system_prompt="Merge sub-results into one coherent answer."),
        tagger=Tagger(system_prompt="Tag the task with required capabilities; at least one."),
        tracer=tracer,
    )

    result = run_recovery(
        "Build a small REST API with a Python backend, a database layer, and a test suite.",
        ctx,
    )
    assert isinstance(result, Output)
    assert any(isinstance(e, TaskDividedEvent) for e in tracer.events), "expected at least one division"
```

- [ ] **Step 2: Run it manually**

Run: `$env:RUN_LLM_TESTS=1; .venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery_llm.py -v -s`
Expected: PASS (division observée). Sinon, ajuster le prompt du divider/tagger — pas le code du runtime.

- [ ] **Step 3: Commit**

```bash
git add tests/runtime/test_run_with_recovery_llm.py
git commit -m "test(d1): smoke LLM reel recuperation par division (hors CI)"
```

---

## Self-Review

**1. Spec coverage** (spec §1–§11) :
- §1 principe « tente à plat, divise sur échec » → Task 7 (`run_with_recovery`). ✓
- §2 décisions verrouillées : approche A paresseuse (Task 7) · déclencheur `unassigned` seul (`run_with_recovery` ne récupère que sur `unassigned`) · `execution_failed`/`qa_fail` terminaux (idem) · roster_gap (Tasks 2/3/6/7) · tagger re-tague chaque sous-tâche (Task 7 `build_sub_tasks`) · barre uniforme (Task 1 + `build_sub_tasks`). ✓
- §3 composants : tagger (Task 4), divider structurel (Task 7a), aggregator inchangé (✓ non touché), runner (Task 7b), DispatchResult roster_gap (Task 3), RosterGapEvent (Task 2), constantes (Task 1 + 7b). ✓
- §4 flux complet (run_recovery → run_with_recovery → divide → build_sub_tasks → run_chain → aggregate) → Task 7. ✓
- §5 tagger nomme une capacité absente → prompt Task 4 ; gate à chaque niveau → `run_with_recovery` step 1. ✓
- §6 atomicité (Task 7a `DivisionResult` validator + prompt) + clean-crash (Task 4 `EmptyTaggingError`, Task 7b). ✓
- §7 barre uniforme + conséquence acquisition (pas de tag acquérable) : implémentée (tous les tags en `required_tags`). ✓
- §8 RunContext (Task 5). ✓
- §9 hors-scope (dashboard, qa_fail, D2, parallèle) : non touchés — `dashboard/graph_model.py` intact, `DividedSubTask` inchangé. ✓
- §10 réglages tranchés : `DEFAULT_REQUIRED_ELO=30` (Task 1), `MAX_RECOVERY_DEPTH=3` (Task 7b), `RosterGapEvent` (Task 2). ✓
- §11 stratégie de tests : purs (Tasks 4/5/6/7c), récursion mockée (Task 7c), real-LLM (Task 8). ✓

**2. Placeholder scan :** aucun « TODO/handle edge cases/similar to ». Chaque step de code montre le code complet. ✓

**3. Type consistency :**
- `Tagger.tag(description, agents, client) -> set[str]` — appelé identiquement dans `build_sub_tasks` et `run_recovery`. ✓
- `TaskDivider.divide(task, client) -> DivisionResult` (agents retiré) — appelé `ctx.divider.divide(task, ctx.client)`. ✓
- `DivisionResult` : `is_atomic: bool`, `sub_tasks: list[SubTaskSpec]` ; `SubTaskSpec(description, depends_on_indices)` — cohérent test/impl. ✓
- `RunContext(agents, client, divider, aggregator, tagger, tracer=None, evaluator=None)` — même ordre/champs partout. ✓
- `run_chain(sub_tasks, ctx, depth)` — nouvelle signature appliquée dans `run_with_recovery` et les tests migrés (Task 7c step 11). ✓
- `aggregator.aggregate(parent_task, sub_outputs, client, tracer=None)` — inchangé (conforme `aggregator.py`). ✓
- `DispatchResult(status=..., agent_id=None, reason=...)` — `roster_gap`/`execution_failed`/`unassigned` avec `agent_id=None`, conforme au validateur. ✓

**Note d'attention pour l'exécutant :** Task 7 est volontairement large (couplage divider↔runner↔démos). Avancer ses sous-étapes dans l'ordre 7a→7e ; la suite n'est verte **qu'à la fin** de Task 7 (commit unique). Ne pas committer au milieu de 7.
