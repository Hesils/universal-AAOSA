import { mountSessions } from "./tabs/sessions.js";
import { mountInfra } from "./tabs/infra.js";
import { mountAgents } from "./tabs/agents.js";
import { mountHealth } from "./tabs/health.js";

// Champ de scales (lattice de diamants) + onde diagonale. L'onde balaie haut-gauche →
// bas-droite via un delay par cellule = (col+row)/maxd * période, décalé pour démarrer en plein loop.
function buildScales() {
  const field = document.getElementById("scales");
  if (!field) return;
  field.replaceChildren();
  const cell = 56;
  const cols = Math.ceil((window.innerWidth + 80) / cell);
  const rows = Math.ceil((window.innerHeight + 80) / cell);
  field.style.gridTemplateColumns = `repeat(${cols}, ${cell}px)`;
  field.style.gridTemplateRows = `repeat(${rows}, ${cell}px)`;
  const maxd = cols + rows;
  const frag = document.createDocumentFragment();
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const d = document.createElement("div");
    d.className = "scale";
    d.style.setProperty("--d", (((c + r) / maxd) * 4.6 - 4.6).toFixed(2) + "s");
    frag.appendChild(d);
  }
  field.appendChild(frag);
}

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

buildScales();
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(buildScales, 200);
});

showTab("sessions"); // tab par défaut
