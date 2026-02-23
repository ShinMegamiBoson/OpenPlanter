"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Message,
  ServerFrame,
  ClientFrame,
  GraphData,
  EvidenceChain,
} from "@/lib/types";
import { getWebSocketUrl } from "@/lib/api";

/** Active tool call indicator shown in the UI. */
export interface ToolCallIndicator {
  tool: string;
  status: "running" | "complete";
  input?: Record<string, unknown>;
  output?: string;
}

export interface UseWebSocketReturn {
  /** All messages in the conversation (user + assistant). */
  messages: Message[];
  /** Send a user message to the agent. */
  sendMessage: (content: string) => void;
  /** Launch a sub-investigation with a specific question. */
  sendSubInvestigation: (question: string) => void;
  /** Whether the WebSocket is currently connected. */
  isConnected: boolean;
  /** Whether the agent is currently streaming a response. */
  isStreaming: boolean;
  /** Latest graph data pushed from the server. */
  graphData: GraphData | null;
  /** Evidence chains pushed from the server. */
  evidenceData: EvidenceChain[];
  /** Current tool call indicators (for UI display). */
  toolCalls: ToolCallIndicator[];
  /** Most recent error message, if any. */
  lastError: string | null;
}

/** Maximum reconnect delay in milliseconds. */
const MAX_RECONNECT_DELAY = 30_000;
/** Base reconnect delay in milliseconds. */
const BASE_RECONNECT_DELAY = 1_000;

/**
 * React hook that manages a WebSocket connection to the Redthread backend
 * for a given investigation. Handles:
 * - Connection lifecycle with reconnection on disconnect (exponential backoff)
 * - Accumulating text_delta frames into complete messages
 * - Tracking tool calls for UI indicators
 * - Updating graph and evidence data from server push events
 */
export function useWebSocket(investigationId: string): UseWebSocketReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [evidenceData, setEvidenceData] = useState<EvidenceChain[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallIndicator[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);

  // Refs for values that need to be accessed in callbacks without re-renders
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamingContentRef = useRef("");
  const mountedRef = useRef(true);

  /** Calculate reconnect delay with exponential backoff and jitter. */
  const getReconnectDelay = useCallback((): number => {
    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(
      BASE_RECONNECT_DELAY * Math.pow(2, attempt),
      MAX_RECONNECT_DELAY,
    );
    // Add jitter: +/- 20%
    const jitter = delay * 0.2 * (Math.random() * 2 - 1);
    return Math.round(delay + jitter);
  }, []);

  /** Process an incoming server frame. */
  const handleFrame = useCallback((frame: ServerFrame): void => {
    switch (frame.type) {
      case "text_delta": {
        streamingContentRef.current += frame.content;
        // Update the last assistant message in-place for streaming display
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: streamingContentRef.current,
            };
          } else {
            // First delta: create a new assistant message
            updated.push({
              id: `streaming-${Date.now()}`,
              investigation_id: "",
              role: "assistant",
              content: streamingContentRef.current,
              created_at: new Date().toISOString(),
            });
          }
          return updated;
        });
        break;
      }

      case "tool_call": {
        setToolCalls((prev) => [
          ...prev,
          { tool: frame.tool, status: "running", input: frame.input },
        ]);
        break;
      }

      case "tool_result": {
        setToolCalls((prev) =>
          prev.map((tc) =>
            tc.tool === frame.tool && tc.status === "running"
              ? { ...tc, status: "complete" as const, output: frame.output }
              : tc,
          ),
        );
        break;
      }

      case "message_complete": {
        setIsStreaming(false);
        streamingContentRef.current = "";
        // Replace streaming message with the finalized version
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              id: `msg-${Date.now()}`,
              content: frame.content,
            };
          }
          return updated;
        });
        // Clear tool call indicators
        setToolCalls([]);
        break;
      }

      case "graph_update": {
        setGraphData(frame.data);
        break;
      }

      case "evidence_update": {
        setEvidenceData((prev) => {
          // Append or update evidence entry
          const existing = prev.findIndex((e) => e.id === frame.data.id);
          if (existing >= 0) {
            const updated = [...prev];
            updated[existing] = frame.data;
            return updated;
          }
          return [...prev, frame.data];
        });
        break;
      }

      case "error": {
        setLastError(frame.message);
        setIsStreaming(false);
        break;
      }
    }
  }, []);

  /** Connect (or reconnect) the WebSocket. */
  const connect = useCallback((): void => {
    if (!mountedRef.current) return;

    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const url = getWebSocketUrl(investigationId);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setIsConnected(true);
      setLastError(null);
      reconnectAttemptRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const frame = JSON.parse(event.data as string) as ServerFrame;
        handleFrame(frame);
      } catch {
        // Ignore malformed frames
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      setIsStreaming(false);

      // Schedule reconnect with exponential backoff
      const delay = getReconnectDelay();
      reconnectAttemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect();
        }
      }, delay);
    };

    ws.onerror = () => {
      // The onclose handler will fire after onerror, so reconnect logic
      // is handled there. Just record the error state.
      if (!mountedRef.current) return;
      setLastError("WebSocket connection error");
    };
  }, [investigationId, handleFrame, getReconnectDelay]);

  /** Send a JSON frame over the WebSocket. */
  const sendFrame = useCallback((frame: ClientFrame): void => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(frame));
    }
  }, []);

  /** Send a user message to the agent. */
  const sendMessage = useCallback(
    (content: string): void => {
      if (!content.trim()) return;

      // Add user message to local state immediately
      const userMessage: Message = {
        id: `user-${Date.now()}`,
        investigation_id: investigationId,
        role: "user",
        content: content.trim(),
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMessage]);
      setIsStreaming(true);
      setLastError(null);
      streamingContentRef.current = "";

      sendFrame({ type: "message", content: content.trim() });
    },
    [investigationId, sendFrame],
  );

  /** Launch a sub-investigation with a specific question. */
  const sendSubInvestigation = useCallback(
    (question: string): void => {
      if (!question.trim()) return;

      setIsStreaming(true);
      setLastError(null);
      streamingContentRef.current = "";

      sendFrame({ type: "sub_investigate", question: question.trim() });
    },
    [sendFrame],
  );

  // Connect on mount, clean up on unmount
  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    messages,
    sendMessage,
    sendSubInvestigation,
    isConnected,
    isStreaming,
    graphData,
    evidenceData,
    toolCalls,
    lastError,
  };
}
