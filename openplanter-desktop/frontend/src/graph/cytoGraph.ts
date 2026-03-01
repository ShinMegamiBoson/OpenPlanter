/** Cytoscape.js 2D graph wrapper for investigative analysis. */
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import fcose from "cytoscape-fcose";
import dagre from "cytoscape-dagre";
import { getCategoryColor, CATEGORY_COLORS } from "./colors";
import type { GraphData, NodeType } from "../api/types";

cytoscape.use(fcose);
cytoscape.use(dagre);

let cy: Core | null = null;
let resizeObserver: ResizeObserver | null = null;

/** Cytoscape stylesheet — tier-based shapes and edge type styling. */
const graphStyle: cytoscape.StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "background-color": "data(color)",
      "background-opacity": 0.85,
      "border-width": 1,
      "border-color": "data(color)",
      "border-opacity": 0.5,
      color: "#ffffff",
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 4,
      "font-size": "data(fontSize)",
      "font-family": "JetBrains Mono, Fira Code, SF Mono, Menlo, monospace",
      shape: "ellipse",
      width: "data(size)",
      height: "data(size)",
      "text-wrap": "ellipsis",
      "text-max-width": "100px",
      "min-zoomed-font-size": 4,
      "text-outline-color": "#0d1117",
      "text-outline-width": 1.5,
      "text-outline-opacity": 0.8,
    },
  },
  // Tier-based shapes
  {
    selector: "node[node_type='section']",
    style: {
      shape: "diamond",
    },
  },
  {
    selector: "node[node_type='fact']",
    style: {
      shape: "round-rectangle",
    },
  },
  {
    selector: "node:selected",
    style: {
      "border-width": 3,
      "border-color": "#ffffff",
      "border-opacity": 1,
      "background-opacity": 1,
    },
  },
  {
    selector: "node.highlighted",
    style: {
      "border-width": 2,
      "border-color": "#ffffff",
      "border-opacity": 0.8,
      "background-opacity": 1,
    },
  },
  {
    selector: "node.search-match",
    style: {
      "border-width": 3,
      "border-color": "#f0e68c",
      "border-opacity": 1,
      "background-opacity": 1,
    },
  },
  {
    selector: "node.dimmed",
    style: {
      opacity: 0.15,
      "text-opacity": 0,
    },
  },
  // Default edge styling
  {
    selector: "edge",
    style: {
      width: 1,
      "line-color": "data(color)",
      "target-arrow-shape": "none",
      "curve-style": "bezier",
      opacity: 0.25,
    },
  },
  // Structural edges (has-section, contains) — subtle dotted
  {
    selector: "edge[label='has-section'], edge[label='contains']",
    style: {
      "line-style": "dotted",
      opacity: 0.12,
      width: 0.5,
    },
  },
  // Cross-reference edges — blue with arrow
  {
    selector: "edge[label='cross-ref']",
    style: {
      "line-color": "#58a6ff",
      "target-arrow-color": "#58a6ff",
      "target-arrow-shape": "triangle",
      opacity: 0.5,
      width: 1.5,
    },
  },
  // Shared-field edges — purple dashed
  {
    selector: "edge[label='shared-field']",
    style: {
      "line-color": "#d2a8ff",
      "line-style": "dashed",
      opacity: 0.4,
      width: 1,
    },
  },
  {
    selector: "edge.highlighted",
    style: {
      "line-color": "#58a6ff",
      width: 2,
      opacity: 0.8,
    },
  },
  {
    selector: "edge.dimmed",
    style: {
      opacity: 0.05,
    },
  },
  {
    selector: "node.hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "edge.hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "node.tier-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "edge.tier-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "node.filter-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "edge.filter-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "node.session-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "edge.session-hidden",
    style: {
      display: "none",
    },
  },
  {
    selector: "node.new-node",
    style: {
      "border-width": 3,
      "border-color": "#3fb950",
      "border-opacity": 1,
      "background-opacity": 1,
    },
  },
] as any;

/** Tier-based sizing parameters. */
function tierSizing(nodeType: NodeType | undefined, deg: number): { size: number; fontSize: string } {
  switch (nodeType) {
    case "section":
      return { size: 14 + Math.sqrt(deg) * 3, fontSize: "7px" };
    case "fact":
      return { size: 8 + Math.sqrt(deg) * 2, fontSize: "5px" };
    case "source":
    default:
      return { size: 35 + Math.sqrt(deg) * 6, fontSize: "10px" };
  }
}

/** Convert GraphData to Cytoscape element definitions with tier-based sizing. */
function toCytoElements(data: GraphData): cytoscape.ElementDefinition[] {
  // Count degree (connections) for each node
  const degree = new Map<string, number>();
  for (const n of data.nodes) degree.set(n.id, 0);
  for (const e of data.edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }

  // Build a node category map for edge coloring
  const nodeCategory = new Map<string, string>();
  for (const n of data.nodes) nodeCategory.set(n.id, n.category);

  const nodes: cytoscape.ElementDefinition[] = data.nodes.map((n) => {
    const deg = degree.get(n.id) ?? 0;
    const { size, fontSize } = tierSizing(n.node_type, deg);
    return {
      data: {
        id: n.id,
        label: n.label,
        category: n.category,
        path: n.path,
        node_type: n.node_type ?? "source",
        parent_id: n.parent_id ?? undefined,
        content: n.content ?? undefined,
        color: getCategoryColor(n.category),
        size,
        fontSize,
      },
    };
  });

  const edges: cytoscape.ElementDefinition[] = data.edges.map((e, i) => ({
    data: {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      label: e.label ?? undefined,
      color: getCategoryColor(nodeCategory.get(e.source) ?? ""),
    },
  }));

  return [...nodes, ...edges];
}

/** Layout options by name. */
function getLayoutOptions(name: string): cytoscape.LayoutOptions {
  switch (name) {
    case "dagre":
      return {
        name: "dagre",
        rankDir: "TB",
        nodeSep: 50,
        rankSep: 80,
        animate: true,
        animationDuration: 300,
      } as any;
    case "circle":
      return {
        name: "circle",
        animate: true,
        animationDuration: 300,
        avoidOverlap: true,
      };
    case "concentric":
      return {
        name: "concentric",
        animate: true,
        animationDuration: 300,
        avoidOverlap: true,
        minNodeSpacing: 30,
        concentric: (node: any) => {
          // Group by category — same category gets same level
          const cats = Array.from(new Set(
            cy?.nodes().map((n) => n.data("category") as string) ?? []
          )).sort();
          return cats.length - cats.indexOf(node.data("category"));
        },
        levelWidth: () => 1,
      } as any;
    case "fcose":
    default:
      return {
        name: "fcose",
        animate: true,
        animationDuration: 500,
        randomize: true,
        quality: "proof",
        nodeSeparation: 100,
        idealEdgeLength: 200,
        nodeRepulsion: () => 25000,
        edgeElasticity: () => 0.45,
        gravity: 0.15,
        gravityRange: 3.8,
        numIter: 2500,
      } as any;
  }
}

let currentLayout = "fcose";

/** Pick the best default layout based on graph structure. */
function pickDefaultLayout(data: GraphData): string {
  if (data.edges.length === 0) {
    // No edges — force-directed is meaningless, group by category
    return "concentric";
  }
  return "fcose";
}

/** Initialize the Cytoscape graph in the given container. */
export function initGraph(container: HTMLElement, data: GraphData): void {
  if (cy) {
    updateGraph(data);
    return;
  }

  const defaultLayout = pickDefaultLayout(data);
  currentLayout = defaultLayout;

  cy = cytoscape({
    container,
    elements: toCytoElements(data),
    style: graphStyle,
    layout: getLayoutOptions(defaultLayout),
    minZoom: 0.1,
    maxZoom: 5,
    wheelSensitivity: 0.3,
  });

  resizeObserver = new ResizeObserver(() => {
    if (cy) cy.resize();
  });
  resizeObserver.observe(container);
}

/** Diff-update graph elements. */
export function updateGraph(data: GraphData): void {
  if (!cy) return;

  cy.elements().remove();
  cy.add(toCytoElements(data));
  cy.layout(getLayoutOptions(currentLayout)).run();
}

/** Destroy the Cytoscape instance and clean up. */
export function destroyGraph(): void {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (cy) {
    cy.destroy();
    cy = null;
  }
}

/** Zoom to fit all visible nodes. */
export function fitView(): void {
  if (!cy) return;
  cy.animate({
    fit: { eles: cy.elements(":visible"), padding: 40 },
    duration: 300,
  });
}

/** Zoom to a specific node and highlight its neighborhood. */
export function focusNode(id: string): void {
  if (!cy) return;
  const node = cy.getElementById(id);
  if (node.empty()) return;

  clearHighlights();
  node.select();
  highlightNeighborhood(node);

  // Emit tap so the interaction handler updates the detail overlay
  node.emit("tap");

  cy.animate({
    center: { eles: node },
    zoom: 2,
    duration: 300,
  });
}

/** Get current layout name (for syncing UI). */
export function getCurrentLayout(): string {
  return currentLayout;
}

/** Switch layout algorithm. */
export function setLayout(name: string): void {
  if (!cy) return;
  currentLayout = name;
  cy.layout(getLayoutOptions(name)).run();
}

/** Hidden class names used by all filter systems. */
const HIDDEN_CLASSES = ["hidden", "tier-hidden", "filter-hidden", "session-hidden"] as const;

/** Sync edge visibility — an edge inherits a hidden class if either endpoint has it. */
function syncEdgeVisibility(): void {
  if (!cy) return;
  cy.edges().forEach((edge) => {
    for (const cls of HIDDEN_CLASSES) {
      if (edge.source().hasClass(cls) || edge.target().hasClass(cls)) {
        edge.addClass(cls);
      } else {
        edge.removeClass(cls);
      }
    }
  });
}

/** Show/hide nodes by category. */
export function filterByCategory(
  hiddenCategories: Set<string>
): void {
  if (!cy) return;

  cy.nodes().forEach((node) => {
    const cat = node.data("category") as string;
    if (hiddenCategories.has(cat)) {
      node.addClass("hidden");
    } else {
      node.removeClass("hidden");
    }
  });
  syncEdgeVisibility();
}

/** Zoom to fit search matches. */
export function fitSearchMatches(): void {
  if (!cy) return;
  const matches = cy.nodes(".search-match");
  if (matches.empty()) return;

  cy.animate({
    fit: { eles: matches, padding: 60 },
    duration: 300,
  });
}

/** Highlight a node's direct neighborhood. */
export function highlightNeighborhood(node: NodeSingular): void {
  if (!cy) return;

  const neighborhood = node.neighborhood().add(node);
  cy.elements().not(neighborhood).addClass("dimmed");
  neighborhood.edges().addClass("highlighted");
  neighborhood.nodes().addClass("highlighted");
  node.removeClass("highlighted"); // selected style takes priority
}

/** Clear all highlights and dimming. */
export function clearHighlights(): void {
  if (!cy) return;
  cy.elements().removeClass("dimmed highlighted");
  cy.nodes().unselect();
}

/** Get the Cytoscape core instance (for interaction handlers). */
export function getCy(): Core | null {
  return cy;
}

/** Get all categories present in the current graph. */
export function getCategories(): string[] {
  if (!cy) return [];
  const cats = new Set<string>();
  cy.nodes().forEach((node) => {
    const cat = node.data("category") as string;
    if (cat) cats.add(cat);
  });
  return Array.from(cats).sort();
}

/** Filter visible nodes by tier level.
 * "all" = show everything
 * "sources-sections" = hide facts
 * "sources" = show only source nodes
 */
export function filterByTier(tier: "all" | "sources-sections" | "sources"): void {
  if (!cy) return;

  cy.nodes().forEach((node) => {
    const nt = node.data("node_type") as string;
    let visible = true;

    if (tier === "sources") {
      visible = nt === "source" || !nt;
    } else if (tier === "sources-sections") {
      visible = nt !== "fact";
    }

    if (visible) {
      node.removeClass("tier-hidden");
    } else {
      node.addClass("tier-hidden");
    }
  });

  syncEdgeVisibility();
}

/** Filter graph by search query. Hides non-matching nodes (+ their non-neighbor nodes).
 * Returns matching node IDs. Empty query clears the filter. */
export function filterBySearch(query: string): string[] {
  if (!cy) return [];

  // Clear previous search state
  cy.nodes().removeClass("search-match filter-hidden");

  const trimmed = query.trim().toLowerCase();
  if (!trimmed) {
    syncEdgeVisibility();
    return [];
  }

  // Find matches: label, category, or content (case-insensitive substring)
  const matchIds: string[] = [];
  cy.nodes().forEach((node) => {
    const label = ((node.data("label") as string) || "").toLowerCase();
    const category = ((node.data("category") as string) || "").toLowerCase();
    const content = ((node.data("content") as string) || "").toLowerCase();
    if (label.includes(trimmed) || category.includes(trimmed) || content.includes(trimmed)) {
      matchIds.push(node.id());
    }
  });

  // No matches → don't hide anything (avoids blank graph)
  if (matchIds.length === 0) {
    syncEdgeVisibility();
    return [];
  }

  // Collect match + 1-hop neighbors
  const visible = new Set<string>();
  for (const id of matchIds) {
    const node = cy.getElementById(id);
    node.addClass("search-match");
    visible.add(id);
    node.neighborhood().nodes().forEach((n) => visible.add(n.id()));
  }

  // Hide everything else
  cy.nodes().forEach((node) => {
    if (!visible.has(node.id())) {
      node.addClass("filter-hidden");
    }
  });

  syncEdgeVisibility();
  return matchIds;
}

/** Filter graph to show only "new" nodes (not in baseline) + their 1-hop neighbors.
 * When active=false, clears the session filter. Returns count of new nodes found. */
export function filterBySession(active: boolean, baselineNodeIds: Set<string>): number {
  if (!cy) return 0;

  // Clear previous session state
  cy.nodes().removeClass("new-node session-hidden");

  if (!active) {
    syncEdgeVisibility();
    return 0;
  }

  // Identify new nodes
  const newIds: string[] = [];
  cy.nodes().forEach((node) => {
    if (!baselineNodeIds.has(node.id())) {
      newIds.push(node.id());
    }
  });

  // If no new nodes, don't hide anything
  if (newIds.length === 0) {
    syncEdgeVisibility();
    return 0;
  }

  // Collect new + 1-hop neighbors
  const visible = new Set<string>();
  for (const id of newIds) {
    const node = cy.getElementById(id);
    node.addClass("new-node");
    visible.add(id);
    node.neighborhood().nodes().forEach((n) => visible.add(n.id()));
  }

  // Hide everything else
  cy.nodes().forEach((node) => {
    if (!visible.has(node.id())) {
      node.addClass("session-hidden");
    }
  });

  syncEdgeVisibility();
  return newIds.length;
}

/** Get all current node IDs (for baseline capture). */
export function getNodeIds(): Set<string> {
  if (!cy) return new Set();
  const ids = new Set<string>();
  cy.nodes().forEach((node) => ids.add(node.id()));
  return ids;
}
