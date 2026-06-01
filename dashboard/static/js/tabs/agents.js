import { api } from "../api.js";
import { lineChart, PALETTE } from "../charts.js";
import { esc } from "../util.js";

function eloBars(tags) {
  return Object.entries(tags)
    .sort((a, b) => b[1] - a[1])
    .map(([tag, elo]) =>
      `<div class="bar-row">
         <span class="bar-label">${esc(tag)}</span>
         <span class="bar-track"><span class="bar-fill" style="width:${elo}%"></span></span>
         <span class="bar-val">${elo}</span>
       </div>`)
    .join("");
}

export async function mountAgents(panel) {
  panel.innerHTML = `
    <h2 class="sec">Agents</h2>
    <div class="toolbar"><select class="sel agent-select"></select></div>
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
      .map((s, i) => `<span class="legend"><i style="background:${PALETTE[i % PALETTE.length]}"></i>${esc(s.tag)}</span>`)
      .join("");
    const act = d.activity;
    view.innerHTML = `
      <div class="afield"><div class="field-label">System prompt</div>
        <div class="field-value">${esc(d.system_prompt)}</div></div>
      <div class="afield"><div class="field-label">Tags · ELO courant</div>
        <div class="bars">${eloBars(d.tags_with_elo)}</div></div>
      <div class="afield afield--grow"><div class="field-label">Historique ELO par tag</div>
        <div class="legend-row">${legend}</div>
        <figure class="panel chart-card"><figcaption>ELO par tag dans le temps</figcaption>
          <svg class="chart elo-curve"></svg></figure></div>
      <div class="afield"><div class="field-label">Activity (cumul tous runs)</div>
        <div class="activity">
          <span class="act-chip"><b>claims</b> ${act.claims}</span>
          <span class="act-chip"><b>wins</b> ${act.wins}</span>
          <span class="act-chip"><b>success</b> ${act.successes}</span>
          <span class="act-chip"><b>fail</b> ${act.failures}</span>
        </div></div>`;
    lineChart(view.querySelector(".elo-curve"), d.elo_history.map(s => ({
      name: s.tag,
      points: s.points.map((pt, i) => ({ x: i, y: pt.elo })),
    })));
  }

  select.addEventListener("change", () => load(select.value));
  await load(list.agents[0].agent_id);
}
