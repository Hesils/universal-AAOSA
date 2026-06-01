import { api } from "../api.js";
import { lineChart, barChart } from "../charts.js";

function card(label, value) {
  return `<div class="card"><div class="card-value">${value}</div><div class="card-label">${label}</div></div>`;
}

export async function mountInfra(panel) {
  const s = await api.infra();
  const pct = s.qa_pass_rate == null ? "—" : `${Math.round(s.qa_pass_rate * 100)}%`;
  const lat = s.latency.mean_ms == null ? "—" : `${Math.round(s.latency.mean_ms)} ms`;

  panel.innerHTML = `
    <div class="cards">
      ${card("Sessions", s.session_count)}
      ${card("Runs", s.run_count)}
      ${card("Agents", s.agent_count)}
      ${card("Tasks", s.task_count)}
      ${card("QA pass", pct)}
      ${card("Tokens in", s.total_tokens_in)}
      ${card("Tokens out", s.total_tokens_out)}
      ${card("Latence moy.", lat)}
    </div>
    <div class="charts">
      <figure><figcaption>QA pass rate dans le temps</figcaption><svg data-c="passrate"></svg></figure>
      <figure><figcaption>Runs par session</figcaption><svg data-c="runs"></svg></figure>
      <figure><figcaption>Tokens in / out par session</figcaption><svg data-c="tokens"></svg></figure>
      <figure><figcaption>Latence moyenne par session</figcaption><svg data-c="latency"></svg></figure>
    </div>`;

  const svg = c => panel.querySelector(`svg[data-c="${c}"]`);

  lineChart(svg("passrate"), [{
    name: "pass rate",
    points: s.pass_rate_over_time.map((p, i) => ({ x: i, y: p.pass_rate })),
  }]);

  barChart(svg("runs"), s.per_session.map((p, i) => ({ label: `#${i + 1}`, value: p.run_count })));

  lineChart(svg("tokens"), [
    { name: "in", points: s.per_session.map((p, i) => ({ x: i, y: p.tokens_in })) },
    { name: "out", points: s.per_session.map((p, i) => ({ x: i, y: p.tokens_out })) },
  ]);

  lineChart(svg("latency"), [{
    name: "latency",
    points: s.per_session
      .map((p, i) => ({ x: i, y: p.latency_mean }))
      .filter(pt => pt.y != null),
  }]);
}
