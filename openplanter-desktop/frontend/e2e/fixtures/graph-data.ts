/** Mock data for E2E tests — matches the GraphData/SessionInfo/ConfigView types. */

export const MOCK_GRAPH_DATA = {
  nodes: [
    { id: "acme-corp", label: "Acme Corp", category: "corporate", path: "wiki/acme-corp.md" },
    { id: "pac-fund-alpha", label: "PAC Fund Alpha", category: "campaign-finance", path: "wiki/pac-fund-alpha.md" },
    { id: "city-bridge-project", label: "City Bridge Project", category: "infrastructure", path: "wiki/city-bridge-project.md" },
    { id: "global-trade-llc", label: "Global Trade LLC", category: "international", path: "wiki/global-trade-llc.md" },
    { id: "lobby-group-one", label: "Lobby Group One", category: "lobbying", path: "wiki/lobby-group-one.md" },
    { id: "smith-foundation", label: "Smith Foundation", category: "nonprofits", path: "wiki/smith-foundation.md" },
    { id: "reg-filing-2024", label: "Reg Filing 2024", category: "regulatory", path: "wiki/reg-filing-2024.md" },
    { id: "bank-of-west", label: "Bank of West", category: "financial", path: "wiki/bank-of-west.md" },
    { id: "defense-contract-7", label: "Defense Contract 7", category: "contracts", path: "wiki/defense-contract-7.md" },
    { id: "sanctioned-entity-x", label: "Sanctioned Entity X", category: "sanctions", path: "wiki/sanctioned-entity-x.md" },
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
