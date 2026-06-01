import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";

const ROLE_LABEL = { fix_target: "train · fix_target", regression_guard: "test · regression_guard" };

function evalSummary(spec) {
  const crit = spec.criteria.map(c => c.name + (c.gate ? " [gate]" : "") + ` ×${c.weight}`).join(", ");
  const judge = spec.judge ? ` · judge ${spec.judge.mode} ×${spec.judge.weight}` : "";
  return `seuil ${spec.success_threshold} · ${crit}${judge}`;
}

function pct(x) { return `${Math.round(x * 100)}%`; }

export async function mountHealth(panel) {
  panel.innerHTML = `
    <div class="toolbar"><select class="hc-select"></select></div>
    <div class="hc-overview"></div>
    <div class="hc-testset"></div>
    <div class="toolbar"><span class="hc-case-label">Cas :</span><select class="case-select"></select><span class="hc-passrate chips"></span></div>
    <div class="graph-wrap"><svg></svg></div>`;

  const hcSelect = panel.querySelector(".hc-select");
  const caseSelect = panel.querySelector(".case-select");
  const svg = panel.querySelector(".graph-wrap svg");
  const passrate = panel.querySelector(".hc-passrate");

  const list = await api.healthChecks();
  if (!list.runs.length) { panel.innerHTML = '<p class="placeholder">Aucun health check.</p>'; return; }
  for (const r of list.runs) {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = r.id;
    hcSelect.appendChild(opt);
  }

  let detail = null, agentNames = {};

  function renderOverview() {
    const quarantine = detail.task_spec_quarantined.length + detail.evaluator_quarantined.length + detail.unattributed.length;
    panel.querySelector(".hc-overview").innerHTML = `
      <div class="cards">
        <div class="card"><div class="card-value">${pct(detail.fix_target_pass_rate)}</div><div class="card-label">fix_target pass</div></div>
        <div class="card"><div class="card-value">${pct(detail.regression_guard_pass_rate)}</div><div class="card-label">regression_guard pass</div></div>
        <div class="card"><div class="card-value">${detail.unstable_cases.length}</div><div class="card-label">unstable</div></div>
        <div class="card"><div class="card-value">${quarantine}</div><div class="card-label">quarantaine</div></div>
      </div>`;
  }

  function renderTestSet() {
    panel.querySelector(".hc-testset").innerHTML =
      `<div class="field-label">TestSet — ${detail.cases.length} cas</div>` +
      detail.cases.map(c => {
        const role = ROLE_LABEL[c.role] || c.role;
        const pr = c.result ? `${c.result.pass_count}/${c.result.n_runs}` : "—";
        const cls = c.graphable ? " case-row--clickable" : " case-quarantined";
        return `<div class="case-row${cls}" data-task="${c.task_id}">
          <span class="case-id">${c.task_id}</span>
          <span class="case-role">${role}</span>
          <span class="case-attr">${c.attribution}</span>
          <span class="case-eval">${evalSummary(c.evaluator_spec)}</span>
          <span class="case-pr">${pr}</span>
        </div>`;
      }).join("");
    panel.querySelectorAll(".hc-testset .case-row--clickable").forEach(row => {
      row.addEventListener("click", () => {
        caseSelect.value = row.dataset.task;
        loadGraph(row.dataset.task);
      });
    });
  }

  function renderCaseOptions() {
    caseSelect.innerHTML = "";
    for (const c of detail.cases.filter(x => x.graphable)) {
      const opt = document.createElement("option");
      opt.value = c.task_id;
      opt.textContent = `${c.task_id} (${c.result.pass_count}/${c.result.n_runs})`;
      caseSelect.appendChild(opt);
    }
  }

  async function loadGraph(taskId) {
    const c = detail.cases.find(x => x.task_id === taskId);
    passrate.textContent = c && c.result ? `pass_rate ${pct(c.result.pass_rate)} (${c.result.pass_count}/${c.result.n_runs})` : "";
    panel.querySelectorAll(".hc-testset .case-row").forEach(r => r.classList.toggle("case-row--active", r.dataset.task === taskId));
    const graph = await api.healthCheckGraph(detail.id, taskId);
    renderGraph(svg, graph, 0, (node, step) => openNodeModal(node, step, detail.agents), agentNames);
  }

  async function load(rid) {
    detail = await api.healthCheck(rid);
    agentNames = Object.fromEntries(detail.agents.map(a => [a.agent_id, a.name]));
    renderOverview();
    renderTestSet();
    renderCaseOptions();
    if (caseSelect.options.length) {
      await loadGraph(caseSelect.value);
    } else {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      passrate.textContent = "aucun cas graphable";
    }
  }

  hcSelect.addEventListener("change", () => load(hcSelect.value));
  caseSelect.addEventListener("change", () => loadGraph(caseSelect.value));
  await load(list.runs[0].id);
}
