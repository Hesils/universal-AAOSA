const root = () => document.getElementById("modal-root");

function closeModal() { root().innerHTML = ""; }

// champ texte long : tronqué + toggle "voir tout" inline
function longField(label, value, max = 220) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const head = document.createElement("div");
  head.className = "field-label";
  head.textContent = label;
  const box = document.createElement("div");
  box.className = "field-value";
  const text = value || "";
  if (text.length <= max) {
    box.textContent = text;
  } else {
    box.textContent = text.slice(0, max) + "… ";
    const toggle = document.createElement("span");
    toggle.className = "expand";
    toggle.textContent = `voir tout (${text.length} car.)`;
    let expanded = false;
    toggle.addEventListener("click", () => {
      expanded = !expanded;
      box.textContent = expanded ? text + " " : text.slice(0, max) + "… ";
      toggle.textContent = expanded ? "réduire" : `voir tout (${text.length} car.)`;
      box.appendChild(toggle);
    });
    box.appendChild(toggle);
  }
  wrap.append(head, box);
  return wrap;
}

function field(label, value) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  wrap.innerHTML = `<div class="field-label">${label}</div><div class="field-value">${value}</div>`;
  return wrap;
}

function renderDispatch(d) {
  const f = document.createDocumentFragment();
  const cand = d.candidates.map(c => `${c.agent_id} — fit ${c.fit_score.toFixed(2)} ${c.passed ? "✓" : "✗"}`).join("<br>");
  f.append(field("Candidats (Phase 1)", cand || "—"));
  const claims = d.claims.map(c => `${c.agent_id} — ${c.decision}`).join("<br>");
  f.append(field("Claims (Phase 2)", claims || "—"));
  for (const c of d.claims) if (c.justification) f.append(longField(`Justification — ${c.agent_id}`, c.justification));
  f.append(field("Winner", d.winner_agent_id || "—"));
  if (d.dispatch_reason) f.append(field("Raison dispatch", d.dispatch_reason));
  if (d.unassigned_reason) f.append(field("Raison non-attribution", d.unassigned_reason));
  return f;
}

function renderAgent(agentId, step, runAgents) {
  const a = step.detail.agents[agentId];
  const reg = (runAgents || []).find(x => x.agent_id === agentId); // join B1 : prompt + ELO courant
  const f = document.createDocumentFragment();
  f.append(field("Rôle", a.role + (a.passed ? " · passed" : " · filtré") + ` · fit ${a.fit_score.toFixed(2)}`));
  if (reg) {
    const bars = Object.entries(reg.tags_with_elo).map(([t, e]) => `${t} : ${e}`).join("<br>");
    f.append(field("Tags · ELO courant", bars || "—"));
    f.append(longField("System prompt", reg.system_prompt));
  }
  if (a.claim_decision) f.append(field("Claim", a.claim_decision));
  if (a.justification) f.append(longField("Justification", a.justification));
  if (a.output_content) f.append(longField("Output", a.output_content));
  if (a.llm_metadata) {
    const m = a.llm_metadata;
    f.append(field("Métriques", `latence ${m.latency_ms} ms · in ${m.tokens_in} · out ${m.tokens_out}`));
  }
  const deltas = Object.entries(a.elo_deltas).map(([t, d]) => `${t} ${d >= 0 ? "+" : ""}${d}`).join(" · ");
  if (deltas) f.append(field("ELO deltas (ce run)", deltas));
  if (a.tags_acquired.length) f.append(field("Tags acquis", a.tags_acquired.map(t => `${t.tag} (${t.initial_elo})`).join(" · ")));
  return f;
}

function renderEvaluator(e) {
  const f = document.createDocumentFragment();
  if (!e.ran) { f.append(field("Evaluator", "non exécuté")); return f; }
  f.append(field("Résultat", (e.success ? "succès" : "échec") + (e.score != null ? ` · score ${e.score.toFixed(2)}` : "")));
  const crit = Object.entries(e.criteria_results).map(([k, v]) => `${k} : ${v ? "✓" : "✗"}`).join("<br>");
  if (crit) f.append(field("Critères / gates", crit));
  if (e.judge) f.append(field("Judge", `${e.judge.mode} · ${e.judge.overall != null ? e.judge.overall.toFixed(2) : "—"}`));
  if (e.reason) f.append(longField("Raison", e.reason));
  return f;
}

function renderInput(inp) {
  const f = document.createDocumentFragment();
  f.append(field("Task", inp.task_id));
  f.append(longField("Description", inp.description));
  const tags = Object.entries(inp.required_tags).map(([t, lvl]) => `${t} ≥ ${lvl}`).join(" · ");
  f.append(field("Tags requis", tags || "—"));
  if (inp.context) f.append(longField("Context", inp.context)); // affiché uniquement si non vide
  return f;
}

function renderOutput(o) {
  const f = document.createDocumentFragment();
  if (!o.produced) { f.append(field("Output", "non produit")); return f; }
  if (o.output_summary) f.append(longField("Résumé", o.output_summary));
  if (o.output_content) f.append(longField("Contenu", o.output_content));
  if (o.llm_metadata) {
    const m = o.llm_metadata;
    f.append(field("Métriques", `latence ${m.latency_ms} ms · in ${m.tokens_in} · out ${m.tokens_out}`));
  }
  return f;
}

function renderTestSet(t) {
  const f = document.createDocumentFragment();
  f.append(field("Forké", t.forked ? "oui" : "non"));
  f.append(field("Depuis task", t.from_task_id));
  return f;
}

// node = {id, type, label} ; step = GraphStep courant ; runAgents = agents du run (B1)
export function openNodeModal(node, step, runAgents) {
  if (!step) return;
  let title = node.label, body;
  switch (node.type) {
    case "dispatch": body = renderDispatch(step.detail.dispatch); break;
    case "agent": body = renderAgent(node.id, step, runAgents); title = node.label + (step.winner_agent_id === node.id ? " ★" : ""); break;
    case "evaluator": body = renderEvaluator(step.detail.evaluator); break;
    case "input": body = renderInput(step.detail.input); break;
    case "output": body = renderOutput(step.detail.output); break;
    case "testset": body = renderTestSet(step.detail.testset); break;
    default: return;
  }

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) closeModal(); });

  const card = document.createElement("div");
  card.className = "modal-card";
  const head = document.createElement("div");
  head.className = "modal-head";
  head.innerHTML = `<span class="modal-title">${title}</span><span class="modal-close">×</span>`;
  head.querySelector(".modal-close").addEventListener("click", closeModal);
  const content = document.createElement("div");
  content.className = "modal-body";
  content.appendChild(body);

  card.append(head, content);
  overlay.appendChild(card);
  root().innerHTML = "";
  root().appendChild(overlay);
}
