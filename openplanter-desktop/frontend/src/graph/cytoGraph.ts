/** Cytoscape.js 2D graph wrapper for investigative analysis. */
import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import fcose from "cytoscape-fcose";
import dagre from "cytoscape-dagre";
import { getCategoryColor, CATEGORY_COLORS } from "./colors";
import type { GraphData } from "../api/types";

cytoscape.use(fcose);
cytoscape.use(dagre);

let cy: Core | null = null;
let resizeObserver: ResizeObserver | null = null;

/** Cytoscape stylesheet — colored circles with degree-based sizing. */
const graphStyle: cytoscape.Stylesheet[] = [
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
      "font-size": "9px",
      "font-family": "JetBrains Mono, Fira Code, SF Mono, Menlo, monospace",
      shape: "ellipse",
      width: "data(size)",
      height: "data(size)",
      "text-wrap": "ellipsis",
      "text-max-width": "100px",
      "min-zoomed-font-size": 6,
      "text-outline-color": "#0d1117",
      "text-outline-width": 1.5,
      "text-outline-opacity": 0.8,
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
] as any;

/** Convert GraphData to Cytoscape element definitions with degree-based sizing. */
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

  const minSize = 20;
  const sizeScale = 8;

  const nodes: cytoscape.ElementDefinition[] = data.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.label,
      category: n.category,
      path: n.path,
      color: getCategoryColor(n.category),
      size: minSize + Math.sqrt(degree.get(n.id) ?? 0) * sizeScale,
    },
  }));

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
        nodeSeparation: 75,
        idealEdgeLength: 150,
        nodeRepulsion: () => 12000,
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

/** Show/hide nodes by category. Returns set of currently visible categories. */
export function filterByCategory(
  hiddenCategories: Set<string>
): void {
  if (!cy) return;

  cy.nodes().forEach((node) => {
    const cat = node.data("category") as string;
    if (hiddenCategories.has(cat)) {
      node.addClass("hidden");
      // Hide connected edges to hidden nodes
      node.connectedEdges().forEach((edge) => {
        const src = edge.source();
        const tgt = edge.target();
        if (hiddenCategories.has(src.data("category")) || hiddenCategories.has(tgt.data("category"))) {
          edge.addClass("hidden");
        }
      });
    } else {
      node.removeClass("hidden");
      node.connectedEdges().forEach((edge) => {
        const src = edge.source();
        const tgt = edge.target();
        if (!hiddenCategories.has(src.data("category")) && !hiddenCategories.has(tgt.data("category"))) {
          edge.removeClass("hidden");
        }
      });
    }
  });
}

/** Search nodes by label. Returns matching node IDs. */
export function searchNodes(query: string): string[] {
  if (!cy || !query.trim()) {
    clearSearchHighlights();
    return [];
  }

  clearSearchHighlights();
  const lowerQuery = query.toLowerCase();
  const matches: string[] = [];

  cy.nodes().forEach((node) => {
    const label = (node.data("label") as string || "").toLowerCase();
    if (label.includes(lowerQuery)) {
      node.addClass("search-match");
      matches.push(node.id());
    }
  });

  return matches;
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

/** Clear search-match highlights only. */
export function clearSearchHighlights(): void {
  if (!cy) return;
  cy.nodes().removeClass("search-match");
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
