# V3 — Tuning seed `run_demo_v3` (run divisé qui passe le QA réel + agrégation visible)

Date : 2026-06-03
Statut : design validé (brainstorming), prêt pour plan d'implémentation
Branche cible : `feat/v3-seed-tuning-run-demo`

## Problème

Depuis le fix du bug spec (Session 7, commit `83a426f`), `run_demo_v3` finit `unassigned` :
les vrais critères LLM rejettent les outputs des agents → aucune sous-tâche ne réussit →
`run_divided_task` retourne `unassigned` sans agrégation. La démo end-to-end (chemin critique
V3 : division → tool calls → QA avec spec → ELO → agrégation) ne se déroule jamais en entier.

C'est un bloquant pour la **nature C** (démo portfolio, ESN 21 sept 2026) : la démo doit montrer
TOUT d'un coup — vrais critères `llm_check` + `judge` qui passent **parce que les outputs sont
bons**, et agrégation progressive visible sur le dashboard (observabilité vague 2).

## Diagnostic (evidence, run réel du 2026-06-02)

Un run de diagnostic a capturé les raisons QA réelles depuis la trace persistée. Le divider
produit un DAG sensé de 6 sous-tâches (investigate auth → analyze SQL → combine root cause →
implement fixes → regression test → synthesize report). **Le découpage n'est pas le problème.**

Deux mécanismes d'échec distincts, puis cascade :

1. **Sous-tâche 0 (auth)** — QA FAIL `score=0.67`, threshold `0.7`. Les critères déterministes
   passent (`det=0.94`). Mais le judge a été émis avec un **poids 1.0** par le LLM
   (`final = (1−w)·det + w·judge = 0·0.94 + 1.0·0.67 = 0.67`). Le judge est devenu le **signal
   primaire** — ce que la séparation stricte V2b interdit (« Le LLM-judge n'est jamais le signal
   primaire, poids 0.3 »). `build_llm_spec` laissait le LLM fixer `weight` librement.

2. **Sous-tâche 1 (SQL)** — QA FAIL `score=0.0`, `gate failed: min_length (166/300 chars)`.
   `build_llm_spec` a fait de `min_length` un **gate** à 300 chars. L'agent a produit 166 chars
   (réponse maigre, sans appeler `explain_query_plan`) → 0 instantané. V2b ne prévoit que
   `non_empty` comme gate.

3. **Cascade** — les sous-tâches 2-5 dépendent toutes de 0 et/ou 1 → `dependency_failed` →
   aucun `Output` réussi → `unassigned`.

Faits d'implémentation utiles :
- `min_length` est **gradué** (`score = min(1, n/threshold)`), pas binaire. À 166/300 → 0.55.
  Le passer de gate à scoré ne suffit donc pas : la qualité de l'agent reste nécessaire pour
  dépasser le threshold.
- `JudgeSpec.weight` a pour défaut `0.3` ; c'est le LLM qui a émis 1.0.
- Conséquence : **le fix invariants seul fait passer la sous-tâche 0** (`0.7·0.94 + 0.3·0.67 = 0.86`).
  Comme elle est sans dépendance, `successful` devient non-vide → **l'agrégation est garantie**.
  La cascade ne casse alors que la *richesse* de l'agrégation, plus son existence.

## Décisions de cadrage (brainstorming)

- **Principe : qualité réelle des outputs.** On ne dégrade pas les critères pour « tricher ». Le
  QA doit valider parce que les outputs sont bons.
- **Scope : corriger `build_llm_spec` + tuner le seed.** Les violations d'invariants V2b dans
  `build_llm_spec` (judge poids 1.0, `min_length` en gate) sont un **vrai bug de génération de
  spec**, distinct de la qualité des agents. Les corriger = faire respecter à l'évaluateur sa
  propre spec V2b, pas du reward hacking.
- **Fiabilité cible : les deux.** Seed robuste qui passe de façon fiable + capture d'une trace
  canonique persistée pour le dashboard.
- **Approche A retenue** : fix invariants + qualité agents ciblée, **sans toucher le divider**
  (l'émergence du graphe reste intacte ; la chaîne de dépendances réaliste est un atout démo).

## Design

### Composant 1 — Garde-fous d'invariants dans `build_llm_spec` (`src/aaosa/qa/adaptive.py`)

Empêcher **par construction** que le LLM produise une spec qui viole V2b :

- **Retirer le champ `weight` de `_LLMJudge`.** `to_judge()` retombe alors sur le défaut
  `JudgeSpec.weight = 0.3`. Le LLM ne contrôle plus le poids du judge → toujours 0.3, jamais
  primaire.
- **Retirer le champ `gate` de `_LLMCriterion`.** Le LLM ne peut plus déclarer de gate ; tous
  ses critères sont scorés (`gate=False` via le défaut `CriterionSpec`). `_ensure_non_empty_gate`
  (déjà en place) injecte/force `non_empty` comme **seul** gate. `min_length` redevient donc
  toujours scoré (gradué), jamais un rejet sec.
- **Ajuster `_build_prompt`** : retirer l'instruction « Toujours inclure non_empty comme
  gate=True » (le champ n'existe plus) et toute mention du poids du judge. Reformuler pour dire
  que `non_empty` est ajouté automatiquement comme gate, et que le LLM ne propose que des
  critères scorés (avec leurs poids) + un judge optionnel (rubric).

Le poids **des critères scorés** (`_LLMCriterion.weight`) reste contrôlé par le LLM — c'est
légitime en V2b (pondération des critères déterministes). Seul le poids du *judge* est verrouillé.

### Composant 2 — Qualité réelle des outputs (`src/aaosa/demo/agents.yaml`, `tools.py`)

Racine du `0.0` : l'agent SQL a écrit 166 chars sans utiliser ses tools. Fix :

- **`agents.yaml`** : ajouter à chaque `system_prompt` une directive de méthode (style RISEN) :
  investiguer avec les tools disponibles avant de répondre ; fournir une réponse complète qui
  cite le code pertinent, explique la cause racine, et inclut un correctif concret (code/SQL) avec
  explications. Cible prioritaire : Backend (winner principal du run divisé).
- **`tools.py`** : enrichissement minimal pour donner de la matière exploitable —
  `explain_query_plan` renvoie une recommandation d'index explicite (ex. `CREATE INDEX ... ON
  orders(user_id)`). `read_file` et `run_tests` sont déjà suffisants. Pas de sur-ingénierie.

### Composant 3 — Divider / aggregator : inchangés

Aucune modification. L'émergence du graphe reste intacte (« le graphe émerge — aucune découpe
hardcodée »). La chaîne investigate→analyze→combine→fix→test→synthesize illustre la résolution de
dépendances par tri topologique Kahn — c'est un atout de la démo, pas une fragilité à masquer.

### Composant 4 — Tests & capture de trace canonique

- **TDD sur le Composant 1** (vrai changement de code, sans LLM réel) :
  - `_LLMJudge` n'expose plus `weight` ; `_LLMCriterion` n'expose plus `gate`.
  - `to_spec()` d'un `_LLMEvaluatorSpec` avec judge → `judge.weight == 0.3`.
  - après `_ensure_non_empty_gate`, `non_empty` est l'**unique** critère avec `gate=True`, quels
    que soient les critères proposés par le LLM (y compris si le LLM en propose plusieurs ou omet
    `non_empty`).
  - mettre à jour les tests existants de `tests/qa/test_adaptive.py` cassés par le retrait des
    champs.
- **Composant 2 validé par run LLM réel** (comme Session 9 pour le seed health check), pas de
  tests unitaires sur les prompts.
- **Critère de réussite** : un run `run_demo_v3` qui aboutit à une **agrégation alimentée par
  plusieurs sous-tâches réussies**, trace persistée dans `runs/`, rendu vérifié sur le dashboard
  (observabilité vague 2). 706 tests existants + nouveaux tests invariants verts.
- **Note `runs/`** : gitignored → la trace canonique est régénérée localement ; ce qui est
  versionné c'est le seed robuste (code + YAML), pas la trace.

## Invariants V2b/V3 préservés

- `EvaluatorSpec` reste une **donnée** ; B1 ne change que le producteur. Le format est inchangé.
- Le LLM-judge n'est jamais le signal primaire (poids verrouillé à 0.3).
- Seul `non_empty` est un gate (gates déterministes = rejet gratuit, judge sauté si gate échoue).
- `_filter_unknown_criteria` et le fallback `build_adaptive_spec` restent en place.
- `AdaptiveSpecEvaluator` et la signature du runner sont inchangés.
- Tools stubés déterministes (A5) ; agents en LLM réel.

## Hors scope (assumé)

- Pas de rework du divider ni de la cascade de dépendances (émergence préservée).
- Pas de garantie déterministe à 100 % du run (LLM non-déterministe) ; on vise un seed robuste +
  une trace canonique capturée.
- Le seed `run_health_check_v3` (B3) est déjà résorbé (Session 9) — hors scope ici.
