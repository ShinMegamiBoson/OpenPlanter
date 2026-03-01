/** Graph pane: 2D investigative graph (Cytoscape.js). */
import type { GraphData } from "../api/types";
import { getGraphData } from "../api/invoke";
import {
  initGraph,
  updateGraph,
  destroyGraph,
  fitView,
  focusNode,
  setLayout,
  getCurrentLayout,
  filterByCategory,
  searchNodes,
  fitSearchMatches,
  clearSearchHighlights,
  getCategories,
} from "../graph/cytoGraph";
import { bindInteractions } from "../graph/interaction";
import { getCategoryColor } from "../graph/colors";

export function createGraphPane(): HTMLElement {
  const pane = document.createElement("div");
  pane.className = "graph-pane";

  // --- Toolbar ---
  const toolbar = document.createElement("div");
  toolbar.className = "graph-toolbar";

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.className = "graph-search";
  searchInput.placeholder = "Search nodes...";

  const layoutSelect = document.createElement("select");
  layoutSelect.className = "graph-layout-select";
  const layouts = [
    { value: "fcose", label: "Force" },
    { value: "concentric", label: "Grouped" },
    { value: "dagre", label: "Hierarchical" },
    { value: "circle", label: "Circle" },
  ];
  for (const l of layouts) {
    const opt = document.createElement("option");
    opt.value = l.value;
    opt.textContent = l.label;
    layoutSelect.appendChild(opt);
  }

  const fitBtn = document.createElement("button");
  fitBtn.className = "graph-fit-btn";
  fitBtn.textContent = "\u229e"; // ⊞
  fitBtn.title = "Fit to view";

  toolbar.append(searchInput, layoutSelect, fitBtn);

  // --- Graph container ---
  const graphContainer = document.createElement("div");
  graphContainer.className = "graph-canvas";

  // --- Legend ---
  const legend = document.createElement("div");
  legend.className = "graph-legend";

  // --- Detail overlay ---
  const detail = document.createElement("div");
  detail.className = "graph-detail";
  detail.style.display = "none";

  pane.append(toolbar, graphContainer, legend, detail);

  // State
  const hiddenCategories = new Set<string>();

  // --- Search handler ---
  searchInput.addEventListener("input", () => {
    searchNodes(searchInput.value);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const matches = searchNodes(searchInput.value);
      if (matches.length > 0) fitSearchMatches();
    }
    if (e.key === "Escape") {
      searchInput.value = "";
      clearSearchHighlights();
      searchInput.blur();
    }
  });

  // --- Layout handler ---
  layoutSelect.addEventListener("change", () => {
    setLayout(layoutSelect.value);
  });

  // --- Fit handler ---
  fitBtn.addEventListener("click", () => {
    fitView();
  });

  // --- Build legend from categories ---
  function buildLegend(categories: string[]): void {
    legend.innerHTML = "";
    for (const cat of categories) {
      const item = document.createElement("span");
      item.className = "graph-legend-item";
      if (hiddenCategories.has(cat)) item.classList.add("legend-hidden");

      const dot = document.createElement("span");
      dot.className = "graph-legend-dot";
      dot.style.backgroundColor = getCategoryColor(cat);

      const label = document.createElement("span");
      label.className = "graph-legend-label";
      label.textContent = cat;

      item.append(dot, label);
      item.addEventListener("click", () => {
        if (hiddenCategories.has(cat)) {
          hiddenCategories.delete(cat);
          item.classList.remove("legend-hidden");
        } else {
          hiddenCategories.add(cat);
          item.classList.add("legend-hidden");
        }
        filterByCategory(hiddenCategories);
      });
      legend.appendChild(item);
    }
  }

  // --- Detail overlay ---
  function showDetail(data: {
    id: string;
    label: string;
    category: string;
    path: string;
    connectedNodes: { id: string; label: string }[];
  }): void {
    detail.style.display = "block";
    detail.innerHTML = "";

    const header = document.createElement("div");
    header.className = "graph-detail-header";

    const title = document.createElement("span");
    title.className = "graph-detail-title";
    title.textContent = data.label;

    const closeBtn = document.createElement("button");
    closeBtn.className = "graph-detail-close";
    closeBtn.textContent = "\u00d7"; // ×
    closeBtn.addEventListener("click", () => hideDetail());

    header.append(title, closeBtn);

    const meta = document.createElement("div");
    meta.className = "graph-detail-meta";

    const catBadge = document.createElement("span");
    catBadge.className = "graph-detail-badge";
    catBadge.style.borderColor = getCategoryColor(data.category);
    catBadge.textContent = data.category;

    const pathEl = document.createElement("span");
    pathEl.className = "graph-detail-path";
    pathEl.textContent = data.path;

    meta.append(catBadge, pathEl);

    detail.append(header, meta);

    if (data.connectedNodes.length > 0) {
      const connLabel = document.createElement("div");
      connLabel.className = "graph-detail-conn-label";
      connLabel.textContent = `Connected (${data.connectedNodes.length})`;
      detail.appendChild(connLabel);

      const connList = document.createElement("div");
      connList.className = "graph-detail-conn-list";
      for (const conn of data.connectedNodes) {
        const connItem = document.createElement("a");
        connItem.className = "graph-detail-conn-item";
        connItem.textContent = conn.label;
        connItem.href = "#";
        connItem.addEventListener("click", (e) => {
          e.preventDefault();
          focusNode(conn.id);
        });
        connList.appendChild(connItem);
      }
      detail.appendChild(connList);
    }
  }

  function hideDetail(): void {
    detail.style.display = "none";
  }

  // --- Initialize graph ---
  let interactionsBound = false;

  function initializeWithData(data: GraphData): void {
    // Remove placeholder if present
    const placeholder = pane.querySelector(".graph-placeholder");
    if (placeholder) placeholder.remove();

    initGraph(graphContainer, data);

    // Sync dropdown to actual layout (may differ from default if no edges)
    layoutSelect.value = getCurrentLayout();

    if (!interactionsBound) {
      bindInteractions({
        onNodeSelect: (nodeData) => showDetail(nodeData),
        onNodeDeselect: () => hideDetail(),
      });
      interactionsBound = true;
    }

    buildLegend(getCategories());
  }

  // Load graph data on mount
  setTimeout(async () => {
    try {
      const data = await getGraphData();
      if (data.nodes.length > 0) {
        initializeWithData(data);
      } else {
        showPlaceholder(pane, "Knowledge Graph \u2014 no wiki data");
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
      initializeWithData(data);
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
