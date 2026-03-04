/** Graph pane: 2D investigative graph (Cytoscape.js). */
import type { GraphData } from "../api/types";
import { getGraphData, readWikiFile } from "../api/invoke";
import {
  initGraph,
  updateGraph,
  destroyGraph,
  fitView,
  focusNode,
  setLayout,
  getCurrentLayout,
  filterByCategory,
  filterByTier,
  filterBySearch,
  filterBySession,
  fitSearchMatches,
  getCategories,
  getNodeIds,
} from "../graph/cytoGraph";
import { bindInteractions } from "../graph/interaction";
import { getCategoryColor } from "../graph/colors";
import MarkdownIt from "markdown-it";
import hljs from "highlight.js";

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
  highlight(str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(str, { language: lang }).value; } catch { /* fallback */ }
    }
    return "";
  },
});

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

  const tierSelect = document.createElement("select");
  tierSelect.className = "graph-tier-select";
  const tiers = [
    { value: "all", label: "All tiers" },
    { value: "sources-sections", label: "Sources + Sections" },
    { value: "sources", label: "Sources only" },
  ];
  for (const t of tiers) {
    const opt = document.createElement("option");
    opt.value = t.value;
    opt.textContent = t.label;
    tierSelect.appendChild(opt);
  }

  const sessionToggle = document.createElement("button");
  sessionToggle.className = "graph-session-toggle";
  sessionToggle.textContent = "\u2726"; // ✦
  sessionToggle.title = "Show only new nodes from this session";
  sessionToggle.classList.add("active");

  const sessionHint = document.createElement("span");
  sessionHint.className = "graph-session-hint";

  const refreshBtn = document.createElement("button");
  refreshBtn.className = "graph-refresh-btn";
  refreshBtn.textContent = "\u21bb"; // ↻
  refreshBtn.title = "Refresh graph data";

  const fitBtn = document.createElement("button");
  fitBtn.className = "graph-fit-btn";
  fitBtn.textContent = "\u229e"; // ⊞
  fitBtn.title = "Fit to view";

  toolbar.append(searchInput, layoutSelect, tierSelect, sessionToggle, sessionHint, refreshBtn, fitBtn);

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

  // --- Source drawer (slide-out panel for wiki markdown) ---
  const drawerBackdrop = document.createElement("div");
  drawerBackdrop.className = "graph-source-drawer-backdrop";

  const drawer = document.createElement("div");
  drawer.className = "graph-source-drawer";

  const drawerHeader = document.createElement("div");
  drawerHeader.className = "graph-source-drawer-header";

  const drawerTitle = document.createElement("span");
  drawerTitle.className = "graph-source-drawer-title";

  const drawerCloseBtn = document.createElement("button");
  drawerCloseBtn.className = "graph-detail-close";
  drawerCloseBtn.textContent = "\u00d7";
  drawerCloseBtn.addEventListener("click", () => hideDrawer());

  drawerHeader.append(drawerTitle, drawerCloseBtn);

  const drawerBody = document.createElement("div");
  drawerBody.className = "graph-source-drawer-body rendered";

  drawer.append(drawerHeader, drawerBody);
  drawerBackdrop.addEventListener("click", () => hideDrawer());

  pane.append(toolbar, graphContainer, legend, detail, drawerBackdrop, drawer);

  // State
  const hiddenCategories = new Set<string>();
  let baselineNodeIds = new Set<string>();
  let baselineCaptured = false;
  let sessionFilterActive = true;

  // --- Search handler (200ms debounce) ---
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  searchInput.addEventListener("input", () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      filterBySearch(searchInput.value);
    }, 200);
  });
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (searchTimer) clearTimeout(searchTimer);
      const matches = filterBySearch(searchInput.value);
      if (matches.length > 0) fitSearchMatches();
    }
    if (e.key === "Escape") {
      if (searchTimer) clearTimeout(searchTimer);
      searchInput.value = "";
      filterBySearch("");
      searchInput.blur();
    }
  });

  // --- Layout handler ---
  layoutSelect.addEventListener("change", () => {
    setLayout(layoutSelect.value);
  });

  // --- Tier filter handler ---
  tierSelect.addEventListener("change", () => {
    filterByTier(tierSelect.value as "all" | "sources-sections" | "sources");
  });

  // --- Session toggle handler ---
  let hintTimer: ReturnType<typeof setTimeout> | null = null;
  function showHint(text: string): void {
    if (hintTimer) clearTimeout(hintTimer);
    sessionHint.textContent = text;
    sessionHint.classList.add("visible");
    hintTimer = setTimeout(() => {
      sessionHint.classList.remove("visible");
    }, 3000);
  }

  sessionToggle.addEventListener("click", () => {
    sessionFilterActive = !sessionFilterActive;
    if (sessionFilterActive) {
      sessionToggle.classList.add("active");
    } else {
      sessionToggle.classList.remove("active");
    }
    const newCount = filterBySession(sessionFilterActive, baselineNodeIds);

    if (sessionFilterActive) {
      showHint(newCount === 0 ? "0 new" : `${newCount} new`);
    } else {
      sessionHint.classList.remove("visible");
    }
  });

  // --- Auto-refresh helper (used by button, agent-step, etc.) ---
  async function autoRefreshGraph() {
    try {
      const data = await getGraphData();
      if (data.nodes.length > 0) {
        updateGraph(data);
        buildLegend(getCategories());
        if (sessionFilterActive) {
          filterBySession(true, baselineNodeIds);
        }
      }
    } catch {
      // Silently ignore — graph refresh is best-effort
    }
  }

  // --- Refresh handler ---
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.classList.add("spinning");
    try {
      await autoRefreshGraph();
    } catch (e) {
      console.error("Failed to refresh graph data:", e);
    } finally {
      refreshBtn.classList.remove("spinning");
    }
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

  // --- Drawer open/close ---
  function openDrawer(label: string, path: string): void {
    drawerTitle.textContent = label;
    drawerBody.innerHTML = '<span style="color:var(--text-muted)">Loading...</span>';
    drawerBackdrop.classList.add("visible");
    drawer.classList.add("visible");

    readWikiFile(path).then((content) => {
      drawerBody.innerHTML = md.render(content);
      interceptDrawerLinks();
    }).catch((err) => {
      drawerBody.innerHTML = `<span style="color:var(--error)">Failed to load: ${err}</span>`;
    });
  }

  function hideDrawer(): void {
    drawerBackdrop.classList.remove("visible");
    drawer.classList.remove("visible");
  }

  /** Intercept internal wiki links in the drawer to load them in-place. */
  function interceptDrawerLinks(): void {
    drawerBody.querySelectorAll("a").forEach((link) => {
      const href = link.getAttribute("href");
      if (!href || !href.endsWith(".md")) return;
      // Skip external links
      if (href.startsWith("http://") || href.startsWith("https://")) return;

      link.addEventListener("click", (e) => {
        e.preventDefault();
        // Resolve relative path: if drawer is showing wiki/fec.md and link is sec.md → wiki/sec.md
        const currentDir = drawerTitle.textContent?.includes("/")
          ? (drawerTitle.textContent || "").substring(0, (drawerTitle.textContent || "").lastIndexOf("/") + 1)
          : "wiki/";
        const resolvedPath = href.startsWith("wiki/") ? href : `wiki/${href}`;
        const nodeId = href.replace(/\.md$/, "").replace(/^.*\//, "");
        openDrawer(nodeId, resolvedPath);
        focusNode(nodeId);
      });
    });
  }

  // --- Detail overlay ---
  function showDetail(data: {
    id: string;
    label: string;
    category: string;
    path: string;
    node_type?: string;
    parent_id?: string;
    content?: string;
    connectedNodes: { id: string; label: string }[];
  }): void {
    // Source nodes: open the full-width drawer instead
    if (data.node_type === "source") {
      hideDetail();
      openDrawer(data.label, data.path);
      return;
    }

    // Non-source nodes: show the compact detail overlay
    hideDrawer();
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

    // Node type badge
    if (data.node_type) {
      const typeBadge = document.createElement("span");
      typeBadge.className = `graph-detail-type graph-detail-type-${data.node_type}`;
      typeBadge.textContent = data.node_type;
      meta.appendChild(typeBadge);
    }

    const catBadge = document.createElement("span");
    catBadge.className = "graph-detail-badge";
    catBadge.style.borderColor = getCategoryColor(data.category);
    catBadge.textContent = data.category;

    const pathEl = document.createElement("span");
    pathEl.className = "graph-detail-path";
    pathEl.textContent = data.path;

    meta.append(catBadge, pathEl);

    detail.append(header, meta);

    // Content block for section/fact nodes
    if (data.content) {
      const contentBlock = document.createElement("div");
      contentBlock.className = "graph-detail-content";
      contentBlock.textContent = data.content;
      detail.appendChild(contentBlock);
    }

    // "View source" button — opens the parent source document in the drawer
    const viewSourceBtn = document.createElement("button");
    viewSourceBtn.className = "graph-detail-view-source";
    viewSourceBtn.textContent = "View source";
    viewSourceBtn.addEventListener("click", () => {
      hideDetail();
      // path is the wiki file path (e.g. wiki/fec.md)
      const sourceLabel = data.path.replace(/^wiki\//, "").replace(/\.md$/, "");
      openDrawer(sourceLabel, data.path);
    });
    detail.appendChild(viewSourceBtn);

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
        onNodeDeselect: () => { hideDetail(); hideDrawer(); },
      });
      interactionsBound = true;
    }

    // Capture baseline node IDs on first load
    if (!baselineCaptured) {
      baselineNodeIds = getNodeIds();
      baselineCaptured = true;
    }

    // Apply session filter if active (e.g. auto-activated for new sessions)
    if (sessionFilterActive) {
      filterBySession(true, baselineNodeIds);
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
      // Re-apply session filter if active
      if (sessionFilterActive) {
        filterBySession(true, baselineNodeIds);
      }
    } else {
      updateGraph(data);
    }
  }) as EventListener);

  // Auto-refresh graph after each agent step (tool calls may write wiki files)
  window.addEventListener("agent-step", () => {
    autoRefreshGraph();
  });

  // Auto-refresh graph when background curator updates wiki files
  window.addEventListener("curator-done", () => {
    autoRefreshGraph();
  });

  // Listen for session changes — reset baseline
  window.addEventListener("session-changed", ((e: CustomEvent<{ isNew: boolean }>) => {
    const isNew = e.detail?.isNew ?? false;
    baselineNodeIds = new Set<string>();
    baselineCaptured = false;

    if (isNew) {
      sessionFilterActive = true;
      sessionToggle.classList.add("active");
    } else {
      sessionFilterActive = false;
      sessionToggle.classList.remove("active");
    }

    // Re-fetch graph for new session
    getGraphData().then((data) => {
      if (data.nodes.length > 0) {
        initializeWithData(data);
      }
    }).catch((e) => {
      console.error("Failed to load graph data on session change:", e);
    });
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
