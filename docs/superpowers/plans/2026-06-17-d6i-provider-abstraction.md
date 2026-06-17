# d6i — Abstraction provider agnostique (OpenAI + Ollama) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre AAOSA agnostique au provider LLM via une abstraction `LLMProvider` (héritage `OpenAIProvider`/`OllamaProvider`) qui devient le seam unique de tous les appels LLM, plus un champ `provider`/`model` par agent.

**Architecture :** Une classe abstraite `LLMProvider` expose `complete()` (raw) et `parse()` (structuré, objet Pydantic `| None`, fallback JSON interne). `OpenAIProvider` wrappe le SDK OpenAI ; `OllamaProvider` réutilise le même SDK avec `base_url` Ollama + clé factice et émule la sortie structurée. La migration se fait en deux temps : (1) flip du paramètre threadé `client: OpenAI` → `provider: LLMProvider` partout, les call-sites non encore migrés lisant `provider.client` (accessor transitoire) ; (2) migration du corps de chaque leaf vers `provider.complete/parse`. La suite reste verte à chaque tâche.

**Tech Stack :** Python 3.14, `uv`, Pydantic 2.13, OpenAI SDK 2.38, pytest 9.0.3. Tests via `.venv\Scripts\python -m pytest`.

## Global Constraints

- **Rétrocompat stricte** : sans champ `provider`/`model` un agent = comportement V1/V2 identique ; les ~1032 tests existants restent verts. Copié de l'invariant projet (`CLAUDE.md`).
- **Default provider = OpenAI / `gpt-4o-mini`** (constante `DEFAULT_MODEL = "gpt-4o-mini"`).
- **Imports absolus uniquement** : `from aaosa.runtime.providers import LLMProvider`.
- **Tests via le venv** : `.venv\Scripts\python -m pytest <fichier> -v`, jamais Python système.
- **Pydantic v2** : `@field_validator` + `@classmethod` ; `ConfigDict(extra="forbid")` hérité via les bases existantes.
- **TaskDivider / TaskAggregator / Tagger ne sont pas des Agent** : pas de provider/model par agent pour eux, ils utilisent le provider par défaut du run.
- **judge** : conserve son `model=spec.model` (déjà paramétré) — le passer en argument `model=` de `parse()`.

---

### Task 1: Module d'abstraction `providers.py`

**Files:**
- Create: `src/aaosa/runtime/providers.py`
- Test: `tests/runtime/test_providers.py`

**Interfaces:**
- Produces:
  - `DEFAULT_MODEL: str = "gpt-4o-mini"`
  - `class LLMProvider(ABC)` avec `complete(*, messages, model=None, tools=None, **kwargs) -> ChatCompletion` et `parse(*, messages, schema, model=None, **kwargs) -> BaseModel | None`, et propriété `client -> OpenAI` (accessor transitoire).
  - `class OpenAIProvider(LLMProvider).__init__(self, client: OpenAI | None = None, default_model: str = DEFAULT_MODEL)`
  - `class OllamaProvider(LLMProvider).__init__(self, base_url="http://localhost:11434/v1", default_model="llama3.1", api_key="ollama")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_providers.py
from unittest.mock import MagicMock

import pytest
from openai import OpenAI
from pydantic import BaseModel

from aaosa.runtime.providers import (
    DEFAULT_MODEL,
    LLMProvider,
    OllamaProvider,
    OpenAIProvider,
)


class _Schema(BaseModel):
    value: str


def _fake_openai():
    client = MagicMock(spec=OpenAI)
    return client


class TestOpenAIProvider:
    def test_is_llmprovider(self):
        assert isinstance(OpenAIProvider(client=_fake_openai()), LLMProvider)

    def test_complete_uses_default_model(self):
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        p.complete(messages=[{"role": "user", "content": "hi"}])
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert "tools" not in kwargs  # tools=None omis

    def test_complete_overrides_model_and_passes_tools_and_kwargs(self):
        client = _fake_openai()
        p = OpenAIProvider(client=client)
        p.complete(messages=[], model="gpt-4o", tools=[{"x": 1}], temperature=0.0)
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["tools"] == [{"x": 1}]
        assert kwargs["temperature"] == 0.0

    def test_parse_returns_parsed_object(self):
        client = _fake_openai()
        resp = MagicMock()
        resp.choices[0].message.parsed = _Schema(value="ok")
        client.beta.chat.completions.parse.return_value = resp
        p = OpenAIProvider(client=client)
        out = p.parse(messages=[], schema=_Schema)
        assert out == _Schema(value="ok")

    def test_parse_falls_back_to_json_completion(self):
        client = _fake_openai()
        client.beta.chat.completions.parse.side_effect = RuntimeError("unsupported")
        comp = MagicMock()
        comp.choices[0].message.content = '{"value": "from_json"}'
        client.chat.completions.create.return_value = comp
        p = OpenAIProvider(client=client)
        out = p.parse(messages=[], schema=_Schema)
        assert out == _Schema(value="from_json")

    def test_parse_returns_none_when_everything_fails(self):
        client = _fake_openai()
        client.beta.chat.completions.parse.side_effect = RuntimeError("x")
        comp = MagicMock()
        comp.choices[0].message.content = "not json"
        client.chat.completions.create.return_value = comp
        p = OpenAIProvider(client=client)
        assert p.parse(messages=[], schema=_Schema) is None

    def test_client_accessor_returns_underlying(self):
        client = _fake_openai()
        assert OpenAIProvider(client=client).client is client


class TestOllamaProvider:
    def test_is_llmprovider(self):
        assert isinstance(OllamaProvider(), LLMProvider)

    def test_uses_ollama_base_url(self):
        p = OllamaProvider(base_url="http://localhost:11434/v1")
        assert p.client.base_url.host == "localhost"

    def test_parse_validates_json_content(self):
        p = OllamaProvider()
        comp = MagicMock()
        comp.choices[0].message.content = '{"value": "v"}'
        p._client = MagicMock(spec=OpenAI)
        p._client.chat.completions.create.return_value = comp
        assert p.parse(messages=[], schema=_Schema) == _Schema(value="v")

    def test_parse_returns_none_on_bad_json(self):
        p = OllamaProvider()
        comp = MagicMock()
        comp.choices[0].message.content = "nope"
        p._client = MagicMock(spec=OpenAI)
        p._client.chat.completions.create.return_value = comp
        assert p.parse(messages=[], schema=_Schema) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aaosa.runtime.providers'`

- [ ] **Step 3: Write the implementation**

```python
# src/aaosa/runtime/providers.py
"""Abstraction provider LLM — seam unique de tous les appels LLM du runtime.

LLMProvider expose deux opérations couvrant les deux familles d'appels du
runtime : complete() (complétion brute) et parse() (sortie structurée Pydantic).
parse() encapsule la divergence des providers : OpenAI via beta.parse, Ollama
via émulation JSON ; les deux retombent sur une validation JSON du contenu.
"""

from abc import ABC, abstractmethod

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

DEFAULT_MODEL = "gpt-4o-mini"


class LLMProvider(ABC):
    """Interface agnostique au provider. Les sous-classes wrappent un SDK concret."""

    _client: OpenAI
    _default_model: str

    @property
    def client(self) -> OpenAI:
        """Accessor transitoire vers le SDK sous-jacent (forme OpenAI-compatible).

        Utilisé pendant la migration par les call-sites pas encore portés sur
        complete()/parse(). À terme, plus aucun appel direct ne devrait subsister.
        """
        return self._client

    @abstractmethod
    def complete(
        self, *, messages: list, model: str | None = None,
        tools: list | None = None, **kwargs,
    ) -> ChatCompletion:
        """Complétion brute. model=None → modèle par défaut du provider."""

    @abstractmethod
    def parse(
        self, *, messages: list, schema: type[BaseModel],
        model: str | None = None, **kwargs,
    ) -> BaseModel | None:
        """Sortie structurée → instance de `schema`, ou None si parse impossible."""

    def _complete(self, *, messages, model, tools, **kwargs) -> ChatCompletion:
        call_kwargs = {"model": model or self._default_model, "messages": messages, **kwargs}
        if tools is not None:
            call_kwargs["tools"] = tools
        return self._client.chat.completions.create(**call_kwargs)

    def _parse_via_json(self, *, messages, schema, model, **kwargs) -> BaseModel | None:
        """Fallback commun : completion brute + validation JSON du contenu."""
        try:
            resp = self._complete(messages=messages, model=model, tools=None, **kwargs)
            raw = resp.choices[0].message.content or ""
            return schema.model_validate_json(raw)
        except Exception:
            return None


class OpenAIProvider(LLMProvider):
    def __init__(self, client: OpenAI | None = None, default_model: str = DEFAULT_MODEL) -> None:
        self._client = client if client is not None else OpenAI()
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None, **kwargs) -> ChatCompletion:
        return self._complete(messages=messages, model=model, tools=tools, **kwargs)

    def parse(self, *, messages, schema, model=None, **kwargs) -> BaseModel | None:
        try:
            resp = self._client.beta.chat.completions.parse(
                model=model or self._default_model,
                messages=messages,
                response_format=schema,
                **kwargs,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is not None:
                return parsed
        except Exception:
            pass  # structured output indisponible — fallback JSON
        return self._parse_via_json(messages=messages, schema=schema, model=model, **kwargs)


class OllamaProvider(LLMProvider):
    DEFAULT_OLLAMA_MODEL = "llama3.1"

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        default_model: str = DEFAULT_OLLAMA_MODEL,
        api_key: str = "ollama",
    ) -> None:
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None, **kwargs) -> ChatCompletion:
        return self._complete(messages=messages, model=model, tools=tools, **kwargs)

    def parse(self, *, messages, schema, model=None, **kwargs) -> BaseModel | None:
        # beta.parse non fiable sur Ollama — émulation directe via JSON.
        kwargs.setdefault("response_format", {"type": "json_object"})
        return self._parse_via_json(messages=messages, schema=schema, model=model, **kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_providers.py -v`
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/providers.py tests/runtime/test_providers.py
git commit -m "feat(providers): abstraction LLMProvider + OpenAI/Ollama (d6i)"
```

---

### Task 2: Champ `provider`/`model` par agent

**Files:**
- Modify: `src/aaosa/core/agent.py` (classe `Agent`, après `tools`, ~ligne 23)
- Modify: `src/aaosa/demo/agents.yaml` (ajouter un exemple de provider sur un agent)
- Test: `tests/core/test_agent.py`, `tests/config/test_loader.py`

**Interfaces:**
- Produces: `Agent.provider: str | None = None`, `Agent.model: str | None = None` (champs optionnels, default None = comportement V1/V2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_agent.py — ajouter
class TestAgentProviderModel:
    def test_provider_and_model_default_to_none(self):
        a = Agent(name="A", tags_with_elo={"x": 50}, system_prompt="p")
        assert a.provider is None
        assert a.model is None

    def test_provider_and_model_can_be_set(self):
        a = Agent(name="A", tags_with_elo={"x": 50}, system_prompt="p",
                  provider="ollama", model="llama3.1")
        assert a.provider == "ollama"
        assert a.model == "llama3.1"
```

```python
# tests/config/test_loader.py — ajouter (adapter le helper d'écriture YAML existant du fichier)
def test_loader_reads_provider_and_model(tmp_path):
    from aaosa.config.loader import load_agents
    p = tmp_path / "agents.yaml"
    p.write_text(
        "- name: Local\n"
        "  tags_with_elo: {python: 50}\n"
        "  system_prompt: p\n"
        "  provider: ollama\n"
        "  model: llama3.1\n",
        encoding="utf-8",
    )
    agents = load_agents(p)
    assert agents[0].provider == "ollama"
    assert agents[0].model == "llama3.1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/core/test_agent.py::TestAgentProviderModel tests/config/test_loader.py::test_loader_reads_provider_and_model -v`
Expected: FAIL (`provider`/`model` rejetés par `extra="forbid"` ou attribut absent)

- [ ] **Step 3: Write the implementation**

Dans `src/aaosa/core/agent.py`, après la ligne `tools: list[ToolDef] = Field(default_factory=list)` :

```python
    provider: str | None = None   # d6i — None = provider par défaut du run
    model: str | None = None      # d6i — None = modèle par défaut du provider
```

Le loader (`config/loader.py`) passe déjà `Agent(**entry)` : aucun changement de code nécessaire, les nouveaux champs sont consommés automatiquement.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/core/test_agent.py tests/config/test_loader.py -v`
Expected: PASS

- [ ] **Step 5: Enrichir la démo (optionnel mais inclus dans la DoD)**

Dans `src/aaosa/demo/agents.yaml`, documenter le champ en commentaire d'en-tête (ne PAS basculer un agent démo sur ollama — garderait la démo dépendante d'un Ollama local) :

```yaml
# Champ optionnel par agent (d6i) :
#   provider: openai | ollama   (défaut : provider du run)
#   model: <nom de modèle>      (défaut : modèle du provider)
```

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/core/agent.py src/aaosa/demo/agents.yaml tests/core/test_agent.py tests/config/test_loader.py
git commit -m "feat(agent): champ provider/model par agent (d6i)"
```

---

### Task 3: Flip du paramètre `client` → `provider` sur toute la chaîne (shallow)

Cette tâche **renomme** le paramètre threadé `client: OpenAI` en `provider: LLMProvider` dans tout le runtime + CLI, et fait migrer **uniquement `agent.py`** vers `provider.complete/parse`. Tous les autres leaves (divider, aggregator, tagger, qa/\*) lisent `provider.client` (accessor transitoire) — corps inchangé, suite verte.

**Files:**
- Modify: `src/aaosa/core/agent.py` (signatures `claim`/`execute` + corps), `src/aaosa/claiming/phase2.py`, `src/aaosa/runtime/runner.py`, `src/aaosa/runtime/llm_client.py` (ajout `create_provider`), `src/aaosa/cli/app.py`, `src/aaosa/demo/run_health_check_v3.py`
- Leaves touchés en signature seulement (param + `client` → `provider.client`) : `src/aaosa/runtime/divider.py`, `src/aaosa/runtime/aggregator.py`, `src/aaosa/runtime/tagger.py`, `src/aaosa/qa/diagnostic.py`, `src/aaosa/qa/triage.py`, `src/aaosa/qa/task_spec_generator.py`, `src/aaosa/qa/criteria.py`, `src/aaosa/qa/judge.py`, `src/aaosa/qa/adaptive.py`
- Test: `tests/core/test_agent.py`, `tests/claiming/test_phase2.py`, `tests/runtime/test_runner*.py`, `tests/cli/test_app.py`, et tout test passant un `client` à une fonction migrée.

**Interfaces:**
- Consumes: `LLMProvider`, `OpenAIProvider` (Task 1) ; `Agent.provider`/`model` (Task 2).
- Produces:
  - `create_provider(provider: str = "openai", *, registry: dict | None = None, **kw) -> LLMProvider` dans `llm_client.py`.
  - `Agent.claim(self, task, provider: LLMProvider) -> Claim` et `Agent.execute(self, task, provider: LLMProvider, tracer=None) -> Output`.
  - `run_task(task, agents, provider: LLMProvider, tracer=None, evaluator=None)` (et `run_chain`, `run_divided_task`, `run_phase2` : `client` → `provider`).

- [ ] **Step 1: Write/adjust the failing tests (agent + phase2 + runner + cli)**

`agent.py` migre pour de bon → ses tests mockent le provider, pas le client :

```python
# tests/core/test_agent.py — remplacer les mocks client par un fake provider
from aaosa.runtime.providers import LLMProvider

def _provider_for_execute(content="answer", model="gpt-4o-mini"):
    provider = MagicMock(spec=LLMProvider)
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.model = model
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    provider.complete.return_value = resp
    return provider

def test_claim_uses_provider_parse():
    from aaosa.schemas.claim import Claim
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = Claim(
        agent_id="x", task_id="t", decision="claim", justification="j")
    agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
    task = Task(id="t", description="d", required_tags=["python"])
    claim = agent.claim(task, provider)
    assert claim.decision == "claim"
    assert claim.agent_id == agent.id  # depuis self.id, jamais la réponse LLM

def test_claim_raises_when_provider_returns_none():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = None
    agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
    task = Task(id="t", description="d", required_tags=["python"])
    with pytest.raises(ValueError):
        agent.claim(task, provider)

def test_execute_passes_agent_model_to_provider():
    provider = _provider_for_execute()
    agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p",
                  model="gpt-4o")
    task = Task(id="t", description="d", required_tags=["python"])
    agent.execute(task, provider)
    assert provider.complete.call_args.kwargs["model"] == "gpt-4o"
```

> **Note d'exécution** : remplacer les anciens tests `tests/core/test_agent.py` qui mockaient `client.beta.chat.completions.parse` / `client.chat.completions.create` (lignes ~119-314) par leurs équivalents `provider.parse` / `provider.complete`. Les assertions de fond (model_name, tokens, call_count, agent_id stable) sont conservées en visant `provider.complete`.

Pour `phase2`/`runner`/`cli` : remplacer dans les tests existants tout `client` passé aux fonctions migrées par un `provider = MagicMock(spec=LLMProvider)` (ou `OpenAIProvider(client=mock_openai)` quand le test veut piloter la forme de réponse). `tests/cli/test_app.py:30` etc. : `monkeypatch.setattr(app_module, "create_client", lambda: object())` → `monkeypatch.setattr(app_module, "create_provider", lambda *a, **k: object())`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/core/test_agent.py tests/claiming/test_phase2.py -v`
Expected: FAIL (signatures `client`/attendues, `provider` inconnu)

- [ ] **Step 3: Migrate `agent.py` (corps complet)**

Remplacer dans `src/aaosa/core/agent.py` :
- import : `from openai import OpenAI` → `from aaosa.runtime.providers import LLMProvider`
- `def claim(self, task: Task, client: OpenAI) -> Claim:` → `def claim(self, task: Task, provider: LLMProvider) -> Claim:`

Corps de `claim` :

```python
    def claim(self, task: Task, provider: LLMProvider) -> Claim:
        from aaosa.claiming.prompts import prompt_template  # éviter l'import circulaire

        user_message = prompt_template(self, task)
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            schema=Claim,
            model=self.model,
        )
        if parsed is None:
            raise ValueError("Failed to parse claim from LLM response")
        return Claim(
            agent_id=self.id,
            task_id=task.id,
            decision=parsed.decision,
            justification=parsed.justification,
        )
```

`execute` : `client: OpenAI` → `provider: LLMProvider` ; chaque `client.chat.completions.create(model="gpt-4o-mini", messages=..., [tools=...])` → `provider.complete(messages=..., model=self.model, [tools=openai_tools])`. La lecture des réponses (`response.choices`, `response.usage`, `response.model`) est inchangée (forme OpenAI préservée).

- [ ] **Step 4: Flip des signatures `phase2` / `runner` / `cli` / `run_health_check_v3`**

- `claiming/phase2.py` : `run_phase2(task, candidates, client, tracer)` → `run_phase2(task, candidates, provider, tracer)` ; l'appel `agent.claim(task, client)` → `agent.claim(task, provider)`.
- `runtime/runner.py` : remplacer `client: OpenAI` → `provider: LLMProvider` dans `run_task`, `run_chain`, `run_divided_task` (et tout helper threadé). Appels : `run_phase2(..., provider, ...)`, `winner.execute(task, provider, tracer)`. Les appels aux leaves non encore migrés passent `provider` tel quel (leur signature change en Step 5).
- `runtime/llm_client.py` : conserver `create_client` ; ajouter :

```python
from aaosa.runtime.providers import LLMProvider, OllamaProvider, OpenAIProvider


def create_provider(provider: str = "openai", **kwargs) -> LLMProvider:
    """Construit un LLMProvider par nom. Défaut : OpenAI (rétrocompat)."""
    if provider == "ollama":
        return OllamaProvider(**kwargs)
    if provider == "openai":
        return OpenAIProvider(**kwargs)
    raise ValueError(f"Unknown provider: {provider!r}")
```

- `cli/app.py` : `from ... import create_client` → `create_provider` ; `client = create_client()` → `provider = create_provider()` ; passer `provider` à `run_once`/`run_campaign` (adapter ces helpers dans `incident_runs.py` : `client` → `provider`).
- `demo/run_health_check_v3.py` : idem `create_client()` → `create_provider()`.

- [ ] **Step 5: Flip de signature des leaves (param uniquement, corps via `.client`)**

Pour CHAQUE leaf ci-dessous : renommer le paramètre `client: OpenAI` → `provider: LLMProvider` et, dans le corps, remplacer `client.` par `provider.client.` (accessor transitoire). Aucune autre logique ne change.

| Fichier | Fonction/méthode | Param à renommer |
|---|---|---|
| `runtime/divider.py` | `Divider.divide` | `client` → `provider` |
| `runtime/aggregator.py` | `Aggregator.aggregate` | `client` → `provider` |
| `runtime/tagger.py` | `Tagger.tag` | `client` → `provider` |
| `qa/diagnostic.py` | `diagnose_failure` | `client` → `provider` |
| `qa/triage.py` | `triage_case`, `triage_unattributed` | `client` → `provider` |
| `qa/task_spec_generator.py` | `*` (fonctions à `client`) | `client` → `provider` |
| `qa/criteria.py` | fonction à `client` | `client` → `provider` |
| `qa/judge.py` | fonction à `client` | `client` → `provider` |
| `qa/adaptive.py` | fonction à `client` | `client` → `provider` |

Mettre à jour les appelants internes (ex. `triage_unattributed` appelle `triage_case(case, provider)`).

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (tout vert ; les leaves passent par `provider.client`, comportement identique)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(runtime): thread LLMProvider en lieu et place de client OpenAI (d6i)"
```

---

### Task 4: Migration des leaves runtime (divider, aggregator, tagger)

Migre le corps de 3 leaves de `provider.client.chat...` vers `provider.complete/parse`.

**Files:**
- Modify: `src/aaosa/runtime/divider.py`, `src/aaosa/runtime/aggregator.py`, `src/aaosa/runtime/tagger.py`
- Test: `tests/runtime/test_divider.py`, `tests/runtime/test_aggregator.py`, `tests/runtime/test_tagger.py`

**Interfaces:**
- Consumes: `LLMProvider.complete/parse` (Task 1) ; signatures `provider` (Task 3).

- [ ] **Step 1: Adapter les tests vers le fake provider**

Dans chaque test, remplacer le `MagicMock(spec=OpenAI)` (avec `.beta.chat.completions.parse.return_value` / `.chat.completions.create.return_value`) par `MagicMock(spec=LLMProvider)` avec `.parse.return_value` / `.complete.return_value`. Exemple divider :

```python
# tests/runtime/test_divider.py
from aaosa.runtime.providers import LLMProvider

def test_divide_returns_parsed_division():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = DivisionResult(sub_tasks=[...])  # forme existante
    result = Divider(system_prompt="p").divide(task, provider)
    assert result == provider.parse.return_value

def test_divide_raises_when_parse_returns_none():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = None
    with pytest.raises(ValueError):
        Divider(system_prompt="p").divide(task, provider)
```

Aggregator : `provider.complete.return_value` = réponse avec `.choices[0].message.content`, `.model`, `.usage`. Tagger : `provider.parse.return_value = TagSet(tags=[...])` (ou `None`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_divider.py tests/runtime/test_aggregator.py tests/runtime/test_tagger.py -v`
Expected: FAIL

- [ ] **Step 3: Migrate les corps**

`divider.py` (`divide`) :

```python
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(
                    task, chained_context, failure_context, cycle_context)},
            ],
            schema=DivisionResult,
            temperature=0.0,
        )
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
```

`aggregator.py` (`aggregate`) : `provider.client.chat.completions.create(model="gpt-4o-mini", messages=...)` → `provider.complete(messages=...)`. Lecture réponse inchangée.

`tagger.py` (`tag`) :

```python
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            schema=TagSet,
            temperature=0.0,
        )
        if parsed is None:
            return set()
        return {t.strip() for t in parsed.tags if t.strip()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/divider.py src/aaosa/runtime/aggregator.py src/aaosa/runtime/tagger.py tests/runtime/
git commit -m "refactor(runtime): divider/aggregator/tagger via LLMProvider (d6i)"
```

---

### Task 5: Migration des leaves `qa/*`

Migre le corps des call-sites `qa/*` vers `provider.parse/complete`. Les blocs duaux *beta.parse → fallback JSON* (`diagnostic`, `triage`, `task_spec_generator`) **se réduisent à un seul `provider.parse`** (le fallback JSON est désormais interne au provider).

**Files:**
- Modify: `src/aaosa/qa/diagnostic.py`, `src/aaosa/qa/triage.py`, `src/aaosa/qa/task_spec_generator.py`, `src/aaosa/qa/criteria.py`, `src/aaosa/qa/judge.py`, `src/aaosa/qa/adaptive.py`
- Test: `tests/qa/test_diagnostic.py`, `tests/qa/test_triage.py`, `tests/qa/test_task_spec_generator.py`, `tests/qa/test_criteria.py`, `tests/qa/test_judge.py`, `tests/qa/test_adaptive.py`

**Interfaces:**
- Consumes: `LLMProvider.parse/complete` (Task 1).

- [ ] **Step 1: Adapter les tests vers le fake provider**

Pour chaque fichier de test : `MagicMock(spec=OpenAI)` → `MagicMock(spec=LLMProvider)` ; `.beta.chat.completions.parse.return_value` → `.parse.return_value` (objet schéma `| None`) ; `.chat.completions.create.return_value` → `.complete.return_value`. Les tests qui vérifiaient le fallback JSON (deux appels) deviennent : `provider.parse.return_value = None` → la fonction retourne `None` (diagnostic/triage/task_spec).

Exemple :

```python
# tests/qa/test_triage.py
def test_triage_case_returns_none_when_provider_parse_none():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = None
    assert triage_case(case, provider) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/qa/ -v`
Expected: FAIL

- [ ] **Step 3: Migrate les corps**

Pattern uniforme — remplacer le bloc dual par un appel unique. Exemple `triage_case` :

```python
def triage_case(case: TestCase, provider: LLMProvider) -> TriageResult | None:
    """Classifie un seul TestCase. Retourne None si le LLM échoue."""
    prompt = _build_triage_prompt(case)
    return provider.parse(
        messages=[{"role": "user", "content": prompt}],
        schema=TriageResult,
        temperature=0,
    )
```

Appliquer le même collapse à `diagnose_failure` (schema `DiagnosticResult`) et à la fonction de `task_spec_generator.py` (schema `TaskSpecFix` ; conserver la transformation `case.model_copy(...)` en aval, sur le résultat `provider.parse`). Pour `criteria.py`/`adaptive.py` (parse simple sans fallback) : `provider.client.beta.chat.completions.parse(...)` → `provider.parse(messages=..., schema=..., temperature=0)`. Pour `judge.py` : `provider.parse(messages=..., schema=..., model=spec.model)` (conserver `spec.model`).

> **Vérifier** : les fonctions qui lisaient `response.choices[0].message.parsed` puis `if parsed is not None: return parsed` retournent maintenant directement la valeur de `provider.parse` (déjà `| None`). Supprimer les imports devenus inutiles (`json`, `OpenAI`) dans ces fichiers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/qa/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/ tests/qa/
git commit -m "refactor(qa): diagnostic/triage/task_spec/criteria/judge/adaptive via LLMProvider (d6i)"
```

---

### Task 6: Finalisation — registre provider par agent + nettoyage

Câble la résolution d'un provider **différent** du default au niveau agent (fork #2 validé : registre `{nom: LLMProvider}` injecté au run), et nettoie l'accessor transitoire si plus utilisé.

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (résolution provider par agent), `src/aaosa/runtime/llm_client.py` (`create_provider` accepte un registry)
- Test: `tests/runtime/test_runner_provider.py` (new)

**Interfaces:**
- Consumes: `Agent.provider` (Task 2), `create_provider` (Task 3).
- Produces: dans `run_task`, l'agent gagnant exécute avec le provider correspondant à `agent.provider` si présent dans le registre, sinon le provider par défaut.

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime/test_runner_provider.py
from unittest.mock import MagicMock
from aaosa.runtime.providers import LLMProvider

def test_agent_with_named_provider_uses_registry(monkeypatch):
    default = MagicMock(spec=LLMProvider)
    ollama = MagicMock(spec=LLMProvider)
    # agent porte provider="ollama" ; le run reçoit un registre {"ollama": ollama}
    # → l'exécution de cet agent doit appeler ollama.complete, pas default.complete
    ...  # cf. helpers de run_task existants ; asserter ollama.complete.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner_provider.py -v`
Expected: FAIL

- [ ] **Step 3: Implement la résolution**

Dans `run_task`, avant `winner.execute(...)`, résoudre :

```python
    exec_provider = provider
    if winner.provider and provider_registry:
        exec_provider = provider_registry.get(winner.provider, provider)
    output = winner.execute(task, exec_provider, tracer)
```

`run_task`/`run_chain` gagnent un paramètre optionnel `provider_registry: dict[str, LLMProvider] | None = None`. `create_provider` documente la construction du registre côté CLI (hors scope d6i : la CLI task-libre est le ticket `erd`).

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Vérifier qu'aucun usage de `provider.client` ne subsiste hors transition légitime**

Run: `.venv\Scripts\python -m pytest -q` puis recherche `provider.client` dans `src/` — ne doit rester que dans des cas justifiés (aucun attendu après Task 5).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(runner): résolution provider par agent via registre (d6i)"
```

---

## Self-Review

**Spec coverage :**
- §2 décisions (abstraction+héritage, tous call-sites, default OpenAI, DoD tests-verts) → Tasks 1, 3, 4, 5.
- §5 contrat `complete`/`parse` (+ fallback JSON interne, `**kwargs`, accessor `.client`) → Task 1.
- §5.2/5.3 OpenAI/Ollama providers → Task 1.
- §5.4 + fork #2 résolution provider par agent (registre) → Tasks 2 + 6.
- §6 migration + réécriture mocks → Tasks 3, 4, 5.
- §1 champ provider/model par agent → Task 2.
- fork #1 (`parse` → objet `| None`) → Task 1. fork #3 (`qa/*` tout migré) → Task 5.

**Placeholder scan :** Task 6 Step 1 laisse un squelette de test (`...`) car il dépend des helpers de construction de `run_task` du repo (à lire à l'exécution) ; tous les autres steps contiennent du code complet.

**Type consistency :** `LLMProvider.complete/parse`, `OpenAIProvider`/`OllamaProvider`, `create_provider`, `Agent.provider`/`model` cohérents entre Tasks 1→6. `parse()` retourne `BaseModel | None` partout consommé comme tel.

## Execution Handoff

Voir offre d'exécution ci-dessous.
