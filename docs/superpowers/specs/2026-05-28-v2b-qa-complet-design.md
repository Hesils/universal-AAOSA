# V2b Design Spec — QA Complet (Evaluator composable + Boucle d'auto-amélioration)

_Date: 2026-05-28_
_Statut: Validated_

## Scope

V2b = "QA complet". Elle construit la couche d'évaluation sérieuse et la boucle d'auto-amélioration fermée, au-dessus des fondations V2a (QAEvaluator Protocol, QAResult, QAFailure, health check minimal).

**Dans le scope :**

1. **Couche evaluator composable** — registry de critères, evaluator-as-spec déclaratif, hybride gates déterministes + LLM-judge pondéré (2 modes).
2. **Boucle d'auto-amélioration fermée** — échec runtime → test set → health check de régression.
3. **Lifecycle des cas de test** — `fix_target` → `regression_guard` (le "train/test split" sous forme de statut, pas de tirage aléatoire).
4. **Attribution d'échec + routage** — un échec est attribué à l'agent / au task_spec / à l'evaluator ; routage en conséquence (champ + quarantaine). Triage manuel en V2b.
5. **Stretch** — sélection de critères adaptée à la tâche, **déterministe** (règles, pas de LLM).

**Hors scope (V3) :**

- Génération de l'`evaluator_spec` par un agent (V2b écrit les specs à la main ; la spec déclarative est le pont).
- TaskSpecGenerator + son intégration comme cible de la boucle de routage.
- Agent de triage qui automatise l'attribution.
- Train/test split par sampling aléatoire (abandonné après discussion).
- LLM-judge pairwise / calibration Spearman automatisée (documenté comme cap qualité, pas implémenté).

---

## Décisions prises

| Question | Décision |
|---|---|
| Représentation evaluator | Spec déclarative Pydantic (`EvaluatorSpec`), interprétée par un `SpecEvaluator` unique. Sérialisable JSON → pont V3. |
| Critères | Fonctions enregistrées dans un registry par nom. Chaque critère retourne un `CriterionOutcome` (granulaire, pas bool). |
| Gates vs scorés | Flag `gate: bool` sur `CriterionSpec`. Gate échoué → rejet immédiat, judge sauté (rejet gratuit). |
| LLM-judge | Conservé, mais jamais signal primaire. 2 modes : `rubric` (runtime, pas de référence) et `reference_based` (health check, variance réduite). Poids modeste, temperature 0. |
| Combinaison du score | Linéaire : `final = (1 - judge.weight) * det_score + judge.weight * judge.overall`. |
| Seuil de succès | `success_threshold` dans la spec → adaptable par tâche. Fixé avant les runs (pas de moving goalpost). |
| Référence du judge | Portée par le `TestCase` (health check). Injectée à la construction du `SpecEvaluator`, pas via le Protocol (signature stable). |
| Structure test set | `TestCase` promu de `tuple[Task, QAEvaluator]` → modèle Pydantic. Sérialisable car l'evaluator est une spec. |
| Boucle | Échec runtime → `TestCase(origin="runtime_failure")` → append + persist. Health check = gate de régression read-only sur l'ELO. |
| Non-déterminisme | Chaque case tourne `n_runs` fois (défaut 5). Métrique = **taux de réussite par case** (pas pass/fail unique). `pass_rate ∈ [0.4, 0.6]` → flag `unstable` (réviser rubrique/prompt, cf vault). |
| Lifecycle | `fix_target` (échec en cours de correction) → gradúe en `regression_guard` quand `case_pass_rate >= graduation_threshold` sur N runs (held-out honnête). |
| Attribution | Champ `attribution` sur `TestCase`. Routage : `agent` → lifecycle ; `task_spec` → quarantaine ; `evaluator` → réviser spec. Triage manuel V2b. |
| Backward compat | `QAEvaluator` Protocol inchangé. `SpecEvaluator` le satisfait. `BasicRuleEvaluator` conservé (baseline). Les 377 tests V1+V2a passent (sauf refactor interne `health_check` documenté). |

---

## 1. Couche evaluator composable

### 1.1 Outcome granulaire (dans `qa/criteria.py`)

```python
class CriterionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    score: float       # 0.0-1.0 — contribution granulaire (le "au-delà du bool")
    detail: str        # audit trail
```

### 1.2 Registry de critères

```python
Criterion = Callable[[Task, Output, dict], CriterionOutcome]

CRITERIA_REGISTRY: dict[str, Criterion] = {}

def register_criterion(name: str) -> Callable[[Criterion], Criterion]:
    """Décorateur. Enregistre une fonction critère sous `name`."""
```

Un critère résout par nom, reçoit ses `params`, retourne un `CriterionOutcome`. Découplé du `SpecEvaluator`.

### 1.3 Bibliothèque de critères livrée (V2b)

| Nom | Type | Params | Gate par défaut |
|---|---|---|---|
| `non_empty` | déterministe | — | oui |
| `min_length` | déterministe scoré | `min_chars` (def 50) | non |
| `references_tags` | déterministe scoré | `tags` (def = required_tags de la tâche) | non |
| `keyword_presence` | déterministe scoré | `keywords: list[str]` | non |
| `format_check` | déterministe | `kind: Literal["json","code_block","non_empty_lines"]` | oui |

Les 3 critères de `BasicRuleEvaluator` V2a (`non_empty`, `min_length`, `references_tags`) sont généralisés dans ce registry. `BasicRuleEvaluator` reste en place comme baseline démo.

### 1.4 Spec déclarative (dans `qa/spec.py`)

```python
class CriterionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str               # clé registry
    params: dict = {}
    weight: float = 1.0
    gate: bool = False      # True = must-pass, court-circuite le judge si échec

class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    model: str = "gpt-4o-mini"
    rubric: list[str]       # dimensions notées, ex ["correctness","completeness","relevance"]
    weight: float = 0.3     # modeste — les gates portent le poids
    temperature: float = 0.0
    instructions: str = ""

class EvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[CriterionSpec]
    judge: JudgeSpec | None = None
    success_threshold: float = 0.7
```

### 1.5 Résultat du judge (dans `qa/judge.py`)

```python
class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_scores: dict[str, float]   # dimension -> 0.0-1.0
    overall: float
    reason: str

def run_judge(
    task: Task,
    output: Output,
    spec: JudgeSpec,
    client: OpenAI,
    reference: str | None = None,
) -> JudgeResult:
    """LLM-judge via structured output (temperature 0).
    mode="reference_based" injecte `reference` dans le prompt (variance réduite).
    mode="rubric" sans référence."""
```

Prompt structuré : description de la tâche + `required_tags` + `output.content` + dimensions du `rubric` (+ `reference` si reference_based) → JSON noté. Le prompt complet est loggé (audit, cf vault).

### 1.6 SpecEvaluator (dans `qa/spec_evaluator.py`)

```python
class SpecEvaluator:
    def __init__(
        self,
        spec: EvaluatorSpec,
        client: OpenAI | None = None,   # requis seulement si spec.judge
        reference: str | None = None,
    ): ...

    def evaluate(self, task: Task, output: Output) -> QAResult: ...   # satisfait QAEvaluator Protocol


def from_spec(
    spec: EvaluatorSpec,
    client: OpenAI | None = None,
    reference: str | None = None,
) -> SpecEvaluator:
    """Factory — découple health_check de la construction."""
```

La référence est portée par l'instance (construction), pas par le Protocol — la signature `evaluate(task, output)` reste stable (V2a inchangé).

### 1.7 Algorithme de combinaison

```
1. Gates d'abord (dans l'ordre de la spec) :
     pour chaque CriterionSpec avec gate=True :
        outcome = registry[name](task, output, params)
        si non passed → return QAResult(success=False, score=0.0,
                                        reason=f"gate failed: {name}", ...)   # judge sauté
2. Critères scorés :
     det_score = somme(outcome.score * weight) / somme(weight)   (= 1.0 si aucun scoré)
3. Judge (si spec.judge et gates passés) :
     judge_result = run_judge(task, output, spec.judge, client, reference)
     final = (1 - judge.weight) * det_score + judge.weight * judge_result.overall
   sinon :
     final = det_score
4. success = final >= spec.success_threshold
5. QAResult(score=final, criteria_results={o.name: o.passed}, reason=agrégé gates+judge)
```

Invariant : `det_score` et `final` ∈ [0.0, 1.0]. Le judge ne tourne jamais si un gate échoue (coût maîtrisé).

---

## 2. Boucle d'auto-amélioration fermée

### 2.1 TestCase & TestSet (dans `qa/test_set.py`)

```python
class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Task
    evaluator_spec: EvaluatorSpec
    reference: str | None = None                          # active reference_based
    origin: Literal["curated", "runtime_failure"]
    wrong_output: Output | None = None                    # known-bad documenté (cf vault 04-regression)
    role: Literal["fix_target", "regression_guard"]       # le "split"
    attribution: Literal["unattributed", "agent", "task_spec", "evaluator"] = "unattributed"

class TestSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[TestCase]
```

Tout est sérialisable JSON (l'evaluator est une spec) → persistance gratuite + pont V3.

### 2.2 Persistence (dans `qa/test_set.py`)

```python
def save_test_set(test_set: TestSet, path: Path) -> Path:
    """Écrit `latest.json` + fichier horodaté (même pattern que elo_snapshots)."""

def load_test_set(path: Path) -> TestSet:
    """Charge un test set. FileNotFoundError si absent."""
```

Layout :
```
test_sets/
├── latest.json
└── 2026-05-28T10-30-00.json
```

### 2.3 Conversion échec runtime → TestCase

```python
def failure_to_test_case(
    failure: QAFailure,
    task: Task,
    evaluator_spec: EvaluatorSpec,
) -> TestCase:
    """origin="runtime_failure", role="fix_target", attribution="unattributed",
    wrong_output=failure.output, reference=None."""
```

Un échec naît `fix_target` / `unattributed`. Pas de référence automatique (cf §2.5).

### 2.4 Health check sur TestSet (refactor `qa/health_check.py`)

`run_health_check` prend désormais un `TestSet` (au lieu de `list[tuple[Task, QAEvaluator]]`) et un paramètre `n_runs`. **Chaque case tourne `n_runs` fois** — l'exécution de l'agent (`run_task`) est non-déterministe (température > 0), donc un passage unique est un échantillon bruité. La métrique est un **taux par case**, pas un pass/fail.

```python
def run_health_check(
    agents: list[Agent],
    test_set: TestSet,
    client: OpenAI,
    n_runs: int = 5,            # vault : 5-10 pour absorber le non-déterminisme
    tracer: Tracer | None = None,
) -> HealthCheckReport: ...
```

Pour chaque case actif (cf §2.6), boucle N fois :

```
evaluator = from_spec(case.evaluator_spec, client=client, reference=case.reference)
pour i dans range(n_runs):
    result = run_task(task, agents, client, tracer=tracer)   # mode V1, read-only ELO
    si DispatchResult → run compté "skipped"
    sinon → qa = evaluator.evaluate(task, result) ; pass/fail comptabilisé
→ CaseResult(pass_count, n_runs, pass_rate, unstable)
```

```python
class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    role: Literal["fix_target", "regression_guard"]
    n_runs: int
    pass_count: int
    pass_rate: float                  # pass_count / n_runs (Avg@k)
    unstable: bool                    # 0.4 <= pass_rate <= 0.6 → réviser rubrique/prompt
    qa_results: list[QAResult]        # les N verdicts (transcripts pour le "pourquoi")
    qa_failures: list[QAFailure]

class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    n_runs: int
    total_cases: int
    case_results: list[CaseResult]
    # agrégats par role (moyenne des case_pass_rate)
    fix_target_pass_rate: float        # avancement de correction
    regression_guard_pass_rate: float  # métrique de santé honnête (held-out)
    unstable_cases: list[str]          # task_ids à 0.4-0.6 → rubrique à revoir
    unattributed: list[str]            # task_ids en attente de triage
```

**Coût :** N runs × cases × (appel agent + judge éventuel). `n_runs=1` pour itérer vite, `n_runs=5` pour une mesure de santé honnête. Le judge est à température 0 (déterministe) ; le non-déterminisme vient de l'exécution de l'agent, c'est lui que N runs échantillonne.

**Refactor documenté :** la signature `TestCase` change (tuple → modèle) ; les tests `test_health_check.py` V2a sont mis à jour. C'est un changement interne assumé de V2b (même projet, V2a récente).

### 2.5 Lifecycle fix_target → regression_guard

| Naissance | Rôle initial | Transition |
|---|---|---|
| Cas du base set (manuel) | `regression_guard` | reste guard |
| Échec runtime | `fix_target` | `case_pass_rate >= graduation_threshold` sur N runs → gradúe en `regression_guard` |

```python
def graduate(
    test_set: TestSet,
    report: HealthCheckReport,
    graduation_threshold: float = 0.8,   # 4/5 par défaut — un guard doit être fiable
) -> TestSet:
    """Promeut en regression_guard les fix_target dont le case_pass_rate (sur N runs)
    atteint graduation_threshold. La graduation repose sur le TAUX, pas une passe unique."""
```

- **`fix_target`** = en cours de correction, re-testé (N runs) jusqu'à atteindre le taux cible.
- **`regression_guard`** = base manuel + cas gradúés ; jamais cible de tuning. `regression_guard_pass_rate` = santé honnête.

Le seuil de graduation encode l'exigence de fiabilité : `1.0` = Pass^k strict (tous les runs passent), `0.8` = tolère une variance résiduelle. Défaut `0.8`. Un case `unstable` (0.4–0.6) ne gradúe jamais — il signale une rubrique ou un prompt à revoir, pas une correction aboutie.

### 2.6 Attribution & routage

Un `fix_target` n'entre dans le lifecycle de correction de l'agent **que** s'il est attribué `agent`.

| `attribution` | Routage |
|---|---|
| `agent` | lifecycle fix_target → regression_guard |
| `task_spec` | **quarantaine** — exclu du health check agent, flaggé pour révision TaskSpec |
| `evaluator` | réviser l'`evaluator_spec` → ré-évaluer |
| `unattributed` | en attente de triage |

```python
def active_cases(test_set: TestSet) -> list[TestCase]:
    """Cases évaluées par le health check : regression_guard + fix_target attribués 'agent'.
    Exclut task_spec (quarantaine) et unattributed."""
```

**Triage manuel (V2b) :** exposé dans le `HealthCheckReport` (les `unattributed` sont listés). Quentin attribue. **V3 :** un agent de triage automatise l'attribution ; le TaskSpecGenerator devient une cible de plus de la même boucle de routage (pas de lifecycle séparé).

---

## 3. Stretch — Sélection de critères adaptée à la tâche (déterministe)

Un constructeur de spec, **sans LLM**, qui dérive un `EvaluatorSpec` depuis une `Task` :

```python
def build_adaptive_spec(task: Task) -> EvaluatorSpec:
    """Règles déterministes :
    - non_empty (gate) toujours
    - references_tags (scoré) toujours, tags = task.required_tags
    - min_length (scoré) : min_chars scalé par le nombre de required_tags (proxy de complexité)
    - judge ajouté SI un required_tag a un ELO requis >= seuil (tâche à fort enjeu)
      rubric dérivée des familles de tags
    """
```

C'est le rapprochement concret de la vision V3 : la logique de sélection est explicite et déterministe. En V3, un agent **remplace** cette fonction (émet l'`EvaluatorSpec` directement). Le seam est la signature `Task -> EvaluatorSpec`.

Les "evaluators spécialisés par domaine" tombent ici : un domaine (famille de tags) = un préréglage de spec produit par `build_adaptive_spec`.

---

## 4. Architecture fichiers V2b

```
src/aaosa/qa/
├── protocol.py          # V2a (inchangé) — QAEvaluator, QAResult, QAFailure
├── rule_based.py        # V2a (inchangé) — BasicRuleEvaluator (baseline)
├── criteria.py          # NOUVEAU — CriterionOutcome, registry, bibliothèque de critères
├── spec.py              # NOUVEAU — CriterionSpec, JudgeSpec, EvaluatorSpec
├── judge.py             # NOUVEAU — JudgeResult, run_judge (LLM-as-judge 2 modes)
├── spec_evaluator.py    # NOUVEAU — SpecEvaluator, from_spec
├── test_set.py          # NOUVEAU — TestCase, TestSet, save/load, failure_to_test_case
├── lifecycle.py         # NOUVEAU — graduate, active_cases (routage attribution)
├── adaptive.py          # NOUVEAU (stretch) — build_adaptive_spec
└── health_check.py      # REFACTOR — TestSet en entrée, pass-rates par role, report enrichi

tests/qa/                # miroir
├── test_criteria.py
├── test_spec.py
├── test_judge.py        # judge mocké (pas de LLM réel en test)
├── test_spec_evaluator.py
├── test_test_set.py
├── test_lifecycle.py
├── test_adaptive.py
└── test_health_check.py # MAJ — nouvelle signature TestSet

demo/run_demo.py         # MAJ (optionnel) — SpecEvaluator au lieu de BasicRuleEvaluator
```

---

## 5. Contraintes et invariants

- `QAEvaluator` Protocol inchangé — `SpecEvaluator` le satisfait par structural typing (signature `evaluate(task, output)` stable).
- La référence du judge passe par la construction du `SpecEvaluator`, jamais par le Protocol.
- `CriterionOutcome.score`, `det_score`, `final` ∈ [0.0, 1.0].
- Le judge ne tourne **jamais** si un gate échoue (coût maîtrisé) ni n'est jamais le signal primaire.
- Health check reste **read-only sur l'ELO** (décision V2a conservée).
- Chaque case du health check tourne `n_runs` fois ; la métrique est un **taux par case** (jamais un pass/fail unique). Un case `unstable` (0.4–0.6) ne gradúe pas et est signalé pour révision.
- Un échec n'est `regression_guard` que **quand il est corrigé** — jamais avant (résout la tension held-out).
- Seul un `fix_target` attribué `agent` entre dans le lifecycle de correction ; `task_spec` est quarantiné (ne pollue pas la suite de régression de l'agent).
- `EvaluatorSpec` et `TestSet` sont entièrement sérialisables JSON (pont V3).
- Tests : le judge est **mocké** (pas d'appel LLM réel dans la suite). Validation LLM réelle = via la démo, comme V2a.
- Backward compat : les tests V1+V2a passent, sauf `test_health_check.py` (refactor signature documenté).

---

## 6. Pont vers V3 (pour mémoire)

Le design V2b est construit pour que V3 soit une **extension, pas une réécriture** :

- **Evaluator généré par agent** : V3 = l'agent émet un `EvaluatorSpec` (JSON), validé par Pydantic. La fonction `build_adaptive_spec` (déterministe) est remplacée par un agent. Seam : `Task -> EvaluatorSpec`.
- **TaskSpecGenerator** : se branche comme cible supplémentaire de la boucle de routage (`attribution="task_spec"`). Pas de lifecycle séparé — une seule boucle indexée par attribution.
- **Agent de triage** : automatise le passage `unattributed -> {agent|task_spec|evaluator}`.
