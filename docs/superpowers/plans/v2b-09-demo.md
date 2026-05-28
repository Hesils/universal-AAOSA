# V2b Subtask 09 — Demo V2b (SpecEvaluator dans le pipeline)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 04 (SpecEvaluator/from_spec), 08 (build_adaptive_spec)_
_Blocking: —_

## Objectif

Mettre à jour `demo/run_demo.py` pour utiliser un `SpecEvaluator` construit via `build_adaptive_spec(task)` (un evaluator adapté par tâche) au lieu du `BasicRuleEvaluator` figé. Montre la couche evaluator composable de bout en bout. C'est l'équivalent V2b de la démo V2a.

## Méthode

TDD léger (la démo est de l'intégration). Tests : pipeline ne crash pas, gère Output / QAFailure / DispatchResult, snapshot ELO créé — via `run_task` monkeypatché (pas de LLM réel dans les tests). La validation LLM réelle se fait en lançant `run_demo()` manuellement.

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/demo/run_demo.py` | MODIFIER |
| `tests/demo/test_demo.py` | AJOUTER une classe `TestDemoV2b` (ne pas supprimer les tests V2a existants) |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/demo/test_demo.py -v
.venv\Scripts\python -m pytest tests/ -v
# Validation LLM réelle (manuel, nécessite OPENAI_API_KEY) :
.venv\Scripts\python -m aaosa.demo.run_demo
```

---

## Context — `run_demo.py` actuel (V2a)

```python
from pathlib import Path
from dotenv import load_dotenv
from aaosa.claiming.dispatch import DispatchResult
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.protocol import QAFailure
from aaosa.qa.rule_based import BasicRuleEvaluator
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.tracer import Tracer

def run_demo() -> None:
    load_dotenv()
    client = create_client()
    tracer = Tracer(session_id="demo")
    evaluator = BasicRuleEvaluator()
    ...
    for task in DEMO_TASKS:
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        ...
```

**Problème :** la V2a utilise **un seul** `evaluator` pour toutes les tâches. La V2b construit un evaluator **par tâche** via `build_adaptive_spec`. Comme `run_task` prend un seul `evaluator`, on le construit dans la boucle, par tâche.

---

## Étape 1 — Modifier `run_demo.py`

Remplacer l'évaluateur figé par un `SpecEvaluator` adaptatif par tâche.

```python
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
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    tracer = Tracer(session_id="demo")

    print("=== AAOSA Demo V2b ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        spec = build_adaptive_spec(task)
        evaluator = from_spec(spec, client=client)
        judge_note = " (+judge)" if spec.judge else ""
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: PASS){judge_note}")
        elif isinstance(result, QAFailure):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: FAIL - {result.qa_result.reason})")
        else:
            print(f"  -> Unassigned")
        print()

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== ELO Snapshot ===")
    snapshot_dir = Path("elo_snapshots")
    snapshot_dir.mkdir(exist_ok=True)
    path = save_snapshot(DEMO_AGENTS, snapshot_dir)
    print(f"Saved to {path}")


if __name__ == "__main__":
    run_demo()
```

- [ ] **Step 1: Modifier `run_demo.py`** comme ci-dessus

---

## Étape 2 — Tests (ajout `TestDemoV2b`)

Ajouter à `tests/demo/test_demo.py`. Monkeypatcher `run_task` et `create_client` dans le module `run_demo`, plus `save_snapshot` pour isoler le filesystem.

```python
import aaosa.demo.run_demo as demo_module
from aaosa.demo.run_demo import run_demo
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.schemas.output import Output, LLMMetadata


def _output_for(task, agent_id, content="x" * 80):
    return Output(
        task_id=task.id, agent_id=agent_id, content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestDemoV2b:
    def test_runs_without_crash(self, monkeypatch, tmp_path):
        from aaosa.demo.agents import DEMO_AGENTS
        a_id = DEMO_AGENTS[0].id
        monkeypatch.setattr(demo_module, "create_client", lambda: object())
        monkeypatch.setattr(demo_module, "run_task",
                            lambda task, *a, **k: _output_for(task, a_id))
        monkeypatch.setattr(demo_module, "save_snapshot", lambda agents, d: tmp_path / "latest.json")
        run_demo()   # ne doit pas lever

    def test_handles_qa_failure(self, monkeypatch, tmp_path):
        from aaosa.demo.agents import DEMO_AGENTS
        a_id = DEMO_AGENTS[0].id
        monkeypatch.setattr(demo_module, "create_client", lambda: object())
        # output vide → gate non_empty échoue → QAFailure
        monkeypatch.setattr(demo_module, "run_task",
                            lambda task, *a, **k: _output_for(task, a_id, content=""))
        monkeypatch.setattr(demo_module, "save_snapshot", lambda agents, d: tmp_path / "latest.json")
        run_demo()   # ne doit pas lever malgré les QAFailure
```

- [ ] **Step 2: Écrire les tests `TestDemoV2b`**
- [ ] **Step 3: RED puis GREEN** — `.venv\Scripts\python -m pytest tests/demo/test_demo.py -v`
- [ ] **Step 4: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 5: Validation LLM réelle (manuel)** — `.venv\Scripts\python -m aaosa.demo.run_demo` (nécessite `OPENAI_API_KEY`). Observer : verdicts QA par tâche, marqueur `(+judge)` sur les tâches expertes, snapshot ELO sauvegardé.
- [ ] **Step 6: Commit** — `git add src/aaosa/demo/run_demo.py tests/demo/test_demo.py && git commit -m "feat(v2b): demo bascule sur SpecEvaluator adaptatif par tâche"`

## Invariants

- Imports absolus. `run_task`, `create_client`, `save_snapshot` importés au niveau module (monkeypatchables).
- Un evaluator **par tâche** via `build_adaptive_spec` (pas un évaluateur global).
- Les tests V2a existants de `test_demo.py` ne sont pas supprimés.
- Aucun appel LLM réel dans la suite de tests (tout monkeypatché).
- La démo gère les 3 cas de retour : `Output`, `QAFailure`, `DispatchResult`.
