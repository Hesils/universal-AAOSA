const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 120, NODE_H = 48, GAP_X = 44, BAND_GAP = 124, PAD = 52;
const LAYERS = ["top", "center", "bottom"];

// Hex wireframe (largeur NODE_W, hauteur NODE_H), centré sur l'origine.
const HEX_PTS = `${NODE_W / 2},0 ${NODE_W / 4},${NODE_H / 2} ${-NODE_W / 4},${NODE_H / 2} ${-NODE_W / 2},0 ${-NODE_W / 4},${-NODE_H / 2} ${NODE_W / 4},${-NODE_H / 2}`;

// Anatomie « arbre » : agents (layer bottom) = feuilles en haut, logique = tronc au milieu,
// in/out (layer top) = racines en bas. On inverse donc l'ordre vertical des bandes.
const TIER_LABEL = { bottom: "leaves · agents", center: "trunk · logic", top: "roots · in/out" };

let hexSeq = 0;

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
  // bandes inversées : bottom (agents) en haut, top (in/out) en bas.
  const bandTop = {
    bottom: PAD,
    center: PAD + NODE_H + BAND_GAP,
    top: PAD + 2 * (NODE_H + BAND_GAP),
  };
  const pos = {};
  for (const layer of LAYERS) {
    const row = byLayer[layer];
    const rowW = row.length * NODE_W + Math.max(0, row.length - 1) * GAP_X;
    const startX = (width - rowW) / 2;
    row.forEach((n, i) => {
      pos[n.id] = { cx: startX + i * (NODE_W + GAP_X) + NODE_W / 2, cy: bandTop[layer] + NODE_H / 2 };
    });
  }
  const tierY = Object.fromEntries(LAYERS.map(l => [l, bandTop[l] + NODE_H / 2]));
  return { pos, width, height, tierY };
}

function edgeKey(e) { return `${e.from}->${e.to}`; }

export function renderGraph(svg, graph, activeStepIndex, onNodeClick, agentNames = {}) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "graph");

  const { pos, width, height, tierY } = layout(graph);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

  // hex partagé, id unique par rendu (évite la collision entre les svg sessions/health).
  const hexId = `hex-${hexSeq++}`;
  const defs = el("defs");
  defs.appendChild(el("polygon", { id: hexId, points: HEX_PTS }));
  svg.appendChild(defs);

  // marqueurs de tier (faibles), à gauche
  for (const layer of LAYERS) {
    const t = el("text", { x: 6, y: tierY[layer] - NODE_H / 2 - 8, class: "gtier" });
    t.textContent = TIER_LABEL[layer];
    svg.appendChild(t);
  }

  const step = graph.steps[activeStepIndex] || null;
  const activeNodes = new Set(step ? step.active_nodes : []);
  const activeEdges = new Set(step ? step.active_edges.map(edgeKey) : []);
  const winnerId = step ? step.winner_agent_id : null;
  const failBranch = step && step.outcome === "qa_fail";

  // arêtes : idle (wire) ; actives (ember) ; branche fail pointillée.
  const edgeLayer = el("g");
  const pulseLayer = el("g");
  let pulseIdx = 0;
  for (const e of graph.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const isActive = activeEdges.has(edgeKey(e));
    const isFail = failBranch && isActive && e.to === "testset";
    const line = el("line", { x1: a.cx, y1: a.cy, x2: b.cx, y2: b.cy });
    line.setAttribute("class", "edge" + (isActive ? " edge--a" : "") + (isFail ? " edge--fail" : ""));
    edgeLayer.appendChild(line);

    // pulse dots ember sur les arêtes actives (calme, staggered) — pas sur la branche fail.
    if (isActive && !isFail) {
      const dot = el("circle", { r: 2.8, class: "pulse" });
      const motion = el("animateMotion", {
        dur: "2.6s",
        begin: (pulseIdx++ * 0.7).toFixed(1) + "s",
        repeatCount: "indefinite",
        path: `M${a.cx},${a.cy} L${b.cx},${b.cy}`,
      });
      dot.appendChild(motion);
      pulseLayer.appendChild(dot);
    }
  }
  svg.appendChild(edgeLayer);
  svg.appendChild(pulseLayer);

  // nœuds (hexagones wireframe)
  for (const n of graph.nodes) {
    const p = pos[n.id];
    const g = el("g", { class: "node node--" + n.type, transform: `translate(${p.cx},${p.cy})` });
    g.dataset.nodeId = n.id;
    if (activeNodes.has(n.id)) g.classList.add("node--active");
    if (n.id === winnerId) g.classList.add("node--winner");

    const hex = el("use", { class: "hex", href: "#" + hexId });
    hex.setAttributeNS("http://www.w3.org/1999/xlink", "href", "#" + hexId);
    const label = el("text", { x: 0, y: 4, "text-anchor": "middle", class: "node-label" });
    label.textContent = (n.type === "agent" && agentNames[n.id]) || n.label;
    g.append(hex, label);
    if (onNodeClick) g.addEventListener("click", () => onNodeClick(n, step));
    svg.appendChild(g);
  }
}
