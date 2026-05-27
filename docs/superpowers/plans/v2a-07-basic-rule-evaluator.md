# V2a Subtask 07 — BasicRuleEvaluator

_Statut: TODO_
_Depends on: subtask 02 (QAEvaluator Protocol, QAResult)_
_Blocking: subtask 09 (health check), subtask 10 (demo V2)_

## Objectif

Implementer `BasicRuleEvaluator`, un evaluateur QA deterministe pour la demo. Criteres simples : non-empty, min length (50 chars), references task tags. Satisfait le `QAEvaluator` Protocol.

## Methode

TDD strict : ecrire les tests d'abord, puis implementer.

## Fichiers a creer

| Fichier | Action |
|---|---|
| `src/aaosa/qa/rule_based.py` | CREER — BasicRuleEvaluator |
| `tests/qa/test_rule_based.py` | CREER — tests exhaustifs |

## Pre-requis

Les fichiers suivants doivent exister (subtask 02 completee) :
- `src/aaosa/qa/__init__.py`
- `src/aaosa/qa/protocol.py` — `QAResult`, `QAEvaluator` Protocol

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_rule_based.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — Schemas utilises

### `QAResult` (dans `src/aaosa/qa/protocol.py` — subtask 02)

```python
class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    success: bool
    score: float          # 0.0-1.0
    reason: str
    criteria_results: dict[str, bool]
```

### `QAEvaluator` Protocol (dans `src/aaosa/qa/protocol.py` — subtask 02)

```python
@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

### `Task` (dans `src/aaosa/schemas/task.py`)

```python
class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    required_tags: dict[str, int]
    acquirable_tags: dict[str, int] = Field(default_factory=dict)
    ...
```

### `Output` (dans `src/aaosa/schemas/output.py`)

```python
class Output(BaseModel):
    task_id: str
    agent_id: str
    content: str
    llm_metadata: LLMMetadata
    timestamp: datetime = ...
```

---

## Etape 1 — Tests (RED)

Creer `tests/qa/test_rule_based.py`.

### Helpers

```python
from aaosa.qa.rule_based import BasicRuleEvaluator
from aaosa.qa.protocol import QAResult, QAEvaluator
from aaosa.schemas.task import Task
from aaosa.schemas.output import Output, LLMMetadata


def make_task(required_tags: dict[str, int]) -> Task:
    return Task(description="Test task", required_tags=required_tags)

def make_output(task: Task, content: str) -> Output:
    return Output(
        task_id=task.id,
        agent_id="agent-1",
        content=content,
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10, tokens_out=5, latency_ms=100.0,
        ),
    )
```

### Tests — Protocol compliance

```python
class TestBasicRuleEvaluatorProtocol:
    def test_satisfies_qa_evaluator_protocol(self):
        evaluator = BasicRuleEvaluator()
        assert isinstance(evaluator, QAEvaluator)

    def test_evaluate_returns_qa_result(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "A" * 60 + " python related content")
        result = evaluator.evaluate(task, output)
        assert isinstance(result, QAResult)
```

### Tests — Critere non-empty

```python
class TestCriteriaNonEmpty:
    def test_empty_content_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.criteria_results["non_empty"] is False

    def test_non_empty_content_passes(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "A" * 60 + " python")
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["non_empty"] is True
```

### Tests — Critere min_length (50 chars)

```python
class TestCriteriaMinLength:
    def test_short_content_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "Too short python")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.criteria_results["min_length"] is False

    def test_exactly_50_chars_passes(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "python " + "x" * 43  # 50 chars total
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["min_length"] is True

    def test_49_chars_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "python " + "x" * 42  # 49 chars
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["min_length"] is False
```

### Tests — Critere references_tags

```python
class TestCriteriaReferencesTags:
    def test_content_references_all_tags(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50, "backend": 40})
        content = "This python backend solution is comprehensive and well-designed for the task"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is True

    def test_content_missing_tag(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50, "backend": 40})
        content = "This python solution is comprehensive and well-designed for the task at hand"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is False

    def test_case_insensitive_tag_matching(self):
        """Tag matching should be case-insensitive."""
        evaluator = BasicRuleEvaluator()
        task = make_task({"Python": 50})
        content = "This PYTHON solution is comprehensive and thorough for production use"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is True
```

### Tests — Score et success

```python
class TestScoreAndSuccess:
    def test_all_criteria_pass_score_1(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "This python solution covers everything needed for the implementation task"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is True
        assert result.score == 1.0

    def test_all_criteria_fail_score_0(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.score == 0.0

    def test_partial_criteria_score_between_0_and_1(self):
        """Score = nombre de criteres passes / nombre total de criteres."""
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        # non_empty: True, min_length: False, references_tags: True
        content = "python is great"  # 15 chars < 50
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is False
        passed = sum(1 for v in result.criteria_results.values() if v)
        total = len(result.criteria_results)
        assert result.score == pytest.approx(passed / total)

    def test_success_requires_all_criteria(self):
        """success=True only if ALL criteria pass."""
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        # Long enough, references tag, non-empty — all pass
        content = "python " + "x" * 50
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is True
        assert all(result.criteria_results.values())

    def test_result_ids_match(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "python " + "x" * 50)
        result = evaluator.evaluate(task, output)
        assert result.task_id == task.id
        assert result.agent_id == output.agent_id
```

---

## Etape 2 — Implementation (GREEN)

Creer `src/aaosa/qa/rule_based.py`.

```python
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class BasicRuleEvaluator:
    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria = {}

        # Criterion 1: non-empty
        criteria["non_empty"] = len(output.content) > 0

        # Criterion 2: min length (50 chars)
        criteria["min_length"] = len(output.content) >= 50

        # Criterion 3: references all required tags (case-insensitive)
        content_lower = output.content.lower()
        criteria["references_tags"] = all(
            tag.lower() in content_lower
            for tag in task.required_tags
        )

        passed = sum(1 for v in criteria.values() if v)
        total = len(criteria)
        score = passed / total if total > 0 else 0.0
        success = all(criteria.values())

        return QAResult(
            task_id=task.id,
            agent_id=output.agent_id,
            success=success,
            score=score,
            reason="All criteria met" if success else "Some criteria failed",
            criteria_results=criteria,
        )
```

Pas de `__init__` necessaire — la classe n'a pas d'etat. Elle satisfait le `QAEvaluator` Protocol par structural typing.

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/qa/test_rule_based.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- Import absolu uniquement
- `BasicRuleEvaluator` n'herite PAS de `QAEvaluator` — c'est du structural typing (duck typing)
- 3 criteres exactement : `non_empty`, `min_length`, `references_tags`
- `score = passed_criteria / total_criteria` (ratio simple)
- `success = True` seulement si TOUS les criteres passent
- Tag matching case-insensitive
- Min length = 50 chars (>=50, pas >50)
