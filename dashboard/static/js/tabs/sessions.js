import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal, openTextModal } from "../modal.js";
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
      <button class="scrub-btn scrub-prev" title="Jalon précédent (maintenir pour défiler)">◀</button>
      <span class="scrub-track" tabindex="0" role="slider" aria-label="Position dans la timeline">
        <span class="scrub-fill"></span><span class="scrub-handle"></span>
      </span>
      <button class="scrub-btn scrub-next" title="Jalon suivant (maintenir pour défiler)">▶</button>
      <span class="scrub-label"></span>
    </div>`;

  const select = panel.querySelector(".session-select");
  const svg = panel.querySelector(".graph-frame svg");
  const chips = panel.querySelector(".chips");
  const todo = panel.querySelector(".todo-list");
  const scrubLabel = panel.querySelector(".scrub-label");
  const scrubFill = panel.querySelector(".scrub-fill");
  const scrubHandle = panel.querySelector(".scrub-handle");
  const scrubTrack = panel.querySelector(".scrub-track");

  const list = await api.sessions();
  if (!list.sessions.length) { panel.innerHTML = '<p class="placeholder">Aucune session persistée.</p>'; return; }
  for (const s of list.sessions) {
    const opt = document.createElement("option");
    opt.value = s.session_id;
    opt.textContent = s.session_id;
    select.appendChild(opt);
  }

  let detail = null, graph = null, activeStepIndex = 0, agentNames = {};

  // Divider/Aggregator ne s'allument qu'à un seul jalon. Leur modal doit refléter l'état à
  // l'instant T : si la timeline a déjà atteint leur jalon, on montre son détail (même en
  // scrubbant ailleurs après) ; si elle est encore AVANT, on garde le jalon courant → état
  // "pas encore exécuté" (sinon le modal afficherait l'état final dès le 1er jalon).
  function stepForNode(node, current) {
    if (node.type === "aggregator") {
      // actif au jalon courant (collecte progressive OU final) → état à l'instant T
      if (current && current.active_nodes.includes("aggregator")) return current;
      // sinon, si la timeline a dépassé l'agrégation finale → ce jalon ; avant toute collecte → pending
      const mi = graph.steps.findIndex(s => s.milestone_type === "aggregator");
      if (mi >= 0 && activeStepIndex >= mi) return graph.steps[mi];
      return current;
    }
    if (node.type === "divider") {
      const mi = graph.steps.findIndex(s => s.milestone_type === "divider");
      if (mi >= 0 && activeStepIndex >= mi) return graph.steps[mi];
    }
    return current;
  }

  // Premier jalon qui traite une tâche donnée (racine → INPUT ; sous-tâche → son 1er jalon).
  function firstStepIndexForTask(tid, isRoot) {
    if (isRoot) return 0;
    const i = graph.steps.findIndex(s => s.sub_task_id === tid);
    return i >= 0 ? i : activeStepIndex;
  }

  function renderTodo() {
    const step = graph.steps[activeStepIndex];
    const items = step ? step.todo : [];
    todo.innerHTML = "";
    for (const t of items) {
      const row = document.createElement("div");
      row.className = `todo-item todo--${t.state}${t.is_root ? "" : " todo--sub"}`;
      row.title = "Aller au premier jalon de cette tâche";

      const mk = document.createElement("span");
      mk.className = "mk";
      const text = document.createElement("span");
      text.className = "todo-text";
      text.textContent = t.description;
      row.append(mk, text);

      // icône dédiée → texte complet en modal, pour TOUTE (sous-)tâche (descriptions longues)
      const exp = document.createElement("button");
      exp.className = "todo-expand";
      const label = t.is_root ? "Voir l'input complet" : "Voir la description complète";
      exp.title = label;
      exp.setAttribute("aria-label", label);
      exp.textContent = "⤢";
      exp.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openTextModal((t.is_root ? "Input · " : "Sous-tâche · ") + t.id, t.description);
      });
      row.appendChild(exp);

      row.addEventListener("click", () => {
        activeStepIndex = firstStepIndexForTask(t.id, t.is_root);
        rerender();
      });
      todo.appendChild(row);
    }
  }

  function renderChips() {
    const div = graph.steps.find(s => s.milestone_type === "divider");
    const subCount = div ? div.detail.divider.sub_tasks.length : 0;
    const sub = subCount ? `<span><b>${subCount}</b> sous-tâches</span>` : "";
    chips.innerHTML = `<span><b>${detail.meta.tasks.length}</b> tasks</span>${sub}<span><b>${detail.meta.agent_ids.length}</b> agents</span>`;
  }

  function rerender() {
    renderGraph(svg, graph, activeStepIndex, (node, step) => openNodeModal(node, stepForNode(node, step), detail.agents), agentNames);
    const n = graph.steps.length;
    if (n) {
      const step = graph.steps[activeStepIndex];
      scrubLabel.innerHTML = `Jalon <b>${activeStepIndex + 1}</b> / ${n} — <span class="mono">${esc(step.label)}</span>`;
      const ratio = n > 1 ? activeStepIndex / (n - 1) : 1;
      scrubFill.style.width = `${ratio * 100}%`;
      scrubHandle.style.left = `${ratio * 100}%`;
      scrubTrack.setAttribute("aria-valuenow", String(activeStepIndex + 1));
      scrubTrack.setAttribute("aria-valuemax", String(n));
    } else {
      scrubLabel.textContent = "Aucun step";
      scrubFill.style.width = "0%";
      scrubHandle.style.left = "0%";
    }
    renderTodo();
  }

  function goTo(index) {
    const n = graph.steps.length;
    if (!n) return;
    const clamped = Math.max(0, Math.min(n - 1, index));
    if (clamped !== activeStepIndex) { activeStepIndex = clamped; rerender(); }
  }
  function nudge(dir) { goTo(activeStepIndex + dir); }

  async function load(sid) {
    [detail, graph] = await Promise.all([api.session(sid), api.sessionGraph(sid)]);
    agentNames = Object.fromEntries(detail.agents.map(a => [a.agent_id, a.name]));
    activeStepIndex = 0;
    renderChips();
    rerender();
  }

  select.addEventListener("change", () => load(select.value));

  // ◀ / ▶ : un pas au clic, puis défilement continu si maintenu (delay 400ms, repeat 110ms).
  function holdable(btn, dir) {
    let repeatTimer = null, delayTimer = null;
    const stop = () => { clearTimeout(delayTimer); clearInterval(repeatTimer); delayTimer = repeatTimer = null; };
    btn.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      nudge(dir);
      delayTimer = setTimeout(() => { repeatTimer = setInterval(() => nudge(dir), 110); }, 400);
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach(e => btn.addEventListener(e, stop));
  }
  holdable(panel.querySelector(".scrub-prev"), -1);
  holdable(panel.querySelector(".scrub-next"), +1);

  // Drag sur la piste : positionne le jalon selon l'abscisse du pointeur.
  function stepFromClientX(clientX) {
    const r = scrubTrack.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    return Math.round(ratio * (graph.steps.length - 1));
  }
  let dragging = false;
  scrubTrack.addEventListener("pointerdown", (ev) => {
    dragging = true;
    scrubTrack.classList.add("scrubbing");
    scrubTrack.setPointerCapture(ev.pointerId);
    goTo(stepFromClientX(ev.clientX));
  });
  scrubTrack.addEventListener("pointermove", (ev) => { if (dragging) goTo(stepFromClientX(ev.clientX)); });
  ["pointerup", "pointercancel"].forEach(e => scrubTrack.addEventListener(e, () => { dragging = false; scrubTrack.classList.remove("scrubbing"); }));
  scrubTrack.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { nudge(-1); ev.preventDefault(); }
    else if (ev.key === "ArrowRight") { nudge(+1); ev.preventDefault(); }
  });

  await load(list.sessions[0].session_id);
}
