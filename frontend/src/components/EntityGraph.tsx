"use client";

import React, { useCallback, useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import coseBilkent from "cytoscape-cose-bilkent";
import type { GraphData } from "@/lib/types";

// Register the cose-bilkent layout once
// eslint-disable-next-line @typescript-eslint/no-explicit-any
cytoscape.use(coseBilkent as any);

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  container: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100%",
    overflow: "hidden",
  } as React.CSSProperties,

  graphContainer: {
    flex: 1,
    position: "relative" as const,
    overflow: "hidden",
  } as React.CSSProperties,

  emptyState: {
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "var(--text-muted)",
    textAlign: "center" as const,
    padding: "var(--panel-padding)",
  } as React.CSSProperties,

  emptyMessage: {
    fontSize: 13,
    lineHeight: 1.6,
    maxWidth: 240,
  } as React.CSSProperties,

  emptyHint: {
    fontSize: 11,
    color: "var(--text-muted)",
    marginTop: 8,
    fontFamily: "var(--font-mono)",
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// Cytoscape style configuration
// ---------------------------------------------------------------------------

/** Map entity types to node colors. */
const NODE_COLORS: Record<string, string> = {
  person: "#4a7cff", // accent-blue
  organization: "#3ac47d", // accent-green
  address: "#e6883a", // accent-orange
  account: "#8a6aff", // accent-purple
  unknown: "#5e5e72", // text-muted
};

/** Map entity types to node shapes. */
const NODE_SHAPES: Record<string, string> = {
  person: "ellipse",
  organization: "round-rectangle",
  address: "diamond",
  account: "hexagon",
  unknown: "ellipse",
};

/** Map relationship types to edge line styles. */
const EDGE_LINE_STYLES: Record<string, string> = {
  TRANSACTED_WITH: "solid",
  AFFILIATED_WITH: "dashed",
  LOCATED_AT: "dotted",
  RELATES_TO: "dashed",
};

const CYTOSCAPE_STYLE: cytoscape.StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "text-valign": "bottom",
      "text-halign": "center",
      "font-size": "10px",
      "font-family": "Inter, -apple-system, sans-serif",
      color: "#e4e4eb",
      "text-margin-y": 6,
      "text-outline-color": "#0a0a0f",
      "text-outline-width": 2,
      "background-color": "#5e5e72",
      width: 28,
      height: 28,
      "border-width": 2,
      "border-color": "#2a2a3a",
      "overlay-padding": 4,
    },
  },
  // Per-type node styles
  ...Object.entries(NODE_COLORS).map(([type, color]) => ({
    selector: `node[type = "${type}"]`,
    style: {
      "background-color": color,
      shape: (NODE_SHAPES[type] ?? "ellipse") as cytoscape.Css.NodeShape,
    },
  })),
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#3a3a50",
      "target-arrow-color": "#3a3a50",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "arrow-scale": 0.8,
      opacity: 0.7,
    },
  },
  // Per-type edge styles
  ...Object.entries(EDGE_LINE_STYLES).map(([type, lineStyle]) => ({
    selector: `edge[type = "${type}"]`,
    style: {
      "line-style": lineStyle as cytoscape.Css.LineStyle,
    },
  })),
  // Selected node
  {
    selector: "node:selected",
    style: {
      "border-width": 3,
      "border-color": "#4a7cff",
      "overlay-color": "#4a7cff",
      "overlay-opacity": 0.15,
    },
  },
  // Highlighted edge (connected to selected node)
  {
    selector: "edge.highlighted",
    style: {
      "line-color": "#4a7cff",
      "target-arrow-color": "#4a7cff",
      width: 2.5,
      opacity: 1,
    },
  },
  // Dimmed elements (not connected to selected node)
  {
    selector: ".dimmed",
    style: {
      opacity: 0.2,
    },
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert GraphData to Cytoscape element definitions. */
function graphDataToElements(data: GraphData): ElementDefinition[] {
  const elements: ElementDefinition[] = [];

  for (const node of data.nodes) {
    elements.push({
      group: "nodes",
      data: {
        id: node.data.id,
        label: truncateLabel(node.data.label),
        type: node.data.type,
      },
    });
  }

  for (const edge of data.edges) {
    elements.push({
      group: "edges",
      data: {
        id: edge.data.id ?? `${edge.data.source}-${edge.data.target}`,
        source: edge.data.source,
        target: edge.data.target,
        type: edge.data.type,
      },
    });
  }

  return elements;
}

/** Truncate long labels for graph display. */
function truncateLabel(label: string, max = 20): string {
  if (label.length <= max) return label;
  return label.slice(0, max - 1) + "\u2026";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface EntityGraphProps {
  /** Graph data from useWebSocket or REST API. */
  graphData: GraphData | null;
  /** Callback when a node is selected (e.g., to filter evidence panel). */
  onNodeSelect?: (entityId: string | null) => void;
}

export function EntityGraph({
  graphData,
  onNodeSelect,
}: EntityGraphProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const prevDataRef = useRef<GraphData | null>(null);

  // -----------------------------------------------------------------------
  // Initialize Cytoscape instance
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: CYTOSCAPE_STYLE,
      layout: { name: "preset" },
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.3,
    });

    // Set background
    cy.container()!.style.background = "var(--bg-tertiary)";

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // -----------------------------------------------------------------------
  // Node click handler
  // -----------------------------------------------------------------------
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const handleNodeTap = (evt: cytoscape.EventObject) => {
      const node = evt.target;
      const nodeId = node.id() as string;

      // Clear previous highlighting
      cy.elements().removeClass("dimmed highlighted");

      // Highlight connected edges, dim the rest
      const connectedEdges = node.connectedEdges();
      const connectedNodes = connectedEdges.connectedNodes().union(node);

      cy.elements().not(connectedNodes).not(connectedEdges).addClass("dimmed");
      connectedEdges.addClass("highlighted");

      onNodeSelect?.(nodeId);
    };

    const handleBackgroundTap = (evt: cytoscape.EventObject) => {
      if (evt.target === cy) {
        cy.elements().removeClass("dimmed highlighted");
        cy.elements().unselect();
        onNodeSelect?.(null);
      }
    };

    cy.on("tap", "node", handleNodeTap);
    cy.on("tap", handleBackgroundTap);

    return () => {
      cy.off("tap", "node", handleNodeTap);
      cy.off("tap", handleBackgroundTap);
    };
  }, [onNodeSelect]);

  // -----------------------------------------------------------------------
  // Incremental graph data updates
  // -----------------------------------------------------------------------
  const runLayout = useCallback(() => {
    const cy = cyRef.current;
    if (!cy || cy.elements().length === 0) return;

    cy.layout({
      name: "cose-bilkent",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      animate: "end" as any,
      animationDuration: 300,
      fit: true,
      padding: 30,
      nodeRepulsion: 4500,
      idealEdgeLength: 100,
      edgeElasticity: 0.45,
      nestingFactor: 0.1,
      gravity: 0.25,
      numIter: 2500,
      tile: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any).run();
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    if (!graphData || (graphData.nodes.length === 0 && graphData.edges.length === 0)) {
      // Clear the graph
      cy.elements().remove();
      prevDataRef.current = null;
      return;
    }

    const prev = prevDataRef.current;

    if (!prev) {
      // First load: add all elements at once
      const elements = graphDataToElements(graphData);
      cy.add(elements);
      runLayout();
    } else {
      // Incremental update: compute diff
      const prevNodeIds = new Set(prev.nodes.map((n) => n.data.id));
      const newNodeIds = new Set(graphData.nodes.map((n) => n.data.id));
      const prevEdgeIds = new Set(
        prev.edges.map(
          (e) => e.data.id ?? `${e.data.source}-${e.data.target}`,
        ),
      );
      const newEdgeIds = new Set(
        graphData.edges.map(
          (e) => e.data.id ?? `${e.data.source}-${e.data.target}`,
        ),
      );

      // Nodes to add
      const nodesToAdd = graphData.nodes.filter(
        (n) => !prevNodeIds.has(n.data.id),
      );
      // Nodes to remove
      const nodeIdsToRemove = Array.from(prevNodeIds).filter(
        (id) => !newNodeIds.has(id),
      );
      // Edges to add
      const edgesToAdd = graphData.edges.filter(
        (e) =>
          !prevEdgeIds.has(
            e.data.id ?? `${e.data.source}-${e.data.target}`,
          ),
      );
      // Edges to remove
      const edgeIdsToRemove = Array.from(prevEdgeIds).filter(
        (id) => !newEdgeIds.has(id),
      );

      // Remove old elements
      for (const id of nodeIdsToRemove) {
        const el = cy.getElementById(id);
        if (el.length > 0) cy.remove(el);
      }
      for (const id of edgeIdsToRemove) {
        const el = cy.getElementById(id);
        if (el.length > 0) cy.remove(el);
      }

      // Add new elements
      const elementsToAdd: ElementDefinition[] = [];
      for (const node of nodesToAdd) {
        elementsToAdd.push({
          group: "nodes",
          data: {
            id: node.data.id,
            label: truncateLabel(node.data.label),
            type: node.data.type,
          },
        });
      }
      for (const edge of edgesToAdd) {
        elementsToAdd.push({
          group: "edges",
          data: {
            id: edge.data.id ?? `${edge.data.source}-${edge.data.target}`,
            source: edge.data.source,
            target: edge.data.target,
            type: edge.data.type,
          },
        });
      }

      if (elementsToAdd.length > 0) {
        cy.add(elementsToAdd);
      }

      // Re-run layout if elements changed
      if (
        elementsToAdd.length > 0 ||
        nodeIdsToRemove.length > 0 ||
        edgeIdsToRemove.length > 0
      ) {
        runLayout();
      }
    }

    prevDataRef.current = graphData;
  }, [graphData, runLayout]);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  const isEmpty =
    !graphData ||
    (graphData.nodes.length === 0 && graphData.edges.length === 0);

  return (
    <div style={styles.container}>
      <div className="panel__header">
        <span className="panel__title">Entity Graph</span>
      </div>
      {isEmpty ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyMessage}>
            Entity relationships will appear here as the investigation
            progresses.
          </div>
          <div style={styles.emptyHint}>
            Nodes colored by entity type
          </div>
        </div>
      ) : (
        <div ref={containerRef} style={styles.graphContainer} />
      )}
    </div>
  );
}
