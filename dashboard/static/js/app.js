import { mountSessions } from "./tabs/sessions.js";
import { mountInfra } from "./tabs/infra.js";
import { mountAgents } from "./tabs/agents.js";
import { mountHealth } from "./tabs/health.js";

const MOUNTERS = { sessions: mountSessions, infra: mountInfra, agents: mountAgents, health: mountHealth };
const mounted = new Set();

function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("is-active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach(p => { p.hidden = p.dataset.tab !== name; });
  const panel = document.querySelector(`.tab-panel[data-tab="${name}"]`);
  if (panel && MOUNTERS[name] && !mounted.has(name)) {
    MOUNTERS[name](panel);
    mounted.add(name);
  }
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

showTab("sessions"); // tab par défaut
