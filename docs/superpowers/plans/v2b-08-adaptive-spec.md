# V2b Subtask 08 — Sélection de critères adaptée à la tâche (stretch, déterministe)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 01 (noms de critères), 02 (EvaluatorSpec)_
_Blocking: 09 (demo peut l'utiliser)_

## Objectif

Implémenter `build_adaptive_spec(task) -> EvaluatorSpec` : un constructeur **déterministe** (aucun LLM) qui dérive un `EvaluatorSpec` depuis une `Task`. C'est le rapprochement concret de la vision V3 — en V3 un agent **remplace** cette fonction. Le seam est la signature `Task -> EvaluatorSpec`.

## Méthode

TDD strict.

## Règles déterministes

1. `non_empty` (gate) — toujours.
2. `references_tags` (scoré, weight 1.0) — toujours, `tags = required_tags` de la tâche (param par défaut → laisser `params={}`).
3. `min_length` (scoré, weight 1.0) — `min_chars = 50 * nombre de required_tags` (proxy de complexité).
4. **Judge ajouté SI** un `required_tag` a un ELO requis `>= ELO_EXPERT_MIN` (tâche à fort enjeu). Sinon pas de judge.
   - rubric = `["correctness", "completeness", "relevance"]`
   - mode = `"rubric"` (pas de référence à la construction)

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/adaptive.py` | CRÉER |
| `tests/qa/test_adaptive.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context

```python
# src/aaosa/schemas/elo.py (constantes existantes V1)
ELO_EXPERT_MIN = 85
ELO_EXPERT_MAX = 95
ELO_COMPETENT_MIN = 30
ELO_COMPETENT_MAX = 50
ELO_BASIC_MIN = 10
ELO_BASIC_MAX = 25
# EvaluatorSpec, CriterionSpec, JudgeSpec : voir qa/spec.py (subtask 02)
```

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_adaptive.py`.

```python
from aaosa.qa.adaptive import build_adaptive_spec
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.task import Task


def task_with(required_tags) -> Task:
    return Task(description="x", required_tags=required_tags)


class TestBuildAdaptiveSpec:
    def test_returns_evaluator_spec(self):
        spec = build_adaptive_spec(task_with({"python": 50}))
        assert isinstance(spec, EvaluatorSpec)

    def test_always_has_non_empty_gate(self):
        spec = build_adaptive_spec(task_with({"python": 50}))
        gates = [c for c in spec.criteria if c.gate]
        assert any(c.name == "non_empty" for c in gates)

    def test_always_has_references_tags(self):
        spec = build_adaptive_spec(task_with({"python": 50}))
        assert any(c.name == "references_tags" for c in spec.criteria)

    def test_min_length_scaled_by_tag_count(self):
        spec = build_adaptive_spec(task_with({"python": 50, "testing": 40, "docker": 30}))
        ml = next(c for c in spec.criteria if c.name == "min_length")
        assert ml.params["min_chars"] == 150  # 50 * 3

    def test_no_judge_for_low_elo(self):
        spec = build_adaptive_spec(task_with({"python": 50, "css": 40}))
        assert spec.judge is None

    def test_judge_added_for_expert_tag(self):
        spec = build_adaptive_spec(task_with({"python": 90}))  # >= 85
        assert spec.judge is not None
        assert spec.judge.mode == "rubric"
        assert "correctness" in spec.judge.rubric

    def test_judge_threshold_boundary(self):
        # exactly 85 → judge présent (>=)
        assert build_adaptive_spec(task_with({"x": 85})).judge is not None
        # 84 → pas de judge
        assert build_adaptive_spec(task_with({"x": 84})).judge is None
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/adaptive.py`.

```python
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.schemas.elo import ELO_EXPERT_MIN
from aaosa.schemas.task import Task


def build_adaptive_spec(task: Task) -> EvaluatorSpec:
    n_tags = len(task.required_tags)

    criteria = [
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="references_tags", weight=1.0),
        CriterionSpec(name="min_length", params={"min_chars": 50 * n_tags}, weight=1.0),
    ]

    judge = None
    if any(elo >= ELO_EXPERT_MIN for elo in task.required_tags.values()):
        judge = JudgeSpec(
            mode="rubric",
            rubric=["correctness", "completeness", "relevance"],
        )

    return EvaluatorSpec(criteria=criteria, judge=judge)
```

- [ ] **Step 3: Écrire `adaptive.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_adaptive.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive.py && git commit -m "feat(v2b): build_adaptive_spec (sélection de critères déterministe)"`

## Invariants

- Imports absolus.
- 100% déterministe — aucun appel LLM dans `build_adaptive_spec`.
- Seuil judge = `ELO_EXPERT_MIN` (85), comparaison `>=`.
- `min_chars = 50 * len(required_tags)`.
- Seam V3 : la signature `Task -> EvaluatorSpec` est le point de remplacement par un agent.
