"use client";

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import type { Message } from "@/lib/types";
import type { ToolCallIndicator } from "@/hooks/useWebSocket";
import { MessageBubble } from "./MessageBubble";

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  container: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100%",
    overflow: "hidden",
  } as React.CSSProperties,

  messagesArea: {
    flex: 1,
    overflowY: "auto" as const,
    padding: "var(--panel-padding)",
    display: "flex",
    flexDirection: "column" as const,
  } as React.CSSProperties,

  emptyState: {
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "var(--text-muted)",
    textAlign: "center" as const,
    padding: "var(--panel-padding)",
  } as React.CSSProperties,

  emptyMessage: {
    fontSize: 13,
    lineHeight: 1.6,
    maxWidth: 240,
  } as React.CSSProperties,

  emptyHint: {
    fontSize: 11,
    color: "var(--text-muted)",
    marginTop: 8,
    fontFamily: "var(--font-mono)",
  } as React.CSSProperties,

  inputArea: {
    flexShrink: 0,
    padding: "12px var(--panel-padding)",
    borderTop: "1px solid var(--border-subtle)",
    background: "var(--bg-secondary)",
  } as React.CSSProperties,

  inputWrapper: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
    background: "var(--bg-tertiary)",
    borderRadius: 10,
    border: "1px solid var(--border-subtle)",
    padding: "8px 12px",
    transition: "border-color 0.15s",
  } as React.CSSProperties,

  textarea: {
    flex: 1,
    background: "transparent",
    border: "none",
    outline: "none",
    color: "var(--text-primary)",
    fontSize: 13,
    fontFamily: "var(--font-sans)",
    lineHeight: 1.5,
    resize: "none" as const,
    maxHeight: 120,
    minHeight: 20,
  } as React.CSSProperties,

  sendButton: {
    flexShrink: 0,
    padding: "4px 12px",
    borderRadius: 6,
    border: "none",
    background: "var(--accent-blue)",
    color: "#ffffff",
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    fontWeight: 600,
    cursor: "pointer",
    letterSpacing: "0.04em",
    transition: "opacity 0.15s",
  } as React.CSSProperties,

  sendButtonDisabled: {
    opacity: 0.4,
    cursor: "not-allowed",
  } as React.CSSProperties,

  streamingIndicator: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px var(--panel-padding)",
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
  } as React.CSSProperties,

  pulseDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--accent-blue)",
    animation: "pulse 1.5s ease-in-out infinite",
  } as React.CSSProperties,

  connectionStatus: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    padding: "0 4px",
  } as React.CSSProperties,

  connectionDot: (connected: boolean): React.CSSProperties => ({
    width: 5,
    height: 5,
    borderRadius: "50%",
    background: connected ? "var(--accent-green)" : "var(--accent-red)",
  }),

  subInvestigateButton: {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "4px 8px",
    borderRadius: 4,
    border: "1px solid var(--border-subtle)",
    background: "transparent",
    color: "var(--text-secondary)",
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    cursor: "pointer",
    transition: "border-color 0.15s, color 0.15s",
  } as React.CSSProperties,

  errorBar: {
    padding: "6px var(--panel-padding)",
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    color: "var(--accent-red)",
    background: "var(--bg-tertiary)",
    borderTop: "1px solid var(--accent-red)",
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ChatPanelProps {
  /** All messages in the conversation. */
  messages: Message[];
  /** Send a user message. */
  onSendMessage: (content: string) => void;
  /** Launch a sub-investigation. */
  onSubInvestigate: (question: string) => void;
  /** Whether the WebSocket is connected. */
  isConnected: boolean;
  /** Whether the agent is currently streaming. */
  isStreaming: boolean;
  /** Active tool call indicators. */
  toolCalls: ToolCallIndicator[];
  /** Most recent error. */
  lastError: string | null;
}

export function ChatPanel({
  messages,
  onSendMessage,
  onSubInvestigate,
  isConnected,
  isStreaming,
  toolCalls,
  lastError,
}: ChatPanelProps): React.ReactElement {
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // -----------------------------------------------------------------------
  // Auto-scroll to bottom on new messages
  // -----------------------------------------------------------------------
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  // -----------------------------------------------------------------------
  // Auto-resize textarea
  // -----------------------------------------------------------------------
  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, []);

  // -----------------------------------------------------------------------
  // Send logic
  // -----------------------------------------------------------------------
  const handleSend = useCallback(() => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming) return;

    // Check for /investigate command
    if (trimmed.startsWith("/investigate ")) {
      const question = trimmed.slice("/investigate ".length).trim();
      if (question) {
        onSubInvestigate(question);
      }
    } else {
      onSendMessage(trimmed);
    }

    setInputValue("");
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [inputValue, isStreaming, onSendMessage, onSubInvestigate]);

  // -----------------------------------------------------------------------
  // Keyboard handler: Enter to send, Shift+Enter for newline
  // -----------------------------------------------------------------------
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // -----------------------------------------------------------------------
  // Determine if the last message is the one being streamed
  // -----------------------------------------------------------------------
  const lastMessage =
    messages.length > 0 ? messages[messages.length - 1] : null;
  const isLastStreaming =
    isStreaming && lastMessage?.role === "assistant";

  return (
    <div style={styles.container}>
      {/* Header with connection status */}
      <div className="panel__header">
        <span className="panel__title">Investigation Chat</span>
        <div style={styles.connectionStatus}>
          <div style={styles.connectionDot(isConnected)} />
          <span>{isConnected ? "connected" : "reconnecting"}</span>
        </div>
      </div>

      {/* Messages area */}
      <div style={styles.messagesArea}>
        {messages.length === 0 ? (
          <div style={styles.emptyState}>
            <div style={styles.emptyMessage}>
              Start an investigation by uploading a dataset or describing
              what you want to analyze.
            </div>
            <div style={styles.emptyHint}>
              Supports CSV, JSON, and XLSX files
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isCurrentStreaming =
              isLastStreaming && idx === messages.length - 1;
            return (
              <MessageBubble
                key={msg.id}
                message={msg}
                toolCalls={
                  isCurrentStreaming ? toolCalls : undefined
                }
                isStreaming={isCurrentStreaming}
              />
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Streaming indicator */}
      {isStreaming && (
        <div style={styles.streamingIndicator}>
          <div style={styles.pulseDot} />
          <span>
            {toolCalls.length > 0 && toolCalls.some((tc) => tc.status === "running")
              ? `Running ${toolCalls.filter((tc) => tc.status === "running")[0]?.tool}...`
              : "Thinking..."}
          </span>
        </div>
      )}

      {/* Error bar */}
      {lastError && <div style={styles.errorBar}>{lastError}</div>}

      {/* Input area */}
      <div style={styles.inputArea}>
        <div style={styles.inputWrapper}>
          <textarea
            ref={textareaRef}
            style={styles.textarea}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value);
              handleInput();
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              isConnected
                ? "Ask a question or describe your investigation..."
                : "Connecting..."
            }
            disabled={!isConnected}
            rows={1}
          />
          <button
            style={{
              ...styles.sendButton,
              ...(!inputValue.trim() || isStreaming || !isConnected
                ? styles.sendButtonDisabled
                : {}),
            }}
            onClick={handleSend}
            disabled={!inputValue.trim() || isStreaming || !isConnected}
            type="button"
          >
            Send
          </button>
        </div>

        {/* Sub-investigation shortcut hint */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 6,
            paddingLeft: 2,
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}
          >
            Enter to send / Shift+Enter for newline
          </span>
          <button
            style={styles.subInvestigateButton}
            onClick={() => {
              setInputValue("/investigate ");
              textareaRef.current?.focus();
            }}
            type="button"
            title="Start a sub-investigation"
          >
            /investigate
          </button>
        </div>
      </div>
    </div>
  );
}
