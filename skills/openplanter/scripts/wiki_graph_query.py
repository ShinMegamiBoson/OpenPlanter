#!/usr/bin/env python3
"""Query an OpenPlanter wiki knowledge graph (read-only).

Reads a NetworkX-compatible knowledge graph JSON file produced by
OpenPlanter's wiki_graph.py during delegated investigations. Supports
entity lookup, neighbor traversal, path finding, and subgraph export.

Use this to inspect investigation results after a delegated run without
requiring NetworkX or the full OpenPlanter agent.

Uses Python stdlib only — zero external dependencies.

Graph format: Node-link JSON (NetworkX node_link_data export):
    {"directed": true, "nodes": [...], "links": [...]}

Usage:
    python3 wiki_graph_query.py /path/to/investigation --entity "Raytheon"
    python3 wiki_graph_query.py /path/to/investigation --entity "Raytheon" --neighbors
    python3 wiki_graph_query.py /path/to/investigation --path "Raytheon" "OFAC SDN"
    python3 wiki_graph_query.py /path/to/investigation --stats
    python3 wiki_graph_query.py /path/to/investigation --types
    python3 wiki_graph_query.py /path/to/investigation --search "missile"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_graph(workspace: Path) -> dict:
    """Find and load the wiki knowledge graph from the workspace."""
    # Check common locations for the graph file
    candidates = [
        workspace / ".openplanter" / "wiki" / "graph.json",
        workspace / "wiki" / "graph.json",
        workspace / "knowledge_graph.json",
        workspace / "entity_graph.json",
    ]
    # Also check sessions for the most recent graph
    session_dir = workspace / ".openplanter" / "sessions"
    if session_dir.exists():
        for d in sorted(session_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                candidates.append(d / "wiki" / "graph.json")
                candidates.append(d / "graph.json")

    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if "nodes" in data:
                    data["_source_path"] = str(path)
                    return data
            except (json.JSONDecodeError, OSError):
                continue

    return {}


def get_nodes(graph: dict) -> list[dict]:
    """Extract nodes from graph data."""
    return graph.get("nodes", [])


def get_links(graph: dict) -> list[dict]:
    """Extract links/edges from graph data."""
    return graph.get("links", graph.get("edges", []))


def find_entity(graph: dict, name: str) -> list[dict]:
    """Find nodes matching an entity name (case-insensitive substring)."""
    name_lower = name.lower()
    matches = []
    for node in get_nodes(graph):
        node_id = str(node.get("id", "")).lower()
        node_label = str(node.get("label", node.get("name", ""))).lower()
        if name_lower in node_id or name_lower in node_label:
            matches.append(node)
    return matches


def get_neighbors(graph: dict, node_id: str) -> dict:
    """Get all neighbors (inbound + outbound) of a node."""
    outbound = []
    inbound = []
    for link in get_links(graph):
        src = str(link.get("source", ""))
        tgt = str(link.get("target", ""))
        rel = link.get("relation", link.get("label", link.get("type", "")))
        if src == node_id:
            outbound.append({"target": tgt, "relation": rel})
        elif tgt == node_id:
            inbound.append({"source": src, "relation": rel})
    return {"outbound": outbound, "inbound": inbound}


def find_path(graph: dict, start: str, end: str, max_depth: int = 6) -> list[list[str]]:
    """BFS to find shortest path(s) between two node IDs."""
    # Build adjacency list
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for link in get_links(graph):
        src = str(link.get("source", ""))
        tgt = str(link.get("target", ""))
        rel = link.get("relation", link.get("label", ""))
        adj[src].append((tgt, rel))
        adj[tgt].append((src, rel))  # Treat as undirected for pathfinding

    # BFS
    queue: list[list[str]] = [[start]]
    visited = {start}
    paths = []

    while queue:
        path = queue.pop(0)
        if len(path) > max_depth * 2:  # Each step adds node + relation
            continue
        current = path[-1]
        for neighbor, rel in adj.get(current, []):
            if neighbor == end:
                paths.append(path + [f"--[{rel}]-->", neighbor])
                continue
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [f"--[{rel}]-->", neighbor])

    return paths


def graph_stats(graph: dict) -> dict:
    """Compute basic graph statistics."""
    nodes = get_nodes(graph)
    links = get_links(graph)

    # Count node types
    type_counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        ntype = node.get("type", node.get("entity_type", "unknown"))
        type_counts[str(ntype)] += 1

    # Count relation types
    rel_counts: dict[str, int] = defaultdict(int)
    for link in links:
        rel = link.get("relation", link.get("label", link.get("type", "unknown")))
        rel_counts[str(rel)] += 1

    # Degree distribution
    degree: dict[str, int] = defaultdict(int)
    for link in links:
        degree[str(link.get("source", ""))] += 1
        degree[str(link.get("target", ""))] += 1

    top_nodes = sorted(degree.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "source_path": graph.get("_source_path", ""),
        "node_count": len(nodes),
        "link_count": len(links),
        "directed": graph.get("directed", False),
        "node_types": dict(type_counts),
        "relation_types": dict(rel_counts),
        "top_connected_nodes": [{"id": n, "degree": d} for n, d in top_nodes],
    }


def search_graph(graph: dict, term: str) -> list[dict]:
    """Search all node and link fields for a term."""
    term_lower = term.lower()
    results = []

    for node in get_nodes(graph):
        for key, val in node.items():
            if term_lower in str(val).lower():
                results.append({"type": "node", "id": node.get("id"), "match_field": key, "data": node})
                break

    for link in get_links(graph):
        for key, val in link.items():
            if term_lower in str(val).lower():
                results.append({
                    "type": "link",
                    "source": link.get("source"),
                    "target": link.get("target"),
                    "match_field": key,
                    "data": link,
                })
                break

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query an OpenPlanter wiki knowledge graph (read-only)"
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Path to investigation workspace directory",
    )
    parser.add_argument("--entity", "-e", help="Find nodes matching entity name")
    parser.add_argument("--neighbors", "-n", action="store_true", help="Show neighbors of matched entity")
    parser.add_argument("--path", nargs=2, metavar=("START", "END"), help="Find path between two entities")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    parser.add_argument("--types", action="store_true", help="List all entity types")
    parser.add_argument("--search", "-s", help="Search all fields for a term")
    parser.add_argument("--graph-file", type=Path, help="Explicit path to graph JSON file")

    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.exists():
        print(f"ERROR: Workspace does not exist: {workspace}", file=sys.stderr)
        sys.exit(1)

    if args.graph_file:
        try:
            graph = json.loads(args.graph_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"ERROR: Cannot read graph file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        graph = load_graph(workspace)

    if not graph or "nodes" not in graph:
        print("No wiki knowledge graph found in workspace", file=sys.stderr)
        print("Run an OpenPlanter investigation first to generate one", file=sys.stderr)
        sys.exit(1)

    if args.stats:
        print(json.dumps(graph_stats(graph), indent=2))
        return

    if args.types:
        type_counts: dict[str, int] = defaultdict(int)
        for node in get_nodes(graph):
            ntype = node.get("type", node.get("entity_type", "unknown"))
            type_counts[str(ntype)] += 1
        for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {t:30s} {c}")
        return

    if args.search:
        results = search_graph(graph, args.search)
        if not results:
            print(f"No matches for '{args.search}'", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(results, indent=2))
        return

    if args.path:
        start, end = args.path
        paths = find_path(graph, start, end)
        if not paths:
            print(f"No path found between '{start}' and '{end}'", file=sys.stderr)
            sys.exit(1)
        for i, p in enumerate(paths[:5]):
            print(f"Path {i+1}: {' '.join(p)}")
        return

    if args.entity:
        matches = find_entity(graph, args.entity)
        if not matches:
            print(f"No entities matching '{args.entity}'", file=sys.stderr)
            sys.exit(1)

        if args.neighbors:
            for m in matches:
                nid = str(m.get("id", ""))
                nbrs = get_neighbors(graph, nid)
                print(json.dumps({"entity": m, "neighbors": nbrs}, indent=2))
        else:
            print(json.dumps(matches, indent=2))
        return

    # Default: show stats
    print(json.dumps(graph_stats(graph), indent=2))


if __name__ == "__main__":
    main()
