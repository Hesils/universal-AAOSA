# Spec `erd` — Commande `aaosa solve` (task libre + N rosters injectés)

> Statut : **proposée** (à valider par Quentin avant plan TDD).
> Ticket : `erd` (P2, épique `aaosa-subbrain`, gate-INDÉPENDANT).
> Source de vérité du cadrage : `seconde_brain/raw/brainstorms/2026-06-17-erd-cli-task-libre-rosters.md` + décision loggée `Projects/universal-AAOSA/decisions.md` (2026-06-17).

## 1. Objectif

Donner à AAOSA une commande CLI qui résout une **tâche libre** avec un ou plusieurs **rosters injectés depuis des chemins arbitraires**, en restant agnostique au domaine. C'est la brique côté AAOSA qui rend le runtime utilisable comme moteur agentic du sub-brain AIOS (l'AIOS — ticket `fqd` — saura où vivent ses rosters et appellera cette commande).

Aujourd'hui `aaosa run --scenario {main|roster_gap}` est **figé** sur le monde incident démo (`_ROSTERS` hardcodé, `build_data_leak_task()` hardcodé, prompts « incident », `provider_registry=None`). `erd` ajoute une commande **à côté**, sans toucher la démo.

## 2. Périmètre

**Dans `erd`** :
1. Nouvelle commande `aaosa solve` (la démo `run --scenario` reste intacte).
2. Chargement de **N rosters** depuis des dossiers (`--roster <dir>` répétable) : `agents.yaml` + `tools.py` optionnel.
3. **Task libre** (`--task`) + contexte (`--context-text` / `--context-file`) → `Task.context`, avec **refus dur sur overflow** (`--context-max`).
4. Câblage du `provider_registry` dans `RunContext` (active la résolution provider-par-agent **déjà codée** en aval), défaut run = **ollama**.
5. Prompts génériques (divider / aggregator / tagger) domain-agnostic.
6. Persistance trace/session en parité `run_once` + ELO snapshot **mono-store** (`--runs-root`).
7. **Manifest** dérivé de la trace (`manifest.json` + résumé stdout + lien trace).

**Hors `erd`** (sous-tickets déjà créés, `blocked_by: erd`) :
- `cnq` — `--context-dir` (arborescence injectée, agents fetchent via tools).
- `alf` — preflight dispo du model par agent dans son provider.
- `u9l` — provider/model **par rôle système** (divider/aggregator/tagger/evaluator).
- `fqd` (AIOS, non bloqué) — pont d'injection AIOS→AAOSA + persistance **par-roster** (multi-`apply_snapshot` au load, re-partition au save). `erd` garde le save/load **mono-store** tel quel.

## 3. Contrat CLI — `aaosa solve`

```
aaosa solve
  --roster <dir>          # répétable, ≥1 obligatoire
  --task <str>            # description libre, obligatoire
  --context-text <str>    # optionnel, exclusif/cumulable avec --context-file
  --context-file <path>   # optionnel, lu en UTF-8
  --context-max <int>     # défaut 20000 (caractères) ; refus dur si dépassé
  --provider <str>        # défaut "ollama" ; "ollama"|"openai" seuls
  --runs-root <dir>       # défaut Path("runs")
```

- `--context-text` et `--context-file` se **concatènent**, chacun préfixé d'un en-tête de provenance `# context: <source>` (`<source>` = `inline` pour `--context-text`, le chemin pour `--context-file`), résultat → `Task.context`. Aucun contexte fourni → `Task.context = None`.
- **Overflow** : `len(context) > context_max` → message d'erreur clair + `raise typer.Exit(code=1)`. **Jamais de troncature** (une résolution défaillante silencieuse est pire qu'un refus). Défaut `context_max = 20000` caractères.
- Sortie stdout : message de résultat (outcome + résumé) + chemins (session, trace, `manifest.json`).
- Codes de sortie : alignés sur `run` (0 nominal ; la DoD fonctionnelle est portée par l'AIOS au passage de la tâche).

## 4. Changements runtime — par module

### 4.1 `src/aaosa/config/roster.py` (nouveau)

Chargement d'un roster = dossier contenant `agents.yaml` + (optionnel) `tools.py`.

```python
def load_roster(directory: Path) -> list[Agent]:
    """Charge UN roster : agents.yaml résolu contre le TOOL_REGISTRY de son tools.py.
    Registre cloisonné (les agents ne résolvent QUE les tools de leur roster)."""

def load_rosters(directories: list[Agent]) -> list[Agent]:
    """Charge N rosters et fusionne en une liste d'agents. Collision de noms
    d'agents entre rosters -> ValueError (clé ELO = name, doit être unique)."""
```

- **Convention `tools.py`** : importé via `importlib.util` (chargement par chemin de fichier), doit exposer un symbole **`TOOL_REGISTRY: dict[str, ToolDef]`** (pas d'auto-scan). Absent + agents déclarant `tools:` → erreur claire (déjà levée par `load_agents` : « declares tools but no tool_registry was provided »). Symbole présent mais pas un `dict[str, ToolDef]` → erreur claire.
- `tools.py` absent → roster sans tools (registry vide passé à `load_agents` ; agents sans `tools:` OK, agents avec `tools:` → erreur claire).
- **Cloisonnement** : `load_roster` appelle `load_agents(dir/"agents.yaml", registry_de_ce_roster)`. On NE fusionne PAS les registries entre rosters.
- **Hypothèse `erd` = rosters de confiance** : importer `tools.py` exécute du code au load — acceptable (auteur = Quentin/AIOS). Sandbox/non-destruction = `v1m`.

### 4.2 `src/aaosa/runtime/default_prompts.py` (nouveau)

Prompts génériques run-level, repris de `demo/incident/prompts.py` avec « incident » → « task ».

```python
DIVIDER_PROMPT = (...)      # identique à l'actuel (déjà domain-agnostic)
AGGREGATOR_PROMPT = (...)   # "...complete answer to the original task." (était "incident")
TAGGER_PROMPT = (...)       # identique à l'actuel
```

Override par fichier custom = YAGNI (sous-ticket si besoin). `demo/incident/prompts.py` reste inchangé (la démo garde ses prompts « incident »).

### 4.3 `src/aaosa/runtime/provider_registry.py` (nouveau)

```python
def build_provider_registry(
    agents: list[Agent], default_provider: str = "ollama"
) -> tuple[LLMProvider, dict[str, LLMProvider]]:
    """Construit le provider par défaut du run + le registre par nom.
    Noms distincts = {default_provider} ∪ {a.provider for a in agents if a.provider}.
    Chaque nom -> create_provider(nom) (lève déjà sur nom != ollama|openai).
    Retourne (provider_defaut, registry)."""
```

- **Défaut projet AAOSA = `ollama`** (gratuit), surchargé par `--provider`.
- Seuls `ollama`/`openai` acceptés (enforcé par `create_provider`).
- Le registre est passé à `RunContext.provider_registry` → la résolution par-agent déjà codée (`run_task` l.64-66, `run_with_recovery`→`run_task` l.502) s'active sans autre changement.
- Config par-provider avancée (base_url custom, model par défaut) = tickets ultérieurs. Preflight dispo model = `alf`.

### 4.4 `src/aaosa/runtime/runner.py` — extraire `build_root_task` (option C)

La logique « tague la description (ou applique `pinned_tags`) et construit la `Task` racine » est extraite de `run_recovery` en une fonction partagée, pour que `run_recovery` ET `solve_once` aient la `Task` (id connu) sur le **même** chemin de tagging.

```python
def build_root_task(
    description: str,
    ctx: RunContext,
    *,
    pinned_tags: dict[str, int] | None = None,
    context: str | None = None,
) -> Task:
    """Tague la racine (ou applique pinned_tags), construit la Task avec context.
    Lève EmptyTaggingError si le tagging ne produit aucun tag (caller décide
    de la dégradation : run_recovery -> execution_failed)."""
```

- `run_recovery` devient un emballage mince : `task = build_root_task(...)` (avec gestion `EmptyTaggingError` → `DispatchResult(execution_failed)`, comportement actuel l.528-533) puis `run_with_recovery(task, ctx)`. Gagne au passage un param `context` threadé via `build_root_task`. **Rétrocompat stricte** : signatures actuelles préservées (params nouveaux optionnels/defaults).
- `solve_once` appelle `build_root_task(task_text, ctx, context=context)` → obtient la `Task` (id connu) **avant** d'écrire le meta provisoire, puis `run_with_recovery(task, ctx)`. Zéro duplication, meta correct (id stable matché aux events).
- Le mode d'échec tagging (`EmptyTaggingError`) est levé par `build_root_task` ; chaque caller le traduit (run_recovery → `execution_failed` ; solve → message clair + `Exit(1)`).

### 4.5 `src/aaosa/runtime/manifest.py` (nouveau) — fonction pure dérivée de la trace

Respecte « tracer = observer découplé » (post-hoc, comme `classify_run`).

```python
class ToolCallRecord(BaseModel):   # extract de ToolCalledEvent
    agent_id: str
    tool_name: str
    arguments: dict
    result: str

class FinalOutputRecord(BaseModel):
    task_id: str
    agent_id: str
    content: str

class Manifest(BaseModel):
    outcome: str                       # kind du run (success|qa_fail|unassigned)
    typologies: list[str]              # = classify_run(events)
    final_outputs: list[FinalOutputRecord]
    tool_calls: list[ToolCallRecord]
    roster_gaps: list[str]             # tags non couverts (RosterGapEvent) -> signal création agent
    trace_path: str                    # chemin relatif session_dir/trace.jsonl

def build_manifest(
    events: Sequence[ClaimEvent],
    result: Output | DispatchResult | QAFailure,
    trace_path: Path,
) -> Manifest: ...
```

- `tool_calls` : tous les `ToolCalledEvent` (agent, tool, args, retour). « tool-calls déclarés », pas FS-diff (effets réels = plus tard, lié `v1m`).
- `final_outputs` : l'`Output` terminal (livrable). Source = `result` si `Output`, sinon dérivé du dernier `ExecutedEvent`/`TaskAggregatedEvent` (run divisé). Un run sans Output attribué → liste vide + outcome reflète `unassigned`/`qa_fail`.
- `roster_gaps` : `missing_tags` des `RosterGapEvent`. **Pas un bug** : signal pour l'AIOS de créer un agent.
- `graph` : `typologies` (via `classify_run`) suffit comme résumé du graphe émergent ; pas de re-sérialisation des sous-tâches (déjà dans la trace).
- Persistance : `manifest.json` dans `session_dir`. Lien trace primaire = `session_dir/trace.jsonl` (offline) ; URL dashboard en bonus stdout.

### 4.6 `src/aaosa/cli/solve_runs.py` (nouveau) — helper pur (zéro print)

Parallèle à `incident_runs.run_once`, partage le **scaffolding session/meta/tracer/snapshot** factorisé (voir §4.7).

```python
@dataclass(frozen=True)
class SolveOutcome:
    kind: RunKind
    session_id: str
    session_dir: Path
    snapshot_path: Path
    manifest_path: Path
    events: list[ClaimEvent]
    task_description: str
    n_agents: int

def solve_once(
    roster_dirs: list[Path],
    task_text: str,
    context: str | None,
    runs_root: Path,
    provider_name: str = "ollama",
) -> SolveOutcome: ...
```

Séquence (l'ordre place le tracer/ctx **avant** `build_root_task`, car le tagging passe par `ctx.tagger` ; le tagger n'émet aucun event → le meta provisoire écrit juste après reste antérieur au run) :
1. `agents = load_rosters(roster_dirs)` ; `provider, registry = build_provider_registry(agents, provider_name)`.
2. `load_elo_into(agents, runs_root)` (mono-store, inchangé).
3. `session_dir` + `StreamingTracer(stream_path=session_dir/"trace.jsonl")`.
4. `ctx = RunContext(agents, provider, divider, aggregator, tagger, tracer, evaluator=AdaptiveSpecEvaluator(provider), provider_registry=registry)` avec prompts **génériques** (`default_prompts`).
5. `task = build_root_task(task_text, ctx, context=context)` (§4.4) → **id connu**. `EmptyTaggingError` → message clair + `Exit(1)`.
6. Scaffolding partagé (§4.7) : meta provisoire `status="running"` (avec le `SessionTaskRecord` du `task`), registre agents.
7. `result = run_with_recovery(task, ctx)` (mêmes garanties de containment que `run_once` : crash → meta finalisé `complete`/`unassigned`, `tracer.close()` en `finally`).
8. Finalisation : meta `complete` + `_META_OUTCOME[kind]`, `save_session`, `save_snapshot` (mono-store).
9. `manifest = build_manifest(tracer.events, result, session_dir/"trace.jsonl")` → écrit `manifest.json`.

> `solve_once` et `run_recovery` partagent le chemin de tagging+build via `build_root_task` (§4.4, option C) ; `solve` appelle ensuite `run_with_recovery` directement pour disposer de l'id du `task` au moment d'écrire le meta provisoire (parité live-mode).

### 4.7 `src/aaosa/cli/incident_runs.py` — factorisation du scaffolding

Extraire de `run_once` le bloc commun **session_dir + meta provisoire + registre + tracer + finalisation (save_session + snapshot)** en un helper partagé (p.ex. `_persisted_run(agents, task, build_ctx, runs_root) -> (result, session_dir, snapshot_path, tracer)` où `build_ctx(tracer) -> RunContext`). `run_once` et `solve_once` l'utilisent.

**Contrainte de rétrocompat dure** : `aaosa run --scenario` doit rester **bit-identique** en comportement. La suite existante (~252 tests V1 + suite globale, 1073 au dernier merge d6i) reste verte. La factorisation est mécanique, pas un changement de comportement.

### 4.8 `src/aaosa/cli/app.py` — wiring `solve`

Nouvelle commande Typer `solve` : lit les options (§3), assemble `context` (concat text+file + en-têtes provenance), applique le garde-fou overflow (`Exit(1)`), appelle `solve_once`, imprime le résultat (outcome, `session_dir`, `trace.jsonl`, `manifest.json`). `load_dotenv()` conservé (OpenAI si `--provider openai`).

## 5. Invariants à ne pas briser

- **Démo figée** : `run --scenario` et `demo/incident/*` inchangés.
- **Rétrocompat V1/V2/V3** : tout champ/param ajouté est optionnel/default ; sans tools ni évaluateur = comportement identique.
- **Le graphe émerge** : aucune découpe hardcodée ; `unassigned`/`roster_gap` = signal (remonté au manifest), pas un bug.
- **Tracer = observer découplé** : `build_manifest` est une fonction **pure** post-hoc, le runtime n'imprime/ne juge jamais lui-même.
- **ELO clé par `name`** : collision de noms d'agents inter-rosters = erreur dure.
- **TaskDivider/TaskAggregator ne sont pas des Agent** ; agrégation porte `agent_id="aggregator"`.
- **Imports absolus**, timestamps UTC `datetime.now(timezone.utc)`, Pydantic v2 `extra="forbid"`.
- **Seuls `ollama`/`openai`** acceptés (enforcé par `create_provider`).

## 6. Découpe en unités (ordre de plan TDD)

1. **`load_roster` / `load_rosters`** (`config/roster.py`) — tools.py via importlib + `TOOL_REGISTRY`, cloisonnement, collision de noms. *Pur, nuit-compatible.*
2. **`default_prompts`** — 3 constantes génériques. *Trivial.*
3. **`build_provider_registry`** — noms distincts → providers, défaut ollama. *Pur (pas d'appel LLM, juste construction d'objets).* 
4. **`build_root_task` + `run_recovery` refactoré** (option C) — extraction tag+build partagée, `run_recovery` devient emballage, gagne `context` ; rétrocompat unitaire. *Pur.*
5. **`build_manifest` + modèles** (`manifest.py`) — dérivation depuis events factices. *Pur, nuit-compatible.*
6. **Factorisation scaffolding** (`incident_runs._persisted_run`) — `run_once` refactoré, suite existante verte. *Refactor sous filet de tests.*
7. **`solve_once`** (`solve_runs.py`) — orchestration, testée avec un provider factice (fake LLMProvider) + roster temp sur disque. *Backend pur testable sans LLM réel.*
8. **Wiring `app.solve`** — assemblage contexte, garde-fou overflow, sortie. Testé via `typer.testing.CliRunner` + monkeypatch `solve_once`.

DoD nuit possible pour 1-7 (TDD, fake provider). Le **smoke LLM réel** (ollama local, roster jouet) = sign-off Quentin au matin.

## 7. DoD

- Suite complète verte via le venv (`.venv\Scripts\python -m pytest`).
- `aaosa solve --roster <jouet> --task "..."` produit : session persistée, `trace.jsonl`, `manifest.json` cohérent (outcome + tool-calls + roster_gaps), snapshot ELO mono-store.
- `run --scenario {main|roster_gap}` inchangé (régression zéro).
- Smoke réel ollama (matin) : un roster jouet résout une tâche libre de bout en bout.

## 8. Décisions tranchées & points laissés ouverts

**Tranché** (décision log 2026-06-17, ne pas re-litiger) : commande dédiée (pas d'extension de `run`) · frontière `erd` (multi-roster côté AAOSA) / `fqd` (côté AIOS) · convention `TOOL_REGISTRY` explicite · refus dur sur overflow · défaut ollama · manifest = fonction pure dérivée de la trace · prompts génériques run-level · persistance mono-store dans `erd`, par-roster dans `fqd` · write-back ELO yaml écarté.

**Validé (2026-06-17)** :
- (a) **Option C** — extraire `build_root_task` partagé par `run_recovery` et `solve_once` ; `solve` appelle `run_with_recovery` pour avoir l'id du `task` au moment du meta provisoire (§4.4, §4.6).
- (b) `--context-max` défaut = **20000** caractères.
- (c) En-tête de provenance = **`# context: <source>`** (`inline` ou chemin).

Plus aucun point ouvert — spec prête pour le plan TDD.
