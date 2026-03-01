/** Graph interaction handlers for Cytoscape.js. */
import type { Core, EventObject, NodeSingular } from "cytoscape";
import {
  highlightNeighborhood,
  clearHighlights,
  fitView,
  getCy,
} from "./cytoGraph";

export interface InteractionCallbacks {
  onNodeSelect: (nodeData: { id: string; label: string; category: string; path: string; connectedNodes: { id: string; label: string }[] }) => void;
  onNodeDeselect: () => void;
}

/** Bind all interaction handlers to the Cytoscape instance. */
export function bindInteractions(callbacks: InteractionCallbacks): void {
  const cy = getCy();
  if (!cy) return;

  // Click node: select, highlight neighborhood, show details
  cy.on("tap", "node", (evt: EventObject) => {
    const node = evt.target as NodeSingular;

    // Shift+click: add to selection without clearing
    if (evt.originalEvent && (evt.originalEvent as MouseEvent).shiftKey) {
      node.select();
      return;
    }

    clearHighlights();
    node.select();
    highlightNeighborhood(node);

    const connectedNodes = node.neighborhood().nodes().map((n) => ({
      id: n.id(),
      label: n.data("label") as string,
    }));

    callbacks.onNodeSelect({
      id: node.id(),
      label: node.data("label") as string,
      category: node.data("category") as string,
      path: node.data("path") as string,
      connectedNodes,
    });
  });

  // Click background: deselect all
  cy.on("tap", (evt: EventObject) => {
    if (evt.target === cy) {
      clearHighlights();
      callbacks.onNodeDeselect();
    }
  });

  // Double-click node: zoom to fit its neighborhood
  cy.on("dbltap", "node", (evt: EventObject) => {
    const node = evt.target as NodeSingular;
    const neighborhood = node.neighborhood().add(node);

    cy.animate({
      fit: { eles: neighborhood, padding: 60 },
      duration: 300,
    });
  });

  // Hover node: add tooltip via title attribute (native browser tooltip)
  cy.on("mouseover", "node", (evt: EventObject) => {
    const node = evt.target as NodeSingular;
    const container = cy.container();
    if (container) container.style.cursor = "pointer";

    const connCount = node.connectedEdges().length;
    const label = node.data("label") as string;
    const category = node.data("category") as string;
    node.data("_origLabel", node.data("label"));

    // Cytoscape doesn't have native tooltips, we set title on container
    if (container) {
      container.title = `${label}\n${category} \u2022 ${connCount} connection${connCount !== 1 ? "s" : ""}`;
    }
  });

  cy.on("mouseout", "node", () => {
    const container = cy.container();
    if (container) {
      container.style.cursor = "default";
      container.title = "";
    }
  });

  // Escape key: deselect all, reset view
  document.addEventListener("keydown", (evt: KeyboardEvent) => {
    if (evt.key === "Escape") {
      clearHighlights();
      callbacks.onNodeDeselect();
    }
  });
}
