/** Mock data for E2E tests — matches the GraphData/SessionInfo/ConfigView types. */

export const MOCK_GRAPH_DATA = {
  nodes: [
    // Source nodes (tier 1)
    { id: "acme-corp", label: "Acme Corp", category: "corporate", path: "wiki/acme-corp.md", node_type: "source" },
    { id: "pac-fund-alpha", label: "PAC Fund Alpha", category: "campaign-finance", path: "wiki/pac-fund-alpha.md", node_type: "source" },
    { id: "city-bridge-project", label: "City Bridge Project", category: "infrastructure", path: "wiki/city-bridge-project.md", node_type: "source" },
    { id: "global-trade-llc", label: "Global Trade LLC", category: "international", path: "wiki/global-trade-llc.md", node_type: "source" },
    { id: "lobby-group-one", label: "Lobby Group One", category: "lobbying", path: "wiki/lobby-group-one.md", node_type: "source" },
    { id: "smith-foundation", label: "Smith Foundation", category: "nonprofits", path: "wiki/smith-foundation.md", node_type: "source" },
    { id: "reg-filing-2024", label: "Reg Filing 2024", category: "regulatory", path: "wiki/reg-filing-2024.md", node_type: "source" },
    { id: "bank-of-west", label: "Bank of West", category: "financial", path: "wiki/bank-of-west.md", node_type: "source" },
    { id: "defense-contract-7", label: "Defense Contract 7", category: "contracts", path: "wiki/defense-contract-7.md", node_type: "source" },
    { id: "sanctioned-entity-x", label: "Sanctioned Entity X", category: "sanctions", path: "wiki/sanctioned-entity-x.md", node_type: "source" },
    // Section nodes (tier 2)
    { id: "acme-corp::summary", label: "Summary", category: "corporate", path: "wiki/acme-corp.md", node_type: "section", parent_id: "acme-corp" },
    { id: "acme-corp::data-schema", label: "Data Schema", category: "corporate", path: "wiki/acme-corp.md", node_type: "section", parent_id: "acme-corp" },
    { id: "pac-fund-alpha::coverage", label: "Coverage", category: "campaign-finance", path: "wiki/pac-fund-alpha.md", node_type: "section", parent_id: "pac-fund-alpha" },
    // Fact nodes (tier 3)
    { id: "acme-corp::data-schema::entity-id", label: "entity_id", category: "corporate", path: "wiki/acme-corp.md", node_type: "fact", parent_id: "acme-corp::data-schema", content: "| entity_id | Unique corporate ID |" },
    { id: "pac-fund-alpha::coverage::jurisdiction", label: "Jurisdiction", category: "campaign-finance", path: "wiki/pac-fund-alpha.md", node_type: "fact", parent_id: "pac-fund-alpha::coverage", content: "- **Jurisdiction**: Federal elections" },
  ],
  edges: [
    { source: "acme-corp", target: "pac-fund-alpha", label: "donated to" },
    { source: "acme-corp", target: "city-bridge-project", label: "contractor" },
    { source: "acme-corp", target: "lobby-group-one", label: "hired" },
    { source: "pac-fund-alpha", target: "reg-filing-2024", label: "filed" },
    { source: "global-trade-llc", target: "sanctioned-entity-x", label: "traded with" },
    { source: "global-trade-llc", target: "bank-of-west", label: "account at" },
    { source: "smith-foundation", target: "acme-corp", label: "grant to" },
    { source: "defense-contract-7", target: "acme-corp", label: "awarded to" },
    { source: "lobby-group-one", target: "reg-filing-2024", label: "lobbied for" },
    // Structural edges
    { source: "acme-corp", target: "acme-corp::summary", label: "has-section" },
    { source: "acme-corp", target: "acme-corp::data-schema", label: "has-section" },
    { source: "pac-fund-alpha", target: "pac-fund-alpha::coverage", label: "has-section" },
    { source: "acme-corp::data-schema", target: "acme-corp::data-schema::entity-id", label: "contains" },
    { source: "pac-fund-alpha::coverage", target: "pac-fund-alpha::coverage::jurisdiction", label: "contains" },
  ],
};

export const MOCK_CONFIG = {
  provider: "anthropic",
  model: "claude-opus-4-6",
  reasoning_effort: null,
  workspace: "/tmp/test-workspace",
  session_id: "test-session-001",
  recursive: false,
  max_depth: 3,
  max_steps_per_call: 25,
  demo: false,
};

export const MOCK_SESSIONS = [
  {
    id: "20260227-100000-aaaa1111",
    created_at: "2026-02-27T10:00:00Z",
    turn_count: 5,
    last_objective: "Investigate Acme Corp connections",
  },
  {
    id: "20260227-090000-bbbb2222",
    created_at: "2026-02-27T09:00:00Z",
    turn_count: 2,
    last_objective: "Review PAC filings",
  },
];

export const MOCK_CREDENTIALS = {
  openai: true,
  anthropic: true,
  openrouter: false,
  cerebras: false,
  ollama: true,
  exa: false,
};

/** Extended mock data with 2 new source nodes + edges (for session toggle tests). */
export const MOCK_GRAPH_DATA_WITH_NEW_NODES = {
  nodes: [
    ...MOCK_GRAPH_DATA.nodes,
    { id: "new-entity-alpha", label: "New Entity Alpha", category: "corporate", path: "wiki/new-entity-alpha.md", node_type: "source" },
    { id: "new-entity-beta", label: "New Entity Beta", category: "financial", path: "wiki/new-entity-beta.md", node_type: "source" },
  ],
  edges: [
    ...MOCK_GRAPH_DATA.edges,
    { source: "new-entity-alpha", target: "acme-corp", label: "subsidiary of" },
    { source: "new-entity-beta", target: "bank-of-west", label: "account at" },
  ],
};
