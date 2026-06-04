# D1 — Division émergente récursive comme récupération

**Date** : 2026-06-04
**Statut** : design présenté, **3 réglages tranchés** (2026-06-04, cf. §10). Reste : spec self-review + revue utilisateur → writing-plans.
**Périmètre** : première des 4 évolutions du run (D1-D4) brainstormées le 2026-06-04. Voir roadmap AIOS, section « Évolutions du run ».

---

## 1. Principe

Aujourd'hui le run divisé (`run_divided_task`) appelle **obligatoirement** le divider en amont, avant tout claiming. D1 inverse : on tente la tâche **à plat** (un seul `run_task`) ; la division n'est qu'une **réponse à un échec de claiming**, appliquée récursivement.

Le divider passe de planificateur à réparateur. La thèse « le graphe émerge du claiming » devient littérale : le graphe ne grandit que quand la tentative à plat échoue. Deux unifications tombent gratuitement :
1. **Skip-divide (entrée déjà gérable) et terminaison de récursion = la même primitive** : le divider gagne un verdict d'atomicité.
2. **Auto-réparation et division émergente = le même flux de contrôle** : « tente à plat, divise sur échec ».

## 2. Décisions verrouillées (durant le brainstorm)

- **Modèle de récursion : approche A — paresseuse, sur échec.** `run_with_recovery` récursif ; on ne divise un nœud que lorsqu'il est `unassigned`, à n'importe quelle profondeur. (Rejeté : approche B avide / pré-expansion — spéculative, re-centralise, contre la thèse.)
- **Déclencheur de division = `unassigned` uniquement.**
  - `execution_failed` **exclu** : panne purement technique, pas un signal de taille.
  - `qa_fail` **hors périmètre** → renvoyé tel quel, traité par D3. `qa_fail` ne divise jamais à l'aveugle.
- **Garde-fou `roster_gap`** : si un tag requis est absent de **tout** le roster, on ne divise pas, on remonte le signal (ne pas diluer le trou de roster).
- **Module de tag assignment (tagger)** : nouveau composant, agnostique à la provenance. **Re-tague chaque sous-tâche depuis sa propre description** — pas d'héritage des tags du parent (sémantiquement faux : un enfant atomique ne porte pas forcément tous les tags du parent ; ex. parent CSS+SQL, enfant SQL seul). Lazy sur la racine : le tagger la tague **seulement si le caller n'a pas épinglé de tags** ; une racine déjà taguée n'est jamais re-taguée.
- **ELO : barre uniforme (idée 3).** Le tagger ne pose que l'**ensemble** des tags ; le seuil est une constante unique `DEFAULT_REQUIRED_ELO`, identique partout. Pas de jugement de difficulté par tâche → pas de sur-division fantôme. (Rejetées pour D1 : idée 1 tagger pose l'ELO par tâche ; idée 2 calibrateur tiers ; idée 4 ancres par tag. Idée 4 retenue comme **approche de la calibration déférée**, pas dans D1.)

## 3. Composants — ce qui naît, ce qui change

| Composant | Fichier | Changement |
|---|---|---|
| **Tagger** (nouveau) | `runtime/tagger.py` | LLM : description → ensemble de tags requis (**≥ 1 garanti** par schéma + validateur), ancré sur le vocabulaire du roster. Ne pose **pas** l'ELO. Sortie vide malgré la contrainte → clean-crash (§6), jamais d'exception non rattrapée. |
| **Divider** | `runtime/divider.py` | Devient **purement structurel** : renvoie un `DivisionResult` (`is_atomic` + sous-specs `description` + `depends_on_indices`), **sans** tags, **sans** construire de `Task`, **sans** résoudre les deps indices→IDs, **sans** émettre d'event. `TagSpec`/`required_tags` retirés de `SubTaskSpec` ; le fallback « hérite des tags du parent » (`divider.py:86`) disparaît. |
| **Aggregator** | `runtime/aggregator.py` | Inchangé en D1 (forme plate réutilisée par niveau ; D2 raffinera la forme). |
| **Runner** | `runtime/runner.py` | `run_recovery` (entrée publique, lazy racine) + `run_with_recovery` (cœur récursif) + helper `build_sub_tasks` (tague chaque sous-spec → `Task`, résout deps indices→IDs, **émet `TaskDividedEvent`** avec les vrais tags, clean-crash si tag ∅). `run_chain` quasi inchangé : seul l'exécuteur par nœud passe de `run_task` à `run_with_recovery`, + `depth`. `run_divided_task` remplacé (callers démo + tests à mettre à jour). `MAX_RECOVERY_DEPTH` vit ici. |
| **DispatchResult** | `claiming/dispatch.py` | Statut `"roster_gap"` ajouté au `Literal`. |
| **RosterGapEvent** (nouveau) | `tracing/events.py` | Event dédié (tag(s) manquant(s) + identité tâche), émis par le runner si `tracer` fourni. Destiné à remonter le trou de roster comme signal actionnable ; **rendu dashboard = follow-up** (cf. §9). |
| **Constantes** | `schemas/elo.py` · `runtime/runner.py` | `DEFAULT_REQUIRED_ELO = ELO_COMPETENT_MIN` (= 30) dans `elo.py` (avec l'échelle ELO existante) ; `MAX_RECOVERY_DEPTH = 3` dans `runner.py` (près de `run_with_recovery`, comme `MAX_TOOL_ROUNDS` près de son usage). |

## 4. Flux de contrôle

Deux formes seulement : une **sous-spec** (`{description, depends_on_indices}`, émise par le divider, sans tags ni ID) et une **`Task`** (taguée, claimable). Le **tagger est le pont** `sous-spec → Task`, avec **deux sites d'appel** : l'**entrée racine** (taguée seulement si le caller n'a pas épinglé de tags) et `build_sub_tasks` (chaque sous-tâche, toujours). `run_with_recovery` reçoit donc toujours une `Task` déjà taguée. `run_with_recovery` et `run_chain` sont **mutuellement récursifs**.

```
run_recovery(description, ctx, pinned_tags=None):   # entrée publique (remplace run_divided_task)
    task = Task(description, pinned_tags) if pinned_tags else tag(description, ctx)   # lazy racine : tagger SI non épinglé
    return run_with_recovery(task, ctx, depth=0)

run_with_recovery(task, ctx, depth=0):       # task TOUJOURS taguée à l'entrée
    1. gate roster_gap : task.required_tags absents de TOUT le roster ?
         → oui : emit RosterGapEvent(manquants) si tracer ; return DispatchResult(roster_gap)
    2. result = run_task(task, ...)                          # tentative à plat (claiming) — jamais récursif
    3. Output / QAFailure / execution_failed → return result # terminaux (qa_fail → D3 ; exec = panne tech)
       unassigned → on tente de récupérer
    4. depth >= MAX_RECOVERY_DEPTH → return result            # filet anti-emballement
    5. division = divider.divide(task, ...)                   # STRUCTUREL : is_atomic + [{description, depends_on_indices}]
         is_atomic → return result                           # cul-de-sac réel : unassigned remonté
    6. sub_tasks = build_sub_tasks(division, ctx)            # ← TAGGER ICI : chaque sous-spec → tags frais → Task ;
                                                            #   résout deps indices→IDs ; émet TaskDividedEvent (tags réels) ;
                                                            #   clean-crash execution_failed si une sous-spec tague ∅ (§6)
    7. sub_results = run_chain(sub_tasks, ctx, depth+1)       # ← RÉCURSION : run_chain rappelle run_with_recovery par nœud
    8. successful = outputs réussis ; aucun → DispatchResult(unassigned, "aucune sous-tâche récupérée")
    9. try: return aggregator.aggregate(task, successful, ...)   # stratégie B
       except: return successful[-1]                            # fallback C : dernier output réussi

run_chain(sub_tasks, ctx, depth):            # quasi inchangé vs A3
    tri Kahn ; pour chaque tâche dans l'ordre :
        deps non satisfaites → DispatchResult(dependency_failed)
        sinon : required_outputs ← outputs des deps
                run_with_recovery(task, ctx, depth)          # ← SEUL changement : exécuteur = run_with_recovery (était run_task)
```

- **Tagger = pont sous-spec → Task**, deux sites. (a) `build_sub_tasks` tague **chaque** sous-tâche depuis sa propre description (pas d'héritage parent). (b) L'entrée racine (`run_recovery`) tague la racine **uniquement si le caller n'a pas épinglé de tags** ; une racine déjà taguée n'est jamais re-taguée (décision §2, précisée).
- **`run_chain` quasi inchangé** : tri Kahn + cascade `dependency_failed` + threading `required_outputs` identiques ; seul l'exécuteur par nœud passe de `run_task` à `run_with_recovery`, plus le paramètre `depth`. → **auditer les tests A3** (ils supposaient `run_task`).
- Récursion **profondeur-d'abord séquentielle** : un nœud divisé agrège ses propres enfants *avant* de remonter → **l'agrégation en arbre tombe gratuitement** (D2 raffinera la *forme* de chaque agrégation, pas la structure).
- **Seul `run_task` est strictement intact.** Tagger et récursion vivent **uniquement** dans la couche de récupération, jamais dans `run_task`. La rétrocompat stricte porte sur `run_task`, **pas** sur `run_chain`.

## 5. Le point subtil : tagger + roster_gap

Pour que `roster_gap` puisse *exister*, le tagger doit pouvoir nommer une capacité **absente** du roster. S'il ne voyait que les tags disponibles avec l'ordre de « les utiliser », il maquillerait toujours un besoin réel en tag existant et ne signalerait jamais un trou.

Solution (même philosophie que le prompt actuel du divider, `divider.py:44-57`) : le tagger voit le vocabulaire du roster **comme référence**, privilégie les tags existants quand ils collent, mais nomme la vraie capacité même si absente. Le gate compare : `missing = required_tags - {tags de tous les agents}`. Pur, cheap, déterministe.

Le gate tourne **à chaque niveau** : une sous-tâche dont le tagger produit un tag introuvable échoue en `roster_gap` (ses dépendants → `dependency_failed`), jamais maquillée en `unassigned` générique. Comme le gate précède chaque division, on ne re-divise jamais en boucle un besoin que le roster ne couvre pas.

## 6. Atomicité = terminateur + skip

`DivisionResult` gagne `is_atomic: bool`. Le validateur passe de « au moins une sous-tâche » à « `is_atomic` XOR sous-tâches non vides ». Prompt du divider : « si la tâche est atomique (une seule capacité, non décomposable utilement), `is_atomic=true`, aucune sous-tâche ; sinon décompose en descriptions + dépendances, **sans** assigner de tags ». Même primitive partout : verdict atomique en bas = terminaison ; et comme on ne divise que sur échec, le skip au sommet est gratuit (une tâche qui passe à plat n'est jamais soumise au divider).

**Tagger contraint + clean-crash (F4).** Le schéma LLM du tagger impose **au moins un tag** (et un validateur le re-vérifie), car `Task` interdit `required_tags` vide (`task.py:26`) et la construction se fait dans `build_sub_tasks` / `run_recovery`, **hors** du containment de `run_task`. Filet : si le tagger renvoie malgré tout un ensemble vide, on renvoie proprement `DispatchResult(status="execution_failed", reason="tagging produced no tags")` — panne technique, pas un signal de taille, donc pas de division. Aucune exception ne remonte tuer le run.

## 7. ELO — barre uniforme

Le tagger ne pose que l'**ensemble** des tags. Le runner construit `required_tags = {tag: DEFAULT_REQUIRED_ELO}`. Un seul nombre, partout. La différenciation entre agents ne disparaît pas, elle se déplace : tie-break dispatch (`fit_score`) + claiming Phase 2 + gate QA + boucle ELO trient la qualité a posteriori. On arrête seulement de **pré-juger** la difficulté au filtre Phase 1. Plus fidèle à la thèse (auto-sélection + qualité apprise, pas pré-jugement central).

> **Conséquence assumée — acquisition de tags.** Le tagger range *tous* les tags dans `required_tags` (filtre dur de Phase 1), aucun dans `acquirable_tags`. Sur les sous-tâches récupérées, la boucle V2 « un agent gagne un tag en réussissant » ne fire donc pas (`passes_filter` exige déjà chaque tag détenu). Choix délibéré pour D1 : on veut des agents déjà qualifiés. L'acquisition redeviendra activable quand on retravaillera la mécanique de définition ELO/tag des tâches (calibration déférée, idée 4 §2) — pas dans D1.

## 8. Simplification de signatures

Threader `agents, client, divider, aggregator, tagger, tracer, evaluator, depth` dans chaque appel ferait exploser les signatures. Proposition : un **`RunContext`** (dataclass frozen) portant les dépendances statiques ; seul `depth` reste threadé explicitement. Amélioration ciblée du code qu'on réécrit de toute façon.

## 9. Hors scope D1 (nommé pour ne rien prétendre)

- **Observabilité des traces récursives** : `build_graph` ne garde aujourd'hui que la *première* division (Gap 14) et infère les frontières de sous-runs par contiguïté (Gap 13). Un run récursif émet plusieurs divisions imbriquées → rendu **incomplet** au dashboard. D1 produit des traces correctes (y compris `RosterGapEvent`) ; leur rendu fidèle au dashboard est un follow-up (lié Gap 13/14), pas D1.
- **`qa_fail`** → D3 (diagnostic d'échec inline). **Forme de l'agrégateur** → D2. **Calibration ELO** (ancres idée 4) → déférée. **Exécution parallèle** → plus tard (prérequis Gaps 5 + 13).

## 10. Réglages — TRANCHÉS (2026-06-04)

1. **`DEFAULT_REQUIRED_ELO` = `ELO_COMPETENT_MIN` (= 30).** « Qualifié, pas expert » = la borne basse du palier COMPETENT (30-50) dans l'échelle existante (`schemas/elo.py`). 30 est fidèle à l'intention *et* au vocabulaire du projet. 25 a été écarté : il colle pile sur `ELO_ACQUIRABLE_THRESHOLD` (= `ELO_BASIC_MAX` = 25), frontière acquérable/requis, sémantiquement bruitée. Ancré à la constante, pas un nombre magique. Ajustable si les runs montrent un claiming trop laxiste.
2. **`MAX_RECOVERY_DEPTH` = 3** (tâche → sous → sous-sous). Point de départ ; on relèvera si les runs réels le justifient.
3. **`roster_gap` = `RosterGapEvent` dédié** (pas seulement un `reason`). Raison : le trou de roster est un signal **actionnable côté utilisateur** (un tag requis qu'aucun agent ne couvre) ; un event propre le fait remonter clairement au dashboard et incite fortement à l'action. Émis par le runner si un `tracer` est fourni (même contrat optionnel que les autres events), porte le(s) tag(s) manquant(s) et l'identité de la tâche.

## 11. Stratégie de tests (TDD)

- **Purs** : `_roster_gap` (logique d'ensembles), mapping tagger→`required_tags` (barre uniforme `DEFAULT_REQUIRED_ELO`), `build_sub_tasks` (construction Task + résolution indices→IDs), gestion du verdict atomique, cap de profondeur, lazy racine (caller épinglé → pas de tagger ; non épinglé → tagger), clean-crash `execution_failed` si tag ∅.
- **Récursion (LLM mocké)** : flat→unassigned→divide→sous-chaîne→agrégation ; roster_gap (racine + sous-tâche) ; cul-de-sac atomique ; cap de profondeur atteint ; agrégation en arbre (division imbriquée).
- **Rétrocompat** : `run_task` strictement inchangé (V1/V2) ; `run_chain` *recovery-aware* (exécuteur = `run_with_recovery`, + `depth`) — non-régression du tri Kahn et de la cascade `dependency_failed` sur les tests A3 existants.
- **Run LLM réel** : un scénario où une tâche large échoue à plat puis se récupère par division.

---

## Annexe — Les 4 évolutions du run (contexte décomposition)

Brainstormées le 2026-06-04, une spec à la fois, D1 d'abord. Principe unificateur : la division devient un mécanisme de récupération, pas une phase obligatoire.

- **D1** (cette spec) — Division émergente récursive comme récupération. Inclut tagger + roster_gap.
- **D2** — Forme de l'agrégateur (agréger un arbre bottom-up, pas une liste plate). Dépend de D1.
- **D3** — Diagnostic d'échec inline (triage runtime sur `qa_fail` : `task_spec`/`evaluator`/`agent` + routage, une route = division). **Franchit la séparation stricte** « B2/B3 jamais dans `run_task` » (CLAUDE.md) → décision d'architecture à part entière. Recoupe D4.
- **D4** — Refonte de la génération d'évaluateur (`build_llm_spec`, `qa/adaptive.py`). Touche la route `evaluator` de D3.
- **Plus tard** — Exécution parallèle des branches indépendantes. Prérequis durs : Gap 5 (ELO mute intra-run → snapshot à figer) + Gap 13 (events entrelacés → identité de sous-tâche sur events).
