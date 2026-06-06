# Design — Démo phase 1 : observabilité série D (arbre émergent bottom-up)

Date : 2026-06-06 · Statut : validé (brainstorm 2026-06-06, sessions 02:21 + reprise)
Prérequis de la campagne démo (phases 2-5). Brainstorm : superpowers:brainstorming + companion visuel
(mockups `.superpowers/brainstorm/421-1780703023/` et `.superpowers/brainstorm/1004-1780732949/`).
Frontend designé sous `/impeccable` (register product, système « wireframe instrument » verrouillé `DESIGN.md`).

## 1. Contexte et objectif

La série D (D1 récursion de récupération, D2 agrégation par sinks, D3 diagnostic/routage,
D4 régénération de spec) est entièrement muette côté dashboard :

- `build_graph` ne lit que le **premier** `TaskDividedEvent` → la récursion D1 est invisible ;
- `RosterGapEvent` est émis mais jamais rendu — une tâche roster_gap n'émet aucun Phase1,
  elle est invisible même comme run ;
- la chaîne D3 n'émet rien (`diagnose_failure` n'émet AUCUN event) : diagnostic, retry consignes,
  ré-évaluation spec v2, origine des divisions sont indétectables.

Objectif : rendre le run de récupération complet (D1+D3+D4) **observable et rejouable** dans le tab
Sessions — c'est le cœur narratif de la démo portfolio (cadrage 2026-06-06, zéro seed).

## 2. Décisions structurantes (actées, ne pas re-trancher)

| # | Décision | Justification |
|---|----------|---------------|
| 1 | **Scope D3 = chaîne complète par inférence** : `DiagnosedEvent` (seul event ajouté) + 2e `QAEvaluatedEvent` émis par le runner sur ré-éval spec v2 ; retry et origine des divisions inférés dans `build_graph` (zéro champ, zéro event retry) | La trace contient déjà l'info ; pattern observer préservé |
| 2 | **Récursion D1 = arbre émergent** : le graphe grandit physiquement au replay ; zoom + drag + auto-centrage sur le sous-arbre actif ; TODO hiérarchique navigable | Lire la subdivision dans la structure |
| 3 | **roster_gap = nœud terminal dédié** (tags manquants en label, cul-de-sac sans descente) | Signal actionnable autoporteur, side-demo live |
| 4 | **diagnostic = nœud DIAG dédié** sur la descente, arête sortante = route prise | Exigence forte de lisibilité du routage |
| 5 | **Structure = arbre pur** : pipeline instancié par branche, agents instanciés badge ×N, pas de tier global | Zéro croisement, branche lisible à toute profondeur. **Réserve explicite de Quentin** : à challenger à l'implémentation ; fallback documenté §8 |
| 6 | **Orientation bottom-up** : INPUT/OUTPUT aux racines (bas), l'arbre pousse vers le haut, les résultats redescendent | Philosophie claiming bottom-up du projet ; cohérent avec le design V2c (I/O = roots) |
| 7 | **Arche par branche** : DISPATCH (montée) → AGENT au sommet (tools en canopée) → EVAL (descente) | Montée = la tâche cherche son agent ; les agents restent les feuilles |
| 8 | **Paire DIVIDER/AGGREGATOR par niveau** : divider = émetteur (gauche), aggregator = récepteur des sinks (droite), descente vers le niveau inférieur (aggregator parent ou OUTPUT) | Mappe 1:1 sur le runtime : chaque niveau de `_divide_and_recover` émet son propre `TaskAggregatedEvent` |
| 9 | **Retry D3 = loop-back interne à la branche** (badge PASS 2 ; route evaluator = EVAL rallumé badge v2) | La croissance de l'arbre est réservée à la subdivision ; un retry n'est pas une nouvelle structure |
| 10 | **Phase 1/2 restent fusionnées dans le nœud DISPATCH** (candidates/claims dans son modal) | Décision V2c maintenue |
| 11 | **TAGGER inféré** : nœud sur le tronc pour la racine, aucun event runtime ; tags des sous-tâches dans le modal DIVIDER | Pas de réouverture de la section events ; l'info est dans `TaskDividedEvent`/meta |
| 12 | **Routage géométrique delta 45°** : bus d'émission + bus de collecte, diagonales convergentes ; convention point = jonction réelle, croisement sans point = pas de contact | Routes communes lisibles quand l'arbre grossit ; esthétique retenue par Quentin |
| 13 | **Colorway crest → fire** : arêtes de montée en `--crest`, descente en `--fire`, pulses directionnels en redondance | La tâche « chauffe » en se résolvant ; un seul héros chaud préservé (anti-slop) |
| 14 | **Follow-mode débrayable** : auto-centrage par défaut, suspendu par interaction manuelle, bouton ⌖ pour réactiver | Pattern standard (suivi de logs/cartes), prévisible |

## 3. Section 1 — Events et émissions runtime (validée 2026-06-06)

### 3.1 `DiagnosedEvent` (nouveau, seul event ajouté)

```python
class DiagnosedEvent(_BaseEvent):
    type: Literal["diagnosed"] = "diagnosed"
    agent_id: str | None          # agent du failed output (None si inconnu)
    attribution: str              # "agent" | "evaluator" | "task_spec" | "unattributed"
    reason: str                   # raison du diagnostic ("" si échec LLM)
    consignes: str | None         # consignes de correction (route agent/evaluator)
```

- Émis par `_route_diagnostic` (`runner.py`) **y compris sur échec LLM** (`diagnostic is None`
  → `attribution="unattributed"`). `diagnostic.py` reste pur (pattern observer : le runtime émet,
  jamais le module de diagnostic).
- Ajouté à l'union `ClaimEvent` (discriminator `type`).

### 3.2 Ré-évaluation visible (route evaluator)

`_route_diagnostic`, branche `evaluator` : après `qa2 = new_evaluator.evaluate(task, failure.output)`,
le **runner** émet un 2e `QAEvaluatedEvent` portant `qa2` (dont `spec` = la spec régénérée via
`QAResult.spec_used`). La trace montre ainsi : QA v1 (fail) → diagnosed → QA v2 (spec régénérée).

### 3.3 Zéro event retry — inférence dans `build_graph`

- **Passe retry** : le retry (`_retry_with_consignes`) passe par `run_task` avec
  `task.model_copy(...)` qui **conserve `task.id`** → les events de la passe 2 portent le même
  `task_id`. Une nouvelle séquence Phase1 qui suit un `DiagnosedEvent` = passe 2.
- **Origine d'une division** (dans les events du `task_id`, juste avant son `TaskDividedEvent`) :
  `UnassignedEvent` → division D1 (recovery) · `DiagnosedEvent(attribution="task_spec")` → division D3.

## 4. Section 2 — `build_graph` : reconstruction en arbre (validée)

### 4.1 Partition par `task_id` + passes

`_split_sub_runs` (heuristique frontière Phase1) est remplacé par une **partition par `task_id`**
(fiable : `_BaseEvent.task_id` sur tous les events). Dans la partition d'une tâche, découpage en
**passes** : nouvelle séquence Phase1 après un `DiagnosedEvent` = passe retry (`pass_index=1`).

### 4.2 Arbre de tâches

Reconstruit depuis **tous** les `TaskDividedEvent` : chaque event relie `task_id` parent →
`sub_tasks[].id` enfants. Un enfant qui a son propre `TaskDividedEvent` devient un sous-arbre
(récursion D1/D3 naturelle). Racine = la tâche de la session (meta, ou la seule tâche tracée).

### 4.3 Nœuds namespacés (arbre pur)

Pipeline instancié par branche : `dispatch:<tid>`, `evaluator:<tid>`, `agent:<tid>:<aid>`,
`tool:<tid>:<name>`, `divider:<tid>`, `aggregator:<tid>`, `roster_gap:<tid>`, `diagnostic:<tid>`.
`input`, `output` et `tagger` restent globaux (racines + tronc). Le badge ×N (même agent sur
plusieurs branches) est un calcul frontend sur les `agent_id` réels portés par les nœuds.

### 4.4 Évolutions du modèle Pydantic

- `Outcome` : + `roster_gap`, + `diagnosed`
- `NodeType` / `MilestoneType` : + `roster_gap`, + `diagnostic`, + `tagger`
- `GraphEdge` : + `flow: Literal["ascent", "descent", "transient"]` (le frontend colore sans ré-inférer)
- `GraphStep` : + `pass_index: int = 0` (0 = première tentative, 1 = retry)
- `StepDetail` : + `diagnostic: DiagnosticDetail | None` (`attribution`, `reason`, `consignes`,
  `route_taken`) · + `roster_gap: RosterGapDetail | None` (`missing_tags`)
- `TodoItem` : + `parent_id: str | None`, + `depth: int`, + `first_step_index: int | None`
  (le calcul JS `firstStepIndexForTask` migre côté backend)

### 4.5 Walk unique — run simple = arbre dégénéré

`_milestones_simple` et `_milestones_divided` fusionnent en **un seul walk récursif** : pour chaque
tâche de l'arbre, rendre sa branche (jalon par jalon, dans l'ordre d'émission) ; si elle a un
`TaskDividedEvent`, descendre dans ses enfants. Un run non divisé = arbre à un nœud, même code,
profondeur 0. Conséquence assumée : **le contrat API graphe casse** (IDs namespacés) — frontend
réécrit (§5), tests `build_graph` migrés, tab Health couvert par la non-régression (§6).

### 4.6 Règles d'apparition (honnêteté avec le runtime)

- `aggregator:<tid>` **seulement** sur `TaskAggregatedEvent` réel de ce niveau. Court-circuit
  single-sink (D2) : pas de nœud, la descente du sink file directement au niveau inférieur.
- Seuls les **sinks** descendent vers l'aggregator de leur niveau ; une sous-tâche consommée par
  une sœur (dep) circule en arête `transient` vers la branche dépendante.
- `roster_gap:<tid>` sur `RosterGapEvent` (la tâche n'a ni Phase1 ni dispatch : branche réduite
  au cul-de-sac).
- `diagnostic:<tid>` sur `DiagnosedEvent` (au plus un par tâche, le runtime ne re-diagnostique
  pas après retry).
- `tagger` : rendu sur le tronc quand la racine porte des `required_tags`. Caveat assumé : la
  trace ne distingue pas tags inférés vs épinglés (`pinned_tags`) — le modal montre les tags
  sans affirmer leur origine.

## 5. Section 3 — Frontend (validée)

### 5.1 Layout : arbre bottom-up, arches, paires

- **Racines en bas** : INPUT (gauche) → TAGGER → paire racine ; OUTPUT (droite) reçoit la descente
  finale. La hauteur de l'arbre = profondeur de subdivision.
- **Arche par branche** : montée par DISPATCH, AGENT au sommet (hex, tools en canopée pointillée),
  descente par EVAL. Organes alignés en rangées entre branches (grille).
- **Paire par niveau** : DIVIDER (gauche) émet via le **bus d'émission** (rail + risers vers chaque
  branche) ; AGGREGATOR (droite) collecte via le **bus de collecte** (les descentes des sinks
  fusionnent puis plongent). La descente du niveau va à l'aggregator parent ou à OUTPUT.
- **DIAG** : losange `--warn` inséré sur la descente (EVAL ✗ → DIAG), arête sortante étiquetée
  `route: agent|evaluator|task_spec`. Route agent/evaluator = **loop-back pointillé** vers la jambe
  de montée (badge PASS 2 au DISPATCH ; route evaluator = EVAL rallumé badge v2). Route task_spec =
  une paire divider/aggregator pousse un étage au-dessus de la branche.
- **ROSTER GAP** : nœud `--fail` terminal, tags manquants en label, riser rouge, aucune descente.

### 5.2 Routage géométrique (dialecte C)

Delta 45° : diagonales convergentes pour les fusions, verticales pour les jambes, rails horizontaux
pour les bus. Convention schéma électrique : **point = jonction réelle, croisement sans point =
pas de contact**. Grille fixe (colonnes par branche, rangées par organe).

### 5.3 Couleur et motion (amendement DESIGN.md)

- Arêtes de **montée** = `--crest` · arêtes de **descente** = `--fire` · arêtes `transient`
  (deps, agent→tool) = `--wire` pointillé. Idle = `--wire`.
- Pulses `animateMotion` directionnels : points crest montent, points ember descendent.
  La direction n'est jamais portée par la couleur seule.
- DESIGN.md sera amendé : `--crest` gagne l'usage « arête de montée du graphe » (famille chaude,
  pas de nouvelle teinte ; la réserve `--cool` = charts only est **maintenue**).
- Le reste du système est inchangé : hex agents, ember = actif/winner, glow réservé au live path.

### 5.4 Caméra

Zoom molette ancré au curseur + drag pan (transform sur le viewBox SVG, pas de lib).
**Follow-mode débrayable** : auto-centrage animé (~250ms ease-out) sur le bounding box des
`active_nodes` du jalon courant ; suspendu par toute interaction manuelle ; bouton `⌖ suivre`
réactive. Auto-fit au chargement.

### 5.5 TODO hiérarchique

Indentation par `depth`, sous-arbres imbriqués (récursion), annotations d'état en marge
(pass 2, roster gap, route diag), clic = saut à `first_step_index`. Expand `⤢` (modal texte) inchangé.

### 5.6 Modals

- **DIAG** : attribution, reason, consignes, route prise.
- **ROSTER GAP** : `missing_tags`, reason du `DispatchResult`.
- **EVALUATOR pass-aware** : montre l'éval de la passe au jalon courant ; specs v1/v2 distinctes
  sur la route evaluator.
- **DIVIDER** : sous-tâches + leurs `required_tags` (tags posés à la division).
- DISPATCH (candidates/claims), AGENT, TOOL, AGGREGATOR : inchangés dans leur principe.

### 5.7 Scrubber

Mécanique inchangée. Labels enrichis : `ROSTER GAP`, `DIAGNOSTIC · route X`, suffixe `· pass 2`,
`EVALUATOR v2`, et la sous-tâche concernée.

## 6. Section 4 — Tests et DoD (validée)

### 6.1 Backend — TDD strict (pattern vague 2, subagent-driven)

- **Events** : `DiagnosedEvent` (3 routes + unattributed sur échec LLM), 2e `QAEvaluatedEvent`
  sur ré-éval (spec régénérée portée). Tests runner.
- **`build_graph`** : tests migrés vers le nouveau contrat + nouveaux tests — partition `task_id`,
  passes retry (`pass_index`), inférence origine division, arbre récursif (paire par niveau),
  court-circuit single-sink sans aggregator, roster_gap, diagnostic, tagger, `GraphEdge.flow`,
  TODO hiérarchique, run simple = arbre dégénéré.
- **Fixtures synthétiques** pour les chemins rares (récursion profonde, roster_gap, routes D3) —
  aucune dépendance à un run LLM réel pour couvrir le walk.

### 6.2 Frontend — hors TDD auto (pattern V2c)

Layout delta 45°, caméra, TODO, modals : validation sur contrat API live, puis checklist navigateur.

### 6.3 DoD

1. Tous les tests verts (822 existants + nouveaux, zéro régression).
2. Un run réel `run_recovery` (LLM) persisté rend l'arbre complet : division, arches, descentes,
   replay jalon par jalon.
3. Checklist navigateur Sessions : arbre bottom-up, bus, colorway, follow-mode (suspension + ⌖),
   TODO navigation, modals (DIAG, roster_gap, evaluator pass-aware), labels scrubber.
4. Non-régression tab Health (consomme aussi `renderGraph`).
5. Sign-off navigateur par Quentin (comme Task 13 vague 2).

## 7. Hors scope explicite

- Live mode (post-démo, prérequis entretien).
- Rendu multi-runs par session (limitation 1 run/graphe assumée, décision vague 2).
- Phases 2-5 de la démo : tools YAML, monde simulé + roster, CLI `run`/`campaign`, campagne + curation.
- `TaggedEvent` runtime (écarté — décision 11).

## 8. Fallback documenté (réserve décision 5)

Si l'arbre pur se révèle illisible à l'implémentation (densité de nœuds dupliqués), le fallback est
le **tier d'agents global conservé** : les agents restent un tier fixe (identité ELO, compétition
visibles), divider/dispatch/evaluator instanciés par niveau, arêtes des branches vers le tier.
Coût connu : croisements d'arêtes dès la profondeur 2, auto-centrage tiraillé. Mitigations de
l'arbre pur à épuiser d'abord : badge ×N + hover illuminant toutes les instances d'un agent +
compétition dans le modal DISPATCH.

## 9. Références

- Capture brainstorm démo : `raw/brainstorms/2026-06-05-demo-run-propre-complete.md` (vault)
- Sessions vault : `wiki/Projects/universal-AAOSA/sessions/2026-06-06.md`
- Mockups : `.superpowers/brainstorm/421-1780703023/content/` (decisions 2-5) et
  `.superpowers/brainstorm/1004-1780732949/content/` (bottom-up, routage delta 45°, colorway)
- Design system : `DESIGN.md` / `PRODUCT.md` (racine repo)
- Runtime série D : `src/aaosa/runtime/runner.py` (`run_with_recovery`, `_route_diagnostic`,
  `_divide_and_recover`), `src/aaosa/tracing/events.py`
