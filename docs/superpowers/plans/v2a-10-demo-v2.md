# V2a Subtask 10 — Demo V2 + Smoke Test

_Statut: TODO_
_Depends on: subtask 06 (formatter V2), subtask 07 (rule evaluator), subtask 08 (runner V2), subtask 04 (persistence)_
_Blocking: nothing (derniere subtask)_

## Objectif

Mettre a jour la demo pour utiliser le pipeline V2 complet : `BasicRuleEvaluator` dans `run_task`, snapshot ELO en fin de run, et gestion du `QAFailure` dans l'affichage.

## Methode

TDD strict : ecrire les tests d'abord, puis modifier le fichier existant.

## Fichiers a modifier

| Fichier | Action |
|---|---|
| `src/aaosa/demo/run_demo.py` | MODIFIER — ajouter evaluator + snapshot + QAFailure handling |
| `tests/demo/test_demo.py` | CREER ou MODIFIER — tests du pipeline V2 demo |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/demo/ -v
.venv\Scripts\python -m pytest tests/ -v   # TOUS les tests doivent passer
```

---

## Context — Fichier existant `demo/run_demo.py`

```python
from dotenv import load_dotenv

from aaosa.claiming.dispatch import DispatchResult
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    tracer = Tracer(session_id="demo")

    print("=== AAOSA Demo ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        result = run_task(task, DEMO_AGENTS, client, tracer)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name}")
        else:
            print(f"  -> Unassigned")
        print()

    print("=== Timeline ===")
    print_timeline(tracer.events)


if __name__ == "__main__":
    run_demo()
```

## Context — Demo agents (dans `demo/agents.py`)

```python
AGENT_FRONTEND = Agent(name="Frontend", tags_with_elo={"frontend": 85, "css": 90, "javascript": 80, "testing": 40}, ...)
AGENT_BACKEND = Agent(name="Backend", tags_with_elo={"backend": 90, "database": 85, "python": 80, "testing": 50}, ...)
AGENT_DEVOPS = Agent(name="DevOps", tags_with_elo={"infrastructure": 90, "docker": 85, "ci_cd": 80, "backend": 30}, ...)
AGENT_FULLSTACK = Agent(name="Fullstack", tags_with_elo={"frontend": 50, "backend": 55, "javascript": 60, "python": 50, "database": 40}, ...)
DEMO_AGENTS = [AGENT_FRONTEND, AGENT_BACKEND, AGENT_DEVOPS, AGENT_FULLSTACK]
```

## Context — Demo tasks (dans `demo/tasks.py`)

```python
TASK_FIX_CSS_HOVER = Task(description="Fix bug CSS hover...", required_tags={"css": 70})
TASK_WRITE_PYTHON_TESTS = Task(description="Write Python unit tests...", required_tags={"python": 40, "testing": 30})
TASK_REFACTOR_REST_API = Task(description="Refactor REST API...", required_tags={"backend": 80, "python": 70})
TASK_SECURITY_AUDIT = Task(description="Perform full security audit...", required_tags={"security": 80})
TASK_OPTIMIZE_SQL = Task(description="Optimize slow SQL queries...", required_tags={"database": 40})
TASK_BUILD_DASHBOARD_UI = Task(description="Build analytics dashboard...", required_tags={"frontend": 60, "javascript": 50})
TASK_DOCUMENT_API = Task(description="Write API documentation...", required_tags={"writing": 30}, acquirable_tags={"backend": 20})
DEMO_TASKS = [...]
```

## Context — Modules V2 utilises

### `BasicRuleEvaluator` (subtask 07)

```python
class BasicRuleEvaluator:
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

### `QAFailure` (subtask 02)

```python
class QAFailure(BaseModel):
    task_id: str
    agent_id: str
    output: Output
    qa_result: QAResult
```

### `save_snapshot` (subtask 04)

```python
def save_snapshot(agents: list[Agent], directory: Path) -> Path:
    """Ecrit un snapshot horodate + ecrase latest.json."""
```

---

## Etape 1 — Tests (RED)

Creer ou modifier les tests de la demo. La demo utilise l'API LLM — les tests doivent patcher `Agent.claim` et `Agent.execute`.

### Fichier : `tests/demo/test_demo.py`

Verifier si ce fichier existe deja. Si oui, ajouter les tests V2. Si non, le creer.

### Imports

```python
from unittest.mock import MagicMock, patch
from pathlib import Path

from aaosa.demo.run_demo import run_demo
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.core.agent import Agent
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.qa.protocol import QAFailure
```

### Tests

```python
class TestDemoV2:
    def test_demo_runs_without_error(self, tmp_path, monkeypatch):
        """La demo V2 complete ne crash pas."""
        # Patch l'API LLM
        def fake_claim(self, task, client):
            return Claim(agent_id=self.id, task_id=task.id, decision="claim", justification="ok")
        def fake_execute(self, task, client):
            tags_str = " ".join(task.required_tags.keys())
            return Output(
                task_id=task.id, agent_id=self.id,
                content=f"Comprehensive solution covering {tags_str} with detailed implementation",
                llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
            )

        monkeypatch.setattr(Agent, "claim", fake_claim)
        monkeypatch.setattr(Agent, "execute", fake_execute)
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        # Redirect snapshot to tmp_path
        monkeypatch.chdir(tmp_path)
        (tmp_path / "elo_snapshots").mkdir()

        run_demo()  # should not raise

    def test_demo_handles_qa_failure(self, capsys, tmp_path, monkeypatch):
        """La demo affiche QAFailure correctement."""
        def fake_claim(self, task, client):
            return Claim(agent_id=self.id, task_id=task.id, decision="claim", justification="ok")
        def fake_execute(self, task, client):
            return Output(
                task_id=task.id, agent_id=self.id,
                content="short",  # will fail QA (min_length)
                llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
            )

        monkeypatch.setattr(Agent, "claim", fake_claim)
        monkeypatch.setattr(Agent, "execute", fake_execute)
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "elo_snapshots").mkdir()

        run_demo()  # should not raise even with QA failures
        captured = capsys.readouterr()
        assert "FAIL" in captured.out or "QA" in captured.out

    def test_demo_creates_snapshot(self, tmp_path, monkeypatch):
        """La demo cree un snapshot ELO en fin de run."""
        def fake_claim(self, task, client):
            return Claim(agent_id=self.id, task_id=task.id, decision="claim", justification="ok")
        def fake_execute(self, task, client):
            tags_str = " ".join(task.required_tags.keys())
            return Output(
                task_id=task.id, agent_id=self.id,
                content=f"Comprehensive solution covering {tags_str} with detailed implementation",
                llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
            )

        monkeypatch.setattr(Agent, "claim", fake_claim)
        monkeypatch.setattr(Agent, "execute", fake_execute)
        monkeypatch.setenv("OPENAI_API_KEY", "fake")
        monkeypatch.chdir(tmp_path)
        snapshot_dir = tmp_path / "elo_snapshots"
        snapshot_dir.mkdir()

        run_demo()

        assert (snapshot_dir / "latest.json").exists()
```

---

## Etape 2 — Implementation (GREEN)

Modifier `src/aaosa/demo/run_demo.py`.

### Changements

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

    print("=== AAOSA Demo V2 ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: PASS)")
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

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/demo/ -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- La demo doit gerer les 3 types de retour : `Output`, `QAFailure`, `DispatchResult`
- Le snapshot est cree dans `elo_snapshots/` (avec `mkdir(exist_ok=True)`)
- L'evaluator est `BasicRuleEvaluator` (deterministe, pas de LLM)
- Le banner passe de "AAOSA Demo" a "AAOSA Demo V2" pour differencier
- `if __name__ == "__main__"` reste en place
- Les tests patchent TOUT ce qui touche l'API (claim + execute) et redirigent le snapshot vers tmp_path
