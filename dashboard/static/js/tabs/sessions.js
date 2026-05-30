import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";

export async function mountSessions(panel) {
  const list = await api.sessions();
  const sid = list.sessions[0].session_id;
  const [detail, graph] = await Promise.all([api.session(sid), api.sessionGraph(sid)]);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  panel.appendChild(svg);
  renderGraph(svg, graph, 0, (node, step) => openNodeModal(node, step, detail.agents));
}
