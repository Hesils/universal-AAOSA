import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";
import { esc } from "../util.js";

export async function mountSessions(panel) {
  panel.innerHTML = `
    <div class="toolbar">
      <select class="sel session-select"></select>
      <span class="chips"></span>
    </div>
    <div class="session-body">
      <div class="panel graph-frame">
        <span class="ghead">EXECUTION GRAPH</span>
        <svg class="graph"></svg>
      </div>
      <aside class="panel todo">
        <h3>Tasks</h3>
        <div class="todo-list"></div>
      </aside>
    </div>
    <div class="scrubber">
      <button class="scrub-btn scrub-prev">◀</button>
      <span class="scrub-track"><span class="scrub-fill"></span></span>
      <button class="scrub-btn scrub-next">▶</button>
      <span class="scrub-label"></span>
    </div>`;

  const select = panel.querySelector(".session-select");
  const svg = panel.querySelector(".graph-frame svg");
  const chips = panel.querySelector(".chips");
  const todo = panel.querySelector(".todo-list");
  const scrubLabel = panel.querySelector(".scrub-label");
  const scrubFill = panel.querySelector(".scrub-fill");

  const list = await api.sessions();
  if (!list.sessions.length) { panel.innerHTML = '<p class="placeholder">Aucune session persistée.</p>'; return; }
  for (const s of list.sessions) {
    const opt = document.createElement("option");
    opt.value = s.session_id;
    opt.textContent = s.session_id;
    select.appendChild(opt);
  }

  let detail = null, graph = null, activeStepIndex = 0, agentNames = {};

  function renderTodo() {
    const tasks = detail.meta.tasks;
    todo.innerHTML = tasks.map((t, i) => {
      const state = i < activeStepIndex ? "done" : (i === activeStepIndex ? "current" : "pending");
      return `<div class="todo-item todo--${state}"><span class="mk"></span><span>${esc(t.description)}</span></div>`;
    }).join("");
  }

  function renderChips() {
    chips.innerHTML = `<span><b>${detail.meta.tasks.length}</b> tasks</span><span><b>${detail.meta.agent_ids.length}</b> agents</span>`;
  }

  function rerender() {
    renderGraph(svg, graph, activeStepIndex, (node, step) => openNodeModal(node, step, detail.agents), agentNames);
    const n = graph.steps.length;
    if (n) {
      const step = graph.steps[activeStepIndex];
      scrubLabel.innerHTML = `Step <b>${activeStepIndex + 1}</b> / ${n} — ${esc(step.label)}`;
      scrubFill.style.width = `${((activeStepIndex + 1) / n) * 100}%`;
    } else {
      scrubLabel.textContent = "Aucun step";
      scrubFill.style.width = "0%";
    }
    renderTodo();
  }

  async function load(sid) {
    [detail, graph] = await Promise.all([api.session(sid), api.sessionGraph(sid)]);
    agentNames = Object.fromEntries(detail.agents.map(a => [a.agent_id, a.name]));
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
