export default function Home() {
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
        <div className="panel__header">
          <span className="panel__title">Investigation Chat</span>
        </div>
        <div className="panel__content">
          <div className="empty-state">
            <div className="empty-state__message">
              Start an investigation by uploading a dataset or describing what
              you want to analyze.
            </div>
            <div className="empty-state__hint">
              Supports CSV, JSON, and XLSX files
            </div>
          </div>
        </div>
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
