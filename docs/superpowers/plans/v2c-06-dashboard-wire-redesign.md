# Plan v2c-06 — Refonte graphique du dashboard (direction « wireframe instrument »)

## Contexte

La couche data + l'app Flask V2c sont complètes (588 tests). La passe `/impeccable` a produit une direction visuelle verrouillée via un design-lab statique. **Source de vérité visuelle** : `design-lab/lab-wire-full.html` (mock complet, 4 tabs, data bakée). Système de design : `DESIGN.md` (racine). Cette tâche = **porter le mock dans le vrai `dashboard/`** sans toucher au backend, à l'API, ni à `build_graph`.

Lancer le mock pour référence : `.venv\Scripts\python -m http.server 5500 -d design-lab` → http://localhost:5500/lab-wire-full.html.

## Invariants à ne pas briser

- **API, collectors, blueprint REST, `graph_model.build_graph`** : inchangés. Mêmes endpoints, mêmes champs. Le frontend consomme exactement la même donnée.
- **`build_graph` reste pur** et ses 588 tests verts. La refonte est **CSS + markup JS only**.
- `ExecutedEvent.llm_metadata` optionnel (déjà le cas).
- Séparation fonctionnelle des couleurs : ember (`--fire`) = actif/winner du graphe uniquement ; le chrome ne le réutilise pas comme déco.

## Découverte clé — le graphe est déjà bien groupé

`graph_model._build_nodes` assigne déjà les layers comme l'exige l'anatomie « arbre » du mock :

- `layer="bottom"` → **agents** (feuilles)
- `layer="center"` → **dispatch, evaluator** (tronc / logique)
- `layer="top"` → **input, output, testset** (racines / I/O)

Le mock veut agents **en haut**, I/O **en bas**. Donc le port = **inverser l'ordre vertical des bandes dans `graph.js` `layout()`** (rendre la bande `bottom` en haut, `center` au milieu, `top` en bas). Aucun changement à `build_graph`, zéro test cassé.

## Fichiers à modifier (tous sous `dashboard/`)

### 1. `templates/index.html`
- Header `.topbar` : marque diamant ember + `AAOSA` (mono) + `observability` ; `nav.tabnav` réordonnée **Sessions · Agents · Health · Infra** (boutons `.tab-btn[data-tab]`, conserver les classes/attributs lus par `app.js`).
- Ajouter les conteneurs background : `<div class="scales" id="scales"></div>` + `<div class="vignette"></div>` (avant `<main>`).
- Garder `#modal-root`.
- Défaut : `sessions`.

### 2. `static/js/app.js`
- Au boot : **construire la lattice de scales** (grid de diamants dimensionnée au viewport, `--d` par cellule = `(c+r)/maxd * 4.6 - 4.6` s) — repris tel quel du `<script>` du mock.
- Le mécanisme tabs existant (toggle `.is-active` + `panel.hidden`) est conservé. Le CSS gère le flex par tab.

### 3. `static/css/style.css` — réécriture complète
Porter le `<style>` du mock. Tokens, composants, motion = `DESIGN.md`. **Aligner les noms de classes sur ce que le JS émet** (table de correspondance ci-dessous) : soit renommer dans le JS pour émettre les classes du mock, soit adapter les sélecteurs CSS. Recommandé : **faire émettre au JS les classes du mock** (plus simple, CSS = copie du mock).

Correspondance réel → mock :
| Réel (actuel) | Mock (cible) |
|---|---|
| `.cards` / `.card` / `.card-value` / `.card-label` (infra, hc-overview) | `.strip` / `.stat` / `.stat-value` / `.stat-label` |
| `.tabnav` / `.tab-btn` | idem (garder) + style pill wire |
| `.session-body` / `.graph-wrap` / `.todo` / `.scrubber` | idem + `.panel`, `.graph-frame`, `.scrub-track` |
| `.agent-view` + `.field` blocs | `.agent-view` flex-col + `.afield` / `.afield--grow` |
| `.bar-row/.bar-track/.bar-fill/.bar-val` | idem (restyle) |
| `.case-row` + `.case-*` | idem + `.case-table`/`.case-head` (panel) |
| `.charts figure figcaption` | `.charts` (grid 2×2) + `.chart-card` + figcaption ember `▸` |
| `.modal-*` | idem (wire card + corner tick) |
| `svg.graph`, `.edge`, `.node`, `.node-label` | + `.hex`, `.gtier`, `.edge--a`, `.pulse`, tiers |
| `svg.chart`, `.chart-axis`, `.chart-bar` | `.grid-line`, `.axis-label`, `.series-1/2`, `.chart-bar` |

**Flex par tab (one screen)** : `.tab-panel:not([hidden]) { display:flex; flex-direction:column; height: calc(100vh - 184px); }` ; `[data-tab="health"]:not([hidden])` en `display:block; min-height` (flow). Élément dominant en `flex:1; min-height:0` (graphe / charts / chart ELO). SVG remplissant : `height:100%` (graph) ou `flex:1` (charts), `preserveAspectRatio` meet.

### 4. `static/js/graph.js` — `renderGraph`
- **Inverser les bandes** dans `layout()` : `bandY = { bottom: PAD (haut), center: milieu, top: bas }`.
- Nœuds en **hexagones wireframe** (`<use href="#hex">` ou polygon par nœud) au lieu de rects ; label mono ; classes `.node`, `.node--active` (live), `.node--winner` (ember + glow). Conserver `onNodeClick`, `agentNames`.
- Arêtes : idle `.edge` (wire), actives `.edge--a` (ember). Sur les arêtes actives, ajouter des **pulse dots** `<animateMotion>` (calme, ~2.6s, staggered). Pas de marching-ants, pas de ping.
- Ajouter labels de tiers faibles (`leaves · agents` / `trunk · logic` / `roots · in/out`) — `.gtier`.
- Hauteur pilotée par le CSS (`svg.graph` height 100% / cap health 40vh). Garder le `viewBox` calculé sur le nb de nœuds par bande.

### 5. `static/js/charts.js` — `lineChart` / `barChart`
- Garder l'API (utilisée par `infra.js`, `agents.js`). Ajouter **gridlines** (lignes pointillées `--wire` aux y min/max), `series-1` = `--fire` (glow via classe), `series-2` = `--cool`, barres `--fire-2`. Option aire sous courbe (polygon `area-1`) pour le pass-rate. Axis labels mono.

### 6. `static/js/tabs/*.js`
- `infra.js` : `.cards` → `.strip`/`.stat` ; charts en **2×2** (`.charts` grid) avec figcaptions.
- `agents.js` : `.agent-view` en colonne empilée (`.afield`, l'ELO chart en `.afield--grow`) ; **`esc()` sur `system_prompt`** (fix XSS, helper déjà créé `static/js/util.js`).
- `health.js` : overview `.cards` → `.strip` ; table `.case-table`/`.case-head` ; le case-graph rendu par `renderGraph` (capé 40vh) ; lignes TestSet cliquables conservées.
- `sessions.js` : `.graph-frame` (panel) + `.todo` (panel) + `.scrubber` avec `.scrub-track` ; bouton modal éventuel.
- Tous les textes libres injectés via `innerHTML` (descriptions, prompts, justifications) passent par `esc()`.

### 7. `static/js/modal.js`
- Restyle wire card (corner tick, titre mono, status pill ember). Logique inchangée. `field-value` déjà en `textContent` (sûr).

## Follow-ups à absorber (notés en V2c)
- **XSS** : `esc()` sur `system_prompt` + descriptions (ci-dessus).
- **`infra.agent_count` gonflé** : UUID distincts cross-session. Même cause que le fix ELO-par-nom ; corriger dans le collector `infra` (compter par `name`, pas par id) si rapide, sinon noter.

## Vérification
- `.venv\Scripts\python -m dashboard` → http://localhost:5000. Les 4 tabs : graphe tree-tiers + clic nœud → modale, charts gridlines, barres/ELO, scrubber, table health cliquable + case-graph, background scales + onde diagonale, chaque tab tient en un écran (sauf health dense).
- Console navigateur propre. `node --check` sur les JS modifiés.
- **XSS** : un `system_prompt` contenant `<script>` s'affiche comme texte.
- **Non-régression** : `.venv\Scripts\python -m pytest -q` reste à **588** verts.

## Après le port
- Supprimer `design-lab/` (jetable) une fois le rendu validé en navigateur.
- `DESIGN.md` et `PRODUCT.md` (palette/anti-refs/motion) sont déjà à jour.
- Mettre à jour CLAUDE.md / contexte AIOS : V2c bouclée (refonte incluse) → V3.
