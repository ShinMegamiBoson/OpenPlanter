/** Simple observable state store. */
type Listener<T> = (value: T) => void;

export class Store<T> {
  private value: T;
  private listeners: Set<Listener<T>> = new Set();

  constructor(initial: T) {
    this.value = initial;
  }

  get(): T {
    return this.value;
  }

  set(newValue: T): void {
    this.value = newValue;
    for (const listener of this.listeners) {
      listener(this.value);
    }
  }

  update(fn: (current: T) => T): void {
    this.set(fn(this.value));
  }

  subscribe(listener: Listener<T>): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export interface ToolCallDisplay {
  name: string;
  args: string;
}

export interface StepToolCall {
  name: string;
  keyArg: string;
  elapsed: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system" | "thinking" | "step-header" | "step-summary" | "tool-tree" | "splash";
  content: string;
  toolName?: string;
  timestamp: number;
  isRendered?: boolean;
  toolCalls?: ToolCallDisplay[];
  /** Step summary data (only for role "step-summary") */
  stepNumber?: number;
  stepTokensIn?: number;
  stepTokensOut?: number;
  stepElapsed?: number;
  stepToolCalls?: StepToolCall[];
  stepModelPreview?: string;
}

export interface AppState {
  provider: string;
  model: string;
  zaiPlan: string;
  webSearchProvider: string;
  sessionId: string | null;
  inputTokens: number;
  outputTokens: number;
  isRunning: boolean;
  messages: ChatMessage[];
  reasoningEffort: string | null;
  recursive: boolean;
  workspace: string;
  maxDepth: number;
  maxStepsPerCall: number;
  currentStep: number;
  currentDepth: number;
  inputHistory: string[];
  inputQueue: string[];
}

export const appState = new Store<AppState>({
  provider: "",
  model: "",
  zaiPlan: "paygo",
  webSearchProvider: "exa",
  sessionId: null,
  inputTokens: 0,
  outputTokens: 0,
  isRunning: false,
  messages: [],
  reasoningEffort: null,
  recursive: true,
  workspace: "",
  maxDepth: 4,
  maxStepsPerCall: 100,
  currentStep: 0,
  currentDepth: 0,
  inputHistory: [],
  inputQueue: [],
});
