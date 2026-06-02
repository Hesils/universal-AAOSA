import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";
import { esc } from "../util.js";

const ROLE_LABEL = { fix_target: "train · fix_target", regression_guard: "test · regression_guard" };

function evalSummary(spec) {
  const crit = spec.criteria.map(c => esc(c.name) + (c.gate ? " [gate]" : "") + ` ×${c.weight}`).join(", ");
  const judge = spec.judge ? ` · judge ${esc(spec.judge.mode)} ×${spec.judge.weight}` : "";
  return `seuil ${spec.success_threshold} · ${crit}${judge}`;
}

function pct(x) { return `${Math.round(x * 100)}%`; }

function prClass(c) {
  if (!c.result) return "none";
  return c.result.pass_rate >= 0.7 ? "ok" : "warn";
}

export async function mountHealth(panel) {
  panel.innerHTML = `
    <h2 class="sec">Health checks</h2>
    <div class="toolbar"><select class="sel hc-select"></select></div>
    <div class="strip hc-overview"></div>
    <div class="panel case-table hc-testset"></div>
    <div class="toolbar hc-case-bar"><span class="chips">Cas :</span><select class="sel case-select"></select><span class="hc-passrate chips"></span></div>
    <div class="panel graph-frame">
      <span class="ghead">CASE GRAPH</span>
      <svg class="graph"></svg>
    </div>`;

  const hcSelect = panel.querySelector(".hc-select");
  const caseSelect = panel.querySelector(".case-select");
  const svg = panel.querySelector(".graph-frame svg");
  const ghead = panel.querySelector(".ghead");
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
      <div class="stat stat--accent"><div class="stat-label">fix_target pass</div><div class="stat-value">${pct(detail.fix_target_pass_rate)}</div></div>
      <div class="stat stat--accent"><div class="stat-label">regression_guard</div><div class="stat-value">${pct(detail.regression_guard_pass_rate)}</div></div>
      <div class="stat"><div class="stat-label">unstable</div><div class="stat-value">${detail.unstable_cases.length}</div></div>
      <div class="stat"><div class="stat-label">quarantaine</div><div class="stat-value">${quarantine}</div></div>`;
  }

  function renderTestSet() {
    const head = `<div class="case-head"><span>task_id</span><span>role</span><span>attribution</span><span>evaluator</span><span>pass</span></div>`;
    const rows = detail.cases.map(c => {
      const role = ROLE_LABEL[c.role] || c.role;
      const pr = c.result ? `${c.result.pass_count}/${c.result.n_runs}` : "—";
      const cls = c.graphable ? " case-row--clickable" : " case-row--quar";
      return `<div class="case-row${cls}" data-task="${esc(c.task_id)}">
        <span class="case-id">${esc(c.task_id)}</span>
        <span class="case-role">${esc(role)}</span>
        <span class="case-attr">${esc(c.attribution)}</span>
        <span class="case-eval">${evalSummary(c.evaluator_spec)}</span>
        <span class="case-pr ${prClass(c)}">${pr}</span>
      </div>`;
    }).join("");
    panel.querySelector(".hc-testset").innerHTML = head + rows;
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

  // Cas health = run mono-tâche, vue statique : on résout chaque nœud vers le jalon
  // qui porte son détail (chaque jalon n'apparaît qu'une fois dans un run simple).
  function stepForNode(graph, node) {
    const last = graph.steps[graph.steps.length - 1];
    const byMilestone = mt => graph.steps.find(s => s.milestone_type === mt) || last;
    if (node.type === "tool") return graph.steps.find(s => s.detail.tool && s.detail.tool.tool_name === node.label) || last;
    if (node.type === "agent") return graph.steps.find(s => s.milestone_type === "agent") || byMilestone("dispatch");
    return byMilestone(node.type);
  }

  async function loadGraph(taskId) {
    const c = detail.cases.find(x => x.task_id === taskId);
    ghead.textContent = `CASE GRAPH — ${taskId}`;
    passrate.innerHTML = c && c.result ? `pass_rate <b>${pct(c.result.pass_rate)}</b> · ${c.result.pass_count}/${c.result.n_runs} runs` : "";
    panel.querySelectorAll(".hc-testset .case-row").forEach(r => r.classList.toggle("case-row--active", r.dataset.task === taskId));
    const graph = await api.healthCheckGraph(detail.id, taskId);
    // chemin complet allumé (pas de scrubber sur le case graph)
    renderGraph(svg, graph, 0, (node) => openNodeModal(node, stepForNode(graph, node), detail.agents), agentNames, { fullPath: true });
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
      ghead.textContent = "CASE GRAPH";
      passrate.textContent = "aucun cas graphable";
    }
  }

  hcSelect.addEventListener("change", () => load(hcSelect.value));
  caseSelect.addEventListener("change", () => loadGraph(caseSelect.value));
  await load(list.runs[0].id);
}
