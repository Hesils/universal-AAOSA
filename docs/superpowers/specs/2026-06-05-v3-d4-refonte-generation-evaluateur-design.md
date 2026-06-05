# D4 — Refonte de la génération d'évaluateur

Date : 2026-06-05
Statut : design validé, prêt pour `writing-plans`
Dépend de : D3 (diagnostic d'échec inline) — fournit `FailureContext`
Débloque : la route `evaluator` de D3 (aujourd'hui un no-op)

---

## 1. Problème

`build_llm_spec` (`qa/adaptive.py`) génère un `EvaluatorSpec` par LLM. Deux défauts.

**Défaut 1 — régénération aveugle (couplage D3).** La route `evaluator` de D3 régénère
l'évaluateur via `AdaptiveSpecEvaluator(client)`, qui rappelle `build_llm_spec(task, client)`
avec **les mêmes inputs et `temperature=0.0`**. La spec régénérée est identique. La route
`evaluator` ne peut donc rien corriger : si la spec était trop stricte, elle le reste → faux
positif "agent fail". La route est un no-op.

**Défaut 2 — génération floue et non bornée.** Le système laisse au LLM une latitude libre
et non validée, sans transparence :
- nombre de `llm_check` illimité ; deux `llm_check` se masquent dans `criteria_results`
  (indexé par `name` → collision silencieuse, l'observabilité n'en montre qu'un alors que
  les deux sont scorés) ;
- `weight: float` libre, sans bornes ni calibration ;
- `success_threshold` choisi librement par le LLM (0.5–0.9) ;
- schéma LLM-facing en "sac de champs optionnels" (`_LLMCriterion` aplatit l'union de tous
  les params possibles ; aucun lien `name ↔ params` encodé).

Il en résulte un sentiment justifié d'imperfection : impossible de savoir si la spec produite
est sensée (bons poids ? bon ratio critères/judge ? bon nombre de critères ?).

---

## 2. Périmètre

D4 a **deux moteurs, à parts égales** (décidé avec Quentin) :

- **Moteur A — régénération informée par l'échec.** `build_llm_spec` accepte un
  `failure_context` optionnel ; quand il est présent, la régénération est informée par
  l'output raté, la raison QA et le diagnostic. Débloque la route `evaluator` de D3.
- **Moteur B — génération lisible et bornée.** Contraindre (caps, importance discrète,
  threshold dérivé) et rendre lisible (rationale, clés distinctes). Dissout le flou.

Hors périmètre :
- B2/B3 batch (`triage`, `fix_task_spec`) : inchangés.
- Le format `EvaluatorSpec` runtime reste une **donnée sérialisable** (séparation V2b/V3) —
  D4 ne change que le producteur, plus un champ optionnel additif (`rationale`).
- Les routes `agent` / `task_spec` / `unattributed` de D3 : inchangées.

---

## 3. Moteur A — régénération informée

### 3.1 Signature unique paramétrée

```python
build_llm_spec(
    task: Task,
    client: OpenAI,
    failure_context: FailureContext | None = None,
) -> EvaluatorSpec
```

- `failure_context=None` → cold-start (comportement nominal + moteur B).
- `failure_context` présent → le prompt inclut l'output raté, la raison QA (critères ratés +
  scores) et le `diagnostic_reason`. Le LLM régénère **sans contrainte de direction** : il
  peut resserrer, desserrer, re-cibler, changer de critères. La direction dépend du contenu
  du diagnostic, jamais d'une règle codée.

`FailureContext` existe déjà (créé en D3 : `failed_output: Output`, `qa_result: QAResult`,
`diagnostic_reason: str`). D4 le réutilise sans nouveau schéma.

### 3.2 Entrée dans `AdaptiveSpecEvaluator`

Le Protocol `QAEvaluator.evaluate(task, output)` reste intouché. On ajoute un paramètre
constructeur optionnel :

```python
class AdaptiveSpecEvaluator:
    def __init__(self, client: OpenAI, failure_context: FailureContext | None = None):
        ...
    def evaluate(self, task: Task, output: Output) -> QAResult:
        spec = build_llm_spec(task, self.client, self.failure_context)
        return SpecEvaluator(spec, client=self.client).evaluate(task, output)
```

- Cold-start : `AdaptiveSpecEvaluator(client)` (inchangé).
- Route `evaluator` de D3 : `AdaptiveSpecEvaluator(client, failure_context=fc)`.

### 3.3 Correction de la route `evaluator` de D3

La route `evaluator` de `run_with_recovery` (D3, non encore poussé) doit construire un
`FailureContext` et le passer à l'évaluateur régénéré — sinon elle reste le no-op identifié.
Petit edit dans `runtime/runner.py` :

```python
elif diagnostic.attribution == "evaluator":
    fc = FailureContext(
        failed_output=output,
        qa_result=qa_result,
        diagnostic_reason=diagnostic.reason,
    )
    new_evaluator = AdaptiveSpecEvaluator(client, failure_context=fc)
    qa_result2 = new_evaluator.evaluate(task, output)
    ...
```

C'est le seul changement de D4 hors `qa/`.

---

## 4. Moteur B — génération lisible et bornée

### 4.1 Schéma LLM-facing : union taguée par type

Le `_LLMCriterion` fourre-tout est remplacé par une **union discriminée sur `type`**. Chaque
variante ne porte que ses params valides :

| type | params propres |
|------|----------------|
| `min_length` | `min_chars: int` |
| `keyword_presence` | `keywords: list[str]` |
| `llm_check` | `description: str` |
| `format_check` | `kind: str` |
| `references_tags` | (aucun) |

Champs communs à toutes les variantes : `type` (discriminant), `importance`, `rationale`.

Le lien `name ↔ params` est encodé par le type — un `min_length` ne peut plus porter de
`keywords`. `non_empty` n'est pas exposé (gate unique, injecté par `_ensure_non_empty_gate`).

**Risque technique.** L'union discriminée (`anyOf` taggé) doit passer en structured output
strict (OpenAI). Le divider fait du structured output mais sans union taguée. **À valider
tôt au plan.** Mitigation si non supporté : garder le schéma plat (`_LLMCriterion`) MAIS
ajouter une validation post-génération `name ↔ params` (drop des params invalides pour le
`name`). Les contraintes comportementales (§4.2–4.6) ne dépendent pas de l'union — elles
tiennent dans les deux cas. L'union est isolable, c'est le raffinement structurel.

### 4.2 Importance discrète au lieu de `weight: float`

Chaque critère porte `importance: Literal["critique", "normal", "mineur"]`. Le LLM ne
manipule plus de floats. Le mapping importance→weight (`critique=3`, `normal=2`, `mineur=1`)
se fait dans `to_criterion()`. La normalisation à l'évaluation (`weighted / total_weight`)
est inchangée.

**Séparation préservée.** `EvaluatorSpec` / `CriterionSpec` runtime restent float-weighted —
l'importance n'existe que dans le schéma LLM-facing. La couche données de V2b/V3 n'est pas
touchée.

### 4.3 Caps

- `llm_check` : **maximum 4** (latitude pour des critères spécifiques à la tâche, vu le peu
  de critères prédéfinis).
- Critères scorés au total : **maximum 6**.

**Enforcement** : nudge dans le prompt + **troncature post-génération déterministe** comme
garde-fou. Tri par importance (`critique` > `normal` > `mineur`) puis ordre d'émission ; on
coupe d'abord au-delà de 4 `llm_check`, puis au-delà de 6 total. Le gate `non_empty` n'est
pas concerné (il n'est pas un critère scoré).

### 4.4 `success_threshold` dérivé (déterministe, zéro LLM)

Le champ `success_threshold` est **retiré** du schéma LLM-facing. Il est dérivé du max des
ELO requis (`task.required_tags.values()`) :

- `max_elo >= ELO_EXPERT_MIN` (85) → **0.8** (hard)
- `max_elo >= ELO_COMPETENT_MIN` (30) → **0.7** (medium)
- sinon → **0.6** (easy)

Tâche sans tags requis → défaut medium (0.7). Le judge reste **choisi par le LLM** dans
`build_llm_spec` (le prompt le nudge pour les tâches complexes/ambiguës) ; seul le fallback
`build_adaptive_spec` ajoute le judge déterministiquement sur tag expert. La dérivation du
threshold ne touche pas à cette décision.

### 4.5 Rationale + clés distinctes (le "rendre lisible")

- **Rationale.** Chaque critère porte un `rationale: str` court (pourquoi ce critère). Ajout
  **optionnel et additif** sur le schéma runtime : `CriterionSpec.rationale: str = ""`
  (rétrocompat — les fixtures existantes sans rationale restent valides).
- **Clés distinctes.** La boucle d'évaluation de `SpecEvaluator.evaluate` indexe
  `criteria_results` par clé unique : `name` si unique dans la spec, `name#k` (k = ordinal
  parmi les homonymes) sinon. Les doublons `llm_check` redeviennent observables ; les deux
  sont déjà scorés correctement, seul le rapport était lossy.

  Micro-changement de contrat : un consommateur lisant `criteria_results["llm_check"]` ne
  voit la clé suffixée que lorsqu'il y a doublon — cas où l'ancien comportement était déjà
  silencieusement faux.

### 4.6 Fallback déterministe

`build_adaptive_spec` (fallback quand le LLM échoue) reçoit aussi le `success_threshold`
dérivé (§4.4), pour cohérence cold-start LLM ↔ fallback. Reste minimal sinon. Conserve son
rôle de filet runtime-safe : un hoquet LLM ne casse pas le run.

### 4.7 Prompt réécrit

`_build_prompt` enseigne :
- les 5 types de critères (l'union) et leurs params propres ;
- l'importance discrète (3 niveaux) ;
- les caps (≤ 6 total, ≤ 4 `llm_check`) ;
- le rationale obligatoire par critère ;
- en mode failure (`failure_context` présent) : une section `# Échec précédent` avec
  l'output raté, les critères QA ratés et le `diagnostic_reason`, et la consigne de corriger
  la spec en conséquence.

Le `success_threshold` n'est plus demandé au LLM (dérivé).

---

## 5. Flux

```
cold-start
  AdaptiveSpecEvaluator(client).evaluate(task, output)
    → build_llm_spec(task, client, failure_context=None)
        → LLM (union, importance, caps, rationale ; threshold dérivé)
        → troncature caps → _filter_unknown_criteria → _ensure_non_empty_gate
        → EvaluatorSpec
    → SpecEvaluator(spec, client).evaluate(task, output)  [clés distinctes]

régénération informée (route evaluator de D3)
  AdaptiveSpecEvaluator(client, failure_context=fc).evaluate(task, output)
    → build_llm_spec(task, client, failure_context=fc)
        → prompt + section "# Échec précédent" → spec potentiellement différente
    → SpecEvaluator(...).evaluate(task, output)

fallback (LLM échoue, n'importe quel mode)
  → build_adaptive_spec(task) avec threshold dérivé
```

---

## 6. Séparations strictes

- **`EvaluatorSpec` reste une donnée.** D4 ne change que le producteur. Seul ajout au format :
  `CriterionSpec.rationale: str = ""`, optionnel et additif. L'importance discrète ne vit que
  dans le schéma LLM-facing.
- **Invariants V2b conservés.** Judge toujours à 0.3 (jamais signal primaire), `non_empty`
  unique gate injecté par `_ensure_non_empty_gate`. Le LLM choisit les critères et leur
  importance, jamais le poids du judge ni le threshold.
- **Le runtime n'invente jamais le contenu de la spec.** `build_llm_spec` est le seul
  producteur LLM ; `SpecEvaluator` interprète une donnée. La dérivation du threshold est
  déterministe et pure (fonction de `task.required_tags`).
- **D4 ne franchit pas la frontière batch.** B2/B3 restent batch. La régénération informée
  est inline, alimentée par le `FailureContext` que D3 lui passe.
- **L'union est isolable.** Le raffinement structurel (§4.1) est séparé des contraintes
  comportementales ; si l'union ne passe pas en strict mode, B tient quand même.

---

## 7. Tests (TDD)

### `build_llm_spec` cold-start
- Caps respectés : spec générée a ≤ 6 critères scorés et ≤ 4 `llm_check` (mock LLM qui
  déborde → troncature par importance).
- Importance mappée : `critique/normal/mineur` → weight `3/2/1` dans l'`EvaluatorSpec`.
- Threshold dérivé : max ELO ≥ 85 → 0.8 ; ≥ 30 → 0.7 ; sinon 0.6 ; sans tags → 0.7.
- Rationale présent sur chaque critère généré.

### `build_llm_spec` informé
- `failure_context` présent → le prompt contient l'output raté + la raison QA + le diagnostic
  (assertion sur le contenu du message envoyé au mock).
- `failure_context=None` → prompt identique au cold-start (rétrocompat).

### `SpecEvaluator` — clés distinctes
- 2 `llm_check` → 2 entrées distinctes dans `criteria_results` (`llm_check#1`, `llm_check#2`),
  les deux scorés et reflétés dans le score final.
- 1 seul critère d'un nom → clé non suffixée (`name`).

### Fallback
- LLM échoue (exception) → `build_adaptive_spec` avec threshold dérivé du max ELO.

### Intégration D3
- Route `evaluator` : `AdaptiveSpecEvaluator(client, failure_context=fc)` régénère une spec
  informée ; re-éval de l'output existant utilise cette nouvelle spec.

### Rétrocompat
- `CriterionSpec` sans `rationale` reste valide (fixtures existantes).
- 792 tests existants verts (`EvaluatorSpec` sérialisable inchangé hors `rationale` optionnel).

---

## 8. Seam (fichiers touchés)

- `src/aaosa/qa/adaptive.py` — schéma LLM-facing (union, importance, retrait threshold),
  troncature caps, dérivation threshold, prompt réécrit, signature `failure_context`.
- `src/aaosa/qa/spec.py` — `CriterionSpec.rationale: str = ""` (additif).
- `src/aaosa/qa/spec_evaluator.py` — `AdaptiveSpecEvaluator.__init__(failure_context=...)`,
  clés distinctes dans `evaluate`.
- `src/aaosa/runtime/runner.py` — route `evaluator` de D3 passe un `FailureContext` (seul
  changement hors `qa/`).
