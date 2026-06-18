# u9l — provider/model par rôle système · Plan d'implémentation

> Ticket `u9l` #universal-AAOSA #epic/aaosa-subbrain. Rendre configurable le provider/model
> des LLM **non-agent** (divider, aggregator, tagger, evaluator + diagnostic, triage,
> task_spec_generator), aujourd'hui tous câblés sur `ctx.provider` (le défaut du run).
> Design symétrique-avec-Agent : curseur de coût (agents Ollama local, rôles système modèle
> plus fort). Surface de config = fichier `roles.yaml`. Périmètre = **tous les non-agents**.

## Contexte & état des lieux

- `Agent` porte déjà `provider: str | None` + `model: str | None` (d6i). Résolu dans
  `run_task` (`src/aaosa/runtime/runner.py:64-66`) :
  `exec_provider = provider_registry.get(winner.provider, provider)` puis `model=self.model`
  passé à `provider.complete/parse`. **C'est le pattern de référence à mimer.**
- `build_provider_registry(agents, default="ollama")` (`src/aaosa/runtime/provider_registry.py`)
  construit `{default} ∪ {a.provider for a in agents}` → `(provider_défaut, registry)`. Il ne
  scanne **que les agents**.
- `LLMProvider.complete(*, messages, model=None, tools=None)` et
  `.parse(*, messages, schema, model=None)` : `model=None` → modèle par défaut du provider.
  Tout est déjà prêt côté seam — il ne manque que de **router un `model` et un provider par rôle**.
- Composants non-agent et leur consommation actuelle de `ctx.provider` :
  - `TaskDivider.divide(task, provider, ...)` → `provider.parse(...)` (`runtime/divider.py`)
  - `Tagger.tag(description, agents, provider)` → `provider.parse(...)` (`runtime/tagger.py`)
  - `TaskAggregator.aggregate(parent, sub_outputs, provider, tracer)` → `provider.complete(...)` (`runtime/aggregator.py`)
  - `diagnose_failure(task, output, qa_result, provider)` → `provider.parse(...)` (`qa/diagnostic.py`)
  - `AdaptiveSpecEvaluator(provider, failure_context=None)` → `build_llm_spec(task, provider, fc)` + `SpecEvaluator(spec, client=provider)` (`qa/spec_evaluator.py`, `qa/adaptive.py`)
  - `SpecEvaluator` passe `provider` aux critères (`llm_check`, via `{**c.params, "provider": self.provider}`) et à `run_judge`.
  - `triage_case/triage_unattributed(case|test_set, provider)` (`qa/triage.py`) — batch
  - `fix_task_spec/fix_task_spec_cases(case|test_set, provider)` (`qa/task_spec_generator.py`) — batch
  - Seul appelant batch de triage/task_spec : `demo/run_health_check_v3.py`.
- **Le juge garde son propre modèle** via `EvaluatorSpec.judge` → `run_judge(..., model=spec.model)`
  (`qa/judge.py:69`). Invariant V2b (poids 0.3, jamais signal primaire). **Ne pas y toucher** :
  le "model evaluator" du rôle s'applique à la génération de spec (`build_llm_spec`) et au
  critère `llm_check`, **pas** au juge.
- RunContext (`runtime/context.py`) : `@dataclass(frozen=True)` portant agents, provider,
  divider, aggregator, tagger, tracer, evaluator, provider_registry. Construit en 2 endroits :
  `cli/incident_runs.run_once.build_ctx` (sans registry/roles) et `cli/solve_runs.solve_once`
  (registry câblé).

## Décision d'architecture (verrouillée)

Mécanisme unique et uniforme, fidèle au pattern Agent :

1. **`RoleProviders`** (config) porte, par rôle, un `RoleProvider(provider: str | None, model: str | None)`.
   Chargé d'un `roles.yaml` (mapping, tout optionnel). Vide = comportement actuel identique.
2. **`resolve_provider(name, registry, default) -> LLMProvider`** : helper unique partagé par
   la résolution agent (`run_task`) ET la résolution rôle. `name` falsy ou pas de registry → `default`.
3. **`RunContext` porte `roles: RoleProviders`** (défaut vide) + méthode
   `resolve_role(name) -> (LLMProvider, str | None)` qui applique `resolve_provider` sur le
   registre + retourne le `model` du rôle.
4. **Les méthodes des composants gagnent un param `model: str | None = None`** passé tel quel à
   `provider.parse/complete`. Rétrocompat : `model=None` = défaut provider = comportement actuel.
5. Le **runner** résout chaque rôle via `ctx.resolve_role(...)` au lieu de passer `ctx.provider` nu.

## Global Constraints (lues par chaque reviewer)

- **Rétrocompat stricte** : sans `roles.yaml` (RoleProviders vide), tout champ optionnel/None →
  comportement V1/V2/V3 **identique**. Baseline = **1097 passed, 1 skipped** ; doit le rester
  (plus les tests neufs de chaque tâche).
- Imports **absolus** uniquement (`from aaosa.…`).
- Pydantic v2, `model_config = ConfigDict(extra="forbid")` sur tout nouveau modèle.
- Le **juge** n'est PAS reconfiguré ici (`run_judge` garde `model=spec.model`). Le model du rôle
  evaluator s'applique à `build_llm_spec` + critère `llm_check` uniquement.
- `resolve_provider` est l'unique point de résolution nom→provider : `run_task` (agents) doit
  être refactoré pour l'utiliser (pas de logique dupliquée).
- Tracer reste observer découplé ; aucun changement de sémantique de signature publique au-delà
  de l'ajout de params optionnels.
- Tests via le venv : `.venv\Scripts\python -m pytest <fichier> -v`.
- TDD : test avant impl, 1 tâche = 1 commit.

---

## Task 1: Schéma + loader `RoleProviders` (roles.yaml)

**Fichier neuf** : `src/aaosa/config/role_providers.py`. **Tests** : `tests/config/test_role_providers.py`.

Modèles Pydantic v2 (`extra="forbid"`) :

```python
class RoleProvider(BaseModel):
    provider: str | None = None   # nom de provider (ollama|openai) ; None = défaut du run
    model: str | None = None      # None = modèle par défaut du provider

class RoleProviders(BaseModel):
    divider: RoleProvider = Field(default_factory=RoleProvider)
    aggregator: RoleProvider = Field(default_factory=RoleProvider)
    tagger: RoleProvider = Field(default_factory=RoleProvider)
    evaluator: RoleProvider = Field(default_factory=RoleProvider)
    diagnostic: RoleProvider = Field(default_factory=RoleProvider)
    triage: RoleProvider = Field(default_factory=RoleProvider)
    task_spec: RoleProvider = Field(default_factory=RoleProvider)
```

Loader, calqué sur `config/loader.py` (même style d'erreurs `ValueError`) :

```python
def load_role_providers(path: Path | None) -> RoleProviders:
    """Charge un roles.yaml (mapping rôle -> {provider?, model?}). path None ou
    fichier absent -> RoleProviders() vide (comportement par défaut). YAML malformé,
    non-mapping, rôle inconnu, ou champ invalide -> ValueError."""
```

Comportement à tester :
- `path=None` → `RoleProviders()` vide (tous rôles `RoleProvider()`).
- fichier absent → `ValueError` (cohérent avec `load_agents`) **OU** vide — **choix** : path explicite
  pointant un fichier absent = `ValueError` ; `None` = vide. (Aligne sur `load_agents` qui lève sur absent.)
- mapping valide partiel (`{"divider": {"provider": "openai", "model": "gpt-4o"}, "evaluator": {"model": "gpt-4o-mini"}}`)
  → champs correspondants peuplés, autres vides.
- clé de rôle inconnue (`{"foo": {...}}`) → `ValueError` explicite (mentionne la clé). `extra="forbid"` couvre ça.
- YAML qui n'est pas un mapping (liste, scalaire) → `ValueError`.
- YAML vide (`None` après parse) → `RoleProviders()` vide.

DoD : `tests/config/test_role_providers.py` vert, suite globale verte.

---

## Task 2: `resolve_provider` helper + `build_provider_registry(roles=...)` + refactor `run_task`

**Fichier** : `src/aaosa/runtime/provider_registry.py`. **Tests** :
`tests/runtime/test_provider_registry.py` (étendre l'existant s'il y en a un, sinon créer) +
ajustement `tests/runtime/test_runner*.py` si la résolution agent y est testée.

1. Ajouter le helper :

```python
def resolve_provider(
    name: str | None,
    registry: dict[str, LLMProvider] | None,
    default: LLMProvider,
) -> LLMProvider:
    """Résout un nom de provider en LLMProvider via le registre. name falsy ou
    registre absent -> default. Nom absent du registre -> default (pas d'erreur)."""
    if name and registry:
        return registry.get(name, default)
    return default
```

2. Étendre `build_provider_registry` pour scanner aussi les providers nommés dans un
   `RoleProviders` (sinon un rôle sur un provider qu'aucun agent n'utilise serait absent du
   registre → résolution silencieuse sur default) :

```python
def build_provider_registry(
    agents: list[Agent],
    default_provider: str = "ollama",
    roles: "RoleProviders | None" = None,
) -> tuple[LLMProvider, dict[str, LLMProvider]]:
    names = {default_provider}
    names.update(a.provider for a in agents if a.provider)
    if roles is not None:
        names.update(
            rp.provider for rp in (roles.divider, roles.aggregator, roles.tagger,
                                   roles.evaluator, roles.diagnostic, roles.triage,
                                   roles.task_spec) if rp.provider
        )
    registry = {name: create_provider(name) for name in sorted(names)}
    return registry[default_provider], registry
```

   (Import `RoleProviders` depuis `aaosa.config.role_providers`. Vérifier l'absence de cycle —
   `config/role_providers.py` n'importe rien de `runtime`.)

3. **Refactor** `run_task` (`runtime/runner.py:64-66`) pour utiliser `resolve_provider` au lieu
   de la logique inline (DRY, point de résolution unique) :
   `exec_provider = resolve_provider(winner.provider, provider_registry, provider)`.

Tests : `resolve_provider` (4 cas : name+registry hit, name+registry miss→default, name sans
registry→default, name None→default). `build_provider_registry` avec `roles` portant un provider
absent des agents → présent dans le registre. Comportement `run_task` inchangé (suite verte).

DoD : tests verts, suite globale verte (mock `create_provider` pour éviter tout réseau).

---

## Task 3: Param `model` sur divider / tagger / aggregator

**Fichiers** : `runtime/divider.py`, `runtime/tagger.py`, `runtime/aggregator.py`.
**Tests** : `tests/runtime/test_divider*.py`, `tests/runtime/test_tagger*.py`,
`tests/runtime/test_aggregator*.py` (ajouter un cas "model transmis" via fake provider chacun).

Ajouter `model: str | None = None` aux signatures et le passer au seam :
- `TaskDivider.divide(self, task, provider, chained_context=None, failure_context=None, cycle_context=None, model=None)`
  → `provider.parse(..., schema=DivisionResult, temperature=0.0, model=model)`.
- `Tagger.tag(self, description, agents, provider, model=None)`
  → `provider.parse(..., schema=TagSet, temperature=0.0, model=model)`.
- `TaskAggregator.aggregate(self, parent_task, sub_outputs, provider, tracer=None, model=None)`
  → `provider.complete(messages=..., model=model)`.

Rétrocompat : `model=None` = comportement actuel. Tests existants inchangés (param optionnel en
dernière position). Nouveau test par composant : un `MagicMock(spec=LLMProvider)` vérifie que
`model="X"` est bien relayé dans l'appel `parse`/`complete`.

DoD : tests verts, suite globale verte.

---

## Task 4: Param `model` sur diagnostic / triage / task_spec_generator

**Fichiers** : `qa/diagnostic.py`, `qa/triage.py`, `qa/task_spec_generator.py`.
**Tests** : fichiers de tests miroirs correspondants.

Ajouter `model: str | None = None` et le relayer à `provider.parse(...)` :
- `diagnose_failure(task, output, qa_result, provider, model=None)`.
- `triage_case(case, provider, model=None)` ; `triage_unattributed(test_set, provider, model=None)`
  passe `model` à `triage_case`.
- `fix_task_spec(case, provider, model=None)` ; `fix_task_spec_cases(test_set, provider, model=None)`
  passe `model` à `fix_task_spec`.

Rétrocompat : param optionnel en dernière position, `None` = défaut. Nouveau test par fonction :
le `model` est relayé dans l'appel `parse`.

DoD : tests verts, suite globale verte.

---

## Task 5: Param `model` sur l'évaluateur (adaptive + spec_evaluator + llm_check)

**Fichiers** : `qa/adaptive.py`, `qa/spec_evaluator.py`, `qa/criteria.py`.
**Tests** : `tests/qa/test_adaptive*.py`, `tests/qa/test_spec_evaluator*.py`, `tests/qa/test_criteria*.py`.

But : que le model du rôle evaluator atteigne la **génération de spec** et le **critère llm_check**,
**sans** toucher le juge (`run_judge` garde `model=spec.model`).

1. `build_llm_spec(task, provider, failure_context=None, model=None)` → `provider.parse(..., model=model)`.
2. `criteria.llm_check` : lire `model = params.get("model")` et appeler `provider.parse(..., model=model)`.
   (Param optionnel ; absent → `None` → défaut. Ne pas casser les autres critères.)
3. `SpecEvaluator.__init__(self, spec, client=None, reference=None, model=None)` : stocker
   `self.model`. Dans `evaluate`, injecter le model dans les params passés aux critères :
   `{**c.params, "provider": self.provider, "model": self.model}` (aux 2 boucles gates + scored).
   **Ne PAS** passer `self.model` à `run_judge` (le juge garde `spec.model`).
4. `AdaptiveSpecEvaluator.__init__(self, client, failure_context=None, model=None)` : stocker
   `self.model` ; `evaluate` → `build_llm_spec(task, self.provider, self.failure_context, model=self.model)`
   et `SpecEvaluator(spec, client=self.provider, model=self.model)`.
5. `from_spec(spec, client=None, reference=None, model=None)` → relaie `model`.

Rétrocompat : tous params optionnels `None`. Tests neufs : model relayé jusqu'à `build_llm_spec`
et jusqu'au `provider.parse` de `llm_check` ; le juge n'est pas affecté (un test vérifie que
`run_judge` reçoit toujours `spec.model`, pas le model evaluator).

DoD : tests verts, suite globale verte.

---

## Task 6: `RunContext.roles` + `resolve_role` + câblage runner

**Fichiers** : `runtime/context.py`, `runtime/runner.py`. **Tests** : `tests/runtime/test_context*.py`
(neuf si besoin) + `tests/runtime/test_runner*.py`.

1. `RunContext` : ajouter `roles: RoleProviders = field(default_factory=RoleProviders)` (frozen
   dataclass → `field(default_factory=...)`, import `from dataclasses import field`). Ajouter :

```python
def resolve_role(self, name: str) -> tuple[LLMProvider, str | None]:
    """(provider effectif, model) pour un rôle, via resolve_provider + le registre.
    Rôle sans provider/model -> (provider défaut du run, None) = comportement actuel."""
    rp = getattr(self.roles, name)
    return resolve_provider(rp.provider, self.provider_registry, self.provider), rp.model
```

   (Import `RoleProviders` depuis `aaosa.config.role_providers`, `resolve_provider` depuis
   `aaosa.runtime.provider_registry`. Vérifier l'absence de cycle d'import.)

2. **Câbler tous les call-sites runner** qui passaient `ctx.provider` à un rôle, en résolvant via
   `ctx.resolve_role(...)` :
   - `build_sub_tasks` : `prov, m = ctx.resolve_role("tagger"); ctx.tagger.tag(spec.description, ctx.agents, prov, model=m)`
   - `build_root_task` : idem `tagger`.
   - `_divide_with_cycle_retry` : `prov, m = ctx.resolve_role("divider")` pour les appels `ctx.divider.divide(..., model=m)`.
   - `_divide_and_recover` : `prov, m = ctx.resolve_role("aggregator"); ctx.aggregator.aggregate(task, sinks, prov, ctx.tracer, model=m)`.
   - `_route_diagnostic` : `prov, m = ctx.resolve_role("diagnostic"); diagnose_failure(task, failure.output, failure.qa_result, prov, model=m)`.
     Et la reconstruction d'évaluateur : `eprov, emodel = ctx.resolve_role("evaluator");
     AdaptiveSpecEvaluator(eprov, failure_context=fc, model=emodel)`.
   - `run_task` / `_retry_with_consignes` : **inchangés** (agents résolus via `provider_registry`
     déjà ; l'évaluateur consommé est `ctx.evaluator`, construit par le CLI — voir Task 7).

   NB : `ctx.provider` reste le défaut passé à `run_task` pour les agents — ne pas le retirer.

Tests : un `RunContext` avec un `RoleProviders` ciblant divider/tagger/aggregator/diagnostic/evaluator
sur des providers nommés (registry de fakes) → `resolve_role` rend le bon fake + le bon model.
Test d'intégration runner (fakes) : un run divisé utilise le provider divider configuré pour la
division et le provider tagger pour le tag (vérifié via les fakes). Rétrocompat : RunContext sans
`roles` → tout passe par `ctx.provider` (suite verte).

DoD : tests verts, suite globale verte.

---

## Task 7: Câblage CLI `solve` + évaluateur résolu + batch health-check + roles.yaml exemple

**Fichiers** : `cli/solve_runs.py`, `cli/app.py`, `cli/incident_runs.py`,
`demo/run_health_check_v3.py`, + un `roles.yaml` exemple commenté (ex.
`src/aaosa/demo/incident/roles.example.yaml` ou `docs/`). **Tests** :
`tests/cli/test_solve_runs*.py`, `tests/cli/test_app*.py` (selon existants).

1. `solve_once(roster_dirs, task_text, context, runs_root, provider_name="ollama", roles_path: Path | None = None)` :
   - `roles = load_role_providers(roles_path)`.
   - `provider, registry = build_provider_registry(agents, provider_name, roles=roles)`.
   - Résoudre l'évaluateur : `eprov, emodel = resolve_provider(roles.evaluator.provider, registry, provider), roles.evaluator.model`
     → `evaluator=AdaptiveSpecEvaluator(eprov, model=emodel)`.
   - `RunContext(..., provider_registry=registry, roles=roles)` (passé à `pre_ctx`).
2. `cli/app.py solve` : ajouter `roles: Path | None = typer.Option(None, "--roles", help="roles.yaml (provider/model par rôle système)")`,
   le passer à `solve_once`. Erreur de chargement roles → `ValueError` → `typer.Exit(1)` (déjà capté).
3. `cli/incident_runs.run_once.build_ctx` : reste fonctionnel sans roles (RunContext.roles défaut
   vide). Optionnel : pas de `--roles` sur `run`/`campaign` (hors scope ; l'évaluateur incident
   reste `AdaptiveSpecEvaluator(provider)`). Ne rien casser.
4. `demo/run_health_check_v3.py` : exposer la capacité de configurer triage/task_spec. Accepter un
   `roles: RoleProviders | None = None` (défaut None → vide) et résoudre :
   `tprov, tmodel = ...("triage")` / `("task_spec")` via `resolve_provider` + registry, passer
   `model=` à `triage_unattributed` / `fix_task_spec_cases`. Si le câblage registry y est lourd,
   au minimum passer le `model` du rôle (provider défaut) — garder le comportement actuel quand
   `roles=None`.
5. `roles.example.yaml` : fichier commenté illustrant le curseur de coût (agents ollama, rôles
   système sur openai modèle plus fort). Documenté mais non chargé par défaut.

Tests : `solve_once` avec un `roles_path` pointant un yaml ciblant l'évaluateur sur openai →
l'évaluateur construit porte le bon provider/model (mock `create_provider`). `solve_once` sans
`--roles` → comportement identique à avant. CLI `solve --roles <fichier>` parse l'option.

DoD : tests verts, suite globale verte. **DoD nuit-compatible** : aucun run LLM réel requis
(tout mocké) ; la validation LLM-réelle finale (curseur Ollama/OpenAI) est laissée à Quentin.

---

## Hors scope

- Validation LLM-réelle du curseur de coût (Quentin, review).
- `--roles` sur `run`/`campaign` (incident) : l'évaluateur incident reste sur le provider défaut.
- Préflight dispo modèle par provider (ticket `alf`, séparé).
- Reconfiguration du **juge** (garde `EvaluatorSpec.judge.model`, invariant V2b).
