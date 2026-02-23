"""FastAPI application skeleton for Redthread."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from redthread.config import Settings

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Placeholder for startup/shutdown logic. Database connections
    (SQLite + graph DB) will be initialized here and stored in app.state
    once the persistence layer is implemented.
    """
    # Startup: DB connections will be wired in here later.
    yield
    # Shutdown: DB connection cleanup will go here later.


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

# Stub routers for /api/v1 and /ws
api_v1_router = APIRouter(prefix="/api/v1")
ws_router = APIRouter(prefix="/ws")

app.include_router(api_v1_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
