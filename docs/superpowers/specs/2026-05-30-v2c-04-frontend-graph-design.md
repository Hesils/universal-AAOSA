# V2c — Épique 04 — Frontend : composant graphe + overlay + scrubber — Design

- **Date** : 2026-05-30
- **Statut** : validé (deep-dive cross-check), prêt pour writing-plans
- **Projet** : universal-AAOSA
- **Prérequis** : Épique 03b (API REST : endpoints graphe + addendum data B1). Épique 02 (`build_graph` pur), 03a (collectors).
- **Spec source** : `2026-05-28-v2c-dashboard-design.md` Section 3 — composant graphe, overlay, Tab 4.

## Contexte & objectif

Le composant visuel central du dashboard, **commun à Tab 3 (health check) et Tab 4 (session run)** : rendu SVG du `GraphModel` en 3 bandes, overlay modal au clic (contenu adapté au type de nœud), scrubber de stepping (Tab 4). Vanilla JS + SVG, **pas de framework, pas de build step**, servi par Flask. Cette épique couvre l'essentiel de Tab 4 et **pose le squelette frontend** que l'Épique 05 complète (3 tabs restants).

**Résultat du cross-check aval (Épique 05)** : le `GraphModel` est **identique** entre session et health check (même structure produite par `build_graph`) ; seul le *montage* diffère (scrubber vs sélecteur de cas, stepping on/off). Le **seul engagement cross-épique** de 04 est donc l'**interface du composant graphe** (seam 2) et le **squelette de structure JS** (seam 5) — pas un gap de données… **sauf un** (voir ci-dessous).

**Gap data découvert (1er du projet) :** `agent.execute` construit l'input réel de l'agent comme `task.description + task.metadata["context"]` (cf. `src/aaosa/core/agent.py`), mais `SessionTaskRecord` ne persiste que `description` + `required_tags`. Le `context` n'est capturé nulle part → le dashboard masquerait une partie de ce que l'agent a vraiment reçu. Traité par un **addendum data rattaché à l'exécution 03b** (frère de B1), voir section dédiée.

## Décisions du deep-dive (2026-05-30)

- **S1 — Layout / auto-fit** : 3 bandes spatiales TOP / CENTER / BOTTOM (le `layer` vient du `GraphModel`). Arêtes **inactives très estompées + chemin actif net** (garde la structure lisible sans plat de spaghetti à 5+ agents). Distribution horizontale régulière des nœuds dans chaque bande, centrée. **viewBox auto-fit** calculé sur la bande la plus large (`width ≈ maxNodesParBande * (nodeW + gap)`, hauteur fixe 3 bandes) → tout loge sans scroll page ; contrôles zoom/dézoom optionnels en réserve.
- **S2 — Interface du composant (renderer dumb + wrappers)** : `renderGraph(svgEl, graphModel, activeStepIndex)` ne connaît **que** le rendu (dessiner nœuds/arêtes + surligner le step à l'index donné). Il ignore scrubber/sélecteur et session/health-check. Deux **wrappers fins par tab** pilotent `activeStepIndex` : Tab 4 (scrubber + todo), Tab 3 (sélecteur de cas, un `GraphModel` par cas, index reste 0, pas de stepping). Tab 3 réutilise `renderGraph` **sans retrofit** → Épique 05 mécanique.
- **S3 — Modale overlay** : modale centrée (gabarit validé : header + badge rôle, sections labellisées, footer métriques). Contenu **adapté par type de nœud**, mappé 1:1 sur `StepDetail`. Champs longs (system prompt, output, **context**) : **tronqué + toggle « voir tout » inline** (déplie sur place ; pas de scroll imbriqué).
- **S4 — Scrubber ↔ surbrillance ↔ todo (Tab 4)** : une seule source de vérité `activeStepIndex` (le wrapper la détient, le scrubber l'incrémente, tout en dérive). **Pas de re-fetch** : le `GraphModel` est chargé une fois (`/sessions/<id>/graph`), le scrubber navigue dans `steps[]` côté client. Le graphe surligne le chemin du **step courant seul** (chaque task = un dispatch indépendant, mêmes nœuds réutilisés → accumuler brouillerait). La **todo est cumulative** : tasks 0..i-1 cochées, task i en cours, i+1.. en attente.
- **S5 — Structure JS (ES modules multi-fichiers)** : `<script type="module">`, pas de build. `graph.js` (dumb) réutilisé par `sessions.js` (Tab 4) et `health.js` (Tab 3). **Épique 04 pose le squelette** (`index.html` shell + nav + `api.js` + `graph.js` + `modal.js` + `sessions.js`) ; **Épique 05 dépose 3 modules** dans `tabs/` (`infra.js`, `agents.js`, `health.js`). Single-page : nav montre/cache les tabs côté client, aucune route serveur par tab.
- **S6 — Skin** : **frais, propre à AAOSA**, conçu en implémentation via le skill `/impeccable` (itération live navigateur sur runs réels). Ce deep-dive fige structure + comportement, **pas le skin**. **Les maquettes du deep-dive (dark + emerald) ne sont PAS la cible visuelle** — ancrages structurels uniquement. (Cohérent avec la décision #8.)

## Hors scope

Tabs 1/2/3 (Épique 05), live mode (WebSocket/SSE), tout nouveau type de nœud V3, conception du skin final (déléguée à `/impeccable` en impl). Pas de TDD automatisé sur le frontend (vérification navigateur).

---

## Addendum data — capture du `context` (rattaché à l'exécution 03b)

### Problème

L'input réel de l'agent = `task.description + task.metadata["context"]` (`core/agent.py`, `execute`). La couche data (`SessionTaskRecord`) ne porte que `description` + `required_tags`. L'overlay Agent/Input afficherait donc un input partiel → infidélité d'un outil d'observabilité.

### Solution (additive — aucun schéma existant cassé)

| Élément | Emplacement | Action |
|---|---|---|
| `SessionTaskRecord` | `src/aaosa/tracing/store.py` | + champ `context: str \| None = None` (optionnel, backward compat — pattern projet `llm_metadata`/`evaluator`/B1) |
| construction du record | `src/aaosa/demo/run_demo.py` (constructeur de `SessionTaskRecord`) | renseigne `context=task.metadata.get("context") or None` (`save_session` reçoit le `meta` déjà construit) |
| `InputDetail` | `dashboard/graph_model.py` | + champ `context: str \| None = None` ; `_build_step` le porte depuis `meta_record` |
| overlay Input / Agent | `dashboard/static/js/modal.js` (Épique 04) | sous-bloc **Context** affiché **uniquement si non vide** (toggle inline comme les autres champs longs) |

**Rattachement** : cet addendum est un **frère de B1** (même nature « rendre l'overlay fidèle au run réel », même pattern additif). Il se folde dans l'**exécution 03b non encore démarrée**. → **Action** : le plan `docs/superpowers/plans/v2c-03b-rest-api.md` (déjà écrit) doit gagner une petite task pour cet addendum `context` avant l'exécution 03b. À traiter au moment d'exécuter 03b.

**Backward compat** : `context` optionnel → les saves/fixtures sans context restent valides ; `InputDetail.context = None` → l'overlay masque le bloc (comportement par défaut inchangé pour les runs sans context).

---

## Composant graphe (commun Tab 3 & 4)

### `renderGraph(svgEl, graphModel, activeStepIndex)`

- Rendu SVG du `GraphModel` en 3 bandes (`layer` = top/center/bottom).
- **Nœuds** : `input`/`output`/`testset` (top), `dispatch`/`evaluator` (center), agents (bottom). Label = `node.label`.
- **Arêtes** : toutes (`graphModel.edges`) tracées estompées ; celles de `steps[activeStepIndex].active_edges` en surbrillance (émeraude). Chemin sollicité net ; **winner** (`steps[i].winner_agent_id`) mis en avant (pulse) ; candidats non-winner grisés ; **branche fail** (`outcome === "qa_fail"`, arête vers `testset`) en pointillé.
- **Auto-fit** : viewBox dynamique selon le nombre de nœuds (bande la plus large) ; pas de scroll page.
- **Clic sur un nœud → `modal.js`** ouvre la modale adaptée au type, à partir de `steps[activeStepIndex].detail`.

### Overlay par type de nœud (`modal.js`, source = `StepDetail`)

- **Dispatch** (`detail.dispatch`) : `fit_score` Phase 1 par candidat, `claims` + justifications Phase 2, `winner_agent_id` / `dispatch_reason` / `unassigned_reason`.
- **Agent** (`detail.agents[id]`) : rôle (winner/candidate), `passed`, `fit_score`, `claim_decision` + `justification`, output (`output_summary`/`output_content` tronqué), `llm_metadata` (latence/tokens), `elo_deltas`, `tags_acquired`. **+ join B1** (agents du run, portés par `/api/sessions/<id>` resp. `/api/health-checks/<id>` — **pas** `/api/agents/<id>`, réservé à Tab 2) pour system prompt + ELO courant (barres par tag).
- **Evaluator** (`detail.evaluator`) : `ran`, gates/`criteria_results`, `judge` (mode + score), `score` final, `success`, `reason`.
- **Input** (`detail.input`) : `task_id`, `description`, `required_tags`, **+ `context` (addendum) si non vide**.
- **Output** (`detail.output`) : `produced`, `output_summary`/`output_content` (tronqué), `llm_metadata`.
- **TestSet** (`detail.testset`) : `forked`, `from_task_id` (lien vers le cas TestSet — résolu côté Tab 3).

## Tab 4 — Session run (`tabs/sessions.js`)

Toolbar (sélecteur de session + chips stats) + graphe + panneau todo (tasks de la session, cochées au fil du stepping) + scrubber (step task-par-task). Flux :

1. `api.js` → `GET /api/sessions` (liste) ; au choix d'une session → `GET /api/sessions/<id>` (meta + agents) **et** `GET /api/sessions/<id>/graph` (`GraphModel`).
2. Wrapper détient `activeStepIndex` (init 0). Scrubber l'incrémente/décrémente.
3. À chaque changement : `renderGraph(svg, graph, activeStepIndex)` + maj todo (cumulative) + maj chips.

## Structure des fichiers

```
dashboard/
  templates/index.html          # shell : nav 4 tabs + points de montage          ← 04
  static/
    css/style.css                # skin frais AAOSA (itéré via /impeccable)         ← 04
    js/
      api.js                     # fetch wrappers sur /api/* (no-store géré côté serveur) ← 04
      graph.js                   # renderGraph(svg, graphModel, activeStepIndex)    ← 04
      modal.js                   # overlay par type de nœud                          ← 04
      tabs/
        sessions.js              # Tab 4 : graph + scrubber + todo                   ← 04
        health.js                # Tab 3 : graph + sélecteur de cas                  ← 05
        agents.js                # Tab 2                                              ← 05
        infra.js                 # Tab 1                                              ← 05
      app.js                     # nav, monte le tab actif                           ← 04 (squelette)
```

Flask sert `index.html` (route `/`) + statics. Aucune route serveur par tab.

## Stratégie de test

- **Frontend hors TDD automatisé** : vérification manuelle navigateur (comme aios), sur runs réels persistés (Épique 01/03a/03b).
- **Addendum data context** : testé côté Python (TDD) avec l'exécution 03b — `save_session` persiste `context` quand présent ; `build_graph`/`InputDetail` le porte ; absent → `None` (non-régression des fixtures).
- **Golden path + edge cases au navigateur** : session sans winner (`unassigned`), QA fail (branche pointillée), session multi-task (scrubber + todo cochées + graphe step courant seul), overlay des 6 types de nœuds, prompt/output/context tronqués + expand, auto-fit sans scroll à N agents.

## Critères de done

- [ ] Addendum data `context` : `SessionTaskRecord.context` + `InputDetail.context` portés ; testé côté Python (folder dans l'exécution 03b).
- [ ] `renderGraph` : SVG 3 bandes, auto-fit sans scroll, arêtes inactives estompées + chemin actif net, pulse winner, pointillé fail, réutilisable Tab 3 & 4.
- [ ] `modal.js` : overlay adapté aux 6 types de nœuds ; expand inline sur prompt/output/context ; bloc Context masqué si vide.
- [ ] Tab 4 (`sessions.js`) fonctionnel : graphe + todo cumulative + scrubber synchronisés sur `activeStepIndex`, sans re-fetch.
- [ ] Squelette JS (index + nav + api + graph + modal + sessions + app) en ES modules ; `graph.js` réutilisable tel quel par l'Épique 05.
- [ ] Skin frais AAOSA itéré via `/impeccable`.
- [ ] Vérifié au navigateur sur runs réels persistés.

## Découpe pressentie (détaillée en writing-plans)

1. **Addendum data context** : `SessionTaskRecord.context` + `save_session` + `InputDetail.context` + `_build_step` (à folder dans l'exécution 03b ; le plan 03b doit gagner cette task).
2. **Squelette** : `index.html` shell + nav + `app.js` + `api.js` (ES modules, route Flask `/`).
3. **`graph.js`** : `renderGraph` (bandes, auto-fit, arêtes estompées/actives, pulse/pointillé).
4. **`modal.js`** : overlay par type de nœud (6 types) + expand inline + bloc Context conditionnel.
5. **`tabs/sessions.js`** : toolbar + graphe + todo + scrubber, état `activeStepIndex`.
6. **Skin `/impeccable`** : itération visuelle live sur runs réels.
7. **Vérification navigateur** : golden path + edge cases.
