import { api } from "../api.js";
import { renderGraph } from "../graph.js";

export async function mountSessions(panel) {
  const list = await api.sessions();
  const sid = list.sessions[0].session_id;
  const graph = await api.sessionGraph(sid);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  panel.appendChild(svg);
  renderGraph(svg, graph, 0, (n) => console.log("clic node", n.id));
}
