"use client";

import React, { useCallback, useMemo, useState } from "react";
import type { Confidence, EvidenceChain } from "@/lib/types";

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

  filterBar: {
    flexShrink: 0,
    padding: "8px var(--panel-padding)",
    borderBottom: "1px solid var(--border-subtle)",
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  } as React.CSSProperties,

  filterRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  } as React.CSSProperties,

  filterLabel: {
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
    flexShrink: 0,
    width: 52,
  } as React.CSSProperties,

  entitySelect: {
    flex: 1,
    background: "var(--bg-tertiary)",
    border: "1px solid var(--border-subtle)",
    borderRadius: 4,
    color: "var(--text-primary)",
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    padding: "3px 6px",
    outline: "none",
    cursor: "pointer",
  } as React.CSSProperties,

  confidenceCheckboxes: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap" as const,
  } as React.CSSProperties,

  checkboxLabel: {
    display: "flex",
    alignItems: "center",
    gap: 3,
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-secondary)",
    cursor: "pointer",
    userSelect: "none" as const,
  } as React.CSSProperties,

  checkbox: {
    accentColor: "var(--accent-blue)",
    cursor: "pointer",
    width: 12,
    height: 12,
  } as React.CSSProperties,

  sortRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px var(--panel-padding)",
    borderBottom: "1px solid var(--border-subtle)",
    flexShrink: 0,
  } as React.CSSProperties,

  sortButton: (active: boolean): React.CSSProperties => ({
    background: active ? "var(--bg-elevated)" : "transparent",
    border: `1px solid ${active ? "var(--border-active)" : "var(--border-subtle)"}`,
    borderRadius: 4,
    color: active ? "var(--text-primary)" : "var(--text-muted)",
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    padding: "2px 8px",
    cursor: "pointer",
    transition: "all 0.15s",
  }),

  listArea: {
    flex: 1,
    overflowY: "auto" as const,
    padding: "var(--panel-padding)",
  } as React.CSSProperties,

  entityGroup: {
    marginBottom: 16,
  } as React.CSSProperties,

  entityGroupHeader: {
    fontSize: 11,
    fontFamily: "var(--font-mono)",
    fontWeight: 600,
    color: "var(--text-secondary)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.06em",
    marginBottom: 8,
    paddingBottom: 4,
    borderBottom: "1px solid var(--border-subtle)",
  } as React.CSSProperties,

  evidenceCard: {
    background: "var(--bg-tertiary)",
    border: "1px solid var(--border-subtle)",
    borderRadius: 6,
    marginBottom: 6,
    overflow: "hidden",
    transition: "border-color 0.15s",
    cursor: "pointer",
  } as React.CSSProperties,

  evidenceCardHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    padding: "8px 10px",
    gap: 8,
  } as React.CSSProperties,

  claimText: {
    fontSize: 12,
    lineHeight: 1.5,
    color: "var(--text-primary)",
    flex: 1,
  } as React.CSSProperties,

  confidenceBadge: (confidence: Confidence): React.CSSProperties => {
    const colors: Record<Confidence, string> = {
      confirmed: "var(--confidence-confirmed)",
      probable: "var(--confidence-probable)",
      possible: "var(--confidence-possible)",
      unresolved: "var(--confidence-unresolved)",
    };
    return {
      flexShrink: 0,
      fontSize: 9,
      fontFamily: "var(--font-mono)",
      fontWeight: 600,
      textTransform: "uppercase" as const,
      letterSpacing: "0.06em",
      padding: "2px 6px",
      borderRadius: 3,
      background: `${colors[confidence]}20`,
      color: colors[confidence],
      border: `1px solid ${colors[confidence]}40`,
    };
  },

  expandedSection: {
    padding: "0 10px 10px 10px",
    borderTop: "1px solid var(--border-subtle)",
  } as React.CSSProperties,

  expandedLabel: {
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.06em",
    marginTop: 8,
    marginBottom: 4,
  } as React.CSSProperties,

  expandedText: {
    fontSize: 11,
    lineHeight: 1.6,
    color: "var(--text-secondary)",
    whiteSpace: "pre-wrap" as const,
  } as React.CSSProperties,

  sourceInfo: {
    display: "flex",
    gap: 12,
    marginTop: 6,
  } as React.CSSProperties,

  sourceTag: {
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    background: "var(--bg-elevated)",
    borderRadius: 3,
    padding: "1px 5px",
    border: "1px solid var(--border-subtle)",
  } as React.CSSProperties,

  dateText: {
    fontSize: 10,
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    marginTop: 4,
    padding: "0 10px",
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
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALL_CONFIDENCES: Confidence[] = [
  "confirmed",
  "probable",
  "possible",
  "unresolved",
];

type SortField = "date" | "confidence";

const CONFIDENCE_ORDER: Record<Confidence, number> = {
  confirmed: 0,
  probable: 1,
  possible: 2,
  unresolved: 3,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface EvidencePanelProps {
  /** Evidence chain entries from useWebSocket or REST API. */
  evidence: EvidenceChain[];
  /** Currently selected entity ID (from EntityGraph node click). */
  selectedEntityId?: string | null;
  /** Callback when an entity name is clicked (to highlight in graph). */
  onEntityClick?: (entityId: string) => void;
}

export function EvidencePanel({
  evidence,
  selectedEntityId,
  onEntityClick,
}: EvidencePanelProps): React.ReactElement {
  const [entityFilter, setEntityFilter] = useState<string>("all");
  const [confidenceFilter, setConfidenceFilter] = useState<Set<Confidence>>(
    new Set(ALL_CONFIDENCES),
  );
  const [sortBy, setSortBy] = useState<SortField>("date");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // -----------------------------------------------------------------------
  // Sync entity filter with external selection
  // -----------------------------------------------------------------------
  const effectiveEntityFilter = selectedEntityId ?? entityFilter;

  // -----------------------------------------------------------------------
  // Extract unique entities for the dropdown
  // -----------------------------------------------------------------------
  const entityOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of evidence) {
      if (e.entity_id) {
        // Use entity_id as key; try to find a display name from metadata
        if (!map.has(e.entity_id)) {
          map.set(e.entity_id, e.entity_id);
        }
      }
    }
    return Array.from(map.entries()).sort((a, b) =>
      a[1].localeCompare(b[1]),
    );
  }, [evidence]);

  // -----------------------------------------------------------------------
  // Filter and sort evidence
  // -----------------------------------------------------------------------
  const filteredEvidence = useMemo(() => {
    let result = evidence;

    // Filter by entity
    if (effectiveEntityFilter && effectiveEntityFilter !== "all") {
      result = result.filter((e) => e.entity_id === effectiveEntityFilter);
    }

    // Filter by confidence
    result = result.filter((e) => confidenceFilter.has(e.confidence));

    // Sort
    if (sortBy === "date") {
      result = [...result].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    } else {
      result = [...result].sort(
        (a, b) =>
          CONFIDENCE_ORDER[a.confidence] - CONFIDENCE_ORDER[b.confidence],
      );
    }

    return result;
  }, [evidence, effectiveEntityFilter, confidenceFilter, sortBy]);

  // -----------------------------------------------------------------------
  // Group filtered evidence by entity
  // -----------------------------------------------------------------------
  const groupedEvidence = useMemo(() => {
    const groups = new Map<string, EvidenceChain[]>();

    for (const entry of filteredEvidence) {
      const key = entry.entity_id ?? "unlinked";
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key)!.push(entry);
    }

    return groups;
  }, [filteredEvidence]);

  // -----------------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------------
  const toggleConfidence = useCallback((conf: Confidence) => {
    setConfidenceFilter((prev) => {
      const next = new Set(prev);
      if (next.has(conf)) {
        // Don't allow deselecting all
        if (next.size > 1) {
          next.delete(conf);
        }
      } else {
        next.add(conf);
      }
      return next;
    });
  }, []);

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  const isEmpty = evidence.length === 0;

  return (
    <div style={styles.container}>
      <div className="panel__header">
        <span className="panel__title">Evidence Chain</span>
        {!isEmpty && (
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}
          >
            {filteredEvidence.length}/{evidence.length}
          </span>
        )}
      </div>

      {isEmpty ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyMessage}>
            Evidence entries with confidence levels and source citations will
            be listed here.
          </div>
          <div style={styles.emptyHint}>
            Filterable by entity and confidence
          </div>
        </div>
      ) : (
        <>
          {/* Filter controls */}
          <div style={styles.filterBar}>
            {/* Entity filter */}
            <div style={styles.filterRow}>
              <span style={styles.filterLabel}>Entity</span>
              <select
                style={styles.entitySelect}
                value={effectiveEntityFilter === null ? "all" : effectiveEntityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
              >
                <option value="all">All entities</option>
                {entityOptions.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            {/* Confidence filter */}
            <div style={styles.filterRow}>
              <span style={styles.filterLabel}>Conf.</span>
              <div style={styles.confidenceCheckboxes}>
                {ALL_CONFIDENCES.map((conf) => (
                  <label key={conf} style={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={confidenceFilter.has(conf)}
                      onChange={() => toggleConfidence(conf)}
                      style={styles.checkbox}
                    />
                    {conf}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Sort controls */}
          <div style={styles.sortRow}>
            <span style={styles.filterLabel}>Sort</span>
            <button
              type="button"
              style={styles.sortButton(sortBy === "date")}
              onClick={() => setSortBy("date")}
            >
              Date
            </button>
            <button
              type="button"
              style={styles.sortButton(sortBy === "confidence")}
              onClick={() => setSortBy("confidence")}
            >
              Confidence
            </button>
          </div>

          {/* Evidence list */}
          <div style={styles.listArea}>
            {filteredEvidence.length === 0 ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyMessage}>
                  No evidence matches the current filters.
                </div>
              </div>
            ) : (
              Array.from(groupedEvidence.entries()).map(([entityId, entries]) => (
                <div key={entityId} style={styles.entityGroup}>
                  <div
                    style={{
                      ...styles.entityGroupHeader,
                      cursor: onEntityClick && entityId !== "unlinked" ? "pointer" : "default",
                    }}
                    onClick={() => {
                      if (onEntityClick && entityId !== "unlinked") {
                        onEntityClick(entityId);
                      }
                    }}
                  >
                    {entityId === "unlinked" ? "Unlinked Evidence" : entityId}
                  </div>

                  {entries.map((entry) => {
                    const isExpanded = expandedIds.has(entry.id);
                    return (
                      <div
                        key={entry.id}
                        style={{
                          ...styles.evidenceCard,
                          borderColor: isExpanded
                            ? "var(--border-active)"
                            : "var(--border-subtle)",
                        }}
                        onClick={() => toggleExpanded(entry.id)}
                      >
                        {/* Header: claim + badge */}
                        <div style={styles.evidenceCardHeader}>
                          <span style={styles.claimText}>{entry.claim}</span>
                          <span style={styles.confidenceBadge(entry.confidence)}>
                            {entry.confidence}
                          </span>
                        </div>

                        {/* Date */}
                        <div style={styles.dateText}>
                          {formatDate(entry.created_at)}
                        </div>

                        {/* Expanded: supporting evidence + source refs */}
                        {isExpanded && (
                          <div style={styles.expandedSection}>
                            <div style={styles.expandedLabel}>
                              Supporting Evidence
                            </div>
                            <div style={styles.expandedText}>
                              {entry.supporting_evidence}
                            </div>

                            {(entry.source_dataset_id || entry.source_record_id) && (
                              <>
                                <div style={styles.expandedLabel}>
                                  Source References
                                </div>
                                <div style={styles.sourceInfo}>
                                  {entry.source_dataset_id && (
                                    <span style={styles.sourceTag}>
                                      Dataset: {entry.source_dataset_id}
                                    </span>
                                  )}
                                  {entry.source_record_id && (
                                    <span style={styles.sourceTag}>
                                      Record: {entry.source_record_id}
                                    </span>
                                  )}
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
