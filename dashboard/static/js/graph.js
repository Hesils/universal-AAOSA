// graph.js — arbre émergent bottom-up (série D). Racines (INPUT/TAGGER/OUTPUT) en bas,
// l'arbre pousse vers le haut : une arche par branche (DISPATCH montée → AGENT apex → EVAL descente),
// paire DIVIDER/AGGREGATOR par niveau, routage delta 45° (rails + chanfreins, point = jonction).
const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 104, NODE_H = 40;
const ROW_H = 96;        // pas vertical de la grille (k-rows)
const SLOT_W = 244;      // largeur d'un slot de branche feuille
const LEG_IN = 56;       // retrait des jambes (montée/descente) depuis les bords du slot
const PAD = 64;
const CH = 14;           // chanfrein 45° aux coudes (dialecte delta)

const HEX_PTS = `${NODE_W / 2},0 ${NODE_W / 4},${NODE_H / 2} ${-NODE_W / 4},${NODE_H / 2} ${-NODE_W / 2},0 ${-NODE_W / 4},${-NODE_H / 2} ${NODE_W / 4},${-NODE_H / 2}`;
const DIA_PTS = `0,${-NODE_H / 2 - 4} ${NODE_W / 3},0 0,${NODE_H / 2 + 4} ${-NODE_W / 3},0`; // losange DIAG

let hexSeq = 0;

function el(name, attrs = {}) {
  const e = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

const fmt = n => Math.round(n * 10) / 10;

// ---------------------------------------------------------------- arbre
function buildTree(graph) {
  const tasks = graph.tasks || [];
  const byId = {}, kids = {};
  let root = null;
  for (const t of tasks) {
    byId[t.id] = t;
    if (t.parent_id == null) root = t.id;
    else (kids[t.parent_id] ||= []).push(t);
  }
  for (const k in kids) kids[k].sort((a, b) => a.order_index - b.order_index);
  return { byId, root, children: id => (kids[id] || []).map(t => t.id) };
}

// ---------------------------------------------------------------- layout
// k-rows depuis le bas : 0 = racines (INPUT/OUTPUT), 1 = TAGGER (tronc).
// Tâche de profondeur d : organes (DISPATCH/EVAL/GAP) k=2d+2, apex (AGENT ou paire
// DIVIDER/AGGREGATOR) k=2d+3, canopée TOOLS k=2d+4. DIAG s'insère sur la jambe de
// descente entre l'organe et la rangée du dessous.
function layout(graph) {
  const tree = buildTree(graph);
  const byTask = {};
  for (const n of graph.nodes) {
    if (!n.task_id) continue;
    const b = (byTask[n.task_id] ||= { agents: [], tools: [] });
    if (n.type === "agent") b.agents.push(n);
    else if (n.type === "tool") b.tools.push(n);
    else b[n.type] = n;
  }

  const span = {};
  let nextSlot = 0;
  (function place(tid) {
    const ks = tree.children(tid);
    if (!ks.length) {
      const x0 = PAD + nextSlot * SLOT_W;
      span[tid] = [x0, x0 + SLOT_W];
      nextSlot++;
      return;
    }
    for (const k of ks) place(k);
    span[tid] = [span[ks[0]][0], span[ks[ks.length - 1]][1]];
  })(tree.root);

  let maxK = 4;
  for (const t of (graph.tasks || [])) maxK = Math.max(maxK, 2 * t.depth + 4);
  const width = Math.max(PAD * 2 + nextSlot * SLOT_W, PAD * 2 + SLOT_W);
  const height = PAD * 2 + maxK * ROW_H + NODE_H;
  const Y = k => height - PAD - NODE_H / 2 - k * ROW_H;

  const pos = {};
  const [rx0, rx1] = span[tree.root] || [PAD, PAD + SLOT_W];
  pos.input = { cx: rx0 + LEG_IN, cy: Y(0) };
  pos.output = { cx: rx1 - LEG_IN, cy: Y(0) };
  pos.tagger = { cx: rx0 + LEG_IN, cy: Y(1) };

  for (const tid in byTask) {
    const t = tree.byId[tid];
    const sp = span[tid];
    if (!t || !sp) continue;
    const [x0, x1] = sp;
    const ax = x0 + LEG_IN, dx = x1 - LEG_IN, cx = (x0 + x1) / 2;
    const kOrg = 2 * t.depth + 2;
    const b = byTask[tid];
    if (b.dispatch) pos[b.dispatch.id] = { cx: ax, cy: Y(kOrg) };
    if (b.evaluator) pos[b.evaluator.id] = { cx: dx, cy: Y(kOrg) };
    if (b.diagnostic) pos[b.diagnostic.id] = { cx: dx, cy: Y(kOrg) + ROW_H * 0.58 };
    if (b.roster_gap) pos[b.roster_gap.id] = { cx: cx, cy: Y(kOrg) };
    b.agents.forEach((n, i) => {
      const off = (i - (b.agents.length - 1) / 2) * (NODE_W + 14);
      pos[n.id] = { cx: cx + off, cy: Y(kOrg + 1) };
    });
    b.tools.forEach((n, i) => {
      const innerW = Math.max(x1 - x0 - LEG_IN * 2, NODE_W);
      const step = b.tools.length > 1 ? innerW / (b.tools.length - 1) : 0;
      pos[n.id] = { cx: b.tools.length > 1 ? x0 + LEG_IN + i * step : cx, cy: Y(kOrg + 2) };
    });
    if (b.divider) pos[b.divider.id] = { cx: x0 + NODE_W / 2 + 4, cy: Y(kOrg + 1) };
    if (b.aggregator) pos[b.aggregator.id] = { cx: x1 - NODE_W / 2 - 4, cy: Y(kOrg + 1) };
  }
  return { pos, width, height };
}

// ---------------------------------------------------------------- routage delta 45°
// Convention schéma électrique : point = jonction réelle ; croisement sans point = rien.
function straight(a, b) { return { d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(b.cx)},${fmt(b.cy)}`, dots: [] }; }

function railThenRise(a, b) {
  // rail horizontal à hauteur de a, chanfrein 45°, verticale vers b (bus d'émission, loop-backs)
  if (Math.abs(a.cx - b.cx) < CH * 2) return straight(a, b);
  const sx = Math.sign(b.cx - a.cx), sy = Math.sign(b.cy - a.cy) || -1;
  const jx = b.cx - sx * CH;
  return {
    d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(jx)},${fmt(a.cy)} L${fmt(b.cx)},${fmt(a.cy + sy * CH)} L${fmt(b.cx)},${fmt(b.cy)}`,
    dots: [{ x: jx, y: a.cy }],
  };
}

function riseThenRail(a, b) {
  // verticale depuis a, chanfrein 45°, rail horizontal à hauteur de b (bus de collecte, montées vers divider)
  if (Math.abs(a.cy - b.cy) < CH * 2) return straight(a, b);
  const sx = Math.sign(b.cx - a.cx) || -1, sy = Math.sign(b.cy - a.cy);
  const jy = b.cy - sy * CH;
  return {
    d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(a.cx)},${fmt(jy)} L${fmt(a.cx + sx * CH)},${fmt(b.cy)} L${fmt(b.cx)},${fmt(b.cy)}`,
    dots: [{ x: a.cx + sx * CH, y: b.cy }],
  };
}

function routeEdge(e, pos, typeById) {
  const a = pos[e.from], b = pos[e.to];
  if (!a || !b) return null;
  const tf = typeById[e.from], tt = typeById[e.to];
  if (tf === "divider" || tf === "diagnostic") return railThenRise(a, b);
  if (tt === "divider" || tt === "aggregator" || tt === "output") return riseThenRail(a, b);
  return straight(a, b);   // tronc, dispatch→agent (diagonale), agent→eval, agent→tool, eval→diag
}

// ---------------------------------------------------------------- état actif
function edgeKey(e) { return `${e.from}->${e.to}`; }

function unionActive(graph) {
  // union cumulée de tous les jalons (vue statique du health tab)
  const nodes = new Set(), edges = new Set();
  let winnerId = null, failBranch = false;
  for (const s of graph.steps) {
    s.active_nodes.forEach(n => nodes.add(n));
    s.active_edges.forEach(e => edges.add(edgeKey(e)));
    if (s.winner_agent_id) winnerId = s.winner_agent_id;
    if (s.outcome === "qa_fail") failBranch = true;
  }
  return { activeNodes: nodes, activeEdges: edges, winnerId, failBranch };
}

export function bboxOf(ids, pos) {
  const xs = [], ys = [];
  for (const id of ids) { const p = pos[id]; if (p) { xs.push(p.cx); ys.push(p.cy); } }
  if (!xs.length) return null;
  const x0 = Math.min(...xs) - NODE_W, x1 = Math.max(...xs) + NODE_W;
  const y0 = Math.min(...ys) - NODE_H * 2, y1 = Math.max(...ys) + NODE_H * 2;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

// ---------------------------------------------------------------- rendu
export function renderGraph(svg, graph, activeStepIndex, onNodeClick, agentNames = {}, opts = {}) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "graph");

  const { pos, width, height } = layout(graph);
  if (!opts.keepViewBox) {
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }

  const hexId = `hex-${hexSeq}`, diaId = `dia-${hexSeq}`;
  hexSeq++;
  const defs = el("defs");
  defs.appendChild(el("polygon", { id: hexId, points: HEX_PTS }));
  defs.appendChild(el("polygon", { id: diaId, points: DIA_PTS }));
  svg.appendChild(defs);

  const typeById = Object.fromEntries(graph.nodes.map(n => [n.id, n.type]));

  const step = graph.steps[activeStepIndex] || null;
  let activeNodes, activeEdges, winnerId, failBranch;
  if (opts.fullPath) {
    const u = unionActive(graph);
    activeNodes = u.activeNodes; activeEdges = u.activeEdges;
    winnerId = u.winnerId; failBranch = u.failBranch;
  } else {
    activeNodes = new Set(step ? step.active_nodes : []);
    activeEdges = new Set(step ? step.active_edges.map(edgeKey) : []);
    winnerId = step ? step.winner_agent_id : null;
    failBranch = step && step.outcome === "qa_fail";
  }

  // arêtes : idle wire ; actives par flow (montée crest, descente fire, transient pointillé)
  const edgeLayer = el("g");
  const dotLayer = el("g");
  const pulseLayer = el("g");
  let pulseIdx = 0;
  for (const e of graph.edges) {
    const r = routeEdge(e, pos, typeById);
    if (!r) continue;
    const isActive = activeEdges.has(edgeKey(e));
    const path = el("path", { d: r.d, class: `edge edge--${e.flow}${isActive ? " edge--a" : ""}` });
    edgeLayer.appendChild(path);
    for (const dot of r.dots) {
      dotLayer.appendChild(el("circle", {
        cx: fmt(dot.x), cy: fmt(dot.y), r: 2.4,
        class: "junction" + (isActive ? " junction--a" : ""),
      }));
    }
    // pulses directionnels : points crest montent, points ember descendent (jamais sur transient)
    if (isActive && e.flow !== "transient") {
      const dot = el("circle", { r: 2.8, class: `pulse pulse--${e.flow}` });
      const motion = el("animateMotion", {
        dur: "2.6s",
        begin: (pulseIdx++ * 0.7).toFixed(1) + "s",
        repeatCount: "indefinite",
        path: r.d,
      });
      dot.appendChild(motion);
      pulseLayer.appendChild(dot);
    }
  }
  svg.appendChild(edgeLayer);
  svg.appendChild(dotLayer);
  svg.appendChild(pulseLayer);

  // badge ×N : même agent réel instancié sur plusieurs branches
  const instances = {};
  for (const n of graph.nodes) if (n.type === "agent" && n.agent_id) (instances[n.agent_id] ||= []).push(n.id);

  for (const n of graph.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const g = el("g", { class: "node node--" + n.type, transform: `translate(${fmt(p.cx)},${fmt(p.cy)})` });
    g.dataset.nodeId = n.id;
    if (n.agent_id) g.dataset.agentId = n.agent_id;
    if (activeNodes.has(n.id)) g.classList.add("node--active");
    if (n.agent_id && n.agent_id === winnerId && activeNodes.has(n.id)) g.classList.add("node--winner");

    const shapeRef = n.type === "diagnostic" ? diaId : hexId;
    const shape = el("use", { class: "hex", href: "#" + shapeRef });
    shape.setAttributeNS("http://www.w3.org/1999/xlink", "href", "#" + shapeRef);
    const label = el("text", { x: 0, y: 4, "text-anchor": "middle", class: "node-label" });
    label.textContent = (n.type === "agent" && agentNames[n.agent_id]) || n.label;
    g.append(shape, label);

    const kin = n.agent_id ? instances[n.agent_id] : null;
    if (kin && kin.length > 1) {
      const badge = el("text", { x: NODE_W / 2 - 6, y: -NODE_H / 2 + 2, "text-anchor": "end", class: "node-badge" });
      badge.textContent = `×${kin.length}`;
      g.appendChild(badge);
      g.addEventListener("mouseenter", () => {
        svg.querySelectorAll(`[data-agent-id="${n.agent_id}"]`).forEach(x => x.classList.add("node--kin"));
      });
      g.addEventListener("mouseleave", () => {
        svg.querySelectorAll(".node--kin").forEach(x => x.classList.remove("node--kin"));
      });
    }
    if (onNodeClick) g.addEventListener("click", () => onNodeClick(n, step));
    svg.appendChild(g);
  }
  return { pos, width, height };
}
