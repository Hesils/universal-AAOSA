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
