"use client";

import React from "react";
import type { Message } from "@/lib/types";
import type { ToolCallIndicator } from "@/hooks/useWebSocket";

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  wrapper: (isUser: boolean): React.CSSProperties => ({
    display: "flex",
    flexDirection: "column",
    alignItems: isUser ? "flex-end" : "flex-start",
    marginBottom: 12,
  }),
  bubble: (isUser: boolean): React.CSSProperties => ({
    maxWidth: "88%",
    padding: "10px 14px",
    borderRadius: isUser ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
    background: isUser
      ? "var(--accent-blue)"
      : "var(--bg-tertiary)",
    color: isUser ? "#ffffff" : "var(--text-primary)",
    fontSize: 13,
    lineHeight: 1.6,
    wordBreak: "break-word" as const,
    whiteSpace: "pre-wrap" as const,
  }),
  role: (isUser: boolean): React.CSSProperties => ({
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    color: isUser ? "var(--accent-blue)" : "var(--text-muted)",
    marginBottom: 4,
    paddingLeft: isUser ? 0 : 2,
    paddingRight: isUser ? 2 : 0,
  }),
  timestamp: {
    fontSize: 10,
    color: "var(--text-muted)",
    marginTop: 4,
    fontFamily: "var(--font-mono)",
  } as React.CSSProperties,
  toolCallContainer: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 4,
    marginTop: 8,
  } as React.CSSProperties,
  toolCall: (status: "running" | "complete"): React.CSSProperties => ({
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    borderRadius: 6,
    background: "var(--bg-elevated)",
    border: `1px solid ${status === "running" ? "var(--accent-orange)" : "var(--accent-green)"}`,
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    color:
      status === "running"
        ? "var(--accent-orange)"
        : "var(--accent-green)",
  }),
  toolDot: (status: "running" | "complete"): React.CSSProperties => ({
    width: 6,
    height: 6,
    borderRadius: "50%",
    background:
      status === "running"
        ? "var(--accent-orange)"
        : "var(--accent-green)",
    animation: status === "running" ? "pulse 1.5s ease-in-out infinite" : "none",
  }),
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface MessageBubbleProps {
  message: Message;
  /** Tool calls to display inline (only for assistant messages). */
  toolCalls?: ToolCallIndicator[];
  /** Whether this message is still being streamed. */
  isStreaming?: boolean;
}

/** Format an ISO timestamp to a short time string. */
function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

/** Render basic markdown-like formatting for assistant messages. */
function renderContent(content: string, isUser: boolean): React.ReactNode {
  if (isUser) return content;

  // Split on code blocks (```...```) and render them differently
  const parts = content.split(/(```[\s\S]*?```)/g);

  return parts.map((part, i) => {
    if (part.startsWith("```") && part.endsWith("```")) {
      const code = part.slice(3, -3);
      // Strip optional language identifier on first line
      const lines = code.split("\n");
      const firstLine = lines[0]?.trim();
      const isLangId = firstLine && /^[a-zA-Z]+$/.test(firstLine);
      const codeContent = isLangId ? lines.slice(1).join("\n") : code;

      return (
        <pre
          key={i}
          style={{
            background: "var(--bg-primary)",
            padding: "8px 10px",
            borderRadius: 6,
            fontSize: 12,
            fontFamily: "var(--font-mono)",
            overflowX: "auto",
            margin: "6px 0",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {codeContent.trim()}
        </pre>
      );
    }

    // Handle inline code: `...`
    const inlineParts = part.split(/(`[^`]+`)/g);
    return (
      <span key={i}>
        {inlineParts.map((ip, j) => {
          if (ip.startsWith("`") && ip.endsWith("`")) {
            return (
              <code
                key={j}
                style={{
                  background: "var(--bg-primary)",
                  padding: "1px 5px",
                  borderRadius: 3,
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                }}
              >
                {ip.slice(1, -1)}
              </code>
            );
          }

          // Handle bold: **...**
          const boldParts = ip.split(/(\*\*[^*]+\*\*)/g);
          return boldParts.map((bp, k) => {
            if (bp.startsWith("**") && bp.endsWith("**")) {
              return (
                <strong key={`${j}-${k}`}>{bp.slice(2, -2)}</strong>
              );
            }
            return <React.Fragment key={`${j}-${k}`}>{bp}</React.Fragment>;
          });
        })}
      </span>
    );
  });
}

export function MessageBubble({
  message,
  toolCalls,
  isStreaming,
}: MessageBubbleProps): React.ReactElement {
  const isUser = message.role === "user";

  return (
    <div style={styles.wrapper(isUser)}>
      <div style={styles.role(isUser)}>
        {isUser ? "You" : "Redthread"}
      </div>

      <div style={styles.bubble(isUser)}>
        {renderContent(message.content, isUser)}

        {/* Streaming cursor */}
        {isStreaming && !isUser && (
          <span
            style={{
              display: "inline-block",
              width: 2,
              height: 14,
              background: "var(--text-primary)",
              marginLeft: 2,
              animation: "blink 1s step-end infinite",
              verticalAlign: "text-bottom",
            }}
          />
        )}

        {/* Tool call indicators */}
        {toolCalls && toolCalls.length > 0 && (
          <div style={styles.toolCallContainer}>
            {toolCalls.map((tc, idx) => (
              <div key={`${tc.tool}-${idx}`} style={styles.toolCall(tc.status)}>
                <div style={styles.toolDot(tc.status)} />
                <span>
                  {tc.tool}
                  {tc.status === "running" ? "..." : " done"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={styles.timestamp}>
        {formatTime(message.created_at)}
      </div>
    </div>
  );
}
