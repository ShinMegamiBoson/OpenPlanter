/** Graph pane: 3D force graph (three.js). */
import type { GraphData } from "../api/types";
import { getGraphData } from "../api/invoke";
import { initGraph, updateGraph } from "../graph/force";

export function createGraphPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "graph-pane";

  // Load graph data on mount
  setTimeout(async () => {
    try {
      const data = await getGraphData();
      if (data.nodes.length > 0) {
        initGraph(pane, data);
      } else {
        showPlaceholder(pane, "Knowledge Graph — no wiki data");
      }
    } catch (e) {
      console.error("Failed to load graph data:", e);
      showPlaceholder(pane, "Knowledge Graph");
    }
  }, 100);

  // Listen for wiki updates
  window.addEventListener("wiki-updated", ((e: CustomEvent<GraphData>) => {
    const data = e.detail;
    if (data.nodes.length > 0) {
      // Remove placeholder if present
      const placeholder = pane.querySelector(".graph-placeholder");
      if (placeholder) placeholder.remove();
      initGraph(pane, data);
    } else {
      updateGraph(data);
    }
  }) as EventListener);

  return pane;
}

function showPlaceholder(pane: HTMLElement, text: string): void {
  const placeholder = document.createElement("div");
  placeholder.className = "graph-placeholder";
  placeholder.style.cssText =
    "display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:12px;";
  placeholder.textContent = text;
  pane.appendChild(placeholder);
}
