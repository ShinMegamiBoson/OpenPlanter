# Redthread - PRD

**Date:** 2026-02-22
**Status:** Brainstorming

## Goal

Rebuild OpenPlanter as **Redthread** — a web-based financial crime investigation agent for BSA/AML analysts. The current codebase has the right vision (recursive LLM-powered investigation with evidence-backed analysis) but weak execution (hand-rolled HTTP, no structured tooling, investigation logic lives entirely in prompt text). The rebuild replaces the architecture while preserving the investigation methodology. The name "Redthread" reflects the tool's core function: following threads of evidence across disparate data sources to surface connections.

## Scope

### In Scope

- **Anthropic Agent SDK-powered investigation agent** with Claude Max subscription support
- **Web UI** (FastAPI backend + Next.js/React frontend) with chat panel and investigation workspace
- **Hybrid interaction model**: analyst drives the investigation interactively; can launch autonomous sub-investigations on specific questions
- **Local file ingestion**: CSV, JSON, spreadsheets dropped into a workspace
- **Web search** for public records, news, and supplementary data
- **OFAC/SDN list screening** as the minimum live data source integration
- **Entity resolution** with structured tooling (fuzzy name matching, address normalization, entity graph)
- **Evidence chain tracking** as a first-class data structure (claim -> evidence -> source -> confidence)
- **Entity relationship graph visualization** in the web UI
- **Transaction timeline visualization** in the web UI
- **On-demand SAR narrative generation** from accumulated evidence
- **Investigation methodology** ported from the current system prompt (epistemic discipline, evidence standards, verification principles)

### Boundaries

Deliberate limits on what this work will NOT do. These aren't oversights — they're active decisions that prevent scope creep and set expectations.

- **No live API integrations beyond OFAC** — additional data source APIs (OpenCorporates, FEC, FinCEN, etc.) are v2+. Local files + web search + OFAC covers the core workflow without months of API plumbing.
- **No multi-user collaboration** — v1 is single-analyst. Shared investigations, role-based access, and team workflows are future scope.
- **No compliance workflow integration** — v1 does not integrate with case management systems, SAR filing platforms, or audit trail requirements. It produces outputs an analyst can use in their existing workflow.
- **No terminal UI** — the current Rich TUI is not being ported. Web UI only.
- **No multi-provider LLM support** — Anthropic only via Agent SDK. No OpenAI, OpenRouter, or Cerebras support.
- **No deterministic investigation pipeline** — v1 is an AI-driven investigation tool, not a rule-based compliance engine. It augments analyst judgment, not replaces it.

## Requirements

| ID | Priority | Requirement |
|----|----------|-------------|
| R1 | Core | Agent can ingest local data files (CSV, JSON, XLSX), resolve entities across them, and build structured evidence chains linking findings to specific source records (target: files up to 50 MB / 500K rows; best-effort parsing with validation warnings for malformed data) |
| R2 | Core | Analyst can interact with the agent conversationally via web UI, directing the investigation and launching autonomous sub-investigations |
| R3 | Must | Web UI displays an entity relationship graph that updates as the investigation progresses |
| R4 | Must | Web UI displays a transaction timeline for entities under investigation |
| R5 | Must | Agent can screen entities against OFAC/SDN lists and flag matches with confidence levels |
| R6 | Must | Agent can perform web searches to verify entities, find public records, and gather supplementary information |
| R7 | Must | Agent can generate a draft SAR narrative from accumulated evidence on analyst request |
| R8 | Must | Evidence chain data model tracks: claim, supporting evidence, source record, source dataset, confidence level (confirmed/probable/possible/unresolved) |
| R9 | Must | Entity resolution handles name variants systematically: fuzzy matching, case normalization, suffix handling (LLC, Inc, Corp), whitespace/punctuation normalization |
| R10 | Must | Investigation sessions persist across browser sessions — analyst can resume where they left off |
| R11 | Nice | Agent streams responses in real-time (token-by-token) in the chat panel |
| R12 | Nice | Evidence panel shows a structured view of all findings with drill-down to source records |
| R13 | Nice | Agent proactively suggests investigation paths ("You might also want to check X...") |
| R14 | Out | Multi-user collaboration — v1 is single-analyst (future scope) |
| R15 | Out | Regulatory audit trail — no tamper-proof logging or compliance certification (future scope) |
| R16 | Out | Integration with external case management or SAR filing systems (future scope) |

## Acceptance Criteria

- **R1 (File ingestion + evidence chains):** Agent successfully ingests a CSV, JSON, or XLSX file up to 50 MB / 500K rows, parses its contents, and produces at least one evidence chain linking a finding to a specific source record and row. Malformed or partially readable files produce validation warnings rather than silent failures.
- **R5 (OFAC screening):** Agent screens a given entity name against the locally downloaded SDN list and returns match results with confidence levels. Screening correctly identifies known exact matches and flags plausible fuzzy matches. Results are suitable for analyst review, not automated decisioning — consistent with OFAC compliance expectations.
- **R7 (SAR narrative):** On analyst request, the agent generates a draft SAR narrative from accumulated evidence. The narrative is clearly labeled as a draft requiring analyst review and editing before any regulatory submission. Narrative references specific evidence chain entries.
- **R8 (Evidence chain model):** Each evidence chain entry contains: claim, supporting evidence, source record identifier, source dataset, and confidence level (confirmed/probable/possible/unresolved). Evidence chains are queryable by entity and by confidence level.

## Chosen Direction

**Agent-first with structured tools.** Build directly on the Anthropic Agent SDK. Investigation capabilities (entity resolution, sanctions screening, evidence tracking) are implemented as Agent SDK tools with structured inputs/outputs. Evidence accumulates in a session-scoped data structure that the web UI renders. The agent IS the investigation engine — no separate investigation kernel or MCP server ecosystem.

This was chosen over two alternatives because it ships fastest and lets us discover the right module boundaries through actual use before extracting them.

## Alternatives Considered

- **Investigation kernel + agent shell** — Build a standalone Python investigation library first, then wrap it with the Agent SDK. Rejected because it requires significant upfront architecture work before producing anything usable, and we don't yet know where the right abstraction boundaries are.
- **MCP server ecosystem** — Each investigation capability as a separate MCP server (OFAC server, corporate registry server, etc.). Rejected because the operational complexity of multiple servers is premature for v1. Can migrate individual tools to MCP servers later if reusability demands it.

## Key Decisions

- **Anthropic Agent SDK + Claude Max**: Single provider, proper SDK, no hand-rolled HTTP. Claude Max subscription provides the API access. **Assumption to validate:** Claude Max subscription grants programmatic access to the Agent SDK (API key or OAuth). If not, fallback is a standard Anthropic API account with usage-based billing.
- **Salvage the system prompt**: The investigation methodology, epistemic discipline, and evidence chain standards from the current `prompts.py` are the most valuable part of the existing codebase. Port these to the new agent's system prompt. Rewrite everything else.
- **Web UI over TUI**: BSA analysts are accustomed to browser-based compliance tools. Entity graphs and timelines need visual rendering that a terminal cannot provide.
- **FastAPI + Next.js/React**: FastAPI for the Python backend (Agent SDK integration, WebSocket streaming), Next.js/React for the frontend (visualization libraries for graphs and timelines, streaming chat UI).
- **OFAC as the only v1 live API**: Sanctions screening is non-negotiable for SAR work. All other live APIs are deferred to keep v1 focused on the core investigation workflow.
- **Hybrid autonomous + interactive**: The analyst drives the investigation but can launch autonomous deep-dives. This preserves the recursive sub-agent concept from OpenPlanter v1 while keeping the analyst in control.

## Resolved Questions

- **Entity resolution approach (R1, R9)** — Two-tier system. **Tier 1 (pairwise):** rapidfuzz + jellyfish (phonetic matching) + cleanco (business suffix stripping) + nameparser (human name decomposition) for quick entity comparisons during conversation. **Tier 2 (batch):** splink with DuckDB backend for probabilistic record linkage across entire datasets — unsupervised (no training data), multi-field matching with statistical confidence scores suitable for evidence-grade documentation. dedupe (inactive, requires human labeling) and recordlinkage (less mature) were eliminated.
- **Persistence layer (R8, R10)** — Dual-database: **Kuzu** (embedded graph DB with native Cypher queries) for entity nodes and typed relationships (path-finding, traversal, pattern matching). **SQLite** for evidence chains, investigation sessions, metadata, and ingested data (normalized relational data, ACID, JSON1). Both are embedded, zero-config, installed via pip. PostgreSQL+AGE (server overhead, immature driver), Neo4j (JVM server), and in-memory+JSON (no ACID, crash risk) were eliminated. Fallback: SQLite + NetworkX if Kuzu maturity is a concern.
- **Visualization libraries (R3, R4)** — **Cytoscape.js** (direct integration, no React wrapper) for entity graphs: 1.5M downloads/week, compound nodes for grouping entities, built-in graph algorithms (shortest path, centrality), 10+ layout plugins, incremental updates via `cy.add()`/`cy.remove()`. **Recharts** for transaction timelines: 7-13M downloads/week, composable React components (ComposedChart with scatter + reference areas + custom tooltips), `syncId` for coordinated multi-entity views. react-force-graph, React Flow, vis-network, and vis-timeline were evaluated and rejected.
- **OFAC/SDN access method** — Download the full SDN list and screen locally. No external API dependency. The agent will need a tool to fetch/update the list and perform fuzzy matching against it.
- **Project name** — Renamed to **Redthread**. "Follow the red thread" is a classic investigation metaphor for tracing evidence chains across sources.

## Risks

- **Data sensitivity:** BSA/AML investigation data contains PII and potentially SAR-related information subject to federal confidentiality requirements (31 USC 5318(g)(2)). v1 runs locally (embedded databases, no cloud sync), which mitigates but does not eliminate this risk. Data handling constraints should be defined during technical planning.
- **LLM hallucination:** Agent-generated SAR narratives must be clearly marked as drafts requiring analyst verification. The evidence chain model (R8) provides traceability but does not prevent fabrication. Analysts remain responsible for validating all agent-produced content before regulatory use.
- **Kuzu maturity:** Kuzu is an embedded graph database with a smaller ecosystem than established alternatives. The PRD already identifies a NetworkX fallback (see Resolved Questions). This should be evaluated early in technical planning to avoid a mid-build migration.

## Next Steps

-> Create technical plan
