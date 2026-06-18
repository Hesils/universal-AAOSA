# Spec `ipv` — HITL comme tool callable (`ask_human`)

> Statut : **proposée** (à valider par Quentin avant plan TDD).
> Ticket : `ipv` (P2, épique `aaosa-subbrain`, gate-INDÉPENDANT).
> Source de vérité du cadrage : `seconde_brain/raw/brainstorms/2026-06-17-aaosa-subbrain-agentic.md` (open-flag HITL) + décisions de la session `/ticket ipv` (2026-06-18, ci-dessous §8).

## 1. Objectif

Donner aux agents AAOSA un moyen de **demander une information à l'humain en cours de run**, sans casser le modèle d'exécution synchrone. Un agent qui manque d'une donnée critique appelle un tool `ask_human(question)` ; un **callback fourni par l'invocateur** (CC / opérateur) répond ; la réponse rentre dans le thread tool-use et le run continue. L'échange est **tracé** (observabilité).

C'est la première brique HITL d'AAOSA (aucune aujourd'hui), côté **gate-indépendant** de l'épique subbrain : utilisable seule, fait avancer le North Star « AAOSA pilotable par un invocateur externe ».

## 2. Décision de forme (tranchée en amont, ne pas re-litiger)

Deux framings étaient possibles (cf. §8) :

- **Pause/reprise persistée** (formulation initiale de la carte) : le run s'arrête, écrit un statut `hitl_pending`, rend la main hors-process, reprend plus tard. → **écartée** : exige un runtime suspendable/reprenable (net-new lourd), AAOSA est synchrone.
- **Tool + callback synchrone** (retenu) : `ask_human` est un `ToolDef` normal ; son `fn` bloque sur un callback injecté qui revient dans le thread. **Le runtime synchrone n'est pas touché** (`execute()`, `run_task`, `run_with_recovery` inchangés). Le run ne sort jamais de `execute()` ; il attend juste la réponse du callback.

**Conséquence directe** : pas de détection runtime d'un agent « bloqué ». C'est l'agent qui **décide** d'appeler `ask_human` via son raisonnement (guidé par son system prompt). Pas de magie côté runtime, pas de nouveau statut de run.

## 3. Périmètre

**Dans `ipv`** :
1. Tool **built-in framework** `ask_human` : builder `make_ask_human_tool(callback) -> ToolDef` (closure sur le callback).
2. Seam d'injection du callback au niveau run : champ optionnel `hitl_callback` sur `RunContext` (forward-looking, cf. §6 extensibilité) ; le tool est construit depuis ce callback.
3. Résolution du tool par **nom** au chargement de roster : un agent déclare `ask_human` dans son `tools:` (agents.yaml) → résolu depuis un **registre de built-ins** fusionné au `TOOL_REGISTRY` du roster (erd).
4. **Dégradation non-interactive** (night-run / batch) : sans humain, un **callback sentinelle** par défaut répond une chaîne claire et non-bloquante → un roster contenant `ask_human` reste exécutable la nuit.
5. **Wiring CLI** : `aaosa solve --hitl` → callback interactif (lecture stdin) ; sans le flag → callback sentinelle.
6. **Trace** : l'échange est porté par le `ToolCalledEvent` existant (`tool_name="ask_human"`, `arguments={"question": ...}`, `result=<réponse>`, `latency_ms`=temps de réponse humain). **Aucun nouveau type d'event en V1** (cf. §5).

**Hors `ipv`** (différé, noté pour V2) :
- HITL callable par les **LLM non-agents** (divider / aggregator / judge) — ces call-sites n'ont pas de boucle tool-use ; chacun devrait gagner un point d'interruption. Le seam V1 (`ctx.hitl_callback` + builder réutilisable) est conçu pour le rendre faisable sans réécriture (§6).
- **Protocole cross-process structuré** CC↔AAOSA (requête/réponse via pipe/fichier plutôt que stdin). V1 = stdin interactif, suffisant pour prouver le mécanisme et utilisable par un opérateur humain.
- Dédié `HITLEvent` à sémantique riche (durée d'attente, état pending) — seulement si un besoin d'observabilité dépasse le `ToolCalledEvent` (§5).

## 4. Changements — par module

### 4.1 `src/aaosa/core/hitl.py` (nouveau) — builder + sentinelle

```python
HITLCallback = Callable[[str], str]   # question -> réponse

ASK_HUMAN_TOOL_NAME = "ask_human"

def unattended_callback(question: str) -> str:
    """Callback par défaut sans humain (night-run/batch). Non-bloquant.
    Réponse explicite pour que l'agent procède sans donnée humaine."""
    return ("No human is available to answer in this run. "
            "Proceed with your best judgment and state any assumption you make.")

def make_ask_human_tool(callback: HITLCallback | None = None) -> ToolDef:
    """Construit le ToolDef ask_human. `callback` capturé en closure :
    le runtime ne le voit jamais (fn(**args) -> str inchangé côté execute()).
    callback=None -> unattended_callback (dégradation sûre)."""
    cb = callback or unattended_callback
    def _fn(question: str) -> str:
        return cb(question)
    return ToolDef(
        name=ASK_HUMAN_TOOL_NAME,
        description=("Ask the human operator a question when you lack a piece of "
                     "information that is critical to complete the task and cannot "
                     "be obtained otherwise. Returns the human's answer as text."),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string",
                "description": "The single, specific question to ask the human."}},
            "required": ["question"],
        },
        fn=_fn,
    )
```

- `fn` respecte le contrat `ToolDef` : `(**args) -> str`. Le callback est dans la closure → **zéro changement de signature** dans `agent.execute()` / `run_task`.
- `unattended_callback` garantit la **sécurité night-run** : un agent peut porter `ask_human` sans qu'un run batch ne bloque.

### 4.2 `src/aaosa/runtime/context.py` — champ `hitl_callback`

Ajouter un champ optionnel à `RunContext` :

```python
hitl_callback: HITLCallback | None = None   # ipv — None = unattended
```

- **Rétrocompat stricte** : default `None`, aucun chemin existant n'est affecté. C'est le seam unique où vit le callback du run → un futur appelant non-agent (V2) le lira ici sans dépendre du builder de tool (§6).

### 4.3 `src/aaosa/config/` — registre de built-ins fusionné au chargement

Le tool `ask_human` est un tool **framework**, pas un tool de roster (il n'a pas sa place dans le `tools.py` d'un roster). Il faut donc qu'un agent déclarant `ask_human` dans son `tools:` le résolve depuis un registre de built-ins, fusionné au registre du roster.

- Builder de built-ins : `build_builtin_tools(callback: HITLCallback | None) -> dict[str, ToolDef]` → `{ASK_HUMAN_TOOL_NAME: make_ask_human_tool(callback)}`.
- `load_roster` / `load_rosters` (erd, `config/roster.py`) gagnent un paramètre optionnel `builtin_tools: dict[str, ToolDef] | None = None`, **fusionné** au `TOOL_REGISTRY` du roster avant `load_agents`.
- **Réservation de nom** : un roster ne peut pas redéfinir `ask_human` (collision built-in vs roster → `ValueError` clair). Les built-ins gagnent.
- Si `ipv` atterrit avant ou après `erd` dans l'ordre réel : le point d'ancrage est le paramètre `tool_registry` que `load_agents` accepte déjà. Si `roster.py` n'existe pas encore, `ipv` cible directement `load_agents` (le seam de fusion est le même).

### 4.4 `src/aaosa/cli/solve_runs.py` + `app.py` (erd) — wiring

- `solve_once(...)` gagne `hitl_callback: HITLCallback | None = None` : posé sur `RunContext.hitl_callback` **et** utilisé pour `build_builtin_tools` passé à `load_rosters`.
- `app.solve` gagne `--hitl / --no-hitl` (défaut `--no-hitl`) :
  - `--hitl` → callback interactif : `_stdin_callback(question)` imprime la question et lit une ligne (`typer.prompt`). Bloque le run jusqu'à réponse — comportement voulu.
  - `--no-hitl` → `hitl_callback=None` → `unattended_callback` (night/batch safe).
- La démo `run --scenario` n'est **pas** touchée (pas de `ask_human` dans le monde incident).

## 5. Pourquoi pas de nouvel event en V1

Le `ToolCalledEvent` existant (`agent.py:128-137`) est déjà émis pour **chaque** appel de tool, avec `agent_id`, `task_id`, `tool_name`, `arguments`, `result`, `latency_ms`. Pour `ask_human` :
- `arguments = {"question": "..."}` — la question posée,
- `result = "<réponse humaine>"` — la réponse,
- `latency_ms` = **temps de réponse de l'humain** (le `fn` bloque pendant l'attente).

→ « HITL émis dans la trace » (exigence de la carte) est **satisfait sans rien ajouter**. Le dashboard filtre `tool_name == "ask_human"` pour un rendu HITL distinct.

Un `HITLEvent` dédié exigerait soit un special-case de `execute()` sur un nom de tool magique (couplage runtime↔tool, à éviter), soit une closure run-scoped portant `task_id`/`agent_id` (inconnus au build). Le coût/bénéfice ne le justifie pas en V1. À reconsidérer en V2 si une sémantique riche (état pending, SLA d'attente) est voulue.

## 6. Extensibilité V2 (agents → non-agents) — conçu, pas implémenté

Décision Quentin : agents seuls en V1, mais « que les non-agents pertinents puissent l'utiliser plus tard n'est pas incohérent ». Le design V1 garde la porte ouverte sans la franchir :

- Le callback vit sur `RunContext.hitl_callback` (§4.2), **pas seulement** dans la closure du tool. Un futur call-site non-agent (divider/aggregator/judge) lira `ctx.hitl_callback` directement.
- `make_ask_human_tool` reste le builder unique : si un jour un de ces call-sites gagne une boucle tool-use, il réutilise le builder tel quel.
- Aucune de ces extensions n'exige de revenir sur le seam V1.

## 7. Invariants à ne pas briser

- **Runtime synchrone intact** : `agent.execute()`, `run_task`, `run_with_recovery` — aucune signature ni comportement modifié. `ask_human` est un `ToolDef` comme un autre, borné par `MAX_TOOL_ROUNDS`.
- **Rétrocompat V1/V2/V3** : tout champ/param ajouté est optionnel/default ; sans `hitl_callback` ni tool `ask_human`, comportement identique.
- **Démo figée** : `run --scenario` et `demo/incident/*` inchangés (pas de `ask_human`).
- **Night-run safe** : un roster portant `ask_human` exécuté sans humain dégrade via `unattended_callback`, jamais de blocage.
- **Tracer = observer découplé** : on réutilise `ToolCalledEvent`, le runtime ne juge/n'imprime pas l'échange HITL lui-même.
- **`ToolDef.fn` reste `(**args) -> str`** : le callback ne fuite jamais dans les args LLM (closure).
- **Imports absolus**, timestamps UTC, Pydantic v2 `extra="forbid"`, `RunContext` reste cohérent.

## 8. Découpe en unités (ordre de plan TDD)

1. **`core/hitl.py`** — `make_ask_human_tool`, `unattended_callback`, `ASK_HUMAN_TOOL_NAME`. Tests : closure capture le callback ; `None` → sentinelle ; `fn(question=...)` retourne la réponse ; schéma `to_openai()` valide. *Pur, nuit-compatible.*
2. **`RunContext.hitl_callback`** — champ optionnel default `None` ; rétrocompat (construction sans le champ inchangée). *Pur.*
3. **`build_builtin_tools` + fusion au chargement** (`config/`) — built-ins fusionnés au registre roster ; collision de nom réservé → `ValueError` ; agent déclarant `ask_human` le résout. *Pur, nuit-compatible.*
4. **Boucle tool-use bout-en-bout avec `ask_human`** — fake `LLMProvider` qui émet un `tool_calls` `ask_human` puis un `stop` ; assert : `fn` appelé avec la question, réponse réinjectée, `ToolCalledEvent` émis (`tool_name="ask_human"`, args/result corrects). *Backend pur, sans LLM réel.*
5. **`solve_once(hitl_callback=...)`** — callback posé sur `ctx` + propagé aux built-ins ; chemin non-interactif (sentinelle) testé avec roster temp + fake provider. *Pur testable.*
6. **Wiring `app.solve --hitl`** — `--hitl` → callback stdin ; `--no-hitl` → sentinelle. Testé via `CliRunner` + monkeypatch `solve_once` (assert le callback choisi). *CLI testable sans LLM réel.*

DoD nuit possible pour 1-6 (TDD, fake provider). Le **smoke LLM réel** (ollama, roster jouet avec un agent qui appelle `ask_human` en mode `--hitl`) = sign-off Quentin au matin.

## 9. DoD

- Suite complète verte via le venv (`.venv\Scripts\python -m pytest`).
- Un agent portant `ask_human` peut, en cours de run, poser une question → réponse réinjectée → run termine ; échange visible dans `trace.jsonl` (`ToolCalledEvent` `ask_human`).
- `aaosa solve --hitl` interactif (stdin) ; `--no-hitl` dégrade sans bloquer.
- `run --scenario {main|roster_gap}` inchangé (régression zéro), suite V1 verte.
- Smoke réel (matin) : roster jouet, un agent appelle `ask_human`, l'opérateur répond, le run aboutit.

## 10. Points laissés ouverts (à confirmer au moment du plan)

- **Dépendance d'ordre avec `erd`** : §4.3/4.4 supposent `config/roster.py` + `solve_once` (livrés par `erd`, mergés master). Confirmé présents → `ipv` s'y branche ; le fallback (`load_agents` direct) couvre le cas contraire.
- **Nom CLI du flag** : `--hitl` proposé (vs `--interactive`). Cosmétique.
- **Texte de la sentinelle** : proposé en §4.1, ajustable.

Hors ces points cosmétiques, spec prête pour le plan TDD.
