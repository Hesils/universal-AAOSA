# D4 — Refonte de la génération d'évaluateur — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refondre `build_llm_spec` en deux moteurs — A (régénération informée par un `FailureContext`, débloque la route `evaluator` de D3) et B (génération bornée et lisible : caps, importance discrète, threshold dérivé, rationale, clés distinctes).

**Architecture:** Le producteur LLM de spec (`qa/adaptive.py`) est seul touché côté génération ; `EvaluatorSpec` runtime reste une donnée sérialisable (séparation V2b/V3), avec un seul ajout additif `CriterionSpec.rationale`. Le schéma LLM-facing passe d'un `_LLMCriterion` fourre-tout à un schéma `type`-discriminé (params gardés par type) ; le `success_threshold` est retiré du LLM et dérivé du max ELO requis ; les caps sont appliqués par troncature déterministe post-génération. `SpecEvaluator` indexe `criteria_results` par clé unique pour rendre les doublons observables. Seul changement hors `qa/` : la route `evaluator` de D3 (`runtime/runner.py`) construit et passe un `FailureContext`.

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38 (structured output `beta.chat.completions.parse`), pytest 9. Tests via `.venv\Scripts\python -m pytest`.

**Spec de référence :** `docs/superpowers/specs/2026-06-05-v3-d4-refonte-generation-evaluateur-design.md`

**Ordre des branches (rappel daily 2026-06-05) :** D1/D2/D3 sont implémentés mais **non poussés** ; D4 touche la route `evaluator` de D3 (Task 8). Travailler sur la branche qui contient D3 (ne pas brancher depuis master nu).

---

## File Structure

| Fichier | Rôle | Tasks |
|---------|------|-------|
| `src/aaosa/qa/spec.py` | `CriterionSpec.rationale: str = ""` (additif, rétrocompat) | 1 |
| `src/aaosa/qa/adaptive.py` | Schéma LLM-facing `type`-discriminé, importance→weight, caps, dérivation threshold, prompt réécrit, signature `failure_context` | 1, 2, 3, 4, 5 |
| `src/aaosa/qa/spec_evaluator.py` | `AdaptiveSpecEvaluator.__init__(failure_context=...)` + clés distinctes dans `evaluate` | 6, 7 |
| `src/aaosa/runtime/runner.py` | Route `evaluator` de D3 passe un `FailureContext` (seul changement hors `qa/`) | 8 |
| `src/aaosa/qa/adaptive.py` | (optionnel) union discriminée stricte si supportée par OpenAI | 9 |

**Tests touchés/créés :**
- `tests/qa/test_adaptive_llm.py` — réécrit en grande partie (le schéma LLM-facing change : `_LLMCriterion` n'a plus `name`/`weight`/`gate` mais `type`/`importance`/`rationale`).
- `tests/qa/test_adaptive.py` — ajouts threshold dérivé / caps (vérifier l'existant reste vert).
- `tests/qa/test_spec.py` — `rationale` additif.
- `tests/qa/test_spec_evaluator.py` — clés distinctes.
- `tests/runtime/test_d3_routes.py` — route `evaluator` reçoit `failure_context` (mettre à jour les stubs existants).

---

## Task 1: `CriterionSpec.rationale` additif + dérivation déterministe du threshold

**Files:**
- Modify: `src/aaosa/qa/spec.py:6-11` (ajout champ `rationale`)
- Modify: `src/aaosa/qa/adaptive.py` (nouveau helper `_derive_threshold`, `build_adaptive_spec` l'utilise)
- Test: `tests/qa/test_spec.py`, `tests/qa/test_adaptive.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Dans `tests/qa/test_spec.py`, ajouter :

```python
from aaosa.qa.spec import CriterionSpec


def test_criterion_spec_rationale_defaults_empty():
    c = CriterionSpec(name="min_length")
    assert c.rationale == ""


def test_criterion_spec_accepts_rationale():
    c = CriterionSpec(name="llm_check", rationale="vérifie la présence d'exemples")
    assert c.rationale == "vérifie la présence d'exemples"
```

Dans `tests/qa/test_adaptive.py`, ajouter :

```python
from aaosa.qa.adaptive import _derive_threshold, build_adaptive_spec
from aaosa.schemas.task import Task


def test_derive_threshold_expert():
    assert _derive_threshold(Task(description="x", required_tags={"db": 90})) == 0.8


def test_derive_threshold_competent():
    assert _derive_threshold(Task(description="x", required_tags={"db": 50})) == 0.7


def test_derive_threshold_basic():
    assert _derive_threshold(Task(description="x", required_tags={"db": 15})) == 0.6


def test_derive_threshold_no_tags_defaults_medium():
    assert _derive_threshold(Task(description="x", required_tags={})) == 0.7


def test_build_adaptive_spec_uses_derived_threshold():
    spec = build_adaptive_spec(Task(description="x", required_tags={"db": 90}))
    assert spec.success_threshold == 0.8
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec.py tests/qa/test_adaptive.py -v`
Expected: FAIL (`rationale` inconnu / `_derive_threshold` non défini).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/spec.py`, ajouter le champ à `CriterionSpec` :

```python
class CriterionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    params: dict = {}
    weight: float = 1.0
    gate: bool = False
    rationale: str = ""
```

Dans `src/aaosa/qa/adaptive.py`, ajouter l'import et le helper, puis brancher `build_adaptive_spec`. Mettre à jour l'import ELO en tête de fichier :

```python
from aaosa.schemas.elo import ELO_COMPETENT_MIN, ELO_EXPERT_MIN
```

Ajouter le helper (au-dessus de `build_adaptive_spec`) :

```python
def _derive_threshold(task: Task) -> float:
    """success_threshold dérivé du max des ELO requis (déterministe, zéro LLM)."""
    elos = task.required_tags.values()
    if not elos:
        return 0.7
    max_elo = max(elos)
    if max_elo >= ELO_EXPERT_MIN:        # 85
        return 0.8
    if max_elo >= ELO_COMPETENT_MIN:     # 30
        return 0.7
    return 0.6
```

Modifier le `return` de `build_adaptive_spec` :

```python
    return EvaluatorSpec(
        criteria=criteria, judge=judge, success_threshold=_derive_threshold(task)
    )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec.py tests/qa/test_adaptive.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/spec.py src/aaosa/qa/adaptive.py tests/qa/test_spec.py tests/qa/test_adaptive.py
git commit -m "feat(d4): CriterionSpec.rationale additif + threshold derive du max ELO

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Schéma LLM-facing `type`-discriminé (importance, rationale, params gardés par type)

Remplace le `_LLMCriterion` fourre-tout par un schéma plat où `type` est le discriminant : `to_criterion` ne copie que les params valides pour le `type` (encode le lien `name ↔ params` de la spec §4.1), mappe l'importance discrète en weight, et porte le rationale. `_LLMEvaluatorSpec` perd `success_threshold` (dérivé en Task 4).

**Files:**
- Modify: `src/aaosa/qa/adaptive.py:19-66` (réécriture des schémas LLM-facing)
- Test: `tests/qa/test_adaptive_llm.py` (réécriture des tests de schéma)

- [ ] **Step 1: Écrire les tests qui échouent**

Réécrire le **haut** de `tests/qa/test_adaptive_llm.py`. Remplacer les imports et la classe `TestBuildLLMSpec` existante par les imports ci-dessous + une nouvelle classe `TestLLMCriterionSchema`. Conserver `_FakeParseClient` et `_RaisingClient` (réutilisés dans les tasks suivantes).

Nouveaux imports en tête (remplacer la ligne `from aaosa.qa.adaptive import (...)`) :

```python
from aaosa.qa.adaptive import (
    _IMPORTANCE_WEIGHT,
    _LLMCriterion,
    _LLMEvaluatorSpec,
    _LLMJudge,
    build_adaptive_spec,
    build_llm_spec,
)
```

Ajouter cette classe de tests :

```python
class TestLLMCriterionSchema:
    def test_importance_maps_to_weight(self):
        for importance, weight in [("critique", 3.0), ("normal", 2.0), ("mineur", 1.0)]:
            c = _LLMCriterion(type="min_length", importance=importance, min_chars=10)
            assert c.to_criterion().weight == weight

    def test_importance_defaults_normal(self):
        c = _LLMCriterion(type="references_tags")
        assert c.to_criterion().weight == _IMPORTANCE_WEIGHT["normal"]

    def test_rationale_carried_to_criterion(self):
        c = _LLMCriterion(type="llm_check", description="d", rationale="pourquoi")
        assert c.to_criterion().rationale == "pourquoi"

    def test_type_becomes_criterion_name(self):
        c = _LLMCriterion(type="format_check", kind="json")
        assert c.to_criterion().name == "format_check"

    def test_params_gated_by_type(self):
        # min_length avec des keywords parasites : seuls les params du type sont copiés
        c = _LLMCriterion(type="min_length", min_chars=80, keywords=["x"], description="y")
        assert c.to_criterion().params == {"min_chars": 80}

    def test_keyword_presence_params(self):
        c = _LLMCriterion(type="keyword_presence", keywords=["a", "b"])
        assert c.to_criterion().params == {"keywords": ["a", "b"]}

    def test_references_tags_has_no_params(self):
        c = _LLMCriterion(type="references_tags", min_chars=10)
        assert c.to_criterion().params == {}

    def test_criterion_rejects_weight_field(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="min_length", weight=2.0)

    def test_criterion_rejects_gate_field(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="min_length", gate=True)

    def test_criterion_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="totally_made_up")

    def test_evaluator_spec_has_no_threshold_field(self):
        with pytest.raises(ValidationError):
            _LLMEvaluatorSpec(criteria=[], success_threshold=0.9)

    def test_to_spec_builds_evaluator_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        spec = llm.to_spec()
        assert [c.name for c in spec.criteria] == ["min_length"]
```

> Note : les anciens tests qui construisaient `_LLMCriterion(name=..., min_chars=..., weight=...)` ou `_LLMEvaluatorSpec(success_threshold=...)` sont supprimés/remplacés ici. Les tests `build_llm_spec` end-to-end sont réécrits en Task 4.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestLLMCriterionSchema -v`
Expected: FAIL (`_IMPORTANCE_WEIGHT` absent, `_LLMCriterion` accepte encore `name`/`weight`).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/adaptive.py`, remplacer le bloc `_LLMCriterion` / `_LLMJudge` / `_LLMEvaluatorSpec` (lignes ~15-66) par :

```python
# --- Schémas LLM-facing (structured output) -------------------------------
# OpenAI structured output interdit les dict ouverts. On expose des params
# explicites par type et on reconstruit le dict CriterionSpec.params côté Python.
# `type` est le discriminant : to_criterion() ne copie que les params du type
# (encode le lien name ↔ params — un min_length ne peut pas porter de keywords).
_CriterionType = Literal[
    "min_length", "keyword_presence", "llm_check", "format_check", "references_tags"
]
_Importance = Literal["critique", "normal", "mineur"]
_IMPORTANCE_WEIGHT: dict[str, float] = {"critique": 3.0, "normal": 2.0, "mineur": 1.0}


class _LLMCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: _CriterionType
    importance: _Importance = "normal"
    rationale: str = ""
    # Pas de `weight` (l'importance discrète le dérive) ni de `gate`
    # (seul non_empty est gate, injecté par _ensure_non_empty_gate).
    # params par type, aplatis ; gardés par type dans to_criterion :
    min_chars: int | None = None          # min_length
    keywords: list[str] | None = None     # keyword_presence
    description: str | None = None        # llm_check
    kind: str | None = None               # format_check

    def to_criterion(self) -> CriterionSpec:
        params: dict = {}
        if self.type == "min_length" and self.min_chars is not None:
            params["min_chars"] = self.min_chars
        elif self.type == "keyword_presence" and self.keywords is not None:
            params["keywords"] = self.keywords
        elif self.type == "llm_check" and self.description is not None:
            params["description"] = self.description
        elif self.type == "format_check" and self.kind is not None:
            params["kind"] = self.kind
        # references_tags : aucun param
        return CriterionSpec(
            name=self.type,
            params=params,
            weight=_IMPORTANCE_WEIGHT[self.importance],
            rationale=self.rationale,
        )


class _LLMJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    rubric: list[str]
    # Pas de champ `weight` : le judge n'est jamais le signal primaire (invariant
    # V2b). Poids verrouillé à 0.3 via le défaut JudgeSpec — le LLM ne le contrôle pas.

    def to_judge(self) -> JudgeSpec:
        return JudgeSpec(mode=self.mode, rubric=self.rubric)


class _LLMEvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[_LLMCriterion]
    judge: _LLMJudge | None = None
    # Pas de success_threshold : dérivé déterministiquement de task.required_tags.

    def to_spec(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            criteria=[c.to_criterion() for c in self.criteria],
            judge=self.judge.to_judge() if self.judge is not None else None,
        )
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestLLMCriterionSchema -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive_llm.py
git commit -m "feat(d4): schema LLM-facing type-discrimine (importance + rationale, params gardes par type)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Caps déterministes (≤ 4 llm_check, ≤ 6 scorés)

Garde-fou : troncature post-génération, tri par importance (weight) puis ordre d'émission (tri stable). Les gates ne sont jamais comptés.

**Files:**
- Modify: `src/aaosa/qa/adaptive.py` (nouveau helper `_apply_caps`)
- Test: `tests/qa/test_adaptive_llm.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/qa/test_adaptive_llm.py` :

```python
from aaosa.qa.adaptive import _apply_caps
from aaosa.qa.spec import CriterionSpec


class TestApplyCaps:
    def test_caps_total_scored_to_six(self):
        crit = [
            CriterionSpec(name="min_length", weight=2.0) for _ in range(8)
        ]
        kept = _apply_caps(crit)
        assert len(kept) == 6

    def test_caps_llm_check_to_four(self):
        crit = [CriterionSpec(name="llm_check", params={"description": str(i)}, weight=2.0)
                for i in range(6)]
        kept = _apply_caps(crit)
        assert sum(c.name == "llm_check" for c in kept) == 4

    def test_caps_keep_highest_importance_first(self):
        crit = [
            CriterionSpec(name="min_length", weight=1.0, rationale="mineur"),
            CriterionSpec(name="references_tags", weight=3.0, rationale="critique"),
            CriterionSpec(name="format_check", weight=2.0, rationale="normal"),
        ]
        # cap fictif : on garde tout (3 ≤ 6) mais l'ordre est trié par weight desc
        kept = _apply_caps(crit)
        assert [c.rationale for c in kept] == ["critique", "normal", "mineur"]

    def test_caps_preserve_emission_order_within_importance(self):
        crit = [
            CriterionSpec(name="min_length", weight=2.0, rationale="first"),
            CriterionSpec(name="references_tags", weight=2.0, rationale="second"),
        ]
        kept = _apply_caps(crit)
        assert [c.rationale for c in kept] == ["first", "second"]

    def test_caps_ignore_gates(self):
        crit = [CriterionSpec(name="non_empty", gate=True)] + [
            CriterionSpec(name="min_length", weight=2.0) for _ in range(6)
        ]
        kept = _apply_caps(crit)
        # le gate est conservé en plus des 6 scorés, et placé en tête
        assert kept[0].name == "non_empty" and kept[0].gate is True
        assert sum(not c.gate for c in kept) == 6
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestApplyCaps -v`
Expected: FAIL (`_apply_caps` non défini).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/adaptive.py`, ajouter (au-dessus de `_filter_unknown_criteria`) :

```python
_MAX_LLM_CHECK = 4
_MAX_SCORED = 6


def _apply_caps(criteria: list[CriterionSpec]) -> list[CriterionSpec]:
    """Troncature déterministe : ≤ 4 llm_check, ≤ 6 critères scorés au total.

    Tri par importance (weight) décroissant, tri stable → ordre d'émission
    préservé à importance égale. Les gates ne sont pas concernés (placés en tête,
    non comptés). On coupe d'abord l'excès de llm_check, puis le total à 6.
    """
    gates = [c for c in criteria if c.gate]
    scored = [c for c in criteria if not c.gate]
    ordered = sorted(scored, key=lambda c: -c.weight)  # stable
    kept: list[CriterionSpec] = []
    llm_seen = 0
    for c in ordered:
        if c.name == "llm_check":
            if llm_seen >= _MAX_LLM_CHECK:
                continue
            llm_seen += 1
        kept.append(c)
    return gates + kept[:_MAX_SCORED]
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestApplyCaps -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive_llm.py
git commit -m "feat(d4): caps deterministes (<=4 llm_check, <=6 scores) par troncature

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `build_llm_spec` cold-start + prompt réécrit (Moteur B complet)

Câble le pipeline : parse → `to_spec` → `_filter_unknown_criteria` → `_apply_caps` → `_ensure_non_empty_gate` → threshold dérivé. Réécrit `_build_prompt` (5 types, importance, caps, rationale, judge ; plus de threshold demandé).

**Files:**
- Modify: `src/aaosa/qa/adaptive.py` (`_build_prompt`, `build_llm_spec`)
- Test: `tests/qa/test_adaptive_llm.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/qa/test_adaptive_llm.py` (note : `_FakeParseClient` et `make_task` existent déjà en tête de fichier) :

```python
class TestBuildLLMSpecColdStart:
    def test_returns_evaluator_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=100)])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert isinstance(result, EvaluatorSpec)
        assert "min_length" in {c.name for c in result.criteria}

    def test_response_format_is_closed_schema(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client)
        assert client.captured_kwargs["response_format"] is _LLMEvaluatorSpec

    def test_always_has_non_empty_gate(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        gates = [c for c in result.criteria if c.name == "non_empty" and c.gate]
        assert len(gates) == 1

    def test_threshold_is_derived_not_from_llm(self):
        # tag expert → 0.8, indépendamment de ce que "voudrait" le LLM
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        task = make_task(required_tags={"frontend": 90})
        result = build_llm_spec(task, _FakeParseClient(llm))
        assert result.success_threshold == 0.8

    def test_importance_mapped_in_resulting_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="min_length", importance="critique", min_chars=50),
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        ml = next(c for c in result.criteria if c.name == "min_length")
        assert ml.weight == 3.0

    def test_rationale_present_on_generated_criteria(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="llm_check", description="d", rationale="parce que"),
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        llm_c = next(c for c in result.criteria if c.name == "llm_check")
        assert llm_c.rationale == "parce que"

    def test_caps_enforced_end_to_end(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="llm_check", description=str(i)) for i in range(6)
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert sum(c.name == "llm_check" for c in result.criteria) == 4

    def test_judge_converted_weight_locked(self):
        llm = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(type="min_length", min_chars=50)],
            judge=_LLMJudge(mode="rubric", rubric=["correctness"]),
        )
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert result.judge is not None and result.judge.weight == 0.3

    def test_filters_unknown_criteria_kept_known(self):
        # un type inconnu ne peut PAS être construit côté _LLMCriterion (ValidationError),
        # mais _filter_unknown_criteria reste la défense secondaire : on vérifie qu'un
        # spec ne contenant que des critères connus passe intact.
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="references_tags")])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert "references_tags" in {c.name for c in result.criteria}

    def test_fallback_on_exception(self):
        task = make_task()
        result = build_llm_spec(task, _RaisingClient())
        assert result == build_adaptive_spec(task)

    def test_prompt_lists_types_and_caps(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client)
        prompt = client.captured_kwargs["messages"][1]["content"]
        assert "llm_check" in prompt and "min_length" in prompt
        assert "importance" in prompt
        assert "non_empty" in prompt  # consigne de ne pas le déclarer
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestBuildLLMSpecColdStart -v`
Expected: FAIL (prompt et pipeline pas encore branchés sur le nouveau schéma).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/adaptive.py`, remplacer `_build_prompt` et `build_llm_spec`. D'abord ajouter une constante de doc des types (au-dessus de `_build_prompt`) :

```python
_CRITERION_TYPES_DOC = (
    "- min_length : params {min_chars: int} — longueur minimale attendue\n"
    "- keyword_presence : params {keywords: list[str]} — mots-clés devant apparaître\n"
    "- llm_check : params {description: str} — critère sémantique libre, vérifié par LLM\n"
    "- format_check : params {kind: str} — 'json' | 'code_block' | 'non_empty_lines'\n"
    "- references_tags : aucun param — la réponse doit référencer les tags requis\n"
)
```

Remplacer `_build_prompt` par (signature étendue ; la section échec est inerte tant que `failure_context=None`, branchée pleinement en Task 5) :

```python
def _build_prompt(task: Task, failure_context: "FailureContext | None" = None) -> str:
    context_section = f"# Contexte domaine\n{task.context}\n\n" if task.context else ""
    failure_section = ""
    if failure_context is not None:
        failed = [
            name for name, ok in failure_context.qa_result.criteria_results.items() if not ok
        ]
        failure_section = (
            "# Échec précédent\n"
            "Une spec précédente a jugé la réponse suivante comme un échec.\n"
            f"Réponse de l'agent:\n{failure_context.failed_output.content}\n\n"
            f"Verdict QA (score={failure_context.qa_result.score:.2f}): "
            f"{failure_context.qa_result.reason}\n"
            f"Critères ratés: {', '.join(failed) or 'aucun'}\n"
            f"Diagnostic: {failure_context.diagnostic_reason}\n"
            "Corrige la spec en conséquence : si les critères étaient inadaptés (trop "
            "stricts, hors-sujet), desserre-les ou remplace-les pour viser une évaluation "
            "juste de cette réponse.\n\n"
        )
    return (
        "Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.\n\n"
        f"# Tâche\n{task.description}\n\n"
        f"{context_section}"
        f"# Tags requis\n{', '.join(task.required_tags) or 'aucun'}\n\n"
        f"{failure_section}"
        "# Types de critères disponibles\n"
        f"{_CRITERION_TYPES_DOC}\n"
        "# Règles\n"
        "- Chaque critère porte un `type` (parmi la liste ci-dessus), une `importance` "
        "('critique' | 'normal' | 'mineur') et un `rationale` court (pourquoi ce critère).\n"
        "- Maximum 6 critères au total, dont au plus 4 de type 'llm_check'.\n"
        "- 'non_empty' est ajouté automatiquement comme unique gate — ne le déclare pas.\n"
        "- Utilise 'llm_check' pour les critères qualitatifs propres à cette tâche.\n"
        "- Ajoute un judge (mode 'rubric') si la tâche est complexe ou ambiguë.\n"
        "- Ne choisis PAS de seuil de succès : il est dérivé automatiquement."
    )
```

Ajouter l'import de `FailureContext` en tête de `adaptive.py` (utilisé en annotation + Task 5) :

```python
from aaosa.qa.diagnostic import FailureContext
```

> Vérifier qu'aucun import circulaire n'apparaît (`diagnostic.py` n'importe pas `adaptive.py`). Si un cycle survient, utiliser `from __future__ import annotations` en tête et garder l'annotation en chaîne `"FailureContext | None"`.

Remplacer `build_llm_spec` (signature étendue ; `failure_context` transmis au prompt) :

```python
def build_llm_spec(
    task: Task,
    client: OpenAI,
    failure_context: FailureContext | None = None,
) -> EvaluatorSpec:
    """Génère un EvaluatorSpec via LLM (structured output).

    Moteur B (génération bornée) : caps déterministes, importance discrète,
    threshold dérivé, rationale. Moteur A (régénération informée) : si
    `failure_context` est fourni, le prompt inclut l'échec précédent.
    Fallback automatique sur build_adaptive_spec si le LLM échoue.
    """
    threshold = _derive_threshold(task)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "Tu produis une spec d'évaluation déclarative."},
                {"role": "user", "content": _build_prompt(task, failure_context)},
            ],
            response_format=_LLMEvaluatorSpec,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsed _LLMEvaluatorSpec")
        spec = _filter_unknown_criteria(parsed.to_spec(), task)
        spec = spec.model_copy(update={"criteria": _apply_caps(list(spec.criteria))})
        spec = _ensure_non_empty_gate(spec)
        return spec.model_copy(update={"success_threshold": threshold})
    except Exception as e:
        logger.warning("build_llm_spec fallback to deterministic spec: %s", e)
        return build_adaptive_spec(task)
```

- [ ] **Step 4: Lancer la suite adaptive complète**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py tests/qa/test_adaptive.py -v`
Expected: PASS (toute la suite adaptive, y compris les classes des tasks 1-3).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive_llm.py
git commit -m "feat(d4): build_llm_spec cold-start (pipeline caps+threshold derive) + prompt reecrit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Moteur A — `build_llm_spec` informé par `failure_context`

La plomberie de signature et la section `# Échec précédent` du prompt sont déjà en place (Task 4). Cette task **verrouille le comportement par des tests** : présence du contenu d'échec dans le message LLM, et rétrocompat `failure_context=None`.

**Files:**
- Test: `tests/qa/test_adaptive_llm.py`
- (aucune modification source attendue ; si un test échoue, corriger `_build_prompt`)

- [ ] **Step 1: Écrire les tests qui échouent (ou confirment)**

Ajouter dans `tests/qa/test_adaptive_llm.py` :

```python
from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import LLMMetadata, Output


def _failure_context() -> FailureContext:
    out = Output(
        task_id="t", agent_id="a", content="réponse ratée bidon",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )
    qa = QAResult(task_id="t", agent_id="a", success=False, score=0.2,
                  reason="trop court", criteria_results={"min_length": False})
    return FailureContext(failed_output=out, qa_result=qa,
                          diagnostic_reason="les critères étaient trop stricts")


class TestBuildLLMSpecInformed:
    def test_prompt_includes_failure_details(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client, failure_context=_failure_context())
        prompt = client.captured_kwargs["messages"][1]["content"]
        assert "Échec précédent" in prompt
        assert "réponse ratée bidon" in prompt          # output raté
        assert "trop court" in prompt                    # raison QA
        assert "les critères étaient trop stricts" in prompt  # diagnostic
        assert "min_length" in prompt                    # critère raté

    def test_none_failure_context_matches_cold_start(self):
        c1 = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        c2 = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), c1)
        build_llm_spec(make_task(), c2, failure_context=None)
        assert c1.captured_kwargs["messages"][1]["content"] == \
            c2.captured_kwargs["messages"][1]["content"]
```

- [ ] **Step 2: Lancer les tests**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py::TestBuildLLMSpecInformed -v`
Expected: PASS (la section échec a été implémentée en Task 4). Si FAIL, ajuster `_build_prompt` jusqu'au vert — ne pas modifier les assertions de test.

- [ ] **Step 3: Commit**

```bash
git add tests/qa/test_adaptive_llm.py
git commit -m "test(d4): moteur A — build_llm_spec informe par failure_context

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `AdaptiveSpecEvaluator(failure_context=...)`

Paramètre constructeur optionnel ; `evaluate` le transmet à `build_llm_spec`. Protocol `QAEvaluator.evaluate(task, output)` intouché.

**Files:**
- Modify: `src/aaosa/qa/spec_evaluator.py:95-108`
- Test: `tests/qa/test_spec_evaluator.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/qa/test_spec_evaluator.py` :

```python
from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator


def _fc():
    out = make_output("bad")
    qa = QAResult(task_id="t", agent_id="a1", success=False, score=0.1,
                  reason="r", criteria_results={})
    return FailureContext(failed_output=out, qa_result=qa, diagnostic_reason="d")


class TestAdaptiveSpecEvaluatorFailureContext:
    def test_default_failure_context_is_none(self):
        ev = AdaptiveSpecEvaluator(client=None)
        assert ev.failure_context is None

    def test_stores_failure_context(self):
        fc = _fc()
        ev = AdaptiveSpecEvaluator(client=None, failure_context=fc)
        assert ev.failure_context is fc

    def test_evaluate_passes_failure_context_to_build(self, monkeypatch):
        captured = {}

        def fake_build(task, client, failure_context=None):
            captured["fc"] = failure_context
            return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])

        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)
        fc = _fc()
        AdaptiveSpecEvaluator(client=None, failure_context=fc).evaluate(
            make_task(), make_output("x")
        )
        assert captured["fc"] is fc
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py::TestAdaptiveSpecEvaluatorFailureContext -v`
Expected: FAIL (`failure_context` non accepté).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/spec_evaluator.py`, ajouter l'import et modifier `AdaptiveSpecEvaluator` :

```python
from aaosa.qa.diagnostic import FailureContext
```

```python
class AdaptiveSpecEvaluator:
    """Evaluator paresseux : génère la spec par tâche (B1) dans evaluate.

    Satisfait le Protocol QAEvaluator. `failure_context` optionnel (D4 moteur A) :
    s'il est fourni, build_llm_spec régénère une spec informée par l'échec.
    """

    def __init__(self, client: OpenAI, failure_context: FailureContext | None = None):
        self.client = client
        self.failure_context = failure_context

    def evaluate(self, task: Task, output: Output) -> QAResult:
        spec = build_llm_spec(task, self.client, self.failure_context)
        return SpecEvaluator(spec, client=self.client).evaluate(task, output)
```

> Vérifier l'absence d'import circulaire : `spec_evaluator.py` importe déjà `build_llm_spec` depuis `adaptive.py`, qui importe `FailureContext` depuis `diagnostic.py`. `diagnostic.py` n'importe que `protocol`/`output`/`task`. Pas de cycle.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`
Expected: PASS (toute la suite spec_evaluator).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py
git commit -m "feat(d4): AdaptiveSpecEvaluator(failure_context=...) — entree moteur A

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Clés distinctes dans `SpecEvaluator.evaluate`

`criteria_results` indexé par clé unique : `name` si unique dans la spec, `name#k` (k = ordinal parmi les homonymes) sinon. Rend les doublons `llm_check` observables.

**Files:**
- Modify: `src/aaosa/qa/spec_evaluator.py:28-84` (helper `_criteria_keys` + boucles d'évaluation)
- Test: `tests/qa/test_spec_evaluator.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `tests/qa/test_spec_evaluator.py`. Un stub de critère scoré déterministe est injecté via le registry pour éviter tout appel LLM.

```python
from aaosa.qa.criteria import CRITERIA_REGISTRY, CriterionOutcome


class TestDistinctKeys:
    def test_single_name_not_suffixed(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 100))
        assert "min_length" in r.criteria_results
        assert "min_length#1" not in r.criteria_results

    def test_duplicate_names_get_distinct_keys(self, monkeypatch):
        # deux critères de même name → deux clés distinctes, les deux scorés
        def stub(task, output, params):
            return CriterionOutcome(name="dup", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "dup", stub)
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="dup", weight=1.0),
                CriterionSpec(name="dup", weight=1.0),
            ],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert "dup#1" in r.criteria_results
        assert "dup#2" in r.criteria_results

    def test_duplicate_gate_keys_distinct(self, monkeypatch):
        def stub(task, output, params):
            return CriterionOutcome(name="g", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "g", stub)
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="g", gate=True),
                CriterionSpec(name="g", gate=True),
            ],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert "g#1" in r.criteria_results and "g#2" in r.criteria_results
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py::TestDistinctKeys -v`
Expected: FAIL (doublons écrasés : une seule clé `dup` / `g`).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/qa/spec_evaluator.py`, ajouter le helper (au-dessus de la classe `SpecEvaluator`) :

```python
def _criteria_keys(criteria) -> list[str]:
    """Clé unique par critère : `name` si unique, `name#k` (k ordinal) si homonymes."""
    totals: dict[str, int] = {}
    for c in criteria:
        totals[c.name] = totals.get(c.name, 0) + 1
    seen: dict[str, int] = {}
    keys: list[str] = []
    for c in criteria:
        if totals[c.name] == 1:
            keys.append(c.name)
        else:
            seen[c.name] = seen.get(c.name, 0) + 1
            keys.append(f"{c.name}#{seen[c.name]}")
    return keys
```

Réécrire la méthode `evaluate` pour utiliser les clés alignées par position. Remplacer les sections 1 et 2 :

```python
    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria_results: dict[str, bool] = {}
        keys = _criteria_keys(self.spec.criteria)
        keyed = list(zip(self.spec.criteria, keys))

        # 1. Gates (ordre de la spec)
        for c, key in keyed:
            if not c.gate:
                continue
            outcome = get_criterion(c.name)(task, output, {**c.params, "client": self.client})
            criteria_results[key] = outcome.passed
            if not outcome.passed:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=False, score=0.0,
                    reason=f"gate failed: {c.name} ({outcome.detail})",
                    criteria_results=criteria_results,
                )

        # 2. Critères scorés
        scored = [(c, key) for c, key in keyed if not c.gate]
        if scored:
            total_weight = sum(c.weight for c, _ in scored)
            weighted = 0.0
            for c, key in scored:
                outcome = get_criterion(c.name)(task, output, {**c.params, "client": self.client})
                criteria_results[key] = outcome.passed
                weighted += outcome.score * c.weight
            det_score = weighted / total_weight if total_weight > 0 else 1.0
        else:
            det_score = 1.0
```

Les sections 3 (judge) et 4 (verdict) restent inchangées.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`
Expected: PASS (suite complète, y compris les tests `criteria_results["non_empty"]` existants — clé non suffixée quand unique).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py
git commit -m "feat(d4): cles distinctes criteria_results (name#k sur homonymes)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Débloquer la route `evaluator` de D3 (Moteur A end-to-end)

La route `evaluator` de `_route_diagnostic` (runner.py) régénère aujourd'hui via `AdaptiveSpecEvaluator(ctx.client)` — mêmes inputs, temp 0 → spec identique → no-op. D4 lui passe un `FailureContext` pour qu'elle régénère une spec informée.

**Files:**
- Modify: `src/aaosa/runtime/runner.py:350-355` (route `evaluator`)
- Test: `tests/runtime/test_d3_routes.py` (mettre à jour les stubs `AdaptiveSpecEvaluator` + nouveau test)

- [ ] **Step 1: Mettre à jour les tests existants + écrire le test qui échoue**

Dans `tests/runtime/test_d3_routes.py`, les 3 tests `test_route_evaluator_*` patchent `AdaptiveSpecEvaluator` avec `lambda client: ...`. Le nouvel appel passe `failure_context=` → mettre la signature à jour dans **les trois** :

```python
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client, failure_context=None: SimpleNamespace(
                            evaluate=lambda task, output: good_qa))
```

(idem `bad_qa` dans les deux autres).

Ajouter un test qui vérifie que le `failure_context` est bien construit et transmis :

```python
def test_route_evaluator_passes_failure_context(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(
                            attribution="evaluator", consignes=None, reason="critères trop stricts"))
    captured = {}
    good_qa = QAResult(task_id="t", agent_id="a", success=True, score=0.9,
                       reason="ok", criteria_results={})

    def fake_evaluator(client, failure_context=None):
        captured["fc"] = failure_context
        return SimpleNamespace(evaluate=lambda task, output: good_qa)

    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator", fake_evaluator)
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    fc = captured["fc"]
    assert fc is not None
    assert fc.diagnostic_reason == "critères trop stricts"
    assert fc.failed_output.content == "bad"        # output raté du _qa_fail()
    assert fc.qa_result.score == 0.2
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_routes.py -v`
Expected: le nouveau test FAIL (`captured["fc"]` est `None` — la route ne passe pas encore de `failure_context`).

- [ ] **Step 3: Implémenter**

Dans `src/aaosa/runtime/runner.py`, remplacer le bloc de la route `evaluator` (lignes ~350-355) :

```python
    if diagnostic.attribution == "evaluator":
        fc = FailureContext(
            failed_output=failure.output,
            qa_result=failure.qa_result,
            diagnostic_reason=diagnostic.reason,
        )
        new_evaluator = AdaptiveSpecEvaluator(ctx.client, failure_context=fc)
        qa2 = new_evaluator.evaluate(task, failure.output)
        if qa2.success:
            return failure.output   # l'output original passe avec la spec régénérée
        return _retry_with_consignes(task, diagnostic.consignes, ctx, attribution="evaluator")
```

> `FailureContext` est déjà importé dans `runner.py` (ligne 8). Aucun nouvel import.

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_routes.py -v`
Expected: PASS (les 3 tests mis à jour + le nouveau).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_d3_routes.py
git commit -m "feat(d4): route evaluator D3 passe un FailureContext (moteur A end-to-end)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9 (optionnel, isolable) : union discriminée stricte si OpenAI la supporte

Raffinement structurel de §4.1 : remplacer le `_LLMCriterion` plat par une **union discriminée sur `type`** (5 variantes ne portant que leurs params), si le structured output strict d'OpenAI l'accepte. Le comportement (caps, importance, threshold, rationale, name↔params) est déjà garanti par le schéma plat — cette task n'ajoute que la rigueur structurelle au schéma envoyé au LLM. **À ne tenter qu'après que les tasks 1-8 sont vertes.**

**Files:**
- Modify: `src/aaosa/qa/adaptive.py` (schéma LLM-facing → union)
- Test: `tests/qa/test_adaptive_llm.py`
- Spike: script jetable + `OPENAI_API_KEY`

- [ ] **Step 1: Spike — l'union discriminée passe-t-elle en strict mode ?**

Créer `spike_union.py` à la racine (jetable) :

```python
from typing import Literal, Union

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


class MinLength(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["min_length"]
    importance: Literal["critique", "normal", "mineur"] = "normal"
    rationale: str = ""
    min_chars: int


class LLMCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["llm_check"]
    importance: Literal["critique", "normal", "mineur"] = "normal"
    rationale: str = ""
    description: str


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[Union[MinLength, LLMCheck]] = Field(discriminator="type")


client = OpenAI()
try:
    resp = client.beta.chat.completions.parse(
        model="gpt-4o-mini", temperature=0,
        messages=[{"role": "user", "content":
                   "Donne 2 critères: un min_length (min_chars 100, importance critique) "
                   "et un llm_check (description 'inclut des exemples')."}],
        response_format=Spec,
    )
    print("OK — union strict supportée")
    print(resp.choices[0].message.parsed)
except Exception as e:
    print("KO — union strict NON supportée:", type(e).__name__, e)
```

Run: `.venv\Scripts\python spike_union.py`

- [ ] **Step 2: Décision (documentée dans le commit / daily)**

- **Si « OK »** → procéder aux steps 3-5 (refactor en union).
- **Si « KO »** → **ne pas refactorer**. Le schéma plat `type`-discriminé (Task 2) satisfait déjà §4.1 (name↔params encodé par `type`, params parasites droppés dans `to_criterion`). Supprimer `spike_union.py`, noter la décision dans la daily, et **clore D4 à la Task 8**.

```bash
git rm spike_union.py 2>$null; del spike_union.py
```

- [ ] **Step 3 (si OK): Écrire le test qui échoue**

Ajouter dans `tests/qa/test_adaptive_llm.py` :

```python
class TestDiscriminatedUnion:
    def test_min_length_variant_rejects_foreign_params(self):
        # la variante min_length ne doit PAS accepter `description`
        from aaosa.qa.adaptive import _LLMMinLength
        with pytest.raises(ValidationError):
            _LLMMinLength(type="min_length", min_chars=10, description="x")

    def test_union_round_trips_to_spec(self):
        from aaosa.qa.adaptive import _LLMLLMCheck, _LLMMinLength
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMMinLength(type="min_length", min_chars=50, importance="critique"),
            _LLMLLMCheck(type="llm_check", description="d"),
        ])
        spec = llm.to_spec()
        assert {c.name for c in spec.criteria} == {"min_length", "llm_check"}
        ml = next(c for c in spec.criteria if c.name == "min_length")
        assert ml.weight == 3.0
```

- [ ] **Step 4 (si OK): Implémenter l'union**

Dans `src/aaosa/qa/adaptive.py`, remplacer le `_LLMCriterion` plat par 5 variantes + une base commune et une union discriminée. `to_criterion()` est défini sur la base (le mapping importance→weight et le name = `type` sont communs ; chaque variante ajoute ses params). Exemple de structure :

```python
from typing import Annotated, Literal, Union
from pydantic import Field

_Importance = Literal["critique", "normal", "mineur"]
_IMPORTANCE_WEIGHT: dict[str, float] = {"critique": 3.0, "normal": 2.0, "mineur": 1.0}


class _LLMCriterionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    importance: _Importance = "normal"
    rationale: str = ""

    def _params(self) -> dict:
        return {}

    def _name(self) -> str:
        raise NotImplementedError

    def to_criterion(self) -> CriterionSpec:
        return CriterionSpec(
            name=self._name(), params=self._params(),
            weight=_IMPORTANCE_WEIGHT[self.importance], rationale=self.rationale,
        )


class _LLMMinLength(_LLMCriterionBase):
    type: Literal["min_length"]
    min_chars: int
    def _name(self): return "min_length"
    def _params(self): return {"min_chars": self.min_chars}


class _LLMKeywordPresence(_LLMCriterionBase):
    type: Literal["keyword_presence"]
    keywords: list[str]
    def _name(self): return "keyword_presence"
    def _params(self): return {"keywords": self.keywords}


class _LLMLLMCheck(_LLMCriterionBase):
    type: Literal["llm_check"]
    description: str
    def _name(self): return "llm_check"
    def _params(self): return {"description": self.description}


class _LLMFormatCheck(_LLMCriterionBase):
    type: Literal["format_check"]
    kind: str
    def _name(self): return "format_check"
    def _params(self): return {"kind": self.kind}


class _LLMReferencesTags(_LLMCriterionBase):
    type: Literal["references_tags"]
    def _name(self): return "references_tags"


_LLMCriterionUnion = Annotated[
    Union[_LLMMinLength, _LLMKeywordPresence, _LLMLLMCheck, _LLMFormatCheck, _LLMReferencesTags],
    Field(discriminator="type"),
]


class _LLMEvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[_LLMCriterionUnion]
    judge: _LLMJudge | None = None

    def to_spec(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            criteria=[c.to_criterion() for c in self.criteria],
            judge=self.judge.to_judge() if self.judge is not None else None,
        )
```

Mettre à jour les tests des tasks 2/4 qui construisaient `_LLMCriterion(type=...)` pour utiliser la variante adéquate (`_LLMMinLength(type="min_length", min_chars=...)`, etc.). `_IMPORTANCE_WEIGHT` reste exporté.

- [ ] **Step 5 (si OK): Lancer toute la suite adaptive + commit**

Run: `.venv\Scripts\python -m pytest tests/qa/test_adaptive_llm.py -v`
Expected: PASS.

```bash
git add src/aaosa/qa/adaptive.py tests/qa/test_adaptive_llm.py
git rm spike_union.py 2>$null
git commit -m "refactor(d4): schema LLM-facing en union discriminee (strict mode supporte)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification finale (après la dernière task implémentée)

- [ ] **Suite complète verte**

Run: `.venv\Scripts\python -m pytest -q`
Expected: 0 échec. Référence d'avant D4 : **792 tests, 1 skipped** ; D4 ajoute ~30 tests (les tests de schéma `test_adaptive_llm.py` sont remplacés, pas seulement ajoutés — le compte net peut varier).

- [ ] **Mettre à jour `CLAUDE.md`** (section État courant) avec une ligne D4 : moteurs A+B, route `evaluator` débloquée, nouveau compte de tests.

- [ ] **Daily / décision** : noter le résultat du spike union (Task 9) et le compte de tests final.

---

## Self-Review (effectuée à l'écriture)

**Couverture spec :**
- §3.1 signature `build_llm_spec(task, client, failure_context=None)` → Task 4 (signature) + Task 5 (comportement informé).
- §3.2 `AdaptiveSpecEvaluator(failure_context=...)` → Task 6.
- §3.3 route `evaluator` de D3 passe un `FailureContext` → Task 8.
- §4.1 union taguée + risque/mitigation → Task 2 (schéma plat `type`-discriminé = mitigation, name↔params encodé) + Task 9 (union stricte si supportée).
- §4.2 importance discrète → weight 3/2/1 → Task 2 (`_IMPORTANCE_WEIGHT`, `to_criterion`).
- §4.3 caps (≤4 llm_check, ≤6 scorés) par troncature → Task 3.
- §4.4 threshold dérivé (0.8/0.7/0.6, sans tags 0.7) → Task 1 (`_derive_threshold`) + Task 4 (override LLM).
- §4.5 rationale additif → Task 1 (`CriterionSpec.rationale`) ; clés distinctes `name#k` → Task 7.
- §4.6 fallback déterministe avec threshold dérivé → Task 1 (`build_adaptive_spec`).
- §4.7 prompt réécrit (5 types, importance, caps, rationale, section échec, plus de threshold) → Task 4 + Task 5.

**Cohérence des types :** `_LLMCriterion`/variantes → `to_criterion()` → `CriterionSpec(name, params, weight, rationale)` ; `_apply_caps(list[CriterionSpec]) -> list[CriterionSpec]` ; `_derive_threshold(task) -> float` ; `_criteria_keys(criteria) -> list[str]`. Noms identiques d'une task à l'autre.

**Placeholders :** aucun — chaque step de code montre le code complet ; la seule branche (Task 9) est explicitement sanctionnée par la spec (§4.1 « l'union est isolable ») et ses deux issues sont entièrement spécifiées.
