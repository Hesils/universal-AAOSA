# D3 — Diagnostic d'échec inline (triage runtime) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quand une tâche échoue au QA (`qa_fail`), diagnostiquer la cause (agent / evaluator / task_spec / unattributed) par un appel LLM unique, et router déterministiquement vers le recovery adapté — le tout inline dans `run_with_recovery`, sans toucher au triage batch B2/B3.

**Architecture:** D3 ajoute un chemin de recovery **parallèle à D1**. D1 récupère sur `unassigned` (division émergente) ; D3 récupère sur `qa_fail` (diagnostic + route). Les deux passent par le même helper de division (`_divide_and_recover`) extrait du code D1 existant. Un nouveau champ premier-rang `Task.context` porte le contexte domaine, consommé par l'agent, l'evaluator adaptatif, et le diagnostic ; il sert aussi de canal pour injecter les consignes de correction lors d'un retry. La récursion `task_spec` réutilise D1 en lui passant un `FailureContext`.

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38 (structured output `beta.chat.completions.parse` + fallback JSON), pytest 9 / pytest-asyncio. Venv obligatoire : `.venv\Scripts\python`.

---

## Écarts spec ↔ code (décisions verrouillées dans ce plan)

La spec `2026-06-05-v3-d3-diagnostic-inline-design.md` décrit certaines signatures qui ne correspondent pas au code réel sur `master`. Ce plan suit le **code réel** :

1. **Divider** : le code réel a `TaskDivider.divide(task, client) -> DivisionResult` (structurel, sans tags, sans tracer). La spec §4.5 décrit `divide(...) -> list[Task]` — faux. Le `context` par sous-tâche est donc ajouté sur `SubTaskSpec` (sortie structurée du divider), et propagé en `Task.context` par `build_sub_tasks` (runner). `chained_context` / `failure_context` sont ajoutés à `divide` comme params kw optionnels qui enrichissent le prompt.
2. **`chained_context`** : il n'existe aucun registre tâche→id pour remonter `parent_task_id`. Il est donc **accumulé par la récursion** : `_divide_and_recover` passe `chained_context + [task]` à `run_chain`, qui le transmet à chaque enfant.
3. **Route `task_spec`** : §3 (divide → run_chain → aggregate) et §4.7 (récursion `run_with_recovery`) se contredisent. Ce plan suit **§3** via le helper partagé `_divide_and_recover(..., failure_context=fctx)`.
4. **`Task.context`** : `agent.execute` lit `task.context` avec **fallback** sur `task.metadata.get("context")` pour ne pas casser les 8 tâches démo V1/V2 (`demo/tasks.py`) qui utilisent encore `metadata`. Seule la démo V3 (`run_demo_v3`) est migrée vers `context=`.

---

## File Structure

**Créés :**
- `src/aaosa/qa/diagnostic.py` — `FailureContext`, `DiagnosticResult`, `diagnose_failure` (pur, 1 LLM call, fallback JSON, `None` sur échec).
- `tests/qa/test_diagnostic.py` — tests de `diagnose_failure`.
- `tests/runtime/test_d3_routes.py` — tests des routes D3 dans `run_with_recovery`.

**Modifiés :**
- `src/aaosa/schemas/task.py` — `+ context: str | None = None`.
- `src/aaosa/core/agent.py` — `_build_user_content` lit `task.context` (fallback metadata).
- `src/aaosa/qa/adaptive.py` — `_build_prompt` injecte `task.context`.
- `src/aaosa/runtime/divider.py` — `SubTaskSpec.context`, `divide(...)` + params, prompt enrichi.
- `src/aaosa/runtime/runner.py` — `build_sub_tasks` propage `context` ; `run_chain` threade `chained_context` ; `run_with_recovery` intercepte `QAFailure` et route ; helpers `_divide_and_recover`, `_route_diagnostic`, `_retry_agent`, `_qa_failed`.
- `src/aaosa/claiming/dispatch.py` — `DispatchResult` : statut `"qa_failed"` + champs `attribution`, `consignes_tried`.
- `src/aaosa/demo/run_demo_v3.py` — migration `metadata={"context":...}` → `context=...`.
- `tests/demo/test_run_demo_v3.py` — assertion migrée vers `task.context`.

**Ordre de dépendance :** schémas (Tasks 1, 5, 7) → consommateurs simples (Tasks 2-4) → divider (Tasks 8-9) → orchestration runner (Tasks 10-13).

---

## Task 1: `Task.context` — champ premier rang

**Files:**
- Modify: `src/aaosa/schemas/task.py`
- Test: `tests/schemas/test_task.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/schemas/test_task.py` :

```python
def test_context_defaults_to_none():
    task = Task(description="do x", required_tags={"python": 50})
    assert task.context is None


def test_context_can_be_set():
    task = Task(description="do x", required_tags={"python": 50}, context="HIPAA, PostgreSQL 14")
    assert task.context == "HIPAA, PostgreSQL 14"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/schemas/test_task.py -v -k context`
Expected: FAIL — `test_context_can_be_set` lève `ValidationError` (extra="forbid" rejette `context`).

- [ ] **Step 3: Add the field**

Dans `src/aaosa/schemas/task.py`, après le bloc V3-A3 (`required_outputs`), ajouter :

```python
    # V3 (D3) — contexte domaine focalisé sur cette tâche. None par défaut (rétrocompat).
    # Distinct de `description` (quoi faire) et `required_outputs` (ce qui précède).
    # Écrit par le caller (racine) ou le divider (nœuds internes) ; lu sans mutation.
    context: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/schemas/test_task.py -v -k context`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/schemas/task.py tests/schemas/test_task.py
git commit -m "feat(d3): Task.context — champ premier rang, None par defaut"
```

---

## Task 2: `agent.execute` lit `task.context`

**Files:**
- Modify: `src/aaosa/core/agent.py:78-88` (`_build_user_content`)
- Test: `tests/core/test_agent.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/core/test_agent.py` (le fichier a déjà un `Agent` de test ; sinon construire un Agent minimal sans tools) :

```python
def test_build_user_content_uses_task_context():
    agent = Agent(name="a", tags_with_elo={"python": 50}, system_prompt="sp")
    task = Task(description="do x", required_tags={"python": 50}, context="DOMAIN CTX")
    content = agent._build_user_content(task)
    assert "DOMAIN CTX" in content


def test_build_user_content_falls_back_to_metadata_context():
    agent = Agent(name="a", tags_with_elo={"python": 50}, system_prompt="sp")
    task = Task(description="do x", required_tags={"python": 50}, metadata={"context": "META CTX"})
    content = agent._build_user_content(task)
    assert "META CTX" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/core/test_agent.py -v -k user_content`
Expected: FAIL — `test_build_user_content_uses_task_context` ne trouve pas "DOMAIN CTX" (l'impl ne lit que `metadata`).

- [ ] **Step 3: Read context from `task.context` with metadata fallback**

Dans `src/aaosa/core/agent.py`, remplacer la première ligne de `_build_user_content` :

```python
    def _build_user_content(self, task: Task) -> str:
        context = task.context if task.context is not None else task.metadata.get("context", "")
```

(le reste de la méthode est inchangé.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/core/test_agent.py -v -k user_content`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/core/agent.py tests/core/test_agent.py
git commit -m "feat(d3): agent.execute lit task.context (fallback metadata)"
```

---

## Task 3: `build_llm_spec` injecte `task.context`

**Files:**
- Modify: `src/aaosa/qa/adaptive.py:111-130` (`_build_prompt`)
- Test: `tests/qa/test_adaptive.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/qa/test_adaptive.py` :

```python
from aaosa.qa.adaptive import _build_prompt


def test_build_prompt_includes_context_when_present():
    task = Task(description="audit auth", required_tags={"security": 80},
                context="HIPAA, secrets en clair interdits")
    prompt = _build_prompt(task)
    assert "HIPAA" in prompt


def test_build_prompt_omits_context_section_when_absent():
    task = Task(description="audit auth", required_tags={"security": 80})
    prompt = _build_prompt(task)
    assert "# Contexte" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v -k build_prompt_includes_context`
Expected: FAIL — "HIPAA" absent du prompt.

- [ ] **Step 3: Inject context into the prompt**

Dans `src/aaosa/qa/adaptive.py`, modifier `_build_prompt` pour insérer une section contexte conditionnelle juste après le bloc `# Tâche` :

```python
def _build_prompt(task: Task) -> str:
    predefined = ", ".join(sorted(CRITERIA_REGISTRY))
    context_section = f"# Contexte domaine\n{task.context}\n\n" if task.context else ""
    return (
        "Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.\n\n"
        f"# Tâche\n{task.description}\n\n"
        f"{context_section}"
        f"# Tags requis\n{', '.join(task.required_tags)}\n\n"
        f"# Critères prédéfinis disponibles (suggestions)\n{predefined}\n\n"
        "# Critère adaptatif libre\n"
        '"llm_check" accepte un param "description" (str) — utilise-le pour tout critère '
        "sémantique spécifique à cette tâche qui ne correspond à aucun critère prédéfini.\n"
        'Exemple : {"name": "llm_check", "params": {"description": "La réponse doit inclure '
        'des exemples de code avec explications"}, "weight": 1.5}\n\n'
        "# Règles\n"
        '- "non_empty" est ajouté automatiquement comme unique gate — ne le déclare pas\n'
        '- Ajouter "min_length" si la tâche attend une réponse détaillée\n'
        '- Utiliser "llm_check" pour des critères qualitatifs propres à cette tâche\n'
        '- Ajouter un judge (mode "rubric") si la tâche est complexe ou ambiguë\n'
        '- Tout nom hors de la liste prédéfinie ET hors "llm_check" sera ignoré\n'
        "- success_threshold entre 0.5 et 0.9 selon la criticité"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v -k build_prompt`
Expected: PASS (2 passed). Lancer aussi `.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v` pour vérifier la non-régression.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive.py
git commit -m "feat(d3): build_llm_spec injecte task.context dans le prompt"
```

---

## Task 4: Migrer la démo V3 vers `Task.context`

**Files:**
- Modify: `src/aaosa/demo/run_demo_v3.py:50-55` (construction de la tâche) et `:108` (SessionTaskRecord)
- Test: `tests/demo/test_run_demo_v3.py:8`

- [ ] **Step 1: Update the test to assert the new field**

Dans `tests/demo/test_run_demo_v3.py`, remplacer :

```python
    assert task.metadata.get("context")
```

par :

```python
    assert task.context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_demo_v3.py -v`
Expected: FAIL — `task.context` est `None` (la tâche utilise encore `metadata`).

- [ ] **Step 3: Migrate the task construction**

Dans `src/aaosa/demo/run_demo_v3.py`, remplacer `metadata={"context": _INCIDENT_CONTEXT},` (ligne ~54) par :

```python
        context=_INCIDENT_CONTEXT,
```

Et remplacer `required_tags=task.required_tags, context=task.metadata.get("context"),` (ligne ~108, dans le `SessionTaskRecord`) par :

```python
            required_tags=task.required_tags, context=task.context,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_demo_v3.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/demo/run_demo_v3.py tests/demo/test_run_demo_v3.py
git commit -m "feat(d3): migre la demo V3 vers Task.context"
```

---

## Task 5: Schémas `FailureContext` + `DiagnosticResult`

**Files:**
- Create: `src/aaosa/qa/diagnostic.py`
- Test: `tests/qa/test_diagnostic.py`

- [ ] **Step 1: Write the failing test**

Créer `tests/qa/test_diagnostic.py` :

```python
import pytest
from pydantic import ValidationError

from aaosa.qa.diagnostic import DiagnosticResult, FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import LLMMetadata, Output


def _output(content="bad") -> Output:
    return Output(task_id="t-1", agent_id="a-1", content=content,
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


def _qa_result() -> QAResult:
    return QAResult(task_id="t-1", agent_id="a-1", success=False, score=0.2,
                    reason="too short", criteria_results={"min_length": False})


def test_failure_context_carries_output_and_qa():
    fc = FailureContext(failed_output=_output(), qa_result=_qa_result(),
                        diagnostic_reason="ambiguous spec")
    assert fc.failed_output.content == "bad"
    assert fc.qa_result.success is False
    assert fc.diagnostic_reason == "ambiguous spec"


def test_diagnostic_result_accepts_known_attributions():
    for attr in ("agent", "evaluator", "task_spec", "unattributed"):
        DiagnosticResult(attribution=attr, reason="r")


def test_diagnostic_result_rejects_unknown_attribution():
    with pytest.raises(ValidationError):
        DiagnosticResult(attribution="weird", reason="r")


def test_diagnostic_result_consignes_optional():
    d = DiagnosticResult(attribution="task_spec", reason="r")
    assert d.consignes is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/qa/test_diagnostic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.qa.diagnostic'`.

- [ ] **Step 3: Create the schemas**

Créer `src/aaosa/qa/diagnostic.py` (les schémas seulement ; `diagnose_failure` arrive en Task 6) :

```python
"""Diagnostic d'échec inline (D3) — chemin parallèle au triage batch B2/B3.

`diagnose_failure` classe un qa_fail live en agent / evaluator / task_spec /
unattributed et propose des consignes courtes pour un retry. Pur : prend des
données, retourne un DiagnosticResult (ou None sur échec LLM). Aucun accès au
runtime, au store, ni à l'historique. Indépendant de qa/triage.py (B2).
"""

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class FailureContext(BaseModel):
    """Contexte d'un échec, passé au divider sur la route task_spec (D3)."""
    model_config = ConfigDict(extra="forbid")
    failed_output: Output
    qa_result: QAResult
    diagnostic_reason: str


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    consignes: str | None = None   # présent si l'agent peut réessayer avec des clarifications
    reason: str                    # alimente FailureContext.diagnostic_reason
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/qa/test_diagnostic.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/diagnostic.py tests/qa/test_diagnostic.py
git commit -m "feat(d3): schemas FailureContext + DiagnosticResult"
```

---

## Task 6: `diagnose_failure` (1 LLM call + fallback JSON)

**Files:**
- Modify: `src/aaosa/qa/diagnostic.py`
- Test: `tests/qa/test_diagnostic.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/qa/test_diagnostic.py` (en réutilisant `_output`/`_qa_result` déjà définis) :

```python
from types import SimpleNamespace

from aaosa.qa.diagnostic import diagnose_failure
from aaosa.schemas.task import Task


def _task() -> Task:
    return Task(description="do the thing", required_tags={"python": 60})


def _parse_client(attribution="agent", consignes="be concise", reason="r"):
    result = DiagnosticResult(attribution=attribution, consignes=consignes, reason=reason)
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def _json_fallback_client(attribution="task_spec", reason="ambiguous"):
    def parse(**kw):
        raise RuntimeError("structured output unavailable")

    def create(**kw):
        payload = json.dumps({"attribution": attribution, "consignes": None, "reason": reason})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def _exploding_client():
    def boom(**kw):
        raise RuntimeError("boom")
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=boom))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=boom)),
    )


def test_diagnose_structured_output_returns_result():
    out = diagnose_failure(_task(), _output(), _qa_result(), _parse_client(attribution="agent"))
    assert out.attribution == "agent"
    assert out.consignes == "be concise"


def test_diagnose_json_fallback_when_structured_fails():
    out = diagnose_failure(_task(), _output(), _qa_result(), _json_fallback_client("task_spec"))
    assert out.attribution == "task_spec"
    assert out.consignes is None


def test_diagnose_returns_none_on_unrecoverable_llm_failure():
    out = diagnose_failure(_task(), _output(), _qa_result(), _exploding_client())
    assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/qa/test_diagnostic.py -v -k diagnose`
Expected: FAIL — `ImportError: cannot import name 'diagnose_failure'`.

- [ ] **Step 3: Implement `diagnose_failure`**

Ajouter dans `src/aaosa/qa/diagnostic.py` (après les schémas) :

```python
def _build_diagnostic_prompt(task: Task, output: Output, qa_result: QAResult) -> str:
    failed = [name for name, ok in qa_result.criteria_results.items() if not ok]
    context_section = f"Contexte domaine:\n{task.context}\n\n" if task.context else ""
    return (
        "Une réponse d'agent vient d'échouer au QA sur un run live. Décide quoi faire "
        "MAINTENANT pour récupérer.\n\n"
        f"Description de la tâche:\n{task.description}\n\n"
        f"{context_section}"
        f"Réponse produite par l'agent:\n{output.content}\n\n"
        f"Verdict QA (score={qa_result.score:.2f}): {qa_result.reason}\n"
        f"Critères ratés: {', '.join(failed) or 'aucun critère scoré nommé'}\n\n"
        "Attribue la cause à exactement une valeur :\n"
        '- "agent": la réponse est objectivement faible, l\'agent peut réessayer avec '
        "des clarifications\n"
        '- "evaluator": les critères d\'évaluation sont inadaptés (trop stricts, mauvais '
        "critères) — la réponse est probablement correcte\n"
        '- "task_spec": la description de la tâche est ambiguë et doit être décomposée/clarifiée\n'
        '- "unattributed": cause indéterminée\n\n'
        'Si "agent" ou "evaluator", fournis des "consignes" courtes et actionnables que '
        "l'agent suivra à sa prochaine tentative. Sinon laisse consignes vide.\n"
        'Donne aussi un "reason" bref expliquant ton attribution.'
    )


def diagnose_failure(
    task: Task,
    output: Output,
    qa_result: QAResult,
    client: OpenAI,
) -> DiagnosticResult | None:
    """Diagnostique un qa_fail. Retourne None si le LLM échoue (caller → unattributed)."""
    prompt = _build_diagnostic_prompt(task, output, qa_result)

    # Structured output (SDK 2.x)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format=DiagnosticResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is not None:
            return parsed
    except Exception:
        pass  # structured output indisponible — fallback JSON

    # Fallback : completion brute + parse JSON (même pattern que triage_case / Agent.claim)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content or ""
        data = json.loads(raw)
        return DiagnosticResult(
            attribution=data["attribution"],
            consignes=data.get("consignes"),
            reason=data["reason"],
        )
    except Exception:
        return None  # diagnostic échoue → caller traite comme unattributed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/qa/test_diagnostic.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/diagnostic.py tests/qa/test_diagnostic.py
git commit -m "feat(d3): diagnose_failure — 1 LLM call, fallback JSON, None sur echec"
```

---

## Task 7: `DispatchResult` — statut `qa_failed` + champs D3

**Files:**
- Modify: `src/aaosa/claiming/dispatch.py:25-39`
- Test: `tests/claiming/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/claiming/test_dispatch.py` :

```python
def test_qa_failed_status_allows_none_agent_and_d3_fields():
    r = DispatchResult(
        status="qa_failed", agent_id=None, reason="qa failed after retry",
        attribution="agent", consignes_tried=True,
    )
    assert r.status == "qa_failed"
    assert r.attribution == "agent"
    assert r.consignes_tried is True


def test_d3_fields_default_to_none_and_false():
    r = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
    assert r.attribution is None
    assert r.consignes_tried is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/claiming/test_dispatch.py -v -k "qa_failed or d3_fields"`
Expected: FAIL — `ValidationError` : `qa_failed` n'est pas dans le `Literal` du statut, `attribution`/`consignes_tried` rejetés par `extra="forbid"`.

- [ ] **Step 3: Extend the schema**

Dans `src/aaosa/claiming/dispatch.py`, modifier la classe `DispatchResult`. Ajouter `"qa_failed"` au `Literal` du `status` et les deux champs D3 :

```python
class DispatchResult(BaseModel):
    """Result of task dispatch/claiming process.

    Attributes:
        status: Whether a task was assigned or remains unassigned.
        agent_id: The agent assigned to the task, or None if unassigned.
        reason: Explanation for the dispatch decision.
        all_claims: All claims received for this task.
        fit_scores: Fit scores for each agent (agent_id -> score).
        attribution: (D3) cause diagnostiquée d'un qa_fail, si applicable.
        consignes_tried: (D3) True si un retry avec consignes a été tenté.
    """

    status: Literal[
        "assigned", "unassigned", "dependency_failed",
        "execution_failed", "roster_gap", "qa_failed",
    ]
    agent_id: str | None
    reason: str
    all_claims: list[Claim] = Field(default_factory=list)
    fit_scores: dict[str, float] = Field(default_factory=dict)
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"] | None = None
    consignes_tried: bool = False

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def agent_id_matches_status(self) -> "DispatchResult":
        if self.status == "assigned" and self.agent_id is None:
            raise ValueError("agent_id must be set when status='assigned'")
        if self.status != "assigned" and self.agent_id is not None:
            raise ValueError(f"agent_id must be None when status={self.status!r}")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/claiming/test_dispatch.py -v`
Expected: PASS (tous les tests dispatch, y compris les 2 nouveaux).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/claiming/dispatch.py tests/claiming/test_dispatch.py
git commit -m "feat(d3): DispatchResult.qa_failed + attribution + consignes_tried"
```

---

## Task 8: `SubTaskSpec.context` + propagation par `build_sub_tasks`

**Files:**
- Modify: `src/aaosa/runtime/divider.py:7-10` (`SubTaskSpec`)
- Modify: `src/aaosa/runtime/runner.py:204-237` (`build_sub_tasks`)
- Test: `tests/runtime/test_runner_build_sub_tasks.py` (créer si absent ; sinon ajouter au fichier de tests `build_sub_tasks` existant)

- [ ] **Step 1: Write the failing test**

Ajouter (ou créer `tests/runtime/test_runner_build_sub_tasks.py`) :

```python
from types import SimpleNamespace

from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks
from aaosa.schemas.task import Task


class _StubTagger:
    def tag(self, description, agents, client):
        return ["python"]


def _ctx() -> RunContext:
    return RunContext(
        agents=[], client=SimpleNamespace(), divider=SimpleNamespace(),
        aggregator=SimpleNamespace(), tagger=_StubTagger(), tracer=None,
    )


def test_build_sub_tasks_propagates_context():
    parent = Task(description="parent", required_tags={"python": 50})
    division = DivisionResult(sub_tasks=[
        SubTaskSpec(description="sub A", context="focalisé A"),
        SubTaskSpec(description="sub B"),  # context None
    ])
    subs = build_sub_tasks(parent, division, _ctx())
    assert subs[0].context == "focalisé A"
    assert subs[1].context is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py -v -k propagates_context`
Expected: FAIL — `SubTaskSpec` n'accepte pas `context` (`extra="forbid"`).

- [ ] **Step 3: Add `context` to `SubTaskSpec` and propagate it**

Dans `src/aaosa/runtime/divider.py`, ajouter le champ à `SubTaskSpec` :

```python
class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    depends_on_indices: list[int] = Field(default_factory=list)
    context: str | None = None   # D3 — contexte distillé pour CETTE sous-tâche
```

Dans `src/aaosa/runtime/runner.py`, fonction `build_sub_tasks`, ajouter `context=spec.context` à la construction de chaque `Task` :

```python
        sub_tasks.append(Task(
            description=spec.description,
            required_tags={t: DEFAULT_REQUIRED_ELO for t in tags},
            parent_task_id=parent_task.id,
            order_index=i,
            context=spec.context,
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_build_sub_tasks.py -v`
Expected: PASS. Lancer aussi les tests divider/runner existants : `.venv\Scripts\python -m pytest tests/runtime -v` → tous verts.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/divider.py src/aaosa/runtime/runner.py tests/runtime/test_runner_build_sub_tasks.py
git commit -m "feat(d3): SubTaskSpec.context propage vers Task.context (build_sub_tasks)"
```

---

## Task 9: `divide()` — `chained_context` + `failure_context` dans le prompt

**Files:**
- Modify: `src/aaosa/runtime/divider.py:31-56` (`_build_divide_prompt`, `divide`)
- Test: `tests/runtime/test_divider.py` (créer si absent)

- [ ] **Step 1: Write the failing test**

Ajouter (ou créer `tests/runtime/test_divider.py`) :

```python
from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.runtime.divider import TaskDivider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _divider() -> TaskDivider:
    return TaskDivider(system_prompt="sp")


def _task() -> Task:
    return Task(description="ship the feature", required_tags={"python": 50})


def test_prompt_unchanged_without_optional_context():
    p = _divider()._build_divide_prompt(_task(), None, None)
    assert "ship the feature" in p
    assert "Contexte hérité" not in p
    assert "Échec précédent" not in p


def test_prompt_includes_chained_context():
    ancestor = Task(description="big incident triage", required_tags={"backend": 70})
    p = _divider()._build_divide_prompt(_task(), [ancestor], None)
    assert "big incident triage" in p
    assert "Contexte hérité" in p


def test_prompt_includes_failure_context():
    out = Output(task_id="t", agent_id="a", content="wrong answer",
                 llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))
    qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1,
                  reason="off-topic", criteria_results={})
    fc = FailureContext(failed_output=out, qa_result=qa, diagnostic_reason="spec ambiguë")
    p = _divider()._build_divide_prompt(_task(), None, fc)
    assert "Échec précédent" in p
    assert "spec ambiguë" in p
    assert "wrong answer" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_divider.py -v`
Expected: FAIL — `_build_divide_prompt` ne prend qu'un argument (`task`), `TypeError`.

- [ ] **Step 3: Extend `_build_divide_prompt` and `divide`**

Dans `src/aaosa/runtime/divider.py`, remplacer `_build_divide_prompt` et `divide`. Ajouter l'import de `FailureContext` en tête de fichier :

```python
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.qa.diagnostic import FailureContext
from aaosa.schemas.task import Task
```

Puis :

```python
    def _build_divide_prompt(
        self,
        task: Task,
        chained_context: list[Task] | None,
        failure_context: FailureContext | None,
    ) -> str:
        inherited = ""
        if chained_context:
            ancestors = "\n".join(f"- {t.description}" for t in chained_context)
            inherited = f"\n\nContexte hérité (tâches ancêtres, racine → parent):\n{ancestors}"

        own_context = f"\n\nContexte domaine de cette tâche:\n{task.context}" if task.context else ""

        failure = ""
        if failure_context is not None:
            failure = (
                "\n\nÉchec précédent à clarifier (la tâche a été jugée ambiguë):\n"
                f"- Diagnostic: {failure_context.diagnostic_reason}\n"
                f"- Verdict QA: {failure_context.qa_result.reason}\n"
                f"- Réponse produite (à désambiguïser):\n{failure_context.failed_output.content}"
            )

        return (
            "If the task is atomic (a single capability, not usefully decomposable),\n"
            "set is_atomic=true and return no sub-tasks.\n"
            "Otherwise set is_atomic=false and decompose it into ordered sub-tasks, each\n"
            "a description plus dependencies (0-based indices into your sub_tasks list).\n"
            "Do NOT assign tags — only describe the work and its ordering.\n"
            "For each sub-task, set `context`: the distilled domain context that THIS "
            "sub-task needs (from the inherited context below), focused — not a copy of "
            "the parent. Leave context null if nothing domain-specific applies.\n\n"
            f"Task: {task.description}"
            f"{own_context}"
            f"{inherited}"
            f"{failure}"
        )

    def divide(
        self,
        task: Task,
        client: OpenAI,
        chained_context: list[Task] | None = None,
        failure_context: FailureContext | None = None,
    ) -> "DivisionResult":
        """LLM call → DivisionResult (structurel, sans tags). Ne construit pas de Task,
        ne résout pas les deps, n'émet aucun event — c'est le runner (build_sub_tasks).

        chained_context / failure_context (D3) enrichissent le prompt et orientent la
        génération du `context` par sous-tâche. Le divider reste pur : il ne sait pas
        d'où viennent ces données ni qui les consomme."""
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(task, chained_context, failure_context)},
            ],
            response_format=DivisionResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
```

**Note import circulaire :** `divider.py` importe désormais `aaosa.qa.diagnostic`. `qa/diagnostic.py` importe `schemas.task`, `schemas.output`, `qa.protocol` — jamais `runtime.divider`. Pas de cycle. Vérifier à l'étape suivante via l'import des tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_divider.py -v`
Expected: PASS (3 passed). Vérifier qu'aucun import circulaire n'apparaît : `.venv\Scripts\python -c "import aaosa.runtime.divider"` → pas d'erreur.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/divider.py tests/runtime/test_divider.py
git commit -m "feat(d3): divide() accepte chained_context + failure_context"
```

---

## Task 10: `run_chain` threade `chained_context`

**Files:**
- Modify: `src/aaosa/runtime/runner.py:180-201` (`run_chain`) et `:284` (appel dans `run_with_recovery`)
- Test: `tests/runtime/test_run_chain.py` (ajouter au fichier existant ; sinon créer)

- [ ] **Step 1: Write the failing test**

Ce test vérifie que `chained_context` est transmis à chaque exécution de nœud. On stub `run_with_recovery` via monkeypatch pour capturer l'argument.

```python
from types import SimpleNamespace

import aaosa.runtime.runner as runner
from aaosa.runtime.context import RunContext
from aaosa.schemas.task import Task


def _ctx() -> RunContext:
    return RunContext(
        agents=[], client=SimpleNamespace(), divider=SimpleNamespace(),
        aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=None,
    )


def test_run_chain_forwards_chained_context(monkeypatch):
    seen = []

    def fake_recovery(task, ctx, depth=0, chained_context=None, failure_context=None):
        seen.append(chained_context)
        return None  # pas d'Output → rien dans outputs_by_id

    monkeypatch.setattr(runner, "run_with_recovery", fake_recovery)

    ancestor = Task(description="root", required_tags={"python": 50})
    sub = Task(description="child", required_tags={"python": 50})
    runner.run_chain([sub], _ctx(), depth=1, chained_context=[ancestor])

    assert seen == [[ancestor]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_chain.py -v -k forwards_chained_context`
Expected: FAIL — `run_chain` n'accepte pas `chained_context` (`TypeError`).

- [ ] **Step 3: Add the parameter and forward it**

Dans `src/aaosa/runtime/runner.py`, modifier la signature et l'appel récursif de `run_chain` :

```python
def run_chain(
    sub_tasks: list[Task],
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None = None,
) -> dict[str, Output]:
    """Exécute des sous-tâches ordonnées par leur DAG de dépendances (Kahn) et renvoie
    les outputs RÉUSSIS indexés par id de tâche (ordre d'insertion = ordre topologique).

    Recovery-aware (D1) : l'exécuteur par nœud est `run_with_recovery`. required_outputs
    des deps réussies injectés, input non muté (model_copy). chained_context (D3) est
    transmis tel quel à chaque nœud (déjà augmenté du parent par l'appelant)."""
    order = _topological_order(sub_tasks)
    outputs: dict[str, Output] = {}

    for task in order:
        unmet = [dep for dep in task.depends_on if dep not in outputs]
        if unmet:
            continue
        resolved = [outputs[dep] for dep in task.depends_on]
        task_to_run = task.model_copy(update={"required_outputs": resolved})
        result = run_with_recovery(task_to_run, ctx, depth, chained_context=chained_context)
        if isinstance(result, Output):
            outputs[task.id] = result

    return outputs
```

(L'appel depuis `run_with_recovery` est mis à jour en Task 11, dans `_divide_and_recover`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_chain.py -v -k forwards_chained_context`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_run_chain.py
git commit -m "feat(d3): run_chain threade chained_context vers chaque noeud"
```

---

## Task 11: Extraire `_divide_and_recover` (refactor, comportement D1 inchangé)

**Files:**
- Modify: `src/aaosa/runtime/runner.py:240-299` (`run_with_recovery`)
- Test: `tests/runtime/test_run_with_recovery.py` (les tests D1 existants doivent rester verts)

But : sortir le bloc « divide → build_sub_tasks → run_chain → sinks → aggregate » de `run_with_recovery` vers un helper réutilisable, sans changer le comportement de la route `unassigned`. C'est un refactor pur — les tests D1 existants sont le filet.

- [ ] **Step 1: Run the existing D1 tests to confirm green baseline**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery.py -v`
Expected: PASS (baseline D1). Noter le nombre de tests.

- [ ] **Step 2: Extract the helper**

Dans `src/aaosa/runtime/runner.py`, ajouter le helper `_divide_and_recover` et réécrire la fin de `run_with_recovery` (route `unassigned`) pour l'appeler. Ajouter les imports nécessaires en tête :

```python
from aaosa.qa.diagnostic import DiagnosticResult, FailureContext, diagnose_failure
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
```

Helper (placer juste avant `run_with_recovery`) :

```python
def _divide_and_recover(
    task: Task,
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None,
    failure_context: FailureContext | None,
    atomic_fallback: Output | DispatchResult | QAFailure,
) -> Output | DispatchResult | QAFailure:
    """Divise `task`, exécute le sous-DAG (run_chain), agrège les sinks (D2).

    Partagé par la route D1 (unassigned, failure_context=None) et la route D3
    task_spec (failure_context renseigné). `atomic_fallback` est renvoyé si le
    divider juge la tâche atomique ou si aucune sous-tâche n'aboutit."""
    if depth >= MAX_RECOVERY_DEPTH:
        return atomic_fallback

    try:
        division = ctx.divider.divide(
            task, ctx.client,
            chained_context=chained_context,
            failure_context=failure_context,
        )
    except Exception:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="divider raised an exception",
        )
    if division.is_atomic:
        return atomic_fallback

    try:
        sub_tasks = build_sub_tasks(task, division, ctx)
    except EmptyTaggingError:
        return DispatchResult(
            status="execution_failed", agent_id=None,
            reason="tagging produced no tags",
        )

    child_context = (chained_context or []) + [task]
    outputs_by_id = run_chain(sub_tasks, ctx, depth + 1, chained_context=child_context)
    if not outputs_by_id:
        return DispatchResult(
            status="unassigned", agent_id=None,
            reason="no sub-tasks recovered",
        )

    sinks = _sinks(sub_tasks, outputs_by_id)
    if len(sinks) == 1:
        return sinks[0]   # court-circuit : un seul résultat terminal, rien à synthétiser

    try:
        return ctx.aggregator.aggregate(task, sinks, ctx.client, ctx.tracer)
    except Exception:
        return sinks[-1]
```

Réécrire `run_with_recovery` pour déléguer la route `unassigned` au helper (le reste — roster gap, run_task — est inchangé) :

```python
def run_with_recovery(
    task: Task,
    ctx: RunContext,
    depth: int = 0,
    chained_context: list[Task] | None = None,
    failure_context: FailureContext | None = None,
) -> Output | DispatchResult | QAFailure:
    """Cœur récursif D1+D3. Tente la tâche à plat ; divise sur `unassigned` (D1) ou
    sur diagnostic `task_spec` (D3) ; route les autres qa_fail (D3). `task` est
    TOUJOURS taguée."""
    missing = _roster_gap(task, ctx.agents)
    if missing:
        if ctx.tracer is not None:
            ctx.tracer.emit(RosterGapEvent(
                session_id=ctx.tracer.session_id,
                task_id=task.id,
                missing_tags=sorted(missing),
            ))
        return DispatchResult(
            status="roster_gap", agent_id=None,
            reason=f"no agent covers required tags: {sorted(missing)}",
        )

    result = run_task(task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)

    if isinstance(result, DispatchResult) and result.status == "unassigned":
        return _divide_and_recover(
            task, ctx, depth, chained_context,
            failure_context=None, atomic_fallback=result,
        )

    return result
```

**Note :** l'interception du `QAFailure` (route D3) est ajoutée en Task 12 — ici on ne fait que le refactor + la signature étendue.

- [ ] **Step 3: Run the existing D1 tests to verify no regression**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery.py -v`
Expected: PASS — même nombre de tests qu'au Step 1. Le refactor préserve le comportement `unassigned`.

- [ ] **Step 4: Run the broader runtime suite**

Run: `.venv\Scripts\python -m pytest tests/runtime -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py
git commit -m "refactor(d3): extrait _divide_and_recover, run_with_recovery +params D3"
```

---

## Task 12: Routes D3 `agent` / `evaluator` / `unattributed`

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (`run_with_recovery` + helpers `_route_diagnostic`, `_retry_agent`, `_qa_failed`)
- Test: `tests/runtime/test_d3_routes.py` (créer)

- [ ] **Step 1: Write the failing tests**

Créer `tests/runtime/test_d3_routes.py`. On pilote le comportement en monkeypatchant `run_task` et `diagnose_failure` dans le module runner, et en stubbant l'evaluator.

```python
from types import SimpleNamespace

import aaosa.runtime.runner as runner
from aaosa.qa.diagnostic import DiagnosticResult
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.runtime.context import RunContext
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _task() -> Task:
    return Task(description="do x", required_tags={"python": 50})


def _output(content="answer") -> Output:
    return Output(task_id="t", agent_id="a", content=content,
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


def _qa_fail() -> QAFailure:
    qa = QAResult(task_id="t", agent_id="a", success=False, score=0.2,
                  reason="too short", criteria_results={"min_length": False})
    return QAFailure(task_id="t", agent_id="a", output=_output("bad"), qa_result=qa)


class _StubAgentRoster:
    """ctx.agents doit couvrir les tags requis pour passer le roster gap."""
    def __init__(self):
        self.tags_with_elo = {"python": 50}


def _ctx(evaluator=None) -> RunContext:
    return RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=SimpleNamespace(),
        aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=None, evaluator=evaluator,
    )


def test_route_agent_retry_succeeds(monkeypatch):
    # 1er run_task → qa_fail ; retry → Output
    calls = [_qa_fail(), _output("good")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="be precise", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "good"


def test_route_agent_retry_fails(monkeypatch):
    calls = [_qa_fail(), _qa_fail()]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="x", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "agent"
    assert out.consignes_tried is True


def test_route_evaluator_reeval_ok_returns_output(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes=None, reason="r"))
    good_qa = QAResult(task_id="t", agent_id="a", success=True, score=0.9, reason="ok", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: good_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "bad"   # l'output original passe avec le nouvel evaluator


def test_route_evaluator_reeval_ko_then_agent_retry_ok(monkeypatch):
    calls = [_qa_fail(), _output("recovered")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes="clarify", reason="r"))
    bad_qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="still bad", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "recovered"


def test_route_evaluator_reeval_ko_then_agent_retry_ko(monkeypatch):
    calls = [_qa_fail(), _qa_fail()]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes="clarify", reason="r"))
    bad_qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="bad", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "evaluator"
    assert out.consignes_tried is True


def test_route_unattributed_no_retry(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="unattributed", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "unattributed"
    assert out.consignes_tried is False


def test_route_diagnostic_none_treated_as_unattributed(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure", lambda *a, **k: None)
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "unattributed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_routes.py -v`
Expected: FAIL — `run_with_recovery` renvoie le `QAFailure` brut (pas encore d'interception D3).

- [ ] **Step 3: Add the diagnostic routing**

Dans `src/aaosa/runtime/runner.py`, ajouter l'interception du `QAFailure` dans `run_with_recovery` (juste avant le `return result` final) :

```python
    if isinstance(result, QAFailure):
        return _route_diagnostic(task, result, ctx, depth, chained_context)

    return result
```

Et ajouter les helpers (après `_divide_and_recover`) :

```python
def _qa_failed(task: Task, attribution: str, consignes_tried: bool) -> DispatchResult:
    return DispatchResult(
        status="qa_failed", agent_id=None,
        reason=f"qa failed (attribution={attribution})",
        attribution=attribution, consignes_tried=consignes_tried,
    )


def _retry_with_consignes(
    task: Task,
    consignes: str | None,
    ctx: RunContext,
    attribution: str,
) -> Output | DispatchResult | QAFailure:
    """Retry agent UNE fois, consignes injectées dans task.context. Output → succès ;
    sinon DispatchResult(qa_failed, consignes_tried=True)."""
    if consignes:
        base = task.context or ""
        new_context = f"{base}\n\n# Consignes de correction\n{consignes}".strip()
        retry_task = task.model_copy(update={"context": new_context})
    else:
        retry_task = task
    result = run_task(retry_task, ctx.agents, ctx.client, ctx.tracer, ctx.evaluator)
    if isinstance(result, Output):
        return result
    return _qa_failed(task, attribution=attribution, consignes_tried=True)


def _route_diagnostic(
    task: Task,
    failure: QAFailure,
    ctx: RunContext,
    depth: int,
    chained_context: list[Task] | None,
) -> Output | DispatchResult | QAFailure:
    diagnostic = diagnose_failure(task, failure.output, failure.qa_result, ctx.client)
    if diagnostic is None:
        return _qa_failed(task, attribution="unattributed", consignes_tried=False)

    if diagnostic.attribution == "agent":
        return _retry_with_consignes(task, diagnostic.consignes, ctx, attribution="agent")

    if diagnostic.attribution == "evaluator":
        new_evaluator = AdaptiveSpecEvaluator(ctx.client)
        qa2 = new_evaluator.evaluate(task, failure.output)
        if qa2.success:
            return failure.output   # l'output original passe avec le nouvel evaluator
        return _retry_with_consignes(task, diagnostic.consignes, ctx, attribution="evaluator")

    if diagnostic.attribution == "task_spec":
        failure_ctx = FailureContext(
            failed_output=failure.output,
            qa_result=failure.qa_result,
            diagnostic_reason=diagnostic.reason,
        )
        return _divide_and_recover(
            task, ctx, depth, chained_context,
            failure_context=failure_ctx,
            atomic_fallback=_qa_failed(task, attribution="task_spec", consignes_tried=False),
        )

    return _qa_failed(task, attribution="unattributed", consignes_tried=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_routes.py -v`
Expected: PASS (7 passed). Le test `task_spec` est couvert en Task 13.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_d3_routes.py
git commit -m "feat(d3): routes agent/evaluator/unattributed dans run_with_recovery"
```

---

## Task 13: Route D3 `task_spec` (récursion via D1 + terminaison)

**Files:**
- Test: `tests/runtime/test_d3_routes.py` (ajouter)
- Modify: `src/aaosa/runtime/runner.py` (uniquement si un ajustement de terminaison est nécessaire ; le code de Task 12 devrait déjà couvrir le cas)

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/runtime/test_d3_routes.py`. On vérifie que la route `task_spec` divise avec un `failure_context` et exécute le sous-DAG, puis que la profondeur max termine sans boucle infinie.

```python
from aaosa.runtime.divider import DivisionResult, SubTaskSpec


class _DividerStub:
    def __init__(self, division):
        self.division = division
        self.calls = []

    def divide(self, task, client, chained_context=None, failure_context=None):
        self.calls.append(failure_context)
        return self.division


class _AggStub:
    def aggregate(self, task, sinks, client, tracer=None):
        return Output(task_id=task.id, agent_id="aggregator", content="aggregated",
                      llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


class _TaggerStub:
    def tag(self, description, agents, client):
        return ["python"]


def test_route_task_spec_divides_with_failure_context(monkeypatch):
    # parent run_task → qa_fail ; diagnostic task_spec ; division en 2 sous-tâches
    # indépendantes qui réussissent → 2 sinks → agrégation.
    division = DivisionResult(sub_tasks=[
        SubTaskSpec(description="clarified part A"),
        SubTaskSpec(description="clarified part B"),
    ])
    divider = _DividerStub(division)

    def run_task_side_effect(task, agents, client, tracer, evaluator):
        if task.description == "do x":
            return _qa_fail()                      # parent échoue
        return _output(f"ok:{task.description}")   # sous-tâches réussissent

    monkeypatch.setattr(runner, "run_task", run_task_side_effect)
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="ambiguë"))

    ctx = RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx)

    assert isinstance(out, Output)
    assert out.content == "aggregated"
    # le divider a bien reçu un failure_context (pas None)
    assert divider.calls and divider.calls[0] is not None
    assert divider.calls[0].diagnostic_reason == "ambiguë"


def test_route_task_spec_atomic_returns_qa_failed(monkeypatch):
    # divider juge la tâche atomique → pas de division possible → qa_failed(task_spec)
    divider = _DividerStub(DivisionResult(is_atomic=True))
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="r"))
    ctx = RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx)
    assert out.status == "qa_failed"
    assert out.attribution == "task_spec"


def test_route_task_spec_terminates_at_max_depth(monkeypatch):
    # à depth >= MAX_RECOVERY_DEPTH, _divide_and_recover renvoie le fallback sans diviser
    divider = _DividerStub(DivisionResult(sub_tasks=[SubTaskSpec(description="sub")]))
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="r"))
    ctx = RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx, depth=runner.MAX_RECOVERY_DEPTH)
    assert out.status == "qa_failed"
    assert out.attribution == "task_spec"
    assert divider.calls == []   # jamais divisé
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_routes.py -v -k task_spec`
Expected: PASS si le code de Task 12 est correct (les helpers `_route_diagnostic` + `_divide_and_recover` couvrent déjà ces cas). Si un test échoue, c'est un signal de bug dans Task 12 — déboguer avec `superpowers:systematic-debugging`, corriger `runner.py`, et relancer.

- [ ] **Step 3: Verify the full runtime + qa suites**

Run: `.venv\Scripts\python -m pytest tests/runtime tests/qa tests/claiming -v`
Expected: PASS — aucune régression sur D1/D2/B2.

- [ ] **Step 4: Run the complete suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS — 761 tests existants + nouveaux tests D3 (≈ +20). Aucun échec.

- [ ] **Step 5: Commit**

```bash
git add tests/runtime/test_d3_routes.py src/aaosa/runtime/runner.py
git commit -m "test(d3): route task_spec (recursion D1 + terminaison max depth)"
```

---

## Self-Review — couverture spec

| Exigence spec | Task |
|---|---|
| §4.1 `FailureContext` | Task 5 |
| §4.2 `DiagnosticResult` | Task 5 |
| §4.3 `diagnose_failure` (structured + fallback + None) | Task 6 |
| §4.4 `Task.context` champ | Task 1 |
| §4.4 consommateur `agent.execute` | Task 2 |
| §4.4 consommateur `AdaptiveSpecEvaluator`/`build_llm_spec` | Task 3 |
| §4.4 consommateur `diagnose_failure` | Task 6 (`_build_diagnostic_prompt` lit `task.context`) |
| §4.4 migration V2c metadata→context (démo) | Task 4 |
| §4.5 `context` par sous-tâche | Task 8 |
| §4.5 `divide` + `chained_context`/`failure_context` | Task 9 |
| §4.5 distillation par sous-tâche (prompt) | Task 9 |
| §4.6 `DispatchResult` + champs | Task 7 |
| §4.7 orchestration `run_with_recovery` | Tasks 11-13 |
| §3 route agent (retry 1x) | Task 12 |
| §3 route evaluator (re-eval + retry) | Task 12 |
| §3 route task_spec (divide+chain+aggregate) | Task 13 |
| §3 route unattributed | Task 12 |
| §3 diagnostic None → unattributed | Task 12 |
| §7 terminaison récursion (max depth / roster_gap) | Tasks 11, 13 |

**Séparations strictes (§5) respectées :** B2/B3 non touchés ; `diagnose_failure` pur ; divider pur (données en entrée/sortie) ; `run_with_recovery` seul point d'orchestration ; récursion `task_spec` via D1 (`_divide_and_recover` partagé) ; `Task.context` = donnée (écrite par caller/divider, lue par agent/evaluator/diagnostic).

**Hors périmètre confirmé :** `execution_failed` (mécanique, inchangé) ; `unassigned` (D1) ; robustesse `build_llm_spec` (D4 — la route evaluator fait confiance au nouvel evaluator, contrainte documentée §6).

---

## Execution Handoff

Plan complet et sauvegardé dans `docs/superpowers/plans/2026-06-05-v3-d3-diagnostic-inline.md`. Deux options d'exécution :

1. **Subagent-Driven (recommandé)** — un subagent frais par task, review entre les tasks, itération rapide.
2. **Inline Execution** — exécution des tasks dans cette session via `executing-plans`, par lots avec checkpoints.

Quelle approche ?
