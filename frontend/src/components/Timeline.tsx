"use client";

import React, { useMemo } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import type { TimelineEvent } from "@/lib/types";

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

  chartWrapper: {
    flex: 1,
    padding: "8px 12px 0 0",
    minHeight: 0,
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

  tooltipContainer: {
    background: "#1a1a24",
    border: "1px solid #2a2a3a",
    borderRadius: 6,
    padding: "8px 12px",
    fontSize: 12,
    fontFamily: "Inter, -apple-system, sans-serif",
    color: "#e4e4eb",
    maxWidth: 260,
  } as React.CSSProperties,

  tooltipLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 11,
    color: "#9494a8",
    marginBottom: 4,
  } as React.CSSProperties,

  tooltipRow: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    marginTop: 2,
  } as React.CSSProperties,

  tooltipKey: {
    color: "#9494a8",
    fontSize: 11,
  } as React.CSSProperties,

  tooltipValue: {
    color: "#e4e4eb",
    fontSize: 11,
    fontFamily: '"JetBrains Mono", monospace',
    textAlign: "right" as const,
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Color palette for different entities on the scatter plot. */
const ENTITY_COLORS = [
  "#4a7cff", // blue
  "#3ac47d", // green
  "#e6883a", // orange
  "#8a6aff", // purple
  "#e64a4a", // red
  "#4acce6", // cyan
  "#e6d44a", // yellow
  "#c44aff", // magenta
];

// ---------------------------------------------------------------------------
// Custom Tooltip
// ---------------------------------------------------------------------------

interface TooltipPayloadEntry {
  payload?: {
    date?: string;
    amount?: number;
    entity_name?: string;
    description?: string;
  };
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}

function TimelineTooltip({
  active,
  payload,
}: CustomTooltipProps): React.ReactElement | null {
  if (!active || !payload || payload.length === 0) return null;

  const data = payload[0]?.payload;
  if (!data) return null;

  return (
    <div style={styles.tooltipContainer}>
      <div style={styles.tooltipLabel}>{data.date}</div>
      {data.entity_name && (
        <div style={styles.tooltipRow}>
          <span style={styles.tooltipKey}>Entity</span>
          <span style={styles.tooltipValue}>{data.entity_name}</span>
        </div>
      )}
      {data.amount != null && (
        <div style={styles.tooltipRow}>
          <span style={styles.tooltipKey}>Amount</span>
          <span style={styles.tooltipValue}>
            {formatAmount(data.amount)}
          </span>
        </div>
      )}
      {data.description && (
        <div style={{ ...styles.tooltipRow, marginTop: 6 }}>
          <span style={{ ...styles.tooltipKey, flex: 1 }}>
            {data.description}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a numeric amount as a currency-like string. */
function formatAmount(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount);
}

/** Format a date string for axis display. */
function formatAxisDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return `${(d.getMonth() + 1).toString().padStart(2, "0")}/${d.getDate().toString().padStart(2, "0")}`;
  } catch {
    return dateStr;
  }
}

/** Assign a stable color index to each entity. */
function getEntityColor(index: number): string {
  return ENTITY_COLORS[index % ENTITY_COLORS.length];
}

// ---------------------------------------------------------------------------
// Data transformation
// ---------------------------------------------------------------------------

interface ScatterPoint {
  date: string;
  dateTimestamp: number;
  amount: number;
  entity_id: string;
  entity_name: string;
  description: string;
}

/** Group timeline events by entity for separate scatter series. */
function groupByEntity(
  events: TimelineEvent[],
): Map<string, { entityName: string; points: ScatterPoint[] }> {
  const groups = new Map<
    string,
    { entityName: string; points: ScatterPoint[] }
  >();

  for (const event of events) {
    const entityId = event.entity_id ?? "unknown";
    const entityName = event.entity_name ?? "Unknown";

    if (!groups.has(entityId)) {
      groups.set(entityId, { entityName, points: [] });
    }

    groups.get(entityId)!.points.push({
      date: event.event_date,
      dateTimestamp: new Date(event.event_date).getTime(),
      amount: event.amount ?? 0,
      entity_id: entityId,
      entity_name: entityName,
      description: event.description ?? "",
    });
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TimelineProps {
  /** Timeline events from REST API. */
  events: TimelineEvent[];
}

export function Timeline({ events }: TimelineProps): React.ReactElement {
  const entityGroups = useMemo(() => groupByEntity(events), [events]);
  const isEmpty = events.length === 0;

  // Compute domain for the X axis
  const allTimestamps = useMemo(() => {
    return events.map((e) => new Date(e.event_date).getTime());
  }, [events]);

  const xDomain = useMemo<[number, number]>(() => {
    if (allTimestamps.length === 0) return [0, 1];
    const min = Math.min(...allTimestamps);
    const max = Math.max(...allTimestamps);
    // Add 5% padding on each side
    const pad = Math.max((max - min) * 0.05, 86400000); // at least 1 day padding
    return [min - pad, max + pad];
  }, [allTimestamps]);

  return (
    <div style={styles.container}>
      <div className="panel__header">
        <span className="panel__title">Transaction Timeline</span>
      </div>
      {isEmpty ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyMessage}>
            Transaction events will populate this timeline during analysis.
          </div>
          <div style={styles.emptyHint}>
            Scatter plot grouped by entity
          </div>
        </div>
      ) : (
        <div style={styles.chartWrapper}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              margin={{ top: 8, right: 12, bottom: 8, left: 12 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#2a2a3a"
                vertical={false}
              />
              <XAxis
                dataKey="dateTimestamp"
                type="number"
                domain={xDomain}
                tickFormatter={(ts: number) =>
                  formatAxisDate(new Date(ts).toISOString())
                }
                tick={{ fill: "#9494a8", fontSize: 10, fontFamily: '"JetBrains Mono", monospace' }}
                axisLine={{ stroke: "#2a2a3a" }}
                tickLine={{ stroke: "#2a2a3a" }}
                scale="time"
              />
              <YAxis
                dataKey="amount"
                tick={{ fill: "#9494a8", fontSize: 10, fontFamily: '"JetBrains Mono", monospace' }}
                axisLine={{ stroke: "#2a2a3a" }}
                tickLine={{ stroke: "#2a2a3a" }}
                tickFormatter={(val: number) => {
                  if (Math.abs(val) >= 1_000_000) return `$${(val / 1_000_000).toFixed(1)}M`;
                  if (Math.abs(val) >= 1_000) return `$${(val / 1_000).toFixed(0)}K`;
                  return `$${val}`;
                }}
                width={60}
              />
              <Tooltip
                content={<TimelineTooltip />}
                cursor={false}
              />
              <Legend
                verticalAlign="top"
                height={28}
                wrapperStyle={{
                  fontSize: 11,
                  fontFamily: '"JetBrains Mono", monospace',
                  color: "#9494a8",
                }}
              />
              {Array.from(entityGroups.entries()).map(
                ([entityId, group], index) => (
                  <Scatter
                    key={entityId}
                    name={group.entityName}
                    data={group.points}
                    fill={getEntityColor(index)}
                    opacity={0.85}
                    r={5}
                  />
                ),
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
