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
| R1 | Core | Agent can ingest local data files (CSV, JSON, XLSX), resolve entities across them, and build structured evidence chains linking findings to specific source records |
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

## Chosen Direction

**Agent-first with structured tools.** Build directly on the Anthropic Agent SDK. Investigation capabilities (entity resolution, sanctions screening, evidence tracking) are implemented as Agent SDK tools with structured inputs/outputs. Evidence accumulates in a session-scoped data structure that the web UI renders. The agent IS the investigation engine — no separate investigation kernel or MCP server ecosystem.

This was chosen over two alternatives because it ships fastest and lets us discover the right module boundaries through actual use before extracting them.

## Alternatives Considered

- **Investigation kernel + agent shell** — Build a standalone Python investigation library first, then wrap it with the Agent SDK. Rejected because it requires significant upfront architecture work before producing anything usable, and we don't yet know where the right abstraction boundaries are.
- **MCP server ecosystem** — Each investigation capability as a separate MCP server (OFAC server, corporate registry server, etc.). Rejected because the operational complexity of multiple servers is premature for v1. Can migrate individual tools to MCP servers later if reusability demands it.

## Key Decisions

- **Anthropic Agent SDK + Claude Max**: Single provider, proper SDK, no hand-rolled HTTP. Claude Max subscription provides the API access.
- **Salvage the system prompt**: The investigation methodology, epistemic discipline, and evidence chain standards from the current `prompts.py` are the most valuable part of the existing codebase. Port these to the new agent's system prompt. Rewrite everything else.
- **Web UI over TUI**: BSA analysts are accustomed to browser-based compliance tools. Entity graphs and timelines need visual rendering that a terminal cannot provide.
- **FastAPI + Next.js/React**: FastAPI for the Python backend (Agent SDK integration, WebSocket streaming), Next.js/React for the frontend (visualization libraries for graphs and timelines, streaming chat UI).
- **OFAC as the only v1 live API**: Sanctions screening is non-negotiable for SAR work. All other live APIs are deferred to keep v1 focused on the core investigation workflow.
- **Hybrid autonomous + interactive**: The analyst drives the investigation but can launch autonomous deep-dives. This preserves the recursive sub-agent concept from OpenPlanter v1 while keeping the analyst in control.

## Open Questions

- **[Affects R1]** What entity resolution library or approach should we use? Options range from simple fuzzy string matching (rapidfuzz) to more sophisticated record linkage (splink, dedupe). The right choice depends on dataset sizes and matching accuracy needs.
- **[Affects R8]** What persistence layer for evidence chains and entity graphs? Options include SQLite (simple, file-based), PostgreSQL (richer queries, graph extensions), or an in-memory structure that serializes to JSON. Affects session persistence (R10) too.
- **[Affects R3, R4]** Which visualization libraries for entity graphs and timelines? React ecosystem has options (react-force-graph, vis.js, D3 direct) with different trade-offs for interactivity and performance.

## Resolved Questions

- **OFAC/SDN access method** — Download the full SDN list and screen locally. No external API dependency. The agent will need a tool to fetch/update the list and perform fuzzy matching against it.
- **Project name** — Renamed to **Redthread**. "Follow the red thread" is a classic investigation metaphor for tracing evidence chains across sources.

## Next Steps

-> Resolve open questions, then create technical plan
