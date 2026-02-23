"use client";

import { useCallback, useEffect, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { ChatPanel } from "@/components/ChatPanel";
import { FileUpload } from "@/components/FileUpload";
import { EntityGraph } from "@/components/EntityGraph";
import { Timeline } from "@/components/Timeline";
import { EvidencePanel } from "@/components/EvidencePanel";
import { getTimeline } from "@/lib/api";
import type { TimelineEvent } from "@/lib/types";

/**
 * Temporary hardcoded investigation ID for development.
 * In production this would come from route params or a selection screen.
 */
const DEV_INVESTIGATION_ID = "dev-investigation";

export default function Home() {
  const {
    messages,
    sendMessage,
    sendSubInvestigation,
    isConnected,
    isStreaming,
    toolCalls,
    lastError,
    graphData,
    evidenceData,
  } = useWebSocket(DEV_INVESTIGATION_ID);

  // -----------------------------------------------------------------
  // Timeline data from REST API
  // -----------------------------------------------------------------
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function fetchTimeline() {
      try {
        const data = await getTimeline(DEV_INVESTIGATION_ID);
        if (!cancelled) {
          setTimelineEvents(data.events);
        }
      } catch {
        // Silently ignore — backend may not be running during dev
      }
    }

    fetchTimeline();
    return () => {
      cancelled = true;
    };
  }, []);

  // Refresh timeline when evidence data changes (new evidence often
  // means new timeline events were also recorded by the agent).
  useEffect(() => {
    if (evidenceData.length === 0) return;
    let cancelled = false;

    async function refreshTimeline() {
      try {
        const data = await getTimeline(DEV_INVESTIGATION_ID);
        if (!cancelled) {
          setTimelineEvents(data.events);
        }
      } catch {
        // ignore
      }
    }

    refreshTimeline();
    return () => {
      cancelled = true;
    };
  }, [evidenceData.length]);

  // -----------------------------------------------------------------
  // Shared state: selected entity (graph <-> evidence panel)
  // -----------------------------------------------------------------
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  const handleNodeSelect = useCallback((entityId: string | null) => {
    setSelectedEntityId(entityId);
  }, []);

  const handleEntityClick = useCallback((entityId: string) => {
    setSelectedEntityId(entityId);
  }, []);

  return (
    <div className="workspace">
      {/* Header */}
      <header className="workspace-header">
        <div>
          <span className="workspace-header__title">REDTHREAD</span>
          <span className="workspace-header__subtitle">
            {" "}
            / Financial Crime Investigation
          </span>
        </div>
      </header>

      {/* Left Panel: Chat */}
      <section className="panel panel--chat">
        <FileUpload
          investigationId={DEV_INVESTIGATION_ID}
          onUploadComplete={sendMessage}
        />
        <ChatPanel
          messages={messages}
          onSendMessage={sendMessage}
          onSubInvestigate={sendSubInvestigation}
          isConnected={isConnected}
          isStreaming={isStreaming}
          toolCalls={toolCalls}
          lastError={lastError}
        />
      </section>

      {/* Center Panel: Visualizations */}
      <section className="panel--viz">
        {/* Entity Graph */}
        <div className="panel--graph">
          <EntityGraph
            graphData={graphData}
            onNodeSelect={handleNodeSelect}
          />
        </div>

        {/* Timeline */}
        <div className="panel--timeline">
          <Timeline events={timelineEvents} />
        </div>
      </section>

      {/* Right Panel: Evidence */}
      <section className="panel panel--evidence">
        <EvidencePanel
          evidence={evidenceData}
          selectedEntityId={selectedEntityId}
          onEntityClick={handleEntityClick}
        />
      </section>
    </div>
  );
}
