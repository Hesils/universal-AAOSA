# V3 — Épique A5 — Tools par agent

- **Couche** : `src/aaosa/core/` · `src/aaosa/schemas/output.py` · `src/aaosa/tracing/events.py`
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : aucune (parallèle à A3/A4)
- **Roadmap** : section V3, épique A5

---

## Contexte

`Agent.execute` est aujourd'hui un seul appel LLM. Certaines tâches requièrent qu'un agent
dispose d'outils (recherche, calcul, accès à une API) — le LLM choisit quels outils appeler,
les résultats sont réinjectés, jusqu'à une réponse textuelle finale.

A5 ajoute la boucle tool-use dans `execute` sans modifier le pipeline claiming (Phase 1/2,
dispatch) ni le contrat `run_task`. Un agent sans outils conserve exactement le comportement V1/V2.

---

## Ce qui ne change pas

- `claim()` : inchangé
- `run_task` / `run_chain` : signature et comportement inchangés
- Tous les tests existants : inchangés (`tools=[]` par défaut sur tout agent existant)
- `Output` : inchangé (seul `LLMMetadata` reçoit un champ optionnel)

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Où vivent les outils ? | `Agent.tools: list[ToolDef] = []` | Champ sur l'agent, vide par défaut → backward compat totale |
| Type `ToolDef` | `@dataclass` dans `src/aaosa/core/tool.py` | Les callables ne sont pas sérialisables Pydantic ; `Agent` a déjà `arbitrary_types_allowed=True` |
| Format tool pour OpenAI | `ToolDef.to_openai() -> dict` | Encapsule le formatage OpenAI API, ToolDef reste framework-agnostic |
| Résultat d'un outil | `str` uniquement | OpenAI exige un tool result en string ; la conversion est à la charge du `fn` |
| Boucle tool-use | `for _ in range(MAX_TOOL_ROUNDS)` puis `RuntimeError` | Protège contre les boucles infinies. `MAX_TOOL_ROUNDS = 10` comme constante dans `tool.py` |
| Signature `execute` | `execute(task, client, tracer=None) -> Output` | Paramètre optionnel → aucun site d'appel cassé |
| Tracing outil | `ToolCalledEvent` par appel outil, émis si `tracer` fourni | Pattern observer existant — `tracer.session_id` récupéré depuis le tracer passé |
| `LLMMetadata.tool_calls_count` | `int = 0` (optionnel, default 0) | Agrège le nombre de tours d'outils dans le run ; rétrocompat totale (les tests existants ne le passent pas) |
| YAML compat (A1) | Agents chargés depuis YAML → `tools=[]` implicitement | Le champ a un `default_factory` ; pas besoin de clé YAML |
| Dashboard (A5) | Hors scope | `ToolCalledEvent` existe dans la trace ; l'intégration UI est une suite (graphe déjà extensible par `NodeType`) |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/core/tool.py` | n'existe pas | Créé : `ToolDef` dataclass + `MAX_TOOL_ROUNDS` |
| `src/aaosa/core/agent.py` | `execute(task, client)`, 1 LLM call | `tools: list[ToolDef] = []` + `execute(..., tracer=None)` + boucle tool-use si tools non vide |
| `src/aaosa/schemas/output.py` | `LLMMetadata` : 4 champs | +`tool_calls_count: int = 0` |
| `src/aaosa/tracing/events.py` | Union sans outil | +`ToolCalledEvent` dans la union `ClaimEvent` |

---

## `ToolDef`

```python
# src/aaosa/core/tool.py
from dataclasses import dataclass
from typing import Callable

MAX_TOOL_ROUNDS = 10

@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict          # JSON Schema "object" — passé tel quel à l'API OpenAI
    fn: Callable[..., str]    # implémentation ; toujours retourne str

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

Exemple d'utilisation :

```python
def search_docs(query: str) -> str:
    return f"Résultat pour : {query}"

tool = ToolDef(
    name="search_docs",
    description="Recherche dans la documentation",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    fn=search_docs,
)
```

---

## `LLMMetadata` — champ additionnel

```python
class LLMMetadata(BaseModel):
    model_config = ConfigDict(strict=True)

    model_name: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    tool_calls_count: int = 0    # nouveau — cumulé sur toute la boucle tool-use
```

---

## `ToolCalledEvent`

```python
class ToolCalledEvent(_BaseEvent):
    type: Literal["tool_called"] = "tool_called"
    agent_id: str
    task_id: str
    tool_name: str
    arguments: dict    # parsé depuis tool_call.function.arguments
    result: str
    latency_ms: float
```

Ajouté à la union `ClaimEvent` dans `events.py`.

---

## Boucle tool-use dans `Agent.execute`

```python
def execute(self, task: Task, client: OpenAI, tracer=None) -> Output:
    context = task.metadata.get("context", "")
    # [A3 — déjà présent quand A5 est implémenté]
    user_content = ...

    start_total = time.monotonic()

    if not self.tools:
        # Chemin V1/V2 — single call (inchangé)
        response = client.chat.completions.create(...)
        latency_ms = (time.monotonic() - start_total) * 1000
        return Output(
            task_id=task.id, agent_id=self.id,
            content=response.choices[0].message.content or "",
            llm_metadata=LLMMetadata(
                model_name=response.model,
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens,
                latency_ms=latency_ms,
            ),
        )

    # Chemin A5 — boucle tool-use
    tool_map = {t.name: t for t in self.tools}
    openai_tools = [t.to_openai() for t in self.tools]
    messages = [
        {"role": "system", "content": self.system_prompt},
        {"role": "user", "content": user_content},
    ]
    total_tokens_in = 0
    total_tokens_out = 0
    tool_calls_count = 0
    content = ""

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=openai_tools,
        )
        choice = response.choices[0]
        total_tokens_in += response.usage.prompt_tokens
        total_tokens_out += response.usage.completion_tokens

        if choice.finish_reason == "stop":
            content = choice.message.content or ""
            break

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)
            tool_results = []
            for tc in choice.message.tool_calls:
                tool = tool_map[tc.function.name]
                args = json.loads(tc.function.arguments)
                t_start = time.monotonic()
                result = tool.fn(**args)
                t_ms = (time.monotonic() - t_start) * 1000
                tool_calls_count += 1
                if tracer:
                    tracer.emit(ToolCalledEvent(
                        session_id=tracer.session_id,
                        agent_id=self.id,
                        task_id=task.id,
                        tool_name=tc.function.name,
                        arguments=args,
                        result=result,
                        latency_ms=t_ms,
                    ))
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            messages.extend(tool_results)
    else:
        raise RuntimeError(f"Max tool rounds ({MAX_TOOL_ROUNDS}) exceeded for task {task.id}")

    latency_ms = (time.monotonic() - start_total) * 1000
    return Output(
        task_id=task.id,
        agent_id=self.id,
        content=content,
        llm_metadata=LLMMetadata(
            model_name=response.model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=latency_ms,
            tool_calls_count=tool_calls_count,
        ),
    )
```

---

## `Agent` — champ ajouté

```python
class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str
    tools: list[ToolDef] = Field(default_factory=list)    # nouveau
```

Invariant : `extra="forbid"` reste ; `arbitrary_types_allowed=True` déjà présent (couvre `Callable` dans `ToolDef`).

---

## Stratégie de test (TDD)

**`tests/core/test_tool.py`** (3 tests) :
- `test_tooldef_creation` : `ToolDef` créé avec name/description/parameters/fn — tous accessibles
- `test_tooldef_to_openai` : `.to_openai()` retourne le dict OpenAI attendu (type="function", clés function/name/description/parameters)
- `test_tooldef_fn_called` : `tool.fn(query="x")` retourne la string attendue

**`tests/core/test_agent_tools.py`** (5 tests) :
- `test_execute_no_tools_unchanged` : agent sans tools → single LLM call, `tool_calls_count=0`
- `test_execute_tools_llm_stops_immediately` : agent avec tools, mock LLM retourne `finish_reason="stop"` → aucun outil invoqué, `tool_calls_count=0`
- `test_execute_tools_one_tool_call` : mock LLM retourne `tool_calls` puis `stop` → `fn` appelé, content correct, `tool_calls_count=1`
- `test_execute_tools_emits_tool_called_event` : avec tracer → `ToolCalledEvent` émis avec `tool_name`/`arguments`/`result` corrects
- `test_execute_max_rounds_raises` : mock LLM toujours `tool_calls` → `RuntimeError` après `MAX_TOOL_ROUNDS` tours

**`tests/tracing/test_tool_event.py`** (2 tests) :
- `test_tool_called_event_valid` : construction + sérialisation JSON roundtrip
- `test_tool_called_event_in_union` : désérialisation depuis JSON discrimine sur `"type": "tool_called"` → `ToolCalledEvent`

---

## Critères de done

- [ ] `src/aaosa/core/tool.py` créé (`ToolDef` dataclass + `MAX_TOOL_ROUNDS`)
- [ ] `Agent.tools: list[ToolDef] = []` ajouté, `execute` accepte `tracer=None`
- [ ] Chemin sans outils : comportement identique à V2 (`tool_calls_count=0`)
- [ ] Chemin avec outils : boucle tool-use, `ToolCalledEvent` émis si tracer, `RuntimeError` si dépasse `MAX_TOOL_ROUNDS`
- [ ] `LLMMetadata.tool_calls_count: int = 0` — rétrocompat totale (aucun test existant modifié)
- [ ] `ToolCalledEvent` dans l'union `ClaimEvent`
- [ ] `tests/core/test_tool.py` : 3 tests verts
- [ ] `tests/core/test_agent_tools.py` : 5 tests verts
- [ ] `tests/tracing/test_tool_event.py` : 2 tests verts
- [ ] Suite complète ≥ 631 + 10 = **641 tests verts** (après A1+B1+A3+A4)

---

## Questions tranchées ici

1. **Agents chargés depuis YAML (A1) peuvent-ils avoir des outils ?**
   Non en A5 — `tools` absent du YAML = liste vide implicitement. Pour attacher des outils
   post-load : `agent.model_copy(update={"tools": [...]})`. Hors scope A5.

2. **`finish_reason` autres que `"stop"` et `"tool_calls"` (ex. `"length"`) ?**
   Traités comme `"stop"` — le contenu partiel est retourné. Pas d'erreur silencieuse grave :
   `content` sera tronqué, ce que le QA evaluator peut détecter.

3. **Tokens agrégés sur toute la boucle — est-ce exact pour la facturation ?**
   Oui — chaque appel `client.chat.completions.create` retourne `usage` propre à ce tour.
   `total_tokens_in/out` est la somme exacte des tours.

4. **Un outil qui lève une exception ?**
   L'exception remonte directement — pas de catch silencieux. Le caller (run_task) la propage
   comme erreur d'exécution. Ajouter un `try/except` dans la boucle si nécessaire : hors scope A5,
   décision à prendre au deep-dive d'une épique de robustesse future.

5. **Plusieurs tool calls en parallèle dans un même tour ?**
   Le mock OpenAI peut retourner plusieurs tool calls dans une seule réponse. La boucle les traite
   séquentiellement (pour la trace et la latence par appel). Compatible OpenAI API.

6. **`tracer.session_id` — est-il public ?**
   Oui — `Tracer.__init__` set `self.session_id` et le flush l'utilise pour le nom du fichier.
   L'accès `tracer.session_id` dans `execute` est safe.
