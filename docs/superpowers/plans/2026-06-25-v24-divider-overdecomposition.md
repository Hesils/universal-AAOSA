# v24 — Divider sur-décompose code+doc : Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supprimer la sur-décomposition récursive et le mis-routing des tâches code+doc, en bornant déterministiquement la récursion sur un AND-set de tags cross-rôle.

**Architecture:** Trois surfaces compounding. (1) Prompt divider : pas de sous-tâche « read/understand » fantôme. (2) Prompt tagger + retry ciblé : pas de set cross-rôle. (3) Verrou déterministe dans `build_sub_tasks` : quand le tagger sur-couvre une sous-spec atomique avec un set qu'aucun agent unique ne porte, re-tag single-rôle une fois, sinon clean-crash — **jamais** re-diviser. La racine code+doc reste libre de diviser (le verrou ne vit qu'au niveau sous-tâche).

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9.0.3, `uv`. Toujours `.venv\Scripts\python -m pytest`.

**Spec source :** `docs/superpowers/specs/2026-06-25-v24-divider-overdecomposition.md` (diagnostic prouvé par trace `…105833-ffc59e09`). Décision §4 tranchée = **option A** (re-tag single-rôle + retry, fail loud en fallback).

## Global Constraints

- Imports **absolus uniquement** (`from aaosa.runtime.runner import ...`).
- Timestamp UTC via `Field(default_factory=lambda: datetime.now(timezone.utc))` — jamais `datetime.utcnow()`.
- Pydantic v2 : `model_config = ConfigDict(extra="forbid")` hérité via `_BaseEvent` — ne pas re-déclarer.
- **Rétrocompat stricte** : tout ajout est optionnel/default ; roster mono-rôle ou sans cross-rôle ⇒ comportement V3 identique.
- **Tagger ≥ 1 tag garanti** : un re-tag ne doit jamais produire un set vide (sinon `EmptyTaggingError`).
- **Séparations** : détecteur = fonction **pure** sans LLM (Phase-1-like) ; le re-tag est un appel tagger isolé, pas un mélange de phases.
- Tests via le venv : `.venv\Scripts\python -m pytest <fichier> -v`.
- Branche `fix/v24-divider-overdecomposition` (déjà créée, worktree `agentic-session-2`).

---

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/aaosa/runtime/runner.py` | détecteur pur `_cross_role_unsatisfiable` + re-tag dans `build_sub_tasks` | Modify |
| `src/aaosa/runtime/tagger.py` | param `unsatisfiable_hint` + prompt durci ; `UnsatisfiableTagSetError` | Modify |
| `src/aaosa/runtime/divider.py` | prompt : pas de sous-tâche « read/understand » | Modify |
| `src/aaosa/tracing/events.py` | `RetagEvent` (observabilité du cross-rôle détecté) + Union | Modify |
| `tests/runtime/test_runner_build_sub_tasks.py` | détecteur + re-tag + clean-crash + anti-récursion | Modify |
| `tests/runtime/test_tagger.py` | `unsatisfiable_hint` dans le prompt | Modify |
| `tests/runtime/test_divider.py` | assertion contenu prompt « no read sub-task » | Modify |
| `tests/tracing/test_events_v2.py` | round-trip `RetagEvent` | Modify |

---

## Task 1 — Détecteur pur `_cross_role_unsatisfiable`

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (à côté de `_roster_gap`, ~l.34)
- Test: `tests/runtime/test_runner_build_sub_tasks.py`

**Interfaces:**
- Produces: `_cross_role_unsatisfiable(tags: set[str], agents: list[Agent]) -> bool` — `True` ssi tous les tags sont couverts par l'**union** du roster mais **aucun agent seul** ne les porte tous. `False` si un tag manque à l'union (= roster_gap, pas notre cas) ou si un agent unique couvre tout.

- [ ] **Step 1: Write the failing test**

Dans `tests/runtime/test_runner_build_sub_tasks.py`, ajouter (réutiliser les helpers de construction d'`Agent` du fichier ; sinon construire en clair) :

```python
from aaosa.core.agent import Agent
from aaosa.runtime.runner import _cross_role_unsatisfiable


def _agent(name, tags):
    return Agent(name=name, tags_with_elo={t: 1500 for t in tags}, system_prompt="x")


_ROSTER = [
    _agent("python-dev", ["python", "coding"]),
    _agent("tech-writer", ["writing", "documentation"]),
]


def test_cross_role_set_is_unsatisfiable():
    # couvert par l'union (python-dev + tech-writer) mais par aucun agent seul
    assert _cross_role_unsatisfiable({"writing", "python", "coding", "documentation"}, _ROSTER) is True


def test_single_role_subset_is_satisfiable():
    assert _cross_role_unsatisfiable({"python", "coding"}, _ROSTER) is False
    assert _cross_role_unsatisfiable({"writing", "documentation"}, _ROSTER) is False


def test_tag_absent_from_union_is_not_our_case():
    # 'rust' n'existe nulle part → roster_gap, pas cross-rôle
    assert _cross_role_unsatisfiable({"python", "rust"}, _ROSTER) is False


def test_single_agent_covering_all_is_satisfiable():
    fullstack = [_agent("fs", ["python", "coding", "writing", "documentation"])]
    assert _cross_role_unsatisfiable({"writing", "python", "coding", "documentation"}, fullstack) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py::test_cross_role_set_is_unsatisfiable -v`
Expected: FAIL — `ImportError: cannot import name '_cross_role_unsatisfiable'`.

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/runner.py`, sous `_roster_gap` :

```python
def _cross_role_unsatisfiable(tags: set[str], agents: list[Agent]) -> bool:
    """Vrai ssi l'AND-set `tags` est couvert par l'UNION du roster mais par AUCUN
    agent seul. C'est un défaut de tagging (sur-couverture cross-rôle), distinct du
    roster_gap (tag absent de l'union). Pur, sans LLM, sans ELO (présence de tag
    seulement, comme _roster_gap). Re-diviser un tel set est futile."""
    union = {tag for a in agents for tag in a.tags_with_elo}
    if not tags <= union:
        return False  # un tag manque à l'union → roster_gap, pas notre cas
    return not any(tags <= set(a.tags_with_elo) for a in agents)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py -v -k cross_role or satisfiable or absent_from_union`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_runner_build_sub_tasks.py
git commit -m "feat(runner): detecteur pur _cross_role_unsatisfiable (verrou v24)"
```

---

## Task 2 — `RetagEvent` d'observabilité

**Files:**
- Modify: `src/aaosa/tracing/events.py` (nouvel event + Union, ~l.127 / l.135)
- Test: `tests/tracing/test_events_v2.py`

**Interfaces:**
- Produces: `RetagEvent(_BaseEvent)` avec `type: Literal["retag"]`, `original_tags: list[str]`, `retagged_tags: list[str] | None`, `resolved: bool` (True = re-tag a produit un set single-rôle satisfiable ; False = re-tag échoué → clean-crash). Ajouté à l'union `ClaimEvent`.

- [ ] **Step 1: Write the failing test**

Dans `tests/tracing/test_events_v2.py` :

```python
from aaosa.tracing.events import RetagEvent


def test_retag_event_roundtrip():
    e = RetagEvent(
        session_id="s1", task_id="t1",
        original_tags=["coding", "documentation", "python", "writing"],
        retagged_tags=["coding", "python"],
        resolved=True,
    )
    assert e.type == "retag"
    dumped = e.model_dump()
    assert dumped["resolved"] is True
    assert dumped["retagged_tags"] == ["coding", "python"]


def test_retag_event_unresolved_has_null_retagged():
    e = RetagEvent(
        session_id="s1", task_id="t1",
        original_tags=["coding", "documentation", "python", "writing"],
        retagged_tags=None, resolved=False,
    )
    assert e.resolved is False
    assert e.retagged_tags is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py::test_retag_event_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'RetagEvent'`.

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/tracing/events.py`, après `DividerCycleEvent` (~l.133) :

```python
class RetagEvent(_BaseEvent):
    type: Literal["retag"] = "retag"
    original_tags: list[str]               # set cross-rôle détecté (trié)
    retagged_tags: list[str] | None = None  # set après re-tag (None si re-tag échoué)
    resolved: bool                          # True = re-tag single-rôle satisfiable ; False = clean-crash
```

Puis ajouter `RetagEvent,` dans l'union `ClaimEvent` (~l.151, après `DividerCycleEvent,`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v -k retag`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/events.py tests/tracing/test_events_v2.py
git commit -m "feat(tracing): RetagEvent (observabilite re-tag cross-role v24)"
```

---

## Task 3 — Tagger : `unsatisfiable_hint` + prompt durci + `UnsatisfiableTagSetError`

**Files:**
- Modify: `src/aaosa/runtime/tagger.py`
- Test: `tests/runtime/test_tagger.py`

**Interfaces:**
- Consumes: rien des tâches précédentes.
- Produces:
  - `Tagger.tag(description, agents, provider, model=None, unsatisfiable_hint: set[str] | None = None) -> set[str]` — param optionnel ; quand fourni, le prompt nomme le set précédent et exige un sous-ensemble single-rôle.
  - `UnsatisfiableTagSetError(Exception)` — levée par `build_sub_tasks` (Task 4) ; définie ici à côté de `EmptyTaggingError`. Porte `description: str` et `tags: set[str]`.

- [ ] **Step 1: Write the failing test**

Dans `tests/runtime/test_tagger.py` (le fichier utilise un provider factice ; calquer le style existant pour capter le `messages` passé à `provider.parse`) :

```python
from aaosa.runtime.tagger import Tagger, UnsatisfiableTagSetError, TagSet


class _CaptureProvider:
    def __init__(self, tags):
        self._tags = tags
        self.last_messages = None

    def parse(self, messages, schema, temperature=0.0, model=None):
        self.last_messages = messages
        return TagSet(tags=self._tags)


def _agents():
    from aaosa.core.agent import Agent
    return [
        Agent(name="python-dev", tags_with_elo={"python": 1500, "coding": 1500}, system_prompt="x"),
        Agent(name="tech-writer", tags_with_elo={"writing": 1500, "documentation": 1500}, system_prompt="x"),
    ]


def test_unsatisfiable_hint_named_in_prompt():
    prov = _CaptureProvider(["python", "coding"])
    tagger = Tagger(system_prompt="sys")
    tagger.tag("Write a helper function", _agents(), prov,
               unsatisfiable_hint={"writing", "python", "coding", "documentation"})
    user_msg = prov.last_messages[-1]["content"]
    # le set fautif est nommé et l'instruction single-rôle présente
    assert "documentation" in user_msg and "python" in user_msg
    assert "single role" in user_msg.lower() or "one role" in user_msg.lower()


def test_no_hint_keeps_prompt_clean():
    prov = _CaptureProvider(["python", "coding"])
    tagger = Tagger(system_prompt="sys")
    tagger.tag("Write a helper function", _agents(), prov)
    user_msg = prov.last_messages[-1]["content"]
    assert "previous tag set" not in user_msg.lower()


def test_unsatisfiable_error_carries_payload():
    err = UnsatisfiableTagSetError("Write a helper", {"writing", "python"})
    assert err.description == "Write a helper"
    assert err.tags == {"writing", "python"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_tagger.py::test_unsatisfiable_hint_named_in_prompt -v`
Expected: FAIL — `ImportError: cannot import name 'UnsatisfiableTagSetError'` (ou TypeError sur `unsatisfiable_hint`).

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/tagger.py` :

a) Sous `EmptyTaggingError` :

```python
class UnsatisfiableTagSetError(Exception):
    """Re-tag d'une sous-spec cross-rôle resté cross-rôle (aucun agent unique ne le
    couvre). Clean-crash géré par _divide_and_recover (comme EmptyTaggingError)."""

    def __init__(self, description: str, tags: set[str]) -> None:
        super().__init__(f"unsatisfiable cross-role tag set for: {description!r} -> {sorted(tags)}")
        self.description = description
        self.tags = tags
```

b) Durcir `_build_prompt` (le bloc d'instructions) — préciser produce-vs-describe, et accepter le hint. Remplacer la signature et le corps :

```python
    def _build_prompt(
        self, description: str, agents: list[Agent], unsatisfiable_hint: set[str] | None = None
    ) -> str:
        bundles = sorted({tuple(sorted(a.tags_with_elo)) for a in agents})
        bundle_lines = "\n".join(f"  - {', '.join(b)}" for b in bundles)
        hint = ""
        if unsatisfiable_hint:
            named = ", ".join(sorted(unsatisfiable_hint))
            hint = (
                f"\n\nATTENTION — your previous tag set ({named}) spanned MULTIPLE role "
                "lines, so no single agent can hold it and the task is unassignable. "
                "Return a subset that belongs to EXACTLY ONE role line above. Producing "
                "code is one role; describing or documenting code is a different role — "
                "never combine them."
            )
        return (
            "Available agent tags (reference vocabulary — not exhaustive), grouped\n"
            "by role — each line is the tag set of one existing role:\n"
            f"{bundle_lines}\n\n"
            "Name the capabilities (tags) this task requires to be done well.\n"
            "The tags are an AND-filter: a single agent must hold ALL of them to take\n"
            "the task. Pick the line above whose role is best suited to do the work and\n"
            "return its 1-2 most relevant tags. Return tags from a SINGLE role line —\n"
            "never mix lines. Writing or implementing code is one role; describing or\n"
            "documenting it is another — a task that produces a deliverable needs only\n"
            "the doer's role, not every capability it touches.\n"
            "If the truly required capability appears on no line, name it even though it\n"
            "is absent from the roster — do not force-fit. Return at least one tag.\n\n"
            f"Task: {description}"
            f"{hint}"
        )
```

c) Propager le param dans `tag` :

```python
    def tag(self, description: str, agents: list[Agent], provider: LLMProvider,
            model: str | None = None, unsatisfiable_hint: set[str] | None = None) -> set[str]:
        prompt = self._build_prompt(description, agents, unsatisfiable_hint)
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            schema=TagSet,
            temperature=0.0,
            model=model,
        )
        if parsed is None:
            return set()
        return {
            piece
            for t in parsed.tags
            for piece in _TAG_SEPARATORS.split(t.strip())
            if piece
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_tagger.py -v`
Expected: PASS (nouveaux + existants inchangés — vérifier que le durcissement n'a pas cassé les assertions de prompt existantes ; ajuster les anciennes assertions si elles testaient le wording exact).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/tagger.py tests/runtime/test_tagger.py
git commit -m "feat(tagger): unsatisfiable_hint + prompt single-role + UnsatisfiableTagSetError (v24)"
```

---

## Task 4 — `build_sub_tasks` : re-tag cross-rôle + clean-crash + anti-récursion

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (`build_sub_tasks` ~l.222 ; import `UnsatisfiableTagSetError` ; `except` dans `_divide_and_recover` ~l.357)
- Test: `tests/runtime/test_runner_build_sub_tasks.py`

**Interfaces:**
- Consumes: `_cross_role_unsatisfiable` (Task 1), `RetagEvent` (Task 2), `Tagger.tag(..., unsatisfiable_hint=...)` + `UnsatisfiableTagSetError` (Task 3).
- Produces: `build_sub_tasks` re-tague une sous-spec cross-rôle une fois ; succès → Task single-rôle ; échec → `UnsatisfiableTagSetError`. `_divide_and_recover` mappe cette erreur sur `DispatchResult(execution_failed, reason="unsatisfiable cross-role tag set")`.

- [ ] **Step 1: Write the failing test**

Dans `tests/runtime/test_runner_build_sub_tasks.py` (calquer la fixture `ctx`/tagger factice du fichier). Un tagger factice qui rend cross-rôle au 1er appel, single-rôle au 2e (présence de `unsatisfiable_hint`) :

```python
import pytest
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks
from aaosa.runtime.tagger import UnsatisfiableTagSetError


class _ScriptedTagger:
    """1er appel (hint=None) → cross-rôle ; 2e appel (hint set) → `recovered`."""
    def __init__(self, first, recovered):
        self.first, self.recovered = first, recovered
        self.calls = []

    def tag(self, description, agents, provider, model=None, unsatisfiable_hint=None):
        self.calls.append(unsatisfiable_hint)
        return set(self.recovered) if unsatisfiable_hint else set(self.first)


def test_cross_role_subspec_is_retagged_single_role(make_ctx):
    # make_ctx : helper du fichier qui fabrique un RunContext avec roster python-dev/tech-writer
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"python", "coding"},
    )
    ctx = make_ctx(tagger=tagger)
    parent = _parent_task()  # helper existant du fichier
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper validate_verdict"),
    ])
    subs = build_sub_tasks(parent, division, ctx)
    assert set(subs[0].required_tags) == {"python", "coding"}  # re-tagué single-rôle
    assert tagger.calls == [None, {"writing", "python", "coding", "documentation"}]  # 2 appels


def test_cross_role_unrecoverable_raises(make_ctx):
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"writing", "python", "coding", "documentation"},  # re-tag reste cross-rôle
    )
    ctx = make_ctx(tagger=tagger)
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper"),
    ])
    with pytest.raises(UnsatisfiableTagSetError):
        build_sub_tasks(_parent_task(), division, ctx)
```

> Note : si le fichier n'expose pas `make_ctx`/`_parent_task`, les définir en haut du fichier (RunContext minimal : agents python-dev/tech-writer, divider/aggregator factices non appelés ici, tracer=None ou un tracer-espion qui collecte `emit`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py::test_cross_role_subspec_is_retagged_single_role -v`
Expected: FAIL — pas de re-tag (les tags restent cross-rôle), `tagger.calls == [None]`.

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/runner.py` :

a) Import (en tête, avec les imports tagger existants) :

```python
from aaosa.runtime.tagger import EmptyTaggingError, UnsatisfiableTagSetError
from aaosa.tracing.events import RetagEvent  # ajouter à l'import events existant
```

b) Dans `build_sub_tasks`, remplacer la boucle de tagging (~l.231-241) :

```python
    for i, spec in enumerate(division.sub_tasks):
        tags = ctx.tagger.tag(spec.description, ctx.agents, tprov, model=tmodel)
        if not tags:
            raise EmptyTaggingError(spec.description)
        if _cross_role_unsatisfiable(tags, ctx.agents):
            original = tags
            tags = ctx.tagger.tag(
                spec.description, ctx.agents, tprov, model=tmodel,
                unsatisfiable_hint=original,
            )
            resolved = bool(tags) and not _cross_role_unsatisfiable(tags, ctx.agents)
            if ctx.tracer is not None:
                ctx.tracer.emit(RetagEvent(
                    session_id=ctx.tracer.session_id,
                    task_id=parent_task.id,
                    original_tags=sorted(original),
                    retagged_tags=sorted(tags) if tags else None,
                    resolved=resolved,
                ))
            if not resolved:
                raise UnsatisfiableTagSetError(spec.description, tags)
        sub_tasks.append(Task(
            description=spec.description,
            required_tags={t: DEFAULT_REQUIRED_ELO for t in tags},
            parent_task_id=parent_task.id,
            order_index=i,
            context=spec.context,
        ))
```

c) Dans `_divide_and_recover`, élargir l'except (~l.356-361) :

```python
    try:
        sub_tasks = build_sub_tasks(task, division, ctx)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="tagging produced no tags",
        )
    except UnsatisfiableTagSetError:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="unsatisfiable cross-role tag set",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py -v`
Expected: PASS (re-tag + raise + détecteur Task 1).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_runner_build_sub_tasks.py
git commit -m "feat(runner): re-tag single-role des sous-specs cross-role (verrou v24)"
```

---

## Task 5 — Divider : pas de sous-tâche « read/understand » fantôme

**Files:**
- Modify: `src/aaosa/runtime/divider.py` (`_build_divide_prompt` ~l.121-139)
- Test: `tests/runtime/test_divider.py`

**Interfaces:**
- Consumes: rien.
- Produces: prompt divider portant une règle explicite « reading existing code is an execution-time tool call, not a sub-task ».

> Note : le comportement réel (le LLM n'émet plus de sous-tâche « read ») n'est vérifiable qu'au **smoke LLM-réel** (review matin Quentin). Ici on verrouille le **contenu du prompt** par assertion déterministe (pattern existant des tests de prompt).

- [ ] **Step 1: Write the failing test**

Dans `tests/runtime/test_divider.py` :

```python
from aaosa.runtime.divider import TaskDivider
from aaosa.schemas.task import Task


def test_divide_prompt_forbids_read_subtask():
    d = TaskDivider(system_prompt="sys")
    task = Task(description="Read solve.py then write a helper", required_tags={"coding": 30})
    prompt = d._build_divide_prompt(task, None, None)
    low = prompt.lower()
    assert "tool" in low and ("not a sub-task" in low or "not a deliverable" in low)
    assert "read" in low  # la règle nomme explicitement la lecture
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_divider.py::test_divide_prompt_forbids_read_subtask -v`
Expected: FAIL — le prompt actuel ne mentionne ni `tool` ni `not a sub-task`.

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/divider.py::_build_divide_prompt`, insérer après le bloc atomic (avant `f"Task: {task.description}"`), dans la chaîne retournée :

```python
            "A task is atomic ONLY when it is a single capability producing a single\n"
            "deliverable. If it chains multiple distinct deliverables or capabilities\n"
            "(e.g. write code AND then document it, implement a feature AND test it),\n"
            "it is NOT atomic, even when phrased as one sentence.\n"
            "Reading, analysing or understanding existing code is NOT a sub-task and NOT\n"
            "a deliverable: the specialist does it at execution time with its own tools.\n"
            "Never emit a 'read/understand the file' sub-task — go straight to the\n"
            "deliverables (e.g. the code, the documentation).\n"
            "If the task is atomic, set is_atomic=true and return no sub-tasks.\n"
            # … (reste inchangé)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_divider.py -v`
Expected: PASS (nouveau + existants).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/divider.py tests/runtime/test_divider.py
git commit -m "feat(divider): interdit la sous-tache read/understand fantome (v24)"
```

---

## Task 6 — Régression intégrée + suite complète

**Files:**
- Test: `tests/runtime/test_runner_build_sub_tasks.py` (régression anti-récursion bout-en-bout, tagger mocké)

- [ ] **Step 1: Write the failing test (déjà vert si Tasks 1-4 OK — sert de garde anti-régression)**

```python
def test_cross_role_does_not_trigger_redivision(make_ctx):
    """La sous-spec 'Write…' cross-rôle est re-taguée single-rôle AU BUILD →
    elle ne reviendra jamais 'unassigned' → zéro re-division (verrou v24)."""
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"python", "coding"},
    )
    ctx = make_ctx(tagger=tagger)
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper validate_verdict"),
    ])
    subs = build_sub_tasks(_parent_task(), division, ctx)
    # single-rôle satisfiable → un agent unique (python-dev) couvre
    from aaosa.runtime.runner import _cross_role_unsatisfiable
    assert _cross_role_unsatisfiable(set(subs[0].required_tags), ctx.agents) is False
```

- [ ] **Step 2: Run the FULL suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (la base était à 1242 tests post-PR #6 ; +~12 nouveaux). Aucun test V1/V2 cassé (rétrocompat).

- [ ] **Step 3: Commit**

```bash
git add tests/runtime/test_runner_build_sub_tasks.py
git commit -m "test(runner): regression anti-recursion cross-role (v24)"
```

---

## DoD & validation finale

- **DoD nuit-compatible** : Tasks 1-6 = backend pur + prompts, suite verte. Aucun appel LLM réel.
- **DoD LLM-réel (review matin Quentin, jamais la nuit)** : rejouer le smoke `dev` —
  `python <AIOS>/scripts/aaosa_bridge/solve.py --ministere dev --task "Lis solve.py, écris un helper validate_verdict, documente-le." --context-dir <solve.py seul>` —
  et vérifier sur `trace.jsonl` : **1 seule** `task_divided` (`code → doc`), **0** sous-tâche « Read », **0** doc redondante de `solve.py`, **≤ 3** `executed`, et idéalement **0** `unassigned` / **≥1** `retag resolved=true` si le tagger sur-couvre encore au 1er pass.
- **Intégration** : `gh pr create` (base `master`), CI verte, squash-merge, bump `pyproject.toml` patch (95c) si justifié, tag auto.

## Self-Review (faite)

- **Couverture spec** : Fix 1 = Task 5 ; Fix 2 = Task 3 ; Fix 3 = Tasks 1+4 ; observabilité = Task 2 ; décision §4 (option A re-tag + fail-loud) = Task 4 ; invariants/rétrocompat = Global Constraints + Task 6.
- **Placeholders** : aucun — code complet à chaque step.
- **Cohérence des types** : `_cross_role_unsatisfiable(tags: set[str], agents)` identique Tasks 1/4/6 ; `Tagger.tag(..., unsatisfiable_hint=)` identique Tasks 3/4 ; `RetagEvent(original_tags, retagged_tags, resolved)` identique Tasks 2/4 ; `UnsatisfiableTagSetError(description, tags)` identique Tasks 3/4.
- **Point d'attention exécution** : `make_ctx`/`_parent_task` peuvent ne pas exister dans `test_runner_build_sub_tasks.py` — la 1re tâche qui en a besoin (Task 4) les définit en tête de fichier (RunContext minimal, tracer-espion).
