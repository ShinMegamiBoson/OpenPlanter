/** Completion tree for slash command autocomplete. */
import { MODEL_ALIASES } from "./model";

export interface CompletionItem {
  value: string;
  description: string;
  children?: CompletionItem[];
}

const PROVIDER_FILTERS: CompletionItem[] = [
  { value: "all", description: "All providers" },
  { value: "openai", description: "OpenAI models" },
  { value: "anthropic", description: "Anthropic models" },
  { value: "ollama", description: "Local Ollama models" },
  { value: "cerebras", description: "Cerebras models" },
  { value: "zai", description: "Z.AI models" },
  { value: "openrouter", description: "OpenRouter models" },
];

const SAVE_FLAG: CompletionItem[] = [
  { value: "--save", description: "Persist to settings" },
];

const MODEL_ALIAS_ITEMS: CompletionItem[] = Object.keys(MODEL_ALIASES).map(
  (alias) => ({
    value: alias,
    description: MODEL_ALIASES[alias],
    children: SAVE_FLAG,
  }),
);

const REASONING_LEVELS: CompletionItem[] = [
  { value: "low", description: "Low reasoning effort", children: SAVE_FLAG },
  { value: "medium", description: "Medium reasoning effort", children: SAVE_FLAG },
  { value: "high", description: "High reasoning effort", children: SAVE_FLAG },
  { value: "off", description: "Disable reasoning", children: SAVE_FLAG },
];

const WEB_SEARCH_PROVIDERS: CompletionItem[] = [
  { value: "exa", description: "Use Exa for web search", children: SAVE_FLAG },
  { value: "firecrawl", description: "Use Firecrawl for web search", children: SAVE_FLAG },
  { value: "brave", description: "Use Brave Search for web search", children: SAVE_FLAG },
  { value: "tavily", description: "Use Tavily for web search", children: SAVE_FLAG },
];

const ZAI_PLANS: CompletionItem[] = [
  { value: "paygo", description: "Use the Z.AI PAYGO endpoint", children: SAVE_FLAG },
  { value: "coding", description: "Use the Z.AI Coding Plan endpoint", children: SAVE_FLAG },
];

export const COMMAND_COMPLETIONS: CompletionItem[] = [
  { value: "/help", description: "Show available commands" },
  { value: "/new", description: "Start a new session" },
  { value: "/clear", description: "Clear chat messages" },
  { value: "/quit", description: "Quit the application" },
  { value: "/exit", description: "Quit the application" },
  { value: "/status", description: "Show current status" },
  {
    value: "/model",
    description: "Show or switch model",
    children: [
      { value: "list", description: "List available models", children: PROVIDER_FILTERS },
      ...MODEL_ALIAS_ITEMS,
    ],
  },
  {
    value: "/zai-plan",
    description: "Show or switch the Z.AI endpoint family",
    children: ZAI_PLANS,
  },
  {
    value: "/web-search",
    description: "Show or switch the web search provider",
    children: WEB_SEARCH_PROVIDERS,
  },
  {
    value: "/reasoning",
    description: "Set reasoning effort",
    children: REASONING_LEVELS,
  },
  {
    value: "/init",
    description: "Workspace initialization and migration",
    children: [
      { value: "status", description: "Show init status" },
      { value: "standard", description: "Initialize the current workspace" },
      { value: "migrate", description: "Open the migration init panel" },
      { value: "open", description: "Open the init panel" },
      { value: "done", description: "Mark the first-run gate complete" },
    ],
  },
];
