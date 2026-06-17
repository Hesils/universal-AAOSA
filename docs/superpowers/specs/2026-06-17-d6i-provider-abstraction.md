# d6i — Abstraction provider agnostique (OpenAI + Ollama) · Spec

> Ticket `d6i` #universal-AAOSA #epic/aaosa-subbrain — premier pas d'implémentation de l'épique sub-brain (pièce gate-indépendante "agnosticité provider", identifiée Q4 du brainstorm `2026-06-17-aaosa-subbrain-agentic.md`).
>
> **Statut : à valider par Quentin avant écriture du plan bite-sized.**

## 1. Objectif

Rendre AAOSA agnostique au provider LLM pour pouvoir faire tourner des **agents sur modèles locaux Ollama** (gratuits, sans cramer les tokens cloud) à côté d'agents cloud. Deux livrables couplés :

1. **Champ `provider` + `model` par agent** dans `agents.yaml` + schéma `Agent` + loader (le d6i littéral).
2. **Une couche d'abstraction provider + héritage** (`LLMProvider` ABC → `OpenAIProvider`, `OllamaProvider`) qui devient le **seam unique** de tous les appels LLM du runtime (décision Q2 : *tous* les call-sites, pas seulement les agents).

## 2. Décisions de cadrage (déjà tranchées)

| Question | Décision |
|---|---|
| Forme | Classe abstraite + héritage (`LLMProvider` / `OpenAIProvider` / `OllamaProvider`). Proposition d'origine de Quentin. |
| Périmètre | **Tous les call-sites LLM** passent par l'abstraction (agents + divider + aggregator + tagger + qa/*). |
| Default | Non-Agents → provider **par défaut** ; Agents → provider/model **par agent** (override), sinon default. |
| DoD | Suite verte (TDD) + abstraction en place + `agents.yaml` démo enrichi. **Smoke Ollama réel différé** (Quentin / ticket suivi). |
| Ollama | API **OpenAI-compatible** (`/v1`) → réutilise le SDK OpenAI (`base_url` + clé factice), pas de nouveau SDK. |

## 3. Contrainte structurante — rétrocompat stricte

Invariant projet : *« sans champ provider = comportement V1/V2 identique »* et les **~1032 tests doivent rester verts**.

- Le **provider par défaut = OpenAI / `gpt-4o-mini`** (modèle hardcodé partout aujourd'hui).
- Un `Agent` sans `provider`/`model` se comporte exactement comme avant.
- Aucune signature publique du runtime ne change de sémantique : on **renomme/élargit** le paramètre `client: OpenAI` en `provider: LLMProvider` (voir §6 migration).

## 4. État des lieux (couplage actuel)

- `runtime/llm_client.py` : `create_client()` → `openai.OpenAI` brut, passé en `client` partout.
- `model="gpt-4o-mini"` **hardcodé** dans 11 call-sites répartis en 2 familles :
  - **`client.chat.completions.create(...)`** (raw) : `agent.execute` (single + tool-loop), `aggregator`, `qa/diagnostic`, `qa/triage`, `qa/task_spec_generator`.
  - **`client.beta.chat.completions.parse(...)`** (structuré Pydantic) : `agent.claim`, `tagger`, `judge` (déjà `model=spec.model`), `criteria`, `qa/diagnostic`, `qa/triage`, `qa/task_spec_generator`, `divider`, `qa/adaptive`.
- `Agent` (`core/agent.py`) : **aucun** champ `provider`/`model`.
- Tests : mockent `client.beta.chat.completions.parse` / `client.chat.completions.create` via `MagicMock(spec=OpenAI)`. **C'est le gros du blast radius** (réécriture mécanique des mocks).

## 5. Design de l'abstraction

### 5.1 Contrat (`src/aaosa/runtime/providers.py`, net-new)

L'abstraction expose **deux méthodes** qui couvrent exactement les 2 familles de call-sites, et **retournent la forme de réponse OpenAI** (Ollama via SDK OpenAI renvoie la même forme → call-sites quasi inchangés, extraction `response.model` / `response.usage` / `response.choices[0].message` préservée).

```python
from abc import ABC, abstractmethod
from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

DEFAULT_MODEL = "gpt-4o-mini"

class LLMProvider(ABC):
    """Seam unique de tous les appels LLM du runtime. Agnostique au provider."""

    @abstractmethod
    def complete(self, *, messages: list, model: str | None = None,
                 tools: list | None = None) -> ChatCompletion:
        """Complétion brute. model=None → modèle par défaut du provider."""

    @abstractmethod
    def parse(self, *, messages: list, schema: type[BaseModel],
              model: str | None = None) -> BaseModel | None:
        """Sortie structurée → instance de `schema`, ou None si parse impossible.
        Normalise la divergence : OpenAI utilise beta.parse ; Ollama émule."""
```

> **Note de contrat — `parse()` retourne l'objet parsé (ou `None`)**, pas la réponse brute. C'est le point où les call-sites `beta...parse` changent le plus : aujourd'hui ils lisent `response.choices[0].message.parsed`. Après, ils lisent directement la valeur de retour. Bénéfice : la divergence OpenAI/Ollama est **entièrement encapsulée** (le but de l'abstraction). `agent.claim` garde sa logique de fallback mais branchée sur `parse()` → `None`.

### 5.2 `OpenAIProvider`

```python
class OpenAIProvider(LLMProvider):
    def __init__(self, client: OpenAI | None = None, default_model: str = DEFAULT_MODEL):
        self._client = client or OpenAI()
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None):
        kwargs = {"model": model or self._default_model, "messages": messages}
        if tools is not None:
            kwargs["tools"] = tools
        return self._client.chat.completions.create(**kwargs)

    def parse(self, *, messages, schema, model=None):
        try:
            resp = self._client.beta.chat.completions.parse(
                model=model or self._default_model,
                messages=messages, response_format=schema)
            return resp.choices[0].message.parsed
        except Exception:
            return None
```

### 5.3 `OllamaProvider`

Même SDK OpenAI, `base_url` Ollama, clé factice. `beta.parse` n'est **pas fiable** sur Ollama → `parse()` émule via `response_format` JSON + validation Pydantic du contenu, fallback JSON brut.

```python
class OllamaProvider(LLMProvider):
    DEFAULT_MODEL = "qwen3:4b"  # confirmé via smoke réel (2026-06-17)

    def __init__(self, base_url="http://localhost:11434/v1",
                 default_model=DEFAULT_MODEL):
        self._client = OpenAI(base_url=base_url, api_key="ollama")
        self._default_model = default_model

    def complete(self, *, messages, model=None, tools=None):
        # identique à OpenAIProvider (forme de réponse compatible)
        ...

    def parse(self, *, messages, schema, model=None):
        resp = self._client.chat.completions.create(
            model=model or self._default_model, messages=messages,
            response_format={"type": "json_object"})
        raw = resp.choices[0].message.content or ""
        try:
            return schema.model_validate_json(raw)
        except Exception:
            return None
```

### 5.4 Factory + résolution par agent

- `runtime/llm_client.py` : `create_client()` **conservé** (rétrocompat, monkeypatché par les tests CLI) mais on ajoute `create_provider(provider: str = "openai", **kw) -> LLMProvider`.
- Résolution du provider d'un agent (dans `agent.claim`/`execute`) : si `agent.provider`/`agent.model` sont posés → utiliser ; sinon → provider/modèle passé par le runtime (default). Mécanisme exact à arrêter dans le plan (option : le runtime construit un `provider` par agent au dispatch, ou l'agent porte une ref). **Recommandation** : le runtime résout `model=agent.model or None` et passe le `provider` courant ; un agent à provider *différent* du default = cas avancé traité via un registre `{provider_name: LLMProvider}` injecté au run. À trancher dans le plan.

## 6. Stratégie de migration (le vrai coût)

Renommer le paramètre `client: OpenAI` → `provider: LLMProvider` sur toute la chaîne (`run_task`, `run_phase2`, `agent.claim/execute`, `divider`, `aggregator`, `tagger`, `qa/*`), et remplacer :
- `client.chat.completions.create(model="gpt-4o-mini", ...)` → `provider.complete(messages=..., model=..., tools=...)`
- `client.beta.chat.completions.parse(...)` + lecture `.parsed` → `provider.parse(messages=..., schema=...)`

**Tests** : chaque `MagicMock(spec=OpenAI)` + `.beta.chat.completions.parse.return_value` devient un **fake provider** (`MagicMock(spec=LLMProvider)` avec `.parse.return_value` / `.complete.return_value`). Mécanique mais nombreux fichiers.

**Phasage proposé du plan** (un deliverable testable par tâche) :
1. `providers.py` + tests unitaires (module pur, 0 call-site touché). Vert.
2. Champ `provider`/`model` sur `Agent` + loader + `agents.yaml` démo (d6i littéral). Default None. Vert.
3. Migration `agent.py` (claim + execute) + réécriture mocks `test_agent.py`. Vert.
4. Migration runtime non-Agent : `divider`, `aggregator`, `tagger` (1 tâche/module). Vert.
5. Migration `qa/*` (`diagnostic`, `triage`, `task_spec_generator`, `criteria`, `judge`, `adaptive`). Vert.
6. Câblage `create_provider` + CLI (`app.py`) + `run_health_check_v3`. Suite complète verte.

## 7. Hors scope (différé / autres tickets)

- Smoke test Ollama réel (DoD §2).
- HITL (`ipv`), CLI task-libre + manifest (`erd`), pont AIOS→AAOSA (`fqd`), worktree+non-destruction (`v1m`) — sœurs de l'épique.
- Choix du modèle Ollama par défaut réel — confirmé `qwen3:4b` (smoke réel 2026-06-17 : `complete()`/`parse()` OK, dégradation `None` propre).

## 8. Forks restant ouverts pour validation Quentin

1. **Contrat `parse()`** : retourne l'objet parsé `| None` (encapsulation max, recommandé) — OK ? Alternative : retourner la réponse brute (call-sites moins touchés mais divergence Ollama qui fuit).
2. **Résolution provider par agent** (§5.4) : registre `{name: provider}` injecté au run vs agent porte le provider. Trancher avant la tâche 3.
3. **Périmètre tâche 5** (`qa/*`) : tout migrer maintenant, ou laisser `judge`/`criteria`/`adaptive` (LLM-judge, hors chemin runtime chaud) pour un suivi ? Recommandation : tout migrer (cohérence du seam unique, décision Q2).
