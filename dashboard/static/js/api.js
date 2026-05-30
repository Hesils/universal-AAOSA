async function get(path) {
  const r = await fetch(path);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `${r.status} ${path}`);
  }
  return r.json();
}

export const api = {
  infra: () => get("/api/infra"),
  agents: () => get("/api/agents"),
  agent: (id) => get(`/api/agents/${encodeURIComponent(id)}`),
  sessions: () => get("/api/sessions"),
  session: (id) => get(`/api/sessions/${encodeURIComponent(id)}`),
  sessionGraph: (id) => get(`/api/sessions/${encodeURIComponent(id)}/graph`),
  healthChecks: () => get("/api/health-checks"),
  healthCheck: (id) => get(`/api/health-checks/${encodeURIComponent(id)}`),
  healthCheckGraph: (id, taskId) =>
    get(`/api/health-checks/${encodeURIComponent(id)}/graph` + (taskId ? `?task_id=${encodeURIComponent(taskId)}` : "")),
};
