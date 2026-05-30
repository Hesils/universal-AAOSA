# V2c — Épique 04 — Frontend : composant graphe + overlay + scrubber — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le composant graphe SVG réutilisable (renderer dumb + overlay modal par type de nœud + scrubber/todo) et le squelette frontend de l'app dashboard, servi par Flask, pour Tab 4 (session run) — en posant la structure que l'Épique 05 complète.

**Architecture:** Vanilla JS + SVG, **pas de framework, pas de build step** (ES modules natifs via `<script type="module">`). Un renderer `renderGraph(svg, graphModel, activeStepIndex)` **dumb** (ignore scrubber/sélecteur, session/HC), réutilisé par des wrappers par tab. État Tab 4 = une seule source de vérité `activeStepIndex`, tout en dérive, pas de re-fetch. Flask sert `index.html` (route `/`) + statics ; aucune route serveur par tab. Le skin est **frais AAOSA**, itéré en fin de plan via le skill `/impeccable`.

**Tech Stack:** Python 3.14 / Flask 3.1 (service statique), JavaScript ES modules, SVG. Aucun outil de build, aucun npm.

---

## Prérequis (NE PAS commencer sans)

1. **Épique 03b implémentée** : API REST (`/api/infra`, `/api/agents`, `/api/sessions`, `/api/sessions/<id>`, `/api/sessions/<id>/graph`, `/api/health-checks/...`) + **addendum context (Task 1B du plan 03b)** : `SessionTaskRecord.context` et `InputDetail.context` existent et sont peuplés.
2. **Au moins un run persisté** dans `runs/` : lancer la démo une fois.
   Run: `.venv\Scripts\python src\aaosa\demo\run_demo.py` (requiert `.env` avec `OPENAI_API_KEY`).
   Vérifier : `runs/sessions/<id>/{trace.jsonl, meta.json, agents.json}` existent.
3. Sanity API : démarrer l'app (Task 1 fournit `python -m dashboard`) et vérifier que `GET /api/sessions` renvoie au moins une session.

## Discipline d'exécution (toutes les tasks)

- **Frontend hors TDD automatisé** (décision épique + CLAUDE.md projet) : pas de cycle pytest red/green pour le JS. Chaque task se termine par une **vérification navigateur** explicite. La logique testable vit déjà côté Python (Épiques 02/03).
- **Commit après reviews** : l'implémenteur ne commit qu'après spec-review + quality-review (cf. subagent-driven-development). La dernière étape de chaque task donne la commande exacte.
- **Le code JS de ce plan est structurel et fonctionnel**, classes CSS référencées mais style minimal. **Le skin final est l'objet de la Task 6 (`/impeccable`)** — ne pas peaufiner le visuel avant.
- Lancer l'app pour vérifier : `.venv\Scripts\python -m dashboard` puis ouvrir `http://localhost:5000`.

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `dashboard/__main__.py` | point d'entrée `python -m dashboard` | Créer |
| `dashboard/app.py` | route `/` → `index.html` | Modifier |
| `dashboard/templates/index.html` | shell : nav 4 tabs + points de montage | Créer |
| `dashboard/static/css/style.css` | skin (minimal puis `/impeccable`) | Créer |
| `dashboard/static/js/app.js` | nav, monte le tab actif | Créer |
| `dashboard/static/js/api.js` | fetch wrappers sur `/api/*` | Créer |
| `dashboard/static/js/graph.js` | `renderGraph(svg, graphModel, activeStepIndex)` — dumb | Créer |
| `dashboard/static/js/modal.js` | overlay par type de nœud + expand inline | Créer |
| `dashboard/static/js/tabs/sessions.js` | Tab 4 : graphe + scrubber + todo | Créer |

> `graph.js` et `modal.js` sont **réutilisés tels quels par l'Épique 05** (Tab 3 health-check). `app.js` pose le système de nav que l'Épique 05 complète (3 tabs restants).

**Commande de lancement (Windows, toujours le venv) :** `.venv\Scripts\python -m dashboard`

---

# PHASE 0 — Squelette servi par Flask

## Task 1: Shell HTML + nav + point d'entrée + `api.js`

**Files:**
- Create: `dashboard/__main__.py`
- Modify: `dashboard/app.py`
- Create: `dashboard/templates/index.html`
- Create: `dashboard/static/css/style.css`
- Create: `dashboard/static/js/app.js`
- Create: `dashboard/static/js/api.js`

- [ ] **Step 1: Point d'entrée `python -m dashboard`**

Créer `dashboard/__main__.py` :

```python
from dashboard.app import create_app
from dashboard.config import DashboardConfig

if __name__ == "__main__":
    cfg = DashboardConfig()
    create_app(cfg).run(host=cfg.host, port=cfg.port, debug=True)
```

- [ ] **Step 2: Route `/` dans `create_app`**

Dans `dashboard/app.py`, ajouter une route qui sert le shell. Ajouter l'import `render_template` et, dans `create_app`, **avant** `return app` :

```python
from flask import Flask, render_template
```

```python
    @app.get("/")
    def index():
        return render_template("index.html")
```

> `Flask(__name__)` pointe déjà `templates/` et `static/` dans `dashboard/`. Aucune config statique supplémentaire.

- [ ] **Step 3: Shell `index.html`**

Créer `dashboard/templates/index.html` :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AAOSA — Observability</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
  <nav class="tabnav">
    <button class="tab-btn" data-tab="infra">Infra</button>
    <button class="tab-btn" data-tab="agents">Agents</button>
    <button class="tab-btn" data-tab="health">Health checks</button>
    <button class="tab-btn is-active" data-tab="sessions">Sessions</button>
  </nav>

  <main>
    <section class="tab-panel" data-tab="infra" hidden><p class="placeholder">Tab Infra — Épique 05</p></section>
    <section class="tab-panel" data-tab="agents" hidden><p class="placeholder">Tab Agents — Épique 05</p></section>
    <section class="tab-panel" data-tab="health" hidden><p class="placeholder">Tab Health checks — Épique 05</p></section>
    <section class="tab-panel" data-tab="sessions"></section>
  </main>

  <div id="modal-root"></div>

  <script type="module" src="{{ url_for('static', filename='js/app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 4: CSS minimal (le skin final = Task 6 `/impeccable`)**

Créer `dashboard/static/css/style.css` :

```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; background: #0f1419; color: #cbd5e1; }
.tabnav { display: flex; gap: 4px; padding: 12px 16px; border-bottom: 1px solid #222b36; }
.tab-btn { background: transparent; border: 1px solid #2b3340; color: #94a3b8; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.tab-btn.is-active { color: #e6edf3; border-color: #3a4658; background: #1a2230; }
main { padding: 16px; }
.placeholder { color: #475569; }
.tab-panel { min-height: 60vh; }
svg.graph { width: 100%; height: auto; display: block; }
```

- [ ] **Step 5: Nav `app.js`**

Créer `dashboard/static/js/app.js` :

```js
import { mountSessions } from "./tabs/sessions.js";

const MOUNTERS = { sessions: mountSessions }; // agents/health/infra ajoutés en Épique 05
const mounted = new Set();

function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("is-active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach(p => { p.hidden = p.dataset.tab !== name; });
  const panel = document.querySelector(`.tab-panel[data-tab="${name}"]`);
  if (panel && MOUNTERS[name] && !mounted.has(name)) {
    MOUNTERS[name](panel);
    mounted.add(name);
  }
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

showTab("sessions"); // tab par défaut
```

- [ ] **Step 6: `api.js` (fetch wrappers)**

Créer `dashboard/static/js/api.js` :

```js
async function get(path) {
  const r = await fetch(path);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `${r.status} ${path}`);
  }
  return r.json();
}

export const api = {
  infra: () => get("/api/infra"),
  agents: () => get("/api/agents"),
  agent: (id) => get(`/api/agents/${encodeURIComponent(id)}`),
  sessions: () => get("/api/sessions"),
  session: (id) => get(`/api/sessions/${encodeURIComponent(id)}`),
  sessionGraph: (id) => get(`/api/sessions/${encodeURIComponent(id)}/graph`),
  healthChecks: () => get("/api/health-checks"),
  healthCheck: (id) => get(`/api/health-checks/${encodeURIComponent(id)}`),
  healthCheckGraph: (id, taskId) =>
    get(`/api/health-checks/${encodeURIComponent(id)}/graph` + (taskId ? `?task_id=${encodeURIComponent(taskId)}` : "")),
};
```

> Step 5 importe `./tabs/sessions.js` qui n'existe pas encore (Task 4). Pour vérifier la nav **avant** la Task 4, créer un stub temporaire `dashboard/static/js/tabs/sessions.js` : `export function mountSessions(panel) { panel.textContent = "Sessions (stub)"; }`. Il sera remplacé en Task 4.

- [ ] **Step 7: Vérification navigateur**

Lancer : `.venv\Scripts\python -m dashboard` → ouvrir `http://localhost:5000`.
Attendu :
- 4 boutons de nav ; « Sessions » actif au chargement, panneau Sessions affiche « Sessions (stub) ».
- Clic sur Infra/Agents/Health checks → bascule le panneau (placeholder « Épique 05 »), bouton actif suit.
- Console navigateur sans erreur (modules ES chargés).

- [ ] **Step 8: Commit (après reviews)**

```bash
git add dashboard/__main__.py dashboard/app.py dashboard/templates/index.html dashboard/static/css/style.css dashboard/static/js/app.js dashboard/static/js/api.js dashboard/static/js/tabs/sessions.js
git commit -m "feat(v2c): squelette frontend dashboard (shell, nav, api, route Flask)"
```

---

# PHASE 1 — Composant graphe

## Task 2: `graph.js` — `renderGraph` (3 bandes, auto-fit, chemin actif)

**Files:**
- Create: `dashboard/static/js/graph.js`

- [ ] **Step 1: Layout + rendu nœuds/arêtes**

Créer `dashboard/static/js/graph.js` :

```js
const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 120, NODE_H = 44, GAP_X = 40, BAND_GAP = 150, PAD = 40;
const LAYERS = ["top", "center", "bottom"];

function el(name, attrs = {}) {
  const e = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function layout(graph) {
  const byLayer = { top: [], center: [], bottom: [] };
  for (const n of graph.nodes) byLayer[n.layer].push(n);
  const maxCount = Math.max(1, ...LAYERS.map(l => byLayer[l].length));
  const width = PAD * 2 + maxCount * NODE_W + (maxCount - 1) * GAP_X;
  const height = PAD * 2 + 3 * NODE_H + 2 * BAND_GAP;
  const bandY = { top: PAD, center: PAD + NODE_H + BAND_GAP, bottom: PAD + 2 * (NODE_H + BAND_GAP) };
  const pos = {};
  for (const layer of LAYERS) {
    const row = byLayer[layer];
    const rowW = row.length * NODE_W + Math.max(0, row.length - 1) * GAP_X;
    const startX = (width - rowW) / 2;
    row.forEach((n, i) => { pos[n.id] = { x: startX + i * (NODE_W + GAP_X), y: bandY[layer] }; });
  }
  return { pos, width, height };
}

function center(p) { return { cx: p.x + NODE_W / 2, cy: p.y + NODE_H / 2 }; }
function edgeKey(e) { return `${e.from}->${e.to}`; }

export function renderGraph(svg, graph, activeStepIndex, onNodeClick) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "graph");

  const { pos, width, height } = layout(graph);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const step = graph.steps[activeStepIndex] || null;
  const activeNodes = new Set(step ? step.active_nodes : []);
  const activeEdges = new Set(step ? step.active_edges.map(edgeKey) : []);
  const winnerId = step ? step.winner_agent_id : null;
  const failBranch = step && step.outcome === "qa_fail";

  // arêtes (toutes estompées ; actives nettes ; branche fail pointillée)
  const edgeLayer = el("g");
  for (const e of graph.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const { cx: x1, cy: y1 } = center(a), { cx: x2, cy: y2 } = center(b);
    const isActive = activeEdges.has(edgeKey(e));
    const isFail = failBranch && isActive && e.to === "testset";
    const line = el("line", { x1, y1, x2, y2 });
    line.setAttribute("class", "edge" + (isActive ? " edge--active" : " edge--idle") + (isFail ? " edge--fail" : ""));
    edgeLayer.appendChild(line);
  }
  svg.appendChild(edgeLayer);

  // nœuds
  for (const n of graph.nodes) {
    const p = pos[n.id];
    const g = el("g", { class: "node node--" + n.type });
    g.dataset.nodeId = n.id;
    if (activeNodes.has(n.id)) g.classList.add("node--active");
    if (n.id === winnerId) g.classList.add("node--winner");

    const rect = el("rect", { x: p.x, y: p.y, width: NODE_W, height: NODE_H, rx: 8 });
    const label = el("text", { x: p.x + NODE_W / 2, y: p.y + NODE_H / 2 + 5, "text-anchor": "middle", class: "node-label" });
    label.textContent = n.label;
    g.append(rect, label);
    if (onNodeClick) g.addEventListener("click", () => onNodeClick(n, step));
    svg.appendChild(g);
  }
}
```

- [ ] **Step 2: Styles graphe (minimal, polish en Task 6)**

Ajouter à `dashboard/static/css/style.css` :

```css
.edge { stroke-width: 1.5; }
.edge--idle { stroke: #2b3340; opacity: 0.35; }
.edge--active { stroke: #10b981; stroke-width: 3; opacity: 1; }
.edge--fail { stroke-dasharray: 6 5; }
.node rect { fill: #1a2230; stroke: #3a4658; }
.node-label { fill: #94a3b8; font-size: 13px; font-family: system-ui; pointer-events: none; }
.node { cursor: pointer; }
.node--active rect { stroke: #10b981; }
.node--active .node-label { fill: #cbd5e1; }
.node--winner rect { stroke: #10b981; stroke-width: 2; fill: #10221c; }
.node--winner .node-label { fill: #6ee7b7; }
```

- [ ] **Step 3: Vérification navigateur (harnais temporaire)**

Pour vérifier `renderGraph` indépendamment de Tab 4, remplacer temporairement le stub `tabs/sessions.js` par :

```js
import { api } from "../api.js";
import { renderGraph } from "../graph.js";

export async function mountSessions(panel) {
  const list = await api.sessions();
  const sid = list.sessions[0].session_id;
  const graph = await api.sessionGraph(sid);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  panel.appendChild(svg);
  renderGraph(svg, graph, 0, (n) => console.log("clic node", n.id));
}
```

Lancer l'app, ouvrir `http://localhost:5000`. Attendu :
- 3 bandes : Input/Output/TestSet en haut, Dispatch/Evaluator au centre, agents en bas.
- Toutes les arêtes visibles estompées ; le chemin actif du step 0 en émeraude ; le winner mis en avant.
- Si le step 0 est `qa_fail` : l'arête evaluator→testset en pointillé.
- Clic sur un nœud → log console `clic node <id>`.
- Le graphe tient sans scroll horizontal (auto-fit).

> Ce harnais est remplacé par la vraie Task 4. Le garder tel quel jusque-là.

- [ ] **Step 4: Commit (après reviews)**

```bash
git add dashboard/static/js/graph.js dashboard/static/css/style.css dashboard/static/js/tabs/sessions.js
git commit -m "feat(v2c): renderGraph SVG 3 bandes (auto-fit, chemin actif, pulse/pointille)"
```

---

## Task 3: `modal.js` — overlay par type de nœud + expand inline

**Files:**
- Create: `dashboard/static/js/modal.js`
- Modify: `dashboard/static/js/graph.js` (brancher le clic sur la modale — fait via le callback déjà en place)

- [ ] **Step 1: Helpers expand + ouverture/fermeture**

Créer `dashboard/static/js/modal.js` :

```js
const root = () => document.getElementById("modal-root");

function closeModal() { root().innerHTML = ""; }

// champ texte long : tronqué + toggle "voir tout" inline
function longField(label, value, max = 220) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const head = document.createElement("div");
  head.className = "field-label";
  head.textContent = label;
  const box = document.createElement("div");
  box.className = "field-value";
  const text = value || "";
  if (text.length <= max) {
    box.textContent = text;
  } else {
    box.textContent = text.slice(0, max) + "… ";
    const toggle = document.createElement("span");
    toggle.className = "expand";
    toggle.textContent = `voir tout (${text.length} car.)`;
    let expanded = false;
    toggle.addEventListener("click", () => {
      expanded = !expanded;
      box.textContent = expanded ? text + " " : text.slice(0, max) + "… ";
      toggle.textContent = expanded ? "réduire" : `voir tout (${text.length} car.)`;
      box.appendChild(toggle);
    });
    box.appendChild(toggle);
  }
  wrap.append(head, box);
  return wrap;
}

function field(label, value) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  wrap.innerHTML = `<div class="field-label">${label}</div><div class="field-value">${value}</div>`;
  return wrap;
}
```

- [ ] **Step 2: Les 6 renderers par type + dispatch**

Ajouter à `dashboard/static/js/modal.js` :

```js
function renderDispatch(d) {
  const f = document.createDocumentFragment();
  const cand = d.candidates.map(c => `${c.agent_id} — fit ${c.fit_score.toFixed(2)} ${c.passed ? "✓" : "✗"}`).join("<br>");
  f.append(field("Candidats (Phase 1)", cand || "—"));
  const claims = d.claims.map(c => `${c.agent_id} — ${c.decision}`).join("<br>");
  f.append(field("Claims (Phase 2)", claims || "—"));
  for (const c of d.claims) if (c.justification) f.append(longField(`Justification — ${c.agent_id}`, c.justification));
  f.append(field("Winner", d.winner_agent_id || "—"));
  if (d.dispatch_reason) f.append(field("Raison dispatch", d.dispatch_reason));
  if (d.unassigned_reason) f.append(field("Raison non-attribution", d.unassigned_reason));
  return f;
}

function renderAgent(agentId, step, runAgents) {
  const a = step.detail.agents[agentId];
  const reg = (runAgents || []).find(x => x.agent_id === agentId); // join B1 : prompt + ELO courant
  const f = document.createDocumentFragment();
  f.append(field("Rôle", a.role + (a.passed ? " · passed" : " · filtré") + ` · fit ${a.fit_score.toFixed(2)}`));
  if (reg) {
    const bars = Object.entries(reg.tags_with_elo).map(([t, e]) => `${t} : ${e}`).join("<br>");
    f.append(field("Tags · ELO courant", bars || "—"));
    f.append(longField("System prompt", reg.system_prompt));
  }
  if (a.claim_decision) f.append(field("Claim", a.claim_decision));
  if (a.justification) f.append(longField("Justification", a.justification));
  if (a.output_content) f.append(longField("Output", a.output_content));
  if (a.llm_metadata) {
    const m = a.llm_metadata;
    f.append(field("Métriques", `latence ${m.latency_ms} ms · in ${m.tokens_in} · out ${m.tokens_out}`));
  }
  const deltas = Object.entries(a.elo_deltas).map(([t, d]) => `${t} ${d >= 0 ? "+" : ""}${d}`).join(" · ");
  if (deltas) f.append(field("ELO deltas (ce run)", deltas));
  if (a.tags_acquired.length) f.append(field("Tags acquis", a.tags_acquired.map(t => `${t.tag} (${t.initial_elo})`).join(" · ")));
  return f;
}

function renderEvaluator(e) {
  const f = document.createDocumentFragment();
  if (!e.ran) { f.append(field("Evaluator", "non exécuté")); return f; }
  f.append(field("Résultat", (e.success ? "succès" : "échec") + (e.score != null ? ` · score ${e.score.toFixed(2)}` : "")));
  const crit = Object.entries(e.criteria_results).map(([k, v]) => `${k} : ${v ? "✓" : "✗"}`).join("<br>");
  if (crit) f.append(field("Critères / gates", crit));
  if (e.judge) f.append(field("Judge", `${e.judge.mode} · ${e.judge.overall != null ? e.judge.overall.toFixed(2) : "—"}`));
  if (e.reason) f.append(longField("Raison", e.reason));
  return f;
}

function renderInput(inp) {
  const f = document.createDocumentFragment();
  f.append(field("Task", inp.task_id));
  f.append(longField("Description", inp.description));
  const tags = Object.entries(inp.required_tags).map(([t, lvl]) => `${t} ≥ ${lvl}`).join(" · ");
  f.append(field("Tags requis", tags || "—"));
  if (inp.context) f.append(longField("Context", inp.context)); // addendum 04 : affiché si non vide
  return f;
}

function renderOutput(o) {
  const f = document.createDocumentFragment();
  if (!o.produced) { f.append(field("Output", "non produit")); return f; }
  if (o.output_summary) f.append(longField("Résumé", o.output_summary));
  if (o.output_content) f.append(longField("Contenu", o.output_content));
  if (o.llm_metadata) {
    const m = o.llm_metadata;
    f.append(field("Métriques", `latence ${m.latency_ms} ms · in ${m.tokens_in} · out ${m.tokens_out}`));
  }
  return f;
}

function renderTestSet(t) {
  const f = document.createDocumentFragment();
  f.append(field("Forké", t.forked ? "oui" : "non"));
  f.append(field("Depuis task", t.from_task_id));
  return f;
}

// node = {id, type, label} ; step = GraphStep courant ; runAgents = agents du run (B1)
export function openNodeModal(node, step, runAgents) {
  if (!step) return;
  let title = node.label, body;
  switch (node.type) {
    case "dispatch": body = renderDispatch(step.detail.dispatch); break;
    case "agent": body = renderAgent(node.id, step, runAgents); title = node.label + (step.winner_agent_id === node.id ? " ★" : ""); break;
    case "evaluator": body = renderEvaluator(step.detail.evaluator); break;
    case "input": body = renderInput(step.detail.input); break;
    case "output": body = renderOutput(step.detail.output); break;
    case "testset": body = renderTestSet(step.detail.testset); break;
    default: return;
  }

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) closeModal(); });

  const card = document.createElement("div");
  card.className = "modal-card";
  const head = document.createElement("div");
  head.className = "modal-head";
  head.innerHTML = `<span class="modal-title">${title}</span><span class="modal-close">×</span>`;
  head.querySelector(".modal-close").addEventListener("click", closeModal);
  const content = document.createElement("div");
  content.className = "modal-body";
  content.appendChild(body);

  card.append(head, content);
  overlay.appendChild(card);
  root().innerHTML = "";
  root().appendChild(overlay);
}
```

- [ ] **Step 3: Styles modale (minimal)**

Ajouter à `dashboard/static/css/style.css` :

```css
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal-card { width: min(560px, 92vw); max-height: 86vh; overflow: auto; background: #141b24; border: 1px solid #2b3340; border-radius: 14px; }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #222b36; }
.modal-title { font-weight: 600; color: #e6edf3; }
.modal-close { cursor: pointer; color: #475569; font-size: 20px; }
.modal-body { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }
.field-label { font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: #64748b; margin-bottom: 5px; }
.field-value { font-size: 13px; line-height: 1.5; color: #cbd5e1; background: #0f151d; border: 1px solid #222b36; border-radius: 8px; padding: 9px 11px; }
.expand { color: #3b82f6; cursor: pointer; margin-left: 4px; }
```

- [ ] **Step 4: Brancher la modale sur le clic du graphe**

Dans le harnais temporaire `tabs/sessions.js`, remplacer le callback `console.log` par l'ouverture de la modale :

```js
import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";

export async function mountSessions(panel) {
  const list = await api.sessions();
  const sid = list.sessions[0].session_id;
  const [detail, graph] = await Promise.all([api.session(sid), api.sessionGraph(sid)]);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  panel.appendChild(svg);
  renderGraph(svg, graph, 0, (node, step) => openNodeModal(node, step, detail.agents));
}
```

- [ ] **Step 5: Vérification navigateur**

Lancer l'app. Attendu, sur le step 0 :
- Clic **Dispatch** → candidats + fit_scores, claims + justifications, winner.
- Clic sur un **agent** → rôle/fit, tags+ELO courant, system prompt tronqué avec « voir tout » qui déplie sur place, output + métriques, ELO deltas.
- Clic **Evaluator** → critères/gates, judge, score, raison (si QA a tourné).
- Clic **Input** → description, tags requis, et **bloc Context uniquement s'il est non vide**.
- Clic **Output** → contenu + métriques.
- Clic **TestSet** → forké / from_task_id.
- Clic en dehors de la carte ou sur × → ferme.

- [ ] **Step 6: Commit (après reviews)**

```bash
git add dashboard/static/js/modal.js dashboard/static/css/style.css dashboard/static/js/tabs/sessions.js
git commit -m "feat(v2c): overlay modal par type de noeud (6 types, expand inline, bloc context conditionnel)"
```

---

# PHASE 2 — Tab 4 (session run)

## Task 4: `tabs/sessions.js` — toolbar + graphe + scrubber + todo

**Files:**
- Modify: `dashboard/static/js/tabs/sessions.js` (remplace le harnais temporaire par la version finale)

- [ ] **Step 1: Version finale du module Tab 4**

Remplacer intégralement `dashboard/static/js/tabs/sessions.js` par :

```js
import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";

export async function mountSessions(panel) {
  panel.innerHTML = `
    <div class="toolbar">
      <select class="session-select"></select>
      <span class="chips"></span>
    </div>
    <div class="session-body">
      <div class="graph-wrap"><svg></svg></div>
      <aside class="todo"></aside>
    </div>
    <div class="scrubber">
      <button class="scrub-prev">◀</button>
      <span class="scrub-label"></span>
      <button class="scrub-next">▶</button>
    </div>`;

  const select = panel.querySelector(".session-select");
  const svg = panel.querySelector(".graph-wrap svg");
  const chips = panel.querySelector(".chips");
  const todo = panel.querySelector(".todo");
  const scrubLabel = panel.querySelector(".scrub-label");

  const list = await api.sessions();
  if (!list.sessions.length) { panel.innerHTML = '<p class="placeholder">Aucune session persistée.</p>'; return; }
  for (const s of list.sessions) {
    const opt = document.createElement("option");
    opt.value = s.session_id;
    opt.textContent = s.session_id;
    select.appendChild(opt);
  }

  let detail = null, graph = null, activeStepIndex = 0;

  function renderTodo() {
    const tasks = detail.meta.tasks;
    todo.innerHTML = "<div class='field-label'>Tasks</div>" + tasks.map((t, i) => {
      const state = i < activeStepIndex ? "done" : (i === activeStepIndex ? "current" : "pending");
      const mark = state === "done" ? "☑" : (state === "current" ? "▶" : "☐");
      return `<div class="todo-item todo--${state}">${mark} ${t.description}</div>`;
    }).join("");
  }

  function renderChips() {
    chips.textContent = `${detail.meta.tasks.length} tasks · ${detail.meta.agent_ids.length} agents`;
  }

  function rerender() {
    renderGraph(svg, graph, activeStepIndex, (node, step) => openNodeModal(node, step, detail.agents));
    scrubLabel.textContent = graph.steps.length
      ? `Step ${activeStepIndex + 1} / ${graph.steps.length} — ${graph.steps[activeStepIndex].label}`
      : "Aucun step";
    renderTodo();
  }

  async function load(sid) {
    [detail, graph] = await Promise.all([api.session(sid), api.sessionGraph(sid)]);
    activeStepIndex = 0;
    renderChips();
    rerender();
  }

  select.addEventListener("change", () => load(select.value));
  panel.querySelector(".scrub-prev").addEventListener("click", () => {
    if (activeStepIndex > 0) { activeStepIndex--; rerender(); }
  });
  panel.querySelector(".scrub-next").addEventListener("click", () => {
    if (activeStepIndex < graph.steps.length - 1) { activeStepIndex++; rerender(); }
  });

  await load(list.sessions[0].session_id);
}
```

- [ ] **Step 2: Styles Tab 4 (minimal)**

Ajouter à `dashboard/static/css/style.css` :

```css
.toolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.session-select { background: #1a2230; color: #cbd5e1; border: 1px solid #2b3340; border-radius: 8px; padding: 6px 10px; }
.chips { color: #64748b; font-size: 13px; }
.session-body { display: flex; gap: 16px; }
.graph-wrap { flex: 1; min-width: 0; }
.todo { width: 240px; flex-shrink: 0; }
.todo-item { padding: 6px 0; font-size: 13px; color: #94a3b8; }
.todo--done { color: #6ee7b7; }
.todo--current { color: #e6edf3; }
.scrubber { display: flex; align-items: center; gap: 14px; margin-top: 14px; }
.scrubber button { background: #1a2230; color: #cbd5e1; border: 1px solid #2b3340; border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.scrub-label { color: #94a3b8; font-size: 13px; }
```

- [ ] **Step 3: Vérification navigateur — golden path**

Lancer l'app. Attendu :
- Le sélecteur liste les sessions ; chips « N tasks · M agents ».
- Graphe affiché sur le step 1 ; scrubber « Step 1 / K — <label> ».
- ▶ avance : le graphe bascule sur le chemin de la task suivante (**step courant seul**), la todo coche cumulativement (tasks précédentes ☑, courante ▶). ◀ recule.
- Clic sur un nœud → modale correcte. Changer de session recharge tout (index remis à 0).

- [ ] **Step 4: Commit (après reviews)**

```bash
git add dashboard/static/js/tabs/sessions.js dashboard/static/css/style.css
git commit -m "feat(v2c): Tab 4 session run (selecteur + graphe + scrubber + todo cumulative)"
```

---

# PHASE 3 — Skin + vérification finale

## Task 5: Skin frais AAOSA via `/impeccable`

**Files:**
- Modify: `dashboard/static/css/style.css` (et marges HTML si nécessaire)

> **REQUIRED SUB-SKILL : `/impeccable`** (frontend-design). Itération visuelle live au navigateur sur runs réels. Cette task ne touche **pas** la structure JS (figée Tasks 1-4) — uniquement le skin (couleurs, typographie, espacements, hiérarchie visuelle, motion léger : pulse winner, transitions de step).

- [ ] **Step 1: Lancer `/impeccable` sur le dashboard**

Invoquer `/impeccable` avec pour cible `dashboard/static/css/style.css` + `dashboard/templates/index.html`. Objectif : identité visuelle distincte AAOSA (pas le dark+emerald des maquettes du deep-dive, qui étaient structurelles). Garder les classes/IDs existants (`renderGraph`/`modal.js`/`sessions.js` en dépendent).

- [ ] **Step 2: Itérer au navigateur**

Sur un run réel (`python -m dashboard`), affiner jusqu'à validation visuelle : lisibilité du graphe à 4-5 agents, hiérarchie de la modale, pulse winner, états todo.

- [ ] **Step 3: Commit (après reviews)**

```bash
git add dashboard/static/css/style.css dashboard/templates/index.html
git commit -m "feat(v2c): skin frais AAOSA (impeccable) pour le dashboard"
```

---

## Task 6: Vérification navigateur — edge cases

**Files:** aucun (vérification ; corrections éventuelles dans les modules concernés)

> Génération de données de couverture : il faut des sessions exhibant chaque cas. Si la démo standard ne les produit pas tous, exécuter la démo plusieurs fois ou utiliser un run health-check (`run_health_check.py`) pour le cas `qa_fail`.

- [ ] **Step 1: Session sans winner (`unassigned`)**

Sur une session dont une task est `unassigned` : le chemin actif s'arrête à `dispatch` (pas d'agent surligné, pas d'output) ; clic Dispatch montre `unassigned_reason`.

- [ ] **Step 2: QA fail (branche pointillée)**

Sur une task `qa_fail` : arête `evaluator → testset` en pointillé ; nœud TestSet dans le chemin actif ; clic Evaluator montre l'échec + raison ; clic TestSet montre `forked: oui`.

- [ ] **Step 3: Session multi-task (scrubber + todo)**

Sur une session ≥ 2 tasks : ▶/◀ parcourent les steps, le graphe ne montre que le step courant, la todo se coche cumulativement. Step 1 → todo 0 « current » ; dernier step → toutes ☑ sauf la courante ▶.

- [ ] **Step 4: Auto-fit à N agents**

Sur une session à 4-5 agents candidats : le graphe tient sans scroll horizontal, arêtes inactives lisibles (estompées), chemin actif net.

- [ ] **Step 5: Overlays + expand**

Les 6 types de nœuds ouvrent la bonne modale ; system prompt / output / context longs : « voir tout » déplie et « réduire » replie ; bloc Context absent quand vide.

- [ ] **Step 6: Console propre**

Aucune erreur JS en console sur l'ensemble du parcours.

- [ ] **Step 7: Commit final éventuel**

```bash
git add -A
git commit -m "fix(v2c): corrections edge cases frontend Tab 4 (verif navigateur)"
```

> Si aucune correction n'a été nécessaire, ne rien committer ici.

---

## Self-review (effectuée à l'écriture)

**Couverture spec (`2026-05-30-v2c-04-frontend-graph-design.md`) :**
- S1 layout/auto-fit (3 bandes, arêtes estompées + actif net, distribution régulière, viewBox bande la plus large) → Task 2 (`layout`, `renderGraph`, CSS `edge--idle/active/fail`) ✓.
- S2 renderer dumb + wrappers → `renderGraph(svg, graph, activeStepIndex, onNodeClick)` ignore tab/mode (Task 2) ; wrapper `mountSessions` détient l'état (Task 4) ✓. Réutilisable Tab 3 (05) tel quel.
- S3 modale (gabarit + 6 types + expand inline sur prompt/output/context) → Task 3 (`openNodeModal` + 6 renderers + `longField`) ✓.
- S4 scrubber : `activeStepIndex` source unique, pas de re-fetch, graphe step courant seul, todo cumulative → Task 4 ✓.
- S5 structure ES modules (squelette 04 / 3 tabs 05) → Tasks 1-4 ; `MOUNTERS` extensible (05) ✓.
- S6 skin frais via `/impeccable` (maquettes ≠ cible) → Task 5 ✓.
- Addendum context : **hors de ce plan** (Task 1B du plan 03b). Ce plan le **consomme** : `renderInput` affiche `inp.context` si non vide (Task 3, Step 2) ✓.
- Critères de done : `renderGraph` réutilisable (Task 2) ; overlay 6 types (Task 3) ; pulse/pointillé (Task 2) ; Tab 4 synchronisé (Task 4) ; skin (Task 5) ; vérif navigateur runs réels (Task 6) ✓.

**Cohérence des types (JSON `by_alias`, cf. `graph_model.py` + collectors 03b) :** `graph.steps[i].active_edges` = `[{from,to}]` → `edgeKey` lit `e.from`/`e.to` ✓ ; `step.detail.{input,dispatch,agents,evaluator,output,testset}` consommés avec les bons champs (`fit_score`, `criteria_results`, `llm_metadata.latency_ms/tokens_in/tokens_out`, `input.context`) ✓ ; `api.session(id)` → `{meta, agents}` (S3-A, pas de graphe) et `api.sessionGraph(id)` → `GraphModel` nu ✓ ; `detail.agents` = `[{agent_id, name, system_prompt, tags_with_elo}]` joint dans `renderAgent` ✓ ; `meta.tasks` ordonnés = `graph.steps` ordonnés (même ordre `build_graph`/`SessionMeta`) → todo↔step aligné ✓.

**Note d'exécution :** Tasks 2-3 utilisent un harnais temporaire dans `tabs/sessions.js`, remplacé par la version finale en Task 4 — chaque task reste vérifiable au navigateur isolément. Pas de placeholder, pas de référence à une fonction non définie.
