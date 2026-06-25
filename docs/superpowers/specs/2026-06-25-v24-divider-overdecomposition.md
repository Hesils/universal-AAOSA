# Spec `v24` — Divider sur-décompose les tâches code+doc (sur-décomposition + mis-routing)

> Statut : **proposée** (diagnostic prouvé par trace ; plan à valider par Quentin avant TDD).
> Ticket : `v24` (P2, `#universal-AAOSA`, pas d'épique).
> Origine : 1er smoke réel du pont AIOS→AAOSA (ticket AIOS `hsd`). Persiste malgré PR #6 (`630729f` — split composite tags + harden divider atomicity).
> Cadrage (session 2026-06-25) : **diagnostic d'abord** (fait, ci-dessous) ; **fix = les 3 surfaces** (divider + tagger + runner) ; mode **plan/spec d'abord**.
> Preuve : repro live `dev` roster, run `context/aaosa-runs/20260625T105833-ffc59e09/…/trace.jsonl` (verdict `success`, mais 3 divisions récursives + 3× doc redondante).

## 1. Symptôme

Sur une simple tâche code+doc (« lis `solve.py`, écris un helper `validate_verdict`, documente-le »), le runtime produit le bon verdict final (`success`) **mais** :
- **3 divisions récursives** là où une seule (code → doc) suffit.
- `solve.py` **documenté 3×** en doublon.
- Outputs poubelle rattrapés par la QA gate → **coût LLM gaspillé** (9 exécutions agent pour un travail qui en demande 2).

## 2. Root cause — prouvé par trace

### 2.1 L'arbre réel des 3 divisions

La racine échoue à plat (`unassigned`, *no agents claimed*) puis se divise. Chaque division reproduit le **même motif** `Read → Write → Document`, et c'est la sous-tâche **Write** qui relance la récursion :

| niveau | sous-tâche « Write » (description) | tags émis par le tagger | dispatch |
|---|---|---|---|
| 1 | « Write a helper… **based on the understanding gained from solve.py** » | `{writing, python, coding, documentation}` | **unassigned** → re-divise |
| 2 | « Write the helper… based on the understanding… » | `{writing, python, coding, documentation}` | **unassigned** → re-divise |
| 3 | « **Implement** the helper… » | `{python, coding}` ✅ | python-dev claim → succès |

La récursion s'arrête au niveau 3 (= `MAX_RECOVERY_DEPTH`, et par chance un wording sobre « Implement »).

### 2.2 Les trois défauts qui s'auto-alimentent

**A. La récursion est pilotée par `unassigned` (D1), pas par `task_spec` (D3).**
Les 2 events `diagnosed` du run sont `attribution=agent` (sur les sous-tâches « Read »), donc retry agent — **jamais** re-division. Ce qui re-divise, c'est exclusivement la branche `unassigned` (`runner.py:510` → `_divide_and_recover`).

**B. Le `unassigned` vient du tagger, pas d'un dispatch malchanceux.**
Sur « Write a function **based on the understanding gained** », le tagger émet `{writing, python, coding, documentation}` — un set qui **couvre deux rôles** (python-dev `{python,coding}` + tech-writer `{writing,documentation}`). L'AND-filter exige **un** agent portant les 4 tags → aucun ne les a tous → `unassigned`. Le tagger viole sa propre consigne « Never mix tags from different lines », amorcé par le wording explicatif. Preuve : dès que le divider dit sobrement « **Implement** » (niv. 3), le tagger tague proprement `{python, coding}` et le dispatch passe.

**C. Le trou structurel : aucun détecteur d'AND-set non-satisfiable par un agent unique.**
`_roster_gap` (`runner.py:34`) teste `required_tags - union(tous les agents)`. Les 4 tags existent **dans l'union** → aucun roster_gap → ça avance → dispatch ne trouve aucun agent **unique** → `unassigned` → re-divise. Re-diviser un tel set est **futile** : ça reproduit le même split cross-rôle. Il manque l'invariant « satisfiable par l'union **mais par aucun agent seul** » = AND-set structurellement inexécutable.

**D. Les « 3× solve.py documenté » = sous-tâches fantômes « Read ».**
Les 3 sous-tâches « Read the file solve.py to understand… » sont taguées `{writing, documentation}` → routées vers **tech-writer**, qui ne sachant pas « lire » **documente** `solve.py` à chaque niveau. Or *lire pour comprendre n'est pas un livrable* : c'est un `fetch_file` à l'exécution. Le divider fabrique un deliverable qui n'en est pas un.

## 3. Plan de fix — 3 surfaces compounding

Les fixes A→C ci-dessous se renforcent : **les prompts (1, 2) suppriment la cause** côté LLM (non déterministe) ; **le runner (3) est le verrou déterministe** qui borne le mode d'échec même si un prompt régresse.

### Fix 1 — Divider : pas de sous-tâche « Read/understand » fantôme
- **Où** : `divider.py::_build_divide_prompt` (le bloc d'instructions, ~l.121-139).
- **Quoi** : ajouter une règle explicite — une sous-tâche est un **livrable**. Lire/analyser/comprendre du code existant est fait par l'exécutant **à l'exécution via ses tools** (`fetch_file`), **jamais** une sous-tâche séparée. Ne pas émettre de sous-tâche dont le verbe est read/analyze/understand/review-to-understand.
- **Effet** : tue le motif `Read → Write → Document` → plus de 3× doc, et la division d'une tâche code+doc redevient `code → doc` (2 sous-tâches).

### Fix 2 — Tagger : interdire le mélange cross-rôle
- **Où** : `tagger.py::_build_prompt` (~l.50-62).
- **Quoi** : durcir la consigne « Never mix tags from different lines » — le set émis doit être un **sous-ensemble d'une seule ligne-rôle**. Distinguer explicitement **produire du code** (`{python,coding}`) de **décrire/documenter du code** (`{writing,documentation}`) : un « write/implement a function » reste code-only même phrasé « based on the understanding » ou « helper ». Un « describe/document the parameters » reste doc-only.
- **Note** : prompt-only = non déterministe ; le Fix 3 est le filet.

### Fix 3 — Runner : détecteur d'AND-set non-satisfiable par un agent unique (le verrou)
- **Où** : `runner.py`, en amont de la re-division `unassigned` (`run_with_recovery`, ~l.510) ; fonction pure nouvelle à côté de `_roster_gap`.
- **Quoi** : `_no_single_agent_covers(task, agents) -> bool` = `not any(set(task.required_tags) <= set(a.tags_with_elo) for a in agents)`. Pur, sans LLM, sans ELO (présence de tag seulement, comme `_roster_gap`).
- **Sémantique** : un AND-set couvert par l'union mais par **aucun agent seul** est un **défaut de tagging**, pas une opportunité de division. Re-diviser est futile (reproduit le même split).
- **Trace** : émettre un event distinct (`UnsatisfiableTagSetEvent` ou réutiliser `RosterGapEvent` avec un flag) nommant les tags fautifs — observabilité du défaut.

## 4. Décision ouverte — que fait le runner quand l'AND-set est non-satisfiable ?

Le détecteur (Fix 3) est clair ; **l'action** ne l'est pas. Trois options :

| Option | Comportement | Verdict |
|---|---|---|
| **A. Re-tag once puis dispatch** | Re-taguer la sous-tâche en forçant un **sous-ensemble single-rôle** (collapse vers le rôle dominant), retenter le dispatch ; échec → fail loud. | **VALIDÉE (2026-06-25)**. Récupère le cas nominal (la sous-tâche EST atomique single-rôle, c'est juste le tag qui a sur-couvert) sans re-division gaspilleuse. Coût : 1 ré-appel tagger ciblé. |
| B. Fail loud (signal terminal) | Traiter comme un `roster_gap`-like : la sous-tâche échoue proprement, pas de re-division. | Rejetée comme primaire : transforme un run aujourd'hui `success` en échec — régression observable. Reste le **fallback** quand le re-tag échoue (la branche fail-loud de A). |
| C. Statu quo + borne | Garder la re-division mais la borner durement sur détection cross-rôle (1 seule au lieu de 3). | Rejetée : ne traite pas la cause, garde du gaspillage. |

**Tranché (2026-06-25) : option A.** Sur détection cross-rôle, re-tag single-rôle puis retry dispatch ; si toujours non-satisfiable, fail loud (= B comme branche terminale de A, pas comme stratégie). Le re-tag ne doit jamais produire un set vide (invariant tagger ≥ 1 tag).

## 5. Invariants à préserver

- **Le graphe émerge** : on ne hardcode aucune découpe. Fix 1/2 = consignes de prompt ; Fix 3 = détecteur pur, pas une découpe imposée.
- **Phase 1 déterministe / Phase 2 cognitive** : Fix 3 est Phase-1-like (pur, sans LLM). Le re-tag (option A) reste un appel tagger isolé, pas un mélange des phases.
- **Rétrocompat** : `_no_single_agent_covers` est additif ; sans cross-rôle, comportement V3 identique. Roster mono-rôle = jamais déclenché.
- **`_roster_gap` inchangé** : le nouveau détecteur est distinct (union OK mais pas d'agent unique), il ne remplace pas le gap « tag absent du roster ».
- **Tagger ≥ 1 tag garanti** : le re-tag (option A) ne doit jamais produire un set vide (sinon `EmptyTaggingError`, déjà géré).

## 6. Plan de test (TDD)

**Pleinement nuit-compatible (backend pur, déterministe)** :
- `_no_single_agent_covers` : table de cas — set single-rôle (False), set cross-rôle couvert par l'union (True), tag absent du roster (relève de `_roster_gap`, pas du nouveau détecteur), roster mono-rôle (jamais True).
- Branche runner : sur AND-set non-satisfiable, **pas** d'appel à `divide` (mock divider, asserter zéro division) + event émis.
- Option A : `_retag_single_role` (ou équivalent) appelé une fois, dispatch retenté, fail loud si toujours non-satisfiable (divider/dispatch mockés).
- Régression : un fixture « tâche code+doc » qui, avec un tagger mocké produisant le set cross-rôle historique, **ne récurse plus** (assert ≤ 1 division).

**LLM-réel = review matin Quentin (jamais la nuit)** : rejouer le smoke `dev` (`--context-dir` solve.py seul) et vérifier sur la trace : 1 seule division `code → doc`, 0 sous-tâche « Read », 0 doc redondante, ≤ 3 exécutions agent. DoD nuit = suite verte + (si run capturé) trace jointe ; sign-off LLM-réel par Quentin.

## 7. Changements par module (prévision)

| Module | Changement |
|---|---|
| `runtime/divider.py` | Prompt : règle « no read/understand sub-task » (Fix 1). |
| `runtime/tagger.py` | Prompt : durcir single-rôle / produce-vs-describe (Fix 2). |
| `runtime/runner.py` | `_no_single_agent_covers` pur + branchement avant re-division `unassigned` (Fix 3) ; option A = `_retag_single_role` + retry dispatch. |
| `tracing/events.py` | Nouvel event d'observabilité de l'AND-set non-satisfiable (ou flag sur `RosterGapEvent`). |
| `tests/runtime/` | Cas purs + régression anti-récursion. |

## 8. Hors scope

- Refonte du scoring claiming / ELO : non touché.
- Multi-rôle légitime (un agent futur portant `{python,coding,writing,documentation}`) : alors l'AND-set redevient satisfiable et le détecteur ne mord pas — by design, rien à faire.
- Tuning de `MAX_RECOVERY_DEPTH` : le verrou Fix 3 rend la borne moins critique ; on ne la touche pas.
