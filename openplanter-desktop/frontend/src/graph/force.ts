/** 3D force graph setup using 3d-force-graph + three-spritetext. */
import ForceGraph3D, { type ForceGraph3DInstance } from "3d-force-graph";
import SpriteText from "three-spritetext";
import { getCategoryColor } from "./colors";
import type { GraphData } from "../api/types";

let graphInstance: ForceGraph3DInstance | null = null;

/** Convert our GraphData (with edges) to 3d-force-graph format (with links). */
function toForceGraphData(data: GraphData) {
  return {
    nodes: data.nodes.map((n) => ({ id: n.id, label: n.label, category: n.category })),
    links: data.edges.map((e) => ({ source: e.source, target: e.target, label: e.label })),
  };
}

export function initGraph(container: HTMLElement, data: GraphData): void {
  const fgData = toForceGraphData(data);

  if (graphInstance) {
    graphInstance.graphData(fgData);
    return;
  }

  graphInstance = new ForceGraph3D(container)
    .backgroundColor("#0d1117")
    .nodeThreeObject((node: any) => {
      const sprite = new SpriteText(node.label || node.id);
      sprite.color = getCategoryColor(node.category);
      sprite.textHeight = 4;
      return sprite;
    })
    .nodeThreeObjectExtend(false)
    .linkColor(() => "#30363d")
    .linkOpacity(0.4)
    .linkWidth(0.5)
    .linkDirectionalArrowLength(3)
    .linkDirectionalArrowRelPos(1)
    .graphData(fgData);

  // ResizeObserver for container resize
  const observer = new ResizeObserver(() => {
    if (graphInstance) {
      const { width, height } = container.getBoundingClientRect();
      graphInstance.width(width).height(height);
    }
  });
  observer.observe(container);
}

export function updateGraph(data: GraphData): void {
  if (graphInstance) {
    graphInstance.graphData(toForceGraphData(data));
  }
}

export function destroyGraph(): void {
  if (graphInstance) {
    graphInstance._destructor();
    graphInstance = null;
  }
}
