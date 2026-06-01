import { api } from "../api.js";
import { lineChart, PALETTE } from "../charts.js";

function eloBars(tags) {
  return Object.entries(tags)
    .sort((a, b) => b[1] - a[1])
    .map(([tag, elo]) =>
      `<div class="bar-row">
         <span class="bar-label">${tag}</span>
         <span class="bar-track"><span class="bar-fill" style="width:${elo}%"></span></span>
         <span class="bar-val">${elo}</span>
       </div>`)
    .join("");
}

export async function mountAgents(panel) {
  panel.innerHTML = `
    <div class="toolbar"><select class="agent-select"></select></div>
    <div class="agent-view"></div>`;
  const select = panel.querySelector(".agent-select");
  const view = panel.querySelector(".agent-view");

  const list = await api.agents();
  if (!list.agents.length) { panel.innerHTML = '<p class="placeholder">Aucun agent.</p>'; return; }
  for (const a of list.agents) {
    const opt = document.createElement("option");
    opt.value = a.agent_id;
    opt.textContent = a.name;
    select.appendChild(opt);
  }

  async function load(aid) {
    const d = await api.agent(aid);
    const legend = d.elo_history
      .map((s, i) => `<span class="legend"><i style="background:${PALETTE[i % PALETTE.length]}"></i>${s.tag}</span>`)
      .join("");
    view.innerHTML = `
      <div class="field"><div class="field-label">System prompt</div><div class="field-value">${d.system_prompt}</div></div>
      <div class="field"><div class="field-label">Tags · ELO courant</div><div class="bars">${eloBars(d.tags_with_elo)}</div></div>
      <div class="field"><div class="field-label">Historique ELO par tag</div><div class="legend-row">${legend}</div><svg class="elo-curve"></svg></div>
      <div class="field"><div class="field-label">Activity (cumul tous runs)</div>
        <div class="chips">claims ${d.activity.claims} · wins ${d.activity.wins} · success ${d.activity.successes} · fail ${d.activity.failures}</div></div>`;
    lineChart(view.querySelector(".elo-curve"), d.elo_history.map(s => ({
      name: s.tag,
      points: s.points.map((pt, i) => ({ x: i, y: pt.elo })),
    })));
  }

  select.addEventListener("change", () => load(select.value));
  await load(list.agents[0].agent_id);
}
