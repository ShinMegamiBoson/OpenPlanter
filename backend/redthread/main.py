"""FastAPI application for Redthread.

Wires together the persistence layer, agent, and API routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from redthread.config import Settings
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    InvestigationRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB
from redthread.security import secure_directory, secure_file

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Initializes database connections and the agent on startup,
    cleans up on shutdown.
    """
    # Ensure data and upload directories exist with proper permissions
    data_dir = Path(settings.DATABASE_DIR)
    upload_dir = Path(settings.UPLOAD_DIR)
    secure_directory(data_dir)
    secure_directory(upload_dir)

    # Initialize SQLite
    db_path = str(data_dir / "redthread.db")
    db = SQLiteDB(db_path)
    secure_file(Path(db_path))

    # Initialize graph DB (NetworkX fallback)
    graph_path = str(data_dir / "graph.json")
    graph_db = NetworkXGraphDB(graph_path)

    # Create repositories
    investigation_repo = InvestigationRepo(db, graph_db)
    dataset_repo = DatasetRepo(db, graph_db)
    evidence_repo = EvidenceRepo(db, graph_db)
    timeline_repo = TimelineEventRepo(db, graph_db)
    message_repo = MessageRepo(db, graph_db)

    # Store on app.state for access in routes
    app.state.settings = settings
    app.state.db = db
    app.state.graph_db = graph_db
    app.state.investigation_repo = investigation_repo
    app.state.dataset_repo = dataset_repo
    app.state.evidence_repo = evidence_repo
    app.state.timeline_repo = timeline_repo
    app.state.message_repo = message_repo

    # Initialize agent (if API key available)
    if settings.ANTHROPIC_API_KEY:
        from redthread.agent.client import RedthreadAgent, Repositories

        repos = Repositories(
            dataset_repo=dataset_repo,
            evidence_repo=evidence_repo,
            timeline_repo=timeline_repo,
            message_repo=message_repo,
        )
        app.state.agent = RedthreadAgent(
            settings=settings,
            db=db,
            graph_db=graph_db,
            repos=repos,
        )
    else:
        app.state.agent = None

    yield

    # Shutdown: close connections and persist graph
    graph_db.close()
    db.close()


app = FastAPI(
    title="Redthread",
    description="Financial crime investigation agent for BSA/AML analysts",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware using Settings.FRONTEND_URL
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes and WebSocket
from redthread.api.routes import router as api_router
from redthread.api.websocket import router as ws_router

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
