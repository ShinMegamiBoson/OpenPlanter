/**
 * Tests for the useWebSocket hook.
 * Uses a mock WebSocket class to simulate server behavior.
 */

import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { ServerFrame } from "@/lib/types";

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

type WSListener = (event: { data: string }) => void;

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readyState: number = MockWebSocket.CONNECTING;
  url: string;

  onopen: (() => void) | null = null;
  onmessage: WSListener | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    // Store the instance so tests can interact with it
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  // --- Test helpers ---

  /** Simulate the server opening the connection. */
  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  /** Simulate receiving a server frame. */
  simulateMessage(frame: ServerFrame): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  /** Simulate the connection closing. */
  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  /** Simulate a connection error. */
  simulateError(): void {
    this.onerror?.();
  }

  // --- Static registry ---
  static instances: MockWebSocket[] = [];
  static reset(): void {
    MockWebSocket.instances = [];
  }
  static get latest(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

// Install mock before all tests
beforeAll(() => {
  (globalThis as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
});

beforeEach(() => {
  MockWebSocket.reset();
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useWebSocket", () => {
  const investigationId = "test-inv-123";

  it("connects WebSocket on mount", () => {
    renderHook(() => useWebSocket(investigationId));

    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.latest!.url).toContain(investigationId);
  });

  it("reports isConnected = true after open", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    expect(result.current.isConnected).toBe(false);

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    expect(result.current.isConnected).toBe(true);
  });

  it("sends correct JSON frame when sendMessage is called", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("Hello, agent");
    });

    const sent = JSON.parse(MockWebSocket.latest!.sent[0]);
    expect(sent).toEqual({ type: "message", content: "Hello, agent" });
  });

  it("adds a user message to local state when sending", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("Hello");
    });

    expect(result.current.messages.length).toBe(1);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("Hello");
  });

  it("accumulates text_delta frames into a streaming message", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("Hi");
    });

    // Simulate streaming deltas
    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "text_delta",
        content: "Hello ",
      });
    });

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "text_delta",
        content: "world",
      });
    });

    // Should have user message + streaming assistant message
    expect(result.current.messages.length).toBe(2);
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].content).toBe("Hello world");
  });

  it("finalizes message on message_complete frame", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("Hi");
    });

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "text_delta",
        content: "Hello ",
      });
    });

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "message_complete",
        content: "Hello world, I'm the agent.",
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages[1].content).toBe(
      "Hello world, I'm the agent.",
    );
  });

  it("tracks tool call indicators", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("Ingest file");
    });

    // Simulate tool_call
    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "tool_call",
        tool: "ingest_file",
        input: { file_path: "/data/test.csv" },
      });
    });

    expect(result.current.toolCalls.length).toBe(1);
    expect(result.current.toolCalls[0].tool).toBe("ingest_file");
    expect(result.current.toolCalls[0].status).toBe("running");

    // Simulate tool_result
    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "tool_result",
        tool: "ingest_file",
        output: "Ingested 100 rows",
      });
    });

    expect(result.current.toolCalls[0].status).toBe("complete");
    expect(result.current.toolCalls[0].output).toBe("Ingested 100 rows");
  });

  it("attempts reconnect on disconnect with exponential backoff", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    expect(result.current.isConnected).toBe(true);
    const instancesBefore = MockWebSocket.instances.length;

    // Simulate disconnect
    act(() => {
      MockWebSocket.latest!.simulateClose();
    });

    expect(result.current.isConnected).toBe(false);

    // Advance timer to trigger reconnect (base delay is 1000ms)
    act(() => {
      jest.advanceTimersByTime(2000);
    });

    // A new WebSocket instance should have been created
    expect(MockWebSocket.instances.length).toBeGreaterThan(instancesBefore);
  });

  it("updates graphData on graph_update frame", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    const graphPayload = {
      nodes: [{ data: { id: "e1", label: "Acme Corp", type: "organization" } }],
      edges: [],
    };

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "graph_update",
        data: graphPayload,
      });
    });

    expect(result.current.graphData).toEqual(graphPayload);
  });

  it("appends evidence on evidence_update frame", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    const evidence = {
      id: "ev-1",
      investigation_id: investigationId,
      claim: "Entity matches SDN list",
      supporting_evidence: "Fuzzy score 0.95",
      confidence: "probable" as const,
      created_at: new Date().toISOString(),
    };

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "evidence_update",
        data: evidence,
      });
    });

    expect(result.current.evidenceData.length).toBe(1);
    expect(result.current.evidenceData[0].id).toBe("ev-1");
  });

  it("sets lastError on error frame", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      MockWebSocket.latest!.simulateMessage({
        type: "error",
        message: "Investigation not found",
      });
    });

    expect(result.current.lastError).toBe("Investigation not found");
  });

  it("sends sub_investigate frame", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendSubInvestigation("Who owns Acme Corp?");
    });

    const sent = JSON.parse(MockWebSocket.latest!.sent[0]);
    expect(sent).toEqual({
      type: "sub_investigate",
      question: "Who owns Acme Corp?",
    });
  });

  it("does not send empty messages", () => {
    const { result } = renderHook(() => useWebSocket(investigationId));

    act(() => {
      MockWebSocket.latest!.simulateOpen();
    });

    act(() => {
      result.current.sendMessage("   ");
    });

    expect(MockWebSocket.latest!.sent.length).toBe(0);
    expect(result.current.messages.length).toBe(0);
  });

  it("cleans up WebSocket on unmount", () => {
    const { unmount } = renderHook(() => useWebSocket(investigationId));

    const ws = MockWebSocket.latest!;
    act(() => {
      ws.simulateOpen();
    });

    unmount();

    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });
});
