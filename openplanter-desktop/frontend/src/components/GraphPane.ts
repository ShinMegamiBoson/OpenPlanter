/** Graph pane: 3D force graph (three.js). */
import type { GraphData } from "../api/types";

export function createGraphPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "graph-pane";

  // Placeholder — full 3d-force-graph integration in Phase 8
  const placeholder = document.createElement("div");
  placeholder.style.cssText =
    "display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:12px;";
  placeholder.textContent = "Knowledge Graph";
  pane.appendChild(placeholder);

  // Listen for wiki updates
  window.addEventListener("wiki-updated", ((e: CustomEvent<GraphData>) => {
    const data = e.detail;
    placeholder.textContent = `${data.nodes.length} nodes, ${data.edges.length} edges`;
  }) as EventListener);

  return pane;
}
