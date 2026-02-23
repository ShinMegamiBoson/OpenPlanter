"use client";

import { useWebSocket } from "@/hooks/useWebSocket";
import { ChatPanel } from "@/components/ChatPanel";
import { FileUpload } from "@/components/FileUpload";

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
  } = useWebSocket(DEV_INVESTIGATION_ID);

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
          <div className="panel__header">
            <span className="panel__title">Entity Graph</span>
          </div>
          <div className="panel__content">
            <div className="empty-state">
              <div className="empty-state__message">
                Entity relationships will appear here as the investigation
                progresses.
              </div>
            </div>
          </div>
        </div>

        {/* Timeline */}
        <div className="panel--timeline">
          <div className="panel__header">
            <span className="panel__title">Transaction Timeline</span>
          </div>
          <div className="panel__content">
            <div className="empty-state">
              <div className="empty-state__message">
                Transaction events will populate this timeline during analysis.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Right Panel: Evidence */}
      <section className="panel panel--evidence">
        <div className="panel__header">
          <span className="panel__title">Evidence Chain</span>
        </div>
        <div className="panel__content">
          <div className="empty-state">
            <div className="empty-state__message">
              Evidence entries with confidence levels and source citations will
              be listed here.
            </div>
            <div className="empty-state__hint">
              Filterable by entity and confidence
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
