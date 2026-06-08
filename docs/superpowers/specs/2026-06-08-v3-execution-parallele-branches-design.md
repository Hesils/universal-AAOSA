# V3 — Exécution parallèle des branches indépendantes de `run_chain`

Date : 2026-06-08
Statut : **spike design** (proposition, n'engage pas l'archi). Aucun code runtime concurrent écrit.
Dépend de : D1 (division émergente récursive) + D2 (agrégateur DAG-aware). Prérequis durs : Gap 5, Gap 13.
Périmètre : `runtime/runner.py` (`run_chain`, `_topological_order`), `elo/updater.py`, `tracing/events.py` + `tracing/tracer.py`, `dashboard/graph_model.py` (consommateur Gap 13).

> **Constat de spike en tête.** Aucun prérequis ne s'est révélé infaisable. Les deux gaps (5, 13)
> sont adressables sans réécriture du runtime — ce sont des ajouts (champ d'identité sur les events,
> instantané ELO figé). La concurrence elle-même est déjà présente dans le code (`run_phase2_async`),
> donc le risque technique est borné. Le travail réel n'est pas « rendre concurrent » mais **rendre
> les invariants implicites du séquentiel explicites** pour qu'ils survivent à l'entrelacement.
> Statut **done** : c'est un constat de spike, pas un blocage.

---

## 1. Problème — séquentiel vs ce que le DAG permet

`run_chain` (runner.py) trie les sous-tâches en ordre topologique (Kahn, `_topological_order`) puis
les exécute **strictement en séquence** :

```python
order = _topological_order(sub_tasks)
for task in order:
    unmet = [dep for dep in task.depends_on if dep not in outputs]
    if unmet:
        continue
    ...
    result = run_with_recovery(task_to_run, ctx, depth, chained_context=chained_context)
```

Le tri de Kahn linéarise le DAG. Mais un DAG porte du **parallélisme de niveau** : à chaque étape,
*tous* les nœuds dont les dépendances sont satisfaites sont prêts simultanément. La linéarisation
les exécute l'un après l'autre alors qu'ils sont indépendants.

### Illustration sur un fan-out réel

Division typique (cf. démo incident) :

```
        ┌──> investigate_db   ──┐
diagnose┤                       ├──> synthesize
        └──> investigate_cache ─┘
```

- Niveau 0 : `diagnose` (1 nœud).
- Niveau 1 : `investigate_db`, `investigate_cache` — **indépendants**, ne partagent que leur dep `diagnose`.
- Niveau 2 : `synthesize` (consomme les deux).

Aujourd'hui : `diagnose` → `investigate_db` → `investigate_cache` → `synthesize` = 4 appels LLM
sérialisés (+ claiming + QA par nœud). Chaque `run_with_recovery` est dominé par la latence réseau
(`agent.execute` boucle d'outils, juge QA, divider). Le niveau 1 pourrait s'exécuter en `gather`,
divisant le mur-temps du fan-out par le degré de parallélisme (ici ÷2). Sur un fan-out large
(N investigations indépendantes), le gain est ×N sur ce niveau.

**Ce que le parallélisme ne change PAS** : le résultat logique. Les dépendances restent respectées
(un niveau N+1 n'est lancé qu'après complétion du niveau N). Seul l'ordre d'émission des effets de
bord (mutations ELO, events tracés) cesse d'être déterministe — d'où Gap 5 et Gap 13.

---

## 2. Gap 5 — l'ELO mute intra-run

### Où ça mute

`update_agent_elo` (updater.py) **mute l'agent en place** :

```python
agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, raw))   # ou del agent.tags_with_elo[tag]
```

Appelé depuis `run_task` (runner.py) après chaque QA réussie/échouée. Dans un run divisé, le **même**
agent peut gagner plusieurs sous-tâches. En séquentiel, chaque verdict déplace son ELO *avant* que la
sous-tâche suivante ne rejoue Phase 1.

### État actuel : déjà tranché pour le séquentiel

Gap 5 est **clos en séquentiel** (documentation-technique.md §5.2, 2026-06-04) : choix « assumer
l'application immédiate » (apprentissage intra-run, effet borné par le plafond de delta). Le
spike ne rouvre pas ce choix pour le séquentiel.

### Ce que la concurrence ajoute : une *race*, pas juste une dérive

En parallèle, deux nœuds du même niveau gagnés par le même agent peuvent appeler `update_agent_elo`
**simultanément** sur le même `dict` `agent.tags_with_elo`. Trois problèmes distincts :

1. **Lecture-modification-écriture non atomique** : `elo_before = dict(...)`, `compute_delta`, puis
   écriture. Deux threads entrelacés peuvent perdre une mise à jour (last-write-wins sur un `old`
   périmé). En CPython le GIL protège les opérations bytecode atomiques individuelles, **pas** la
   séquence read-modify-write : la corruption est réelle.
2. **Phase 1 lit un ELO en cours d'écriture** : un nœud du même niveau qui rejoue `passes_filter` /
   `fit_score` lit un `tags_with_elo` partiellement muté. Non déterministe et non rejouable.
3. **Suppression de tag concurrente** (`del agent.tags_with_elo[tag]` sous le seuil de perte) =
   `KeyError` potentiel chez un lecteur concurrent.

### Comment figer un instantané

Le principe (déjà listé en piste §5.2) : **figer un instantané de l'ELO au début du niveau parallèle
et n'appliquer les mutations qu'après le `gather`.** Concrètement :

- **Lecture** : chaque nœud d'un même niveau claime/score contre un **snapshot ELO immuable** pris
  avant le lancement du niveau (les agents en lecture seule, ou une copie `tags_with_elo` par agent).
  → supprime la race de lecture (problème 2) et stabilise la topologie du niveau.
- **Écriture** : `update_agent_elo` ne mute plus l'agent pendant le `gather`. Il **retourne déjà**
  un `EloUpdateResult` complet (deltas, acquired, lost, before/after). On collecte les
  `EloUpdateResult` du niveau et on les **applique en série après le join**, dans un ordre
  déterministe (ordre des sous-tâches du divider). → supprime la race d'écriture (problèmes 1, 3).

Cela demande un découplage : séparer **calculer le résultat ELO** (pur, déjà le cas) de **l'appliquer
à l'agent** (mutation). Aujourd'hui les deux sont fusionnés dans `update_agent_elo` (`_apply_delta`
mute en même temps qu'il calcule). Le découpage proposé : `compute_elo_update(agent_snapshot, task,
success) -> EloUpdateResult` (pur) + `apply_elo_update(agent, result)` (mutation isolée). C'est une
**refactor sans changement de comportement séquentiel** (l'ordre d'application reste l'ordre Kahn).

### Impact sur l'asymétrie per-tag

L'asymétrie du barème (un succès rapporte peu / un échec coûte K — Gap 6, assumée) est **préservée
exactement** : `compute_delta` est inchangé, seul le *moment* d'application change (fin de niveau vs
immédiat). Subtilité honnête : avec snapshot par niveau, deux succès du **même** agent sur deux nœuds
frères calculent leur delta contre le **même** ELO de départ — ils ne se « confirment » plus
mutuellement intra-niveau. C'est un léger affaiblissement de l'apprentissage immédiat, **borné au sein
d'un niveau** (entre niveaux, le snapshot est rafraîchi). À assumer et documenter (cf. décision §5.2
existante, qui couvre déjà l'application différée comme une option légitime).

---

## 3. Gap 13 — events entrelacés

### Quels events s'entrelacent

`Tracer.emit` (tracer.py) **append à une liste partagée** (`self.events.append`). `StreamingTracer`
écrit en plus dans un handle de fichier. Aucun des deux n'est thread-safe, et surtout : le
**consommateur** suppose un ordre.

`build_graph` (dashboard/graph_model.py) reconstruit les sous-tâches en supposant que leurs events
sont émis **de façon contiguë et séquentielle**. `_Pass._split_passes` détecte une nouvelle passe à
un `Phase1FilteredEvent` qui suit un event d'un autre type — une **frontière inférée par contiguïté
d'ordre**, pas par identité. Cet invariant tient *uniquement* parce que `run_chain` est séquentiel.

Sous concurrence, les events de `investigate_db` et `investigate_cache` (chacun : Phase1 ×N, Phase2,
Dispatched, Executed, QA, EloUpdated…) s'**interfolient** dans la liste. `_split_passes` mélangerait
alors silencieusement les deux sous-runs : un `Phase1FilteredEvent` de `investigate_cache` arrivant au
milieu des events de `investigate_db` serait lu comme une frontière de passe interne. Corruption
silencieuse de l'observabilité — exactement le scénario nommé en §6 Gap 13.

### Note : `task_id` est déjà là, mais insuffisant

Tous les events portent déjà `task_id` (`_BaseEvent`). `build_graph` groupe déjà par `task_id` au
niveau `_TaskRun`. **Mais** `_split_passes` re-segmente *à l'intérieur* d'un `task_id` par contiguïté
(pour séparer les retries D3 d'une même tâche). C'est ce niveau-là qui casse : deux sous-tâches ont
des `task_id` distincts, donc le groupement par tâche les sépare correctement — le vrai risque est
l'**ordre d'append dans la liste partagée** et tout consommateur futur qui lirait le flux comme une
séquence par session plutôt que par tâche.

### Comment porter l'identité de sous-tâche

Deux compléments, du plus simple au plus robuste :

1. **Tracer thread-safe** (prérequis minimal) : protéger `emit` par un `threading.Lock` (la liste
   reste cohérente, le fichier `StreamingTracer` n'entrelace pas des demi-lignes). Ne résout PAS la
   réinférence par ordre, mais empêche la corruption de structure de données.
2. **Identité explicite de sous-tâche sur chaque event** (piste §6) : tous les events portent déjà
   `task_id` ; il faut que `build_graph` **groupe et segmente par `task_id` (et par tentative), jamais
   par contiguïté d'ordre**. Remplacer la frontière inférée de `_split_passes` par un découpage piloté
   par `(task_id, attempt_index)`. La donnée existe quasi intégralement ; manque un marqueur de
   tentative explicite (aujourd'hui inféré du `DiagnosedEvent` + Phase1 suivant) pour distinguer une
   passe initiale d'un retry D3 sans dépendre de l'ordre.

→ Le travail Gap 13 est **majoritairement côté consommateur** (`build_graph`), pas côté runtime. Le
runtime n'a qu'à (a) émettre de façon thread-safe et (b) garantir qu'aucune identité ne dépend de
l'ordre d'émission. C'est une bonne nouvelle pour le découpage : Gap 13 peut être préparé **avant**
toute concurrence, à séquentiel constant (refactor de `_split_passes` testable sur traces existantes).

---

## 4. Approche proposée — `gather` sur les nœuds prêts d'un niveau Kahn

Miroir direct de `run_phase2_async` (phase2.py), qui fait déjà tourner les claims des candidats en
parallèle via `asyncio.to_thread(agent.claim, …)` + `asyncio.gather`. Le pattern est éprouvé dans le
code ; on l'étend d'un cran (du claiming au nœud entier).

### Forme cible (esquisse, non implémentée)

`_topological_order` (qui renvoie une liste plate) est complété/remplacé par un découpage en
**niveaux** : `_topological_levels(sub_tasks) -> list[list[Task]]`, chaque niveau = les nœuds dont
toutes les deps sont dans les niveaux précédents (in-degree 0 à cette vague). Puis :

```python
async def run_chain_async(sub_tasks, ctx, depth, chained_context=None):
    levels = _topological_levels(sub_tasks)
    outputs: dict[str, Output] = {}
    for level in levels:
        ready = [t for t in level if all(dep in outputs for dep in t.depends_on)]
        snapshot = freeze_elo(ctx.agents)              # Gap 5 : lecture stable du niveau
        async def _run_node(task):
            resolved = [outputs[dep] for dep in task.depends_on]
            task_to_run = task.model_copy(update={"required_outputs": resolved})
            return task.id, await asyncio.to_thread(
                run_with_recovery, task_to_run, ctx_with_snapshot(ctx, snapshot),
                depth, chained_context,
            )
        results = await asyncio.gather(*(_run_node(t) for t in ready))
        for tid, res in results:                       # application DÉTERMINISTE post-join
            if isinstance(res, Output):
                outputs[tid] = res
        apply_pending_elo_updates(ctx.agents, order=ready)   # Gap 5 : écriture sérialisée
    return outputs
```

Points clés :
- **`asyncio.to_thread`** : `run_with_recovery` est synchrone et bloquant (appels OpenAI SDK
  synchrones). On le pousse dans un thread du pool, exactement comme `run_phase2_async` le fait pour
  `agent.claim`. Pas de réécriture async du runtime.
- **Barrière par niveau** : on `gather` un niveau entier, on join, *puis* on applique ELO et passe au
  niveau suivant. La barrière est ce qui rend le snapshot ELO cohérent et l'ordre d'application
  déterministe.
- **`run_chain` séquentiel reste l'API par défaut** ; `run_chain_async` est un chemin opt-in (comme
  `run_phase2` vs `run_phase2_async` coexistent). Rétrocompat stricte : sans opt-in, comportement V3
  identique.

### Trade-off : asyncio vs threads

| Critère | `asyncio.to_thread` (proposé) | `ThreadPoolExecutor` direct | async natif (SDK async) |
|---|---|---|---|
| Réécriture runtime | Nulle (wrap synchrone) | Nulle | **Lourde** (tout le chemin `execute`/divider/juge en async) |
| Cohérence avec l'existant | **Forte** (= `run_phase2_async`) | Moyenne | Faible (nouveau paradigme) |
| Modèle mental | 1 (asyncio partout) | 2 (asyncio claiming + threads chain) | 1 |
| Vrai parallélisme I/O | Oui (threads libèrent le GIL sur I/O réseau) | Oui | Oui |
| Contrôle de la concurrence | `gather` + sémaphore si besoin | `max_workers` natif | `gather` + sémaphore |

**Recommandation du spike** : `asyncio.to_thread` + `gather`. C'est le miroir exact d'un pattern déjà
validé et testé dans le repo, coût de réécriture nul, un seul modèle mental (asyncio) pour toute la
concurrence du runtime. Les appels LLM étant I/O-bound, les threads libèrent le GIL pendant l'attente
réseau : le parallélisme est réel. Un async natif n'apporterait un gain que si le runtime entier
passait en async — hors proportion pour ce spike. **Non engageant** : ce choix est présenté en option,
à valider par Quentin.

---

## 5. Risques

### R1 — Déterminisme des traces
L'ordre d'émission des events au sein d'un niveau devient non déterministe. Mitigation : Gap 13
(découpage par identité, pas par ordre) + tri stable des events par `(task_id, timestamp)` à la
lecture si un ordre d'affichage canonique est requis. Les tests qui assertaient un ordre d'events
**absolu** dans un run divisé deviennent fragiles → audit nécessaire (cf. §6).

### R2 — Court-circuit D2 sous concurrence
`_sinks` + le court-circuit « un seul sink → on retourne sans agréger » (runner.py) sont **purs** et
calculés **après** `run_chain` (post-join). Donc indépendants de l'ordre d'exécution intra-niveau —
**non impactés** tant que la barrière par niveau tient. Risque résiduel : si un futur refactor
calculait les sinks au fil de l'eau (streaming) plutôt qu'après join, la concurrence le casserait. À
garder explicitement post-barrière.

### R3 — Ordre d'agrégation des sinks
`aggregator.aggregate` reçoit `sinks` dans l'**ordre de `sub_tasks`** (ordre du divider), pas l'ordre
de complétion. Comme `_sinks` itère `sub_tasks` et `outputs_by_id` est rempli post-join, l'ordre
d'agrégation reste déterministe **à condition** que `outputs` ne soit pas muté dans l'ordre de
complétion des `gather`. La forme §4 (boucle d'application déterministe après join) le garantit. Risque
si on insérait dans `outputs` depuis les callbacks de complétion → à proscrire.

### R4 — Tracer non thread-safe
`emit` append concurremment → liste corrompue / lignes JSONL entremêlées dans `StreamingTracer`.
Mitigation : lock dans `emit` (Gap 13, item 1). Faible coût.

### R5 — Containment d'erreur par nœud
`run_with_recovery`/`run_task` contiennent déjà leurs exceptions (renvoient `DispatchResult`, ne
propagent jamais). Donc un nœud qui échoue dans un `gather` **ne fait pas tomber le niveau** : il
renvoie un non-`Output`, simplement absent de `outputs`. `asyncio.gather` sans `return_exceptions`
suffit puisque les coroutines ne lèvent pas. **À vérifier** : que `asyncio.to_thread` ne transforme
pas une exception inattendue (hors containment) en échec global du `gather` — préférer
`return_exceptions=True` par prudence.

### R6 — Profondeur × largeur (explosion de threads)
Récursion D1 : un nœud parallèle peut lui-même se diviser et lancer son propre `gather`. Sans borne,
N niveaux × M branches = explosion du pool de threads. Mitigation : sémaphore global de concurrence
(borne le nombre d'appels LLM simultanés), partagé via `RunContext`. `MAX_RECOVERY_DEPTH=3` borne déjà
la profondeur.

### R7 — `RunContext` frozen + snapshot ELO
`RunContext` est `frozen=True`. Injecter un snapshot ELO par niveau implique soit un nouveau champ
(non-frozen ? ou `ctx.model_copy`-like via `dataclasses.replace`), soit passer le snapshot hors ctx.
Préférer `dataclasses.replace(ctx, ...)` ou un paramètre explicite, sans casser l'immutabilité.

---

## 6. Découpage en plans implémentables

Ordre imposé par les dépendances : **les deux prérequis d'abord, à séquentiel constant, puis la
concurrence.** Chaque plan a un critère vérifiable (tests verts) formulé avant le code.

### Plan A — Gap 13 préparé (séquentiel, aucune concurrence)
- Refactor `build_graph._split_passes` : segmenter par `(task_id, attempt_index)` explicite, plus par
  contiguïté d'ordre. Ajouter un marqueur de tentative explicite si nécessaire (event ou champ).
- Rendre `Tracer.emit` / `StreamingTracer.emit` thread-safe (lock).
- **Critère** : tests `dashboard/` existants verts sur traces actuelles + nouveau test « events
  d'une trace volontairement réordonnée/entrelacée → même graphe ». Aucun changement de comportement
  runtime.

### Plan B — Gap 5 préparé (séquentiel, aucune concurrence)
- Découpler `update_agent_elo` en `compute_elo_update` (pur) + `apply_elo_update` (mutation).
- Introduire `freeze_elo(agents)` / application différée, **sans** changer l'ordre séquentiel
  (l'application reste immédiate en séquentiel → comportement identique).
- **Critère** : tests `elo/` verts (comportement séquentiel byte-identique) + tests purs sur
  `compute_elo_update` (aucune mutation) et `apply_elo_update` (mutation isolée).

### Plan C — `run_chain_async` (concurrence, opt-in)
- `_topological_levels` (pur, testable hors LLM).
- `run_chain_async` miroir de `run_phase2_async` : `gather` par niveau, barrière, snapshot ELO (Plan
  B), application déterministe post-join, sémaphore de concurrence (R6), `return_exceptions=True` (R5).
- Court-circuit D2 et agrégation **post-barrière** inchangés (R2, R3).
- **Critère** : test « DAG fan-out, exécution parallèle → mêmes outputs/sinks/agrégat que
  `run_chain` séquentiel » (équivalence observable) + test « deux nœuds même agent → ELO appliqué une
  fois, déterministe » + audit/réparation des tests A3/D1 supposant un ordre d'events absolu (R1).

### Plan D (optionnel) — câblage entrée + démo
- Exposer le chemin parallèle depuis `run_recovery` / CLI (flag opt-in).
- Scénario démo fan-out (matériel nature C : « le graphe émergent s'exécute en parallèle »).
- **Critère** : run LLM réel d'un fan-out, trace capturée, dashboard fidèle (validation Quentin, pas la nuit).

---

## 7. Hors scope (nommé)
- **Async natif du runtime entier** (`execute`/divider/juge en `async def`) — surdimensionné, cf. §4.
- **Streaming des sinks / agrégation au fil de l'eau** — casserait R2/R3, explicitement post-barrière.
- **Calibration ELO** (ancres idée 4) — orthogonale, déférée depuis D1.
- **Validation navigateur / sign-off LLM réel** — jamais la nuit (Plan D), review Quentin au matin.
