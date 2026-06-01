const SVG_NS = "http://www.w3.org/2000/svg";

// Palette partagée (légende des tabs alignée sur l'ordre des séries).
export const PALETTE = ["#10b981", "#a78bfa", "#f59e0b", "#38bdf8", "#f472b6", "#84cc16"];

function el(name, attrs = {}) {
  const e = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function fmt(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function reset(svg, width, height) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "chart");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
}

function empty(svg, width, height) {
  const t = el("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-empty" });
  t.textContent = "no data";
  svg.appendChild(t);
}

// series = [{ name, color?, points: [{x:number, y:number}] }]
export function lineChart(svg, series, { width = 520, height = 200, pad = 30 } = {}) {
  reset(svg, width, height);
  const all = series.flatMap(s => s.points);
  if (!all.length) { empty(svg, width, height); return; }

  const xs = all.map(p => p.x), ys = all.map(p => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const sx = x => pad + (xMax === xMin ? 0.5 : (x - xMin) / (xMax - xMin)) * (width - 2 * pad);
  const sy = y => height - pad - (yMax === yMin ? 0.5 : (y - yMin) / (yMax - yMin)) * (height - 2 * pad);

  for (const [val, yy] of [[yMax, yMax], [yMin, yMin]]) {
    const lbl = el("text", { x: 4, y: sy(yy) + 4, class: "chart-axis" });
    lbl.textContent = fmt(val);
    svg.appendChild(lbl);
  }

  series.forEach((s, i) => {
    const color = s.color || PALETTE[i % PALETTE.length];
    if (s.points.length > 1) {
      const pts = s.points.map(p => `${sx(p.x)},${sy(p.y)}`).join(" ");
      svg.appendChild(el("polyline", { points: pts, fill: "none", stroke: color, "stroke-width": 2 }));
    }
    for (const p of s.points) svg.appendChild(el("circle", { cx: sx(p.x), cy: sy(p.y), r: 2.5, fill: color }));
  });
}

// bars = [{ label, value }]
export function barChart(svg, bars, { width = 520, height = 200, pad = 30 } = {}) {
  reset(svg, width, height);
  if (!bars.length) { empty(svg, width, height); return; }

  const max = Math.max(...bars.map(b => b.value), 1);
  const slot = (width - 2 * pad) / bars.length;
  const bw = Math.min(slot * 0.6, 48);
  bars.forEach((b, i) => {
    const x = pad + i * slot + (slot - bw) / 2;
    const h = (b.value / max) * (height - 2 * pad);
    const y = height - pad - h;
    svg.appendChild(el("rect", { x, y, width: bw, height: h, rx: 3, class: "chart-bar" }));
    const val = el("text", { x: x + bw / 2, y: y - 4, "text-anchor": "middle", class: "chart-axis" });
    val.textContent = fmt(b.value);
    svg.appendChild(val);
    const lbl = el("text", { x: x + bw / 2, y: height - pad + 12, "text-anchor": "middle", class: "chart-axis" });
    lbl.textContent = b.label;
    svg.appendChild(lbl);
  });
}
