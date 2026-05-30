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
