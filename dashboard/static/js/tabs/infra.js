import { api } from "../api.js";
import { lineChart, barChart } from "../charts.js";

function stat(label, value, accent = false) {
  return `<div class="stat${accent ? " stat--accent" : ""}"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`;
}

export async function mountInfra(panel) {
  const s = await api.infra();
  const qa = s.qa_pass_rate == null ? "—" : `${Math.round(s.qa_pass_rate * 100)}<small>%</small>`;
  const lat = s.latency.mean_ms == null ? "—" : `${Math.round(s.latency.mean_ms)}<small>ms</small>`;

  panel.innerHTML = `
    <h2 class="sec">Infra</h2>
    <div class="strip">
      ${stat("Sessions", s.session_count)}
      ${stat("Runs", s.run_count)}
      ${stat("Agents", s.agent_count)}
      ${stat("Tasks", s.task_count)}
      ${stat("QA pass", qa, true)}
      ${stat("Tokens in", s.total_tokens_in)}
      ${stat("Tokens out", s.total_tokens_out)}
      ${stat("Latence moy.", lat)}
    </div>
    <div class="charts">
      <figure class="panel chart-card"><figcaption>qa_pass_rate / time</figcaption><svg class="chart" data-c="passrate"></svg></figure>
      <figure class="panel chart-card"><figcaption>runs / session</figcaption><svg class="chart" data-c="runs"></svg></figure>
      <figure class="panel chart-card"><figcaption>tokens / session</figcaption>
        <div class="chart-legend">
          <span class="legend"><i style="background:var(--fire)"></i>in</span>
          <span class="legend"><i style="background:var(--cool)"></i>out</span>
        </div>
        <svg class="chart" data-c="tokens"></svg></figure>
      <figure class="panel chart-card"><figcaption>latency / session</figcaption><svg class="chart" data-c="latency"></svg></figure>
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
