# Redthread v2 Rebuild - Technical Plan

**Date:** 2026-02-22
**Status:** Planning
**PRD:** `docs/prd/2026-02-22-openplanter-v2-rebuild-prd.md`

## Overview

Rebuild OpenPlanter as Redthread — a web-based financial crime investigation agent for BSA/AML analysts. The system consists of a Python backend (FastAPI + Anthropic Agent SDK) and a React frontend (Next.js) running in Docker containers. The agent uses structured tools for file ingestion, entity resolution, OFAC screening, web search, and evidence tracking. Data persists in SQLite (relational) and LadybugDB (graph). The frontend renders a chat panel, entity relationship graph (Cytoscape.js), and transaction timeline (Recharts).

This plan covers the full v1 scope from the PRD. Subtasks are ordered so each builds on prior work, enabling incremental delivery.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Docker Compose                     │
│                                                      │
│  ┌──────────────────────┐  ┌──────────────────────┐ │
│  │   Frontend (Next.js) │  │  Backend (FastAPI)    │ │
│  │                      │  │                       │ │
│  │  ChatPanel           │  │  WebSocket /ws/chat   │ │
│  │  EntityGraph (Cyto)  │◄─┤  REST /api/v1/...    │ │
│  │  Timeline (Recharts) │  │                       │ │
│  │  EvidencePanel       │  │  ┌─────────────────┐  │ │
│  │  FileUpload          │  │  │  Agent SDK       │  │ │
│  └──────────────────────┘  │  │  ClaudeSDKClient │  │ │
│                            │  │                   │  │ │
│                            │  │  Tools (MCP):     │  │ │
│                            │  │  - ingest_file    │  │ │
│                            │  │  - resolve_entity │  │ │
│                            │  │  - screen_ofac    │  │ │
│                            │  │  - web_search     │  │ │
│                            │  │  - record_evidence│  │ │
│                            │  │  - generate_sar   │  │ │
│                            │  └────────┬──────────┘  │ │
│                            │           │             │ │
│                            │  ┌────────▼──────────┐  │ │
│                            │  │  Persistence       │  │ │
│                            │  │  SQLite + LadybugDB│  │ │
│                            │  └───────────────────┘  │ │
│                            └──────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Key architectural decisions:**

- **Agent SDK tools as in-process MCP servers.** Each investigation capability is a Python function decorated with `@tool`, assembled into a Model Context Protocol (MCP) server — the standard interface through which the Claude agent discovers and calls tools — via `create_sdk_mcp_server()`. The agent accesses them as `mcp__redthread__<tool_name>`. This keeps all tools in one process with shared access to the persistence layer.
- **Dual persistence.** SQLite for structured relational data (evidence chains, sessions, ingested records, metadata). LadybugDB for entity graph (nodes, relationships, traversal). Both embedded, zero-config. Graph layer abstracted behind a Python protocol for swappability to NetworkX fallback.
- **WebSocket streaming.** Backend streams agent responses token-by-token to the frontend over WebSocket. Agent SDK's `include_partial_messages=True` yields `StreamEvent` objects that the backend forwards as JSON frames.
- **Sub-agents for autonomous deep-dives.** Analyst-initiated sub-investigations use `AgentDefinition` + `Task` tool in the Agent SDK. Sub-agents inherit the same MCP tool server but get a narrower system prompt focused on their specific question.

---

## 1. Project Scaffolding & Infrastructure

#### 1.1 Create monorepo structure and root configuration

**Depends on:** none
**Files:** `backend/pyproject.toml`, `backend/redthread/__init__.py`, `backend/redthread/config.py`, `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.js`, `.gitignore`

Create the top-level monorepo layout under the existing repo root. The `backend/` directory is a Python package managed by pyproject.toml. The `frontend/` directory is a Next.js 14 app with TypeScript.

Backend dependencies (pyproject.toml):
- Runtime: `fastapi`, `uvicorn[standard]`, `websockets`, `claude-agent-sdk`, `lbug` (LadybugDB), `rapidfuzz`, `jellyfish`, `cleanco`, `nameparser`, `splink`, `duckdb`, `openpyxl`, `aiofiles`, `pydantic`, `pydantic-settings`, `httpx`, `chardet`
- Dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`

Frontend dependencies (package.json):
- Runtime: `next`, `react`, `react-dom`, `cytoscape`, `recharts`
- Dev: `typescript`, `@types/react`, `@types/node`, `@types/cytoscape`, `eslint`, `eslint-config-next`

`config.py` uses pydantic-settings `BaseSettings` to load from environment variables: `ANTHROPIC_API_KEY`, `EXA_API_KEY`, `DATABASE_DIR` (default `./data`), `OFAC_SDN_PATH`, `UPLOAD_DIR` (default `./uploads`), `FRONTEND_URL` (for CORS).

Update root `.gitignore` to include `data/`, `uploads/`, `__pycache__/`, `node_modules/`, `.next/`, `.env`.

**Test scenarios:** (`backend/tests/test_config.py`)
- Default settings load without errors when no env vars set (uses defaults)
- `DATABASE_DIR` override via env var is respected
- Missing `ANTHROPIC_API_KEY` loads as `None` (not a startup crash — validated at agent init time)

**Verify:** `cd backend && pip install -e ".[dev]"` completes. `cd frontend && npm install` completes. `python -c "from redthread.config import Settings; Settings()"` succeeds.

#### 1.2 Set up Docker Compose with backend and frontend services

**Depends on:** 1.1
**Files:** `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`

Backend Dockerfile: Python 3.12 slim base, copies `pyproject.toml`, installs deps, copies source. Exposes port 8000. CMD: `uvicorn redthread.main:app --host 0.0.0.0 --port 8000`.

Frontend Dockerfile: Node 20 alpine, copies `package.json`, installs deps, copies source. Exposes port 3000. CMD: `npm run dev` (dev mode; production build is future optimization).

docker-compose.yml defines two services:
- `backend`: builds from `./backend`, mounts `./data` and `./uploads` as volumes, reads `.env` for API keys, exposes 8000.
- `frontend`: builds from `./frontend`, env var `NEXT_PUBLIC_API_URL=http://localhost:8000`, exposes 3000, depends_on backend.

Both services mount source directories for hot-reload during development.

**Test scenarios:** (manual)
- `docker compose build` succeeds for both services
- `docker compose up` starts both containers without crashes
- Backend health endpoint responds at `http://localhost:8000/health`
- Frontend loads at `http://localhost:3000`

**Verify:** `docker compose up --build -d && curl http://localhost:8000/health && docker compose down`

#### 1.3 Create FastAPI application skeleton with health endpoint

**Depends on:** 1.1
**Files:** `backend/redthread/main.py`, `backend/tests/test_main.py`

Minimal FastAPI app with:
- CORS middleware (origins from `Settings.FRONTEND_URL`)
- `GET /health` returning `{"status": "ok"}`
- Lifespan handler that initializes and tears down database connections (SQLite + graph DB) as app state
- Router includes for `/api/v1` (stubbed) and WebSocket `/ws` (stubbed)

Pattern: Use FastAPI's lifespan context manager for startup/shutdown. Store DB connections in `app.state`.

**Test scenarios:** (`backend/tests/test_main.py`)
- `GET /health` returns 200 with `{"status": "ok"}`
- CORS headers present on response when `Origin` header sent
- App starts and shuts down without errors

**Verify:** `cd backend && pytest tests/test_main.py -v`

#### 1.4 Create Next.js application skeleton with layout

**Depends on:** 1.1
**Files:** `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/src/app/globals.css`, `frontend/src/lib/types.ts`

Next.js 14 App Router skeleton. Layout renders a three-panel workspace:
- Left: Chat panel (placeholder div)
- Center: Visualization area — entity graph on top, timeline on bottom (placeholder divs)
- Right: Evidence panel (placeholder div)

Use CSS Grid for the layout. Dark theme matching financial/compliance tool aesthetics (dark background, subtle borders, monospace accents).

`types.ts` defines shared TypeScript interfaces: `Message`, `Entity`, `Relationship`, `EvidenceChain`, `TimelineEvent`, `Investigation`. These mirror the backend Pydantic models.

**Test scenarios:** (manual)
- `npm run dev` starts without errors
- Layout renders with three visible panel regions
- Page is accessible at `http://localhost:3000`

**Verify:** `cd frontend && npm run build` succeeds without TypeScript errors.

---

## 2. Persistence Layer

#### 2.1 Implement SQLite database schema and connection manager

**Depends on:** 1.1
**Files:** `backend/redthread/db/sqlite.py`, `backend/redthread/db/models.py`, `backend/tests/test_sqlite.py`

SQLite database with the following tables:

```sql
-- Investigation sessions
investigations (
  id TEXT PRIMARY KEY,  -- uuid
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,  -- ISO 8601
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',  -- active | archived
  metadata TEXT  -- JSON blob for extensibility
);

-- Ingested datasets
datasets (
  id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id),
  filename TEXT NOT NULL,
  file_type TEXT NOT NULL,  -- csv | json | xlsx
  row_count INTEGER,
  column_names TEXT,  -- JSON array
  ingested_at TEXT NOT NULL,
  validation_warnings TEXT  -- JSON array
);

-- Ingested records (normalized rows from datasets)
records (
  id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL REFERENCES datasets(id),
  row_number INTEGER NOT NULL,
  data TEXT NOT NULL  -- JSON object of column:value pairs
);

-- Evidence chains
evidence_chains (
  id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id),
  entity_id TEXT,  -- references graph entity node
  claim TEXT NOT NULL,
  supporting_evidence TEXT NOT NULL,
  source_record_id TEXT REFERENCES records(id),
  source_dataset_id TEXT REFERENCES datasets(id),
  confidence TEXT NOT NULL CHECK(confidence IN ('confirmed','probable','possible','unresolved')),
  created_at TEXT NOT NULL,
  metadata TEXT  -- JSON blob
);

-- Timeline events (transactions, transfers, significant dated events)
timeline_events (
  id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id),
  entity_id TEXT,
  entity_name TEXT,
  event_date TEXT NOT NULL,  -- ISO 8601
  amount REAL,
  description TEXT,
  source_record_id TEXT REFERENCES records(id),
  source_dataset_id TEXT REFERENCES datasets(id),
  created_at TEXT NOT NULL
);

-- Chat messages
messages (
  id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id),
  role TEXT NOT NULL,  -- user | assistant
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

Connection manager: a class `SQLiteDB` with `__init__(db_path)`, context manager support, `execute()`, `executemany()`, `fetchone()`, `fetchall()`. Enables WAL mode and foreign keys on connect.

Pydantic models in `models.py`: `Investigation`, `Dataset`, `Record`, `EvidenceChain`, `TimelineEvent`, `Message` — matching the table schemas. These are shared between DB layer and API responses.

**Test scenarios:** (`backend/tests/test_sqlite.py`)
- Schema creates all tables on fresh database
- Insert and retrieve an investigation round-trips correctly
- Insert evidence chain with all required fields succeeds
- Evidence chain with invalid confidence value raises constraint error
- Foreign key constraint prevents orphaned evidence chains (nonexistent investigation_id)
- Query evidence chains filtered by entity_id returns correct subset
- Query evidence chains filtered by confidence returns correct subset
- WAL mode is enabled after connection

**Verify:** `cd backend && pytest tests/test_sqlite.py -v`

#### 2.2 Implement graph database interface and LadybugDB adapter

**Depends on:** 1.1
**Files:** `backend/redthread/db/graph.py`, `backend/tests/test_graph.py`

Define a Python `Protocol` (abstract interface) for graph operations:

```python
class GraphDB(Protocol):
    def add_entity(self, entity_id: str, entity_type: str, name: str, properties: dict) -> None: ...
    def add_relationship(self, source_id: str, target_id: str, rel_type: str, properties: dict) -> None: ...
    def get_entity(self, entity_id: str) -> dict | None: ...
    def get_relationships(self, entity_id: str) -> list[dict]: ...
    def get_all_entities(self, investigation_id: str) -> list[dict]: ...
    def get_all_relationships(self, investigation_id: str) -> list[dict]: ...
    def find_path(self, source_id: str, target_id: str) -> list[dict]: ...
    def close(self) -> None: ...
```

LadybugDB implementation (`LadybugGraphDB`):
- Node table: `Entity(id STRING, investigation_id STRING, entity_type STRING, name STRING, properties STRING, PRIMARY KEY(id))`
- Relationship table groups: `RELATES_TO`, `TRANSACTED_WITH`, `AFFILIATED_WITH`, `LOCATED_AT` — each `FROM Entity TO Entity` with properties STRING + created_at STRING.
- Uses Cypher queries via `lbug.Connection`. Schema created on init if tables don't exist (use `CREATE NODE TABLE IF NOT EXISTS`).
- `find_path` uses variable-length path query: `MATCH p = (a)-[*1..5]-(b) WHERE a.id = $src AND b.id = $dst RETURN p LIMIT 1`.

Fallback: If LadybugDB import fails, log a warning and provide a `NetworkXGraphDB` fallback using `networkx.MultiDiGraph` with JSON file persistence. Same interface, no Cypher — just Python graph operations.

Rationale: Abstracting behind Protocol lets us swap implementations without touching any consumer code. LadybugDB is pre-1.0 — the fallback is a safety net. (Satisfies the PRD's swappability requirement from Resolved Questions.)

**Test scenarios:** (`backend/tests/test_graph.py`)
- Add entity and retrieve by ID returns correct data
- Add relationship between two entities and retrieve relationships returns it
- Get all entities filtered by investigation_id returns correct subset
- Find path between connected entities returns non-empty path
- Find path between disconnected entities returns empty list
- Duplicate entity ID raises or updates gracefully
- Graph DB closes without errors
- (If testing fallback) NetworkXGraphDB passes the same test suite

**Verify:** `cd backend && pytest tests/test_graph.py -v`

#### 2.3 Implement data access repositories

**Depends on:** 2.1, 2.2
**Files:** `backend/redthread/db/repositories.py`, `backend/tests/test_repositories.py`

Repository classes that combine SQLite and graph operations:

- `InvestigationRepo`: create, get, list, update status. On create, initializes a fresh LadybugDB database file scoped to the investigation.
- `DatasetRepo`: create, get by investigation, store records in batch.
- `EvidenceRepo`: create chain entry, query by investigation, query by entity_id, query by confidence. Satisfies R8 acceptance criteria.
- `TimelineEventRepo`: create event, query by investigation (sorted by event_date), query by entity_id.
- `MessageRepo`: append message, get conversation history for investigation.

Each repo takes `SQLiteDB` and `GraphDB` instances (dependency injection). Repositories are the single entry point for all persistence — no direct DB access from tools or API routes.

**Test scenarios:** (`backend/tests/test_repositories.py`)
- Create investigation and retrieve it
- Create dataset with records and retrieve records by dataset
- Create evidence chain and query by entity returns it
- Create evidence chain and query by confidence='confirmed' returns only confirmed entries
- Message repo appends and retrieves in chronological order
- Timeline event repo creates event and queries by investigation sorted by event_date
- Timeline event repo queries by entity_id returns correct subset
- Investigation listing returns all investigations sorted by updated_at desc

**Verify:** `cd backend && pytest tests/test_repositories.py -v`

---

## 3. File Ingestion Pipeline

#### 3.1 Implement file parsers for CSV, JSON, and XLSX

**Depends on:** 1.1
**Files:** `backend/redthread/ingestion/parsers.py`, `backend/tests/test_parsers.py`

Parser module with a unified interface:

```python
@dataclass
class ParseResult:
    rows: list[dict[str, Any]]  # column:value dicts
    column_names: list[str]
    row_count: int
    warnings: list[str]  # validation issues
    file_type: str

def parse_file(path: Path, file_type: str) -> ParseResult: ...
```

Implementations:
- **CSV:** `csv.DictReader` with encoding detection via `chardet` (add to deps). Handle BOM, detect delimiter. Warning on rows with mismatched column count.
- **JSON:** Support both JSON array of objects and JSON Lines (one object per line). Warning on mixed schemas across rows.
- **XLSX:** `openpyxl` in read-only mode (memory efficient for large files). First row as headers. Warning on empty rows, merged cells.

File size guard: Reject files > 50 MB with a clear error. For files approaching 500K rows, parse in streaming mode (CSV uses iterator, XLSX uses `iter_rows`). Store parsed rows as JSON dicts.

Best-effort parsing: malformed rows produce a warning entry but don't abort the parse. The ParseResult includes both valid rows and a warnings list. (Satisfies R1 acceptance criteria for validation warnings.)

**Test scenarios:** (`backend/tests/test_parsers.py`)
- Parse well-formed CSV returns correct rows and column names
- Parse CSV with BOM encoding succeeds
- Parse CSV with inconsistent column counts produces warnings but still parses valid rows
- Parse JSON array returns correct rows
- Parse JSON Lines format returns correct rows
- Parse XLSX returns correct rows from first sheet
- File > 50 MB rejected with clear error message
- Empty file returns zero rows with a warning
- File with non-UTF-8 encoding is detected and parsed correctly
- Malformed JSON produces warning, returns parseable rows

**Verify:** `cd backend && pytest tests/test_parsers.py -v`

#### 3.2 Implement file ingestion Agent SDK tool

**Depends on:** 3.1, 2.3
**Files:** `backend/redthread/agent/tools/ingest.py`, `backend/tests/test_tool_ingest.py`

Agent SDK tool that the agent calls to ingest an uploaded file into an investigation:

```python
@tool
def ingest_file(
    file_path: str,
    investigation_id: str,
    description: str = "",
) -> str:
    """Ingest a local data file (CSV, JSON, XLSX) into the investigation.
    Parses the file, stores records in the database, and returns a summary
    including column names, row count, and any validation warnings."""
```

The tool:
1. Detects file type from extension
2. Calls `parse_file()` to get ParseResult
3. Creates a Dataset record via `DatasetRepo`
4. Stores all parsed rows as Record entries (batch insert)
5. Returns a structured summary: filename, row_count, column_names, warnings (if any)

Returns clear error messages for unsupported file types, files not found, or parse failures. (Satisfies R1.)

**Test scenarios:** (`backend/tests/test_tool_ingest.py`)
- Ingest a CSV file creates dataset and records in DB
- Ingest returns summary with correct row count and column names
- Ingest file with validation warnings includes warnings in response
- Ingest unsupported file type returns error message
- Ingest nonexistent file returns error message
- Ingested records are retrievable from DatasetRepo

**Verify:** `cd backend && pytest tests/test_tool_ingest.py -v`

---

## 4. Entity Resolution

#### 4.1 Implement Tier 1 pairwise entity resolution

**Depends on:** 1.1
**Files:** `backend/redthread/entity/pairwise.py`, `backend/tests/test_pairwise.py`

Pairwise entity comparison using four libraries in combination:

```python
@dataclass
class MatchResult:
    score: float  # 0.0-1.0 composite score
    name_similarity: float  # rapidfuzz ratio
    phonetic_match: bool  # jellyfish soundex/metaphone
    normalized_a: str
    normalized_b: str
    match_type: str  # exact | fuzzy | phonetic | weak

def compare_entities(name_a: str, name_b: str, entity_type: str = "unknown") -> MatchResult: ...
```

Pipeline:
1. **Normalize:** Strip whitespace, lowercase, remove punctuation
2. **Business suffix strip:** `cleanco.basename()` for business entities (removes LLC, Inc, Corp, Ltd, etc.)
3. **Human name decomposition:** `nameparser.HumanName` for person entities (handles "Smith, John" vs "John Smith", suffixes like Jr/Sr)
4. **Fuzzy score:** `rapidfuzz.fuzz.token_sort_ratio` (handles word reordering)
5. **Phonetic check:** `jellyfish.soundex` comparison as a secondary signal
6. **Composite score:** Weighted combination — fuzzy score (0.7) + phonetic bonus (0.15 if match) + exact-after-normalization bonus (0.15)

Thresholds: `>= 0.95` = confirmed, `>= 0.80` = probable, `>= 0.60` = possible, `< 0.60` = unresolved. These map directly to the PRD's confidence tiers. (Satisfies R9.)

**Test scenarios:** (`backend/tests/test_pairwise.py`)
- "ACME LLC" vs "Acme" → confirmed (suffix stripping + normalization)
- "John Smith" vs "Smith, John" → confirmed (name parsing + token sort)
- "Johnson & Johnson" vs "Johnson and Johnson" → confirmed (punctuation normalization)
- "Robert Smith" vs "Bob Smith" → possible (phonetic helps but not exact)
- "Completely Different" vs "Something Else" → unresolved
- "Deutsche Bank AG" vs "Deutsche Bank" → confirmed (suffix stripping)
- Empty string input → handled gracefully (returns unresolved, score 0)

**Verify:** `cd backend && pytest tests/test_pairwise.py -v`

#### 4.2 Implement entity graph operations tool

**Depends on:** 2.2, 4.1
**Files:** `backend/redthread/agent/tools/entity.py`, `backend/tests/test_tool_entity.py`

Agent SDK tools for entity operations:

```python
@tool
def resolve_entity(
    name: str,
    entity_type: str,
    investigation_id: str,
    source_record_id: str = "",
) -> str:
    """Resolve an entity name against known entities in the investigation graph.
    If a match is found above the 'probable' threshold, returns the existing entity.
    If no match, creates a new entity node. Returns the entity ID and any matches found."""

@tool
def add_relationship(
    source_entity_id: str,
    target_entity_id: str,
    relationship_type: str,
    properties: str = "{}",
    investigation_id: str = "",
) -> str:
    """Add a typed relationship between two entities in the investigation graph.
    relationship_type should be one of: TRANSACTED_WITH, AFFILIATED_WITH, LOCATED_AT, RELATES_TO."""

@tool
def query_entity_graph(
    investigation_id: str,
    entity_id: str = "",
) -> str:
    """Query the entity graph. If entity_id is provided, returns that entity and its
    immediate relationships. Otherwise returns the full graph for the investigation."""
```

`resolve_entity` workflow:
1. Fetch all entities for the investigation from graph DB
2. Compare input name against each using `compare_entities()` from 4.1
3. If best match >= probable threshold: return existing entity (with match details)
4. Otherwise: create new entity node in graph, return new entity ID

**Test scenarios:** (`backend/tests/test_tool_entity.py`)
- Resolve a new entity creates a node in the graph
- Resolve a name that fuzzy-matches an existing entity returns the existing entity ID
- Add relationship between two entities creates edge in graph
- Query graph for investigation returns all entities and relationships
- Query graph for specific entity returns its relationships
- Resolve with empty name returns error

**Verify:** `cd backend && pytest tests/test_tool_entity.py -v`

#### 4.3 Implement Tier 2 batch entity resolution with splink

**Depends on:** 4.1, 2.3
**Files:** `backend/redthread/entity/batch.py`, `backend/tests/test_batch_entity.py`

Batch entity resolution across entire datasets using splink with DuckDB backend:

```python
@dataclass
class BatchMatchResult:
    pairs: list[dict]  # Each: {entity_a, entity_b, score, match_probability, matching_fields}
    total_comparisons: int
    matches_found: int

def batch_resolve(
    records: list[dict],
    match_fields: list[str],
    threshold: float = 0.8,
) -> BatchMatchResult: ...
```

Uses splink's unsupervised mode (no training data). Configuration:
- Blocking rules on first letter of name + entity type (reduces comparison space)
- Comparison columns: name (jaro-winkler + levenshtein at multiple thresholds), address (if present), date fields (if present)
- DuckDB backend for in-process SQL execution
- Returns match probabilities that map to confidence tiers

This is the heavy-lifting tool for when an analyst uploads a large dataset and asks the agent to "find all related entities across these files." The pairwise tool (4.1) handles real-time comparisons during conversation; this handles bulk dataset processing.

**Test scenarios:** (`backend/tests/test_batch_entity.py`)
- Batch resolve on 100 records with known duplicates identifies them
- Match results include match probability scores
- Threshold filtering excludes low-confidence pairs
- Empty input returns empty results
- Records with missing fields in match columns handled gracefully
- Results sorted by match probability descending

**Verify:** `cd backend && pytest tests/test_batch_entity.py -v`

---

## 5. OFAC/SDN Screening

#### 5.1 Implement SDN list downloader and local storage

**Depends on:** 1.1
**Files:** `backend/redthread/ofac/downloader.py`, `backend/tests/test_ofac_downloader.py`

Downloads the OFAC SDN list from the Treasury Department's public XML feed and parses it into a local SQLite table for fast screening.

SDN XML source: `https://www.treasury.gov/ofac/downloads/sdn.xml` (publicly available, no auth required). Alternative CSV: `https://www.treasury.gov/ofac/downloads/sdn.csv`.

```python
async def download_sdn_list(target_path: Path) -> DownloadResult: ...
def parse_sdn_xml(xml_path: Path) -> list[SDNEntry]: ...
def load_sdn_to_sqlite(entries: list[SDNEntry], db: SQLiteDB) -> int: ...
```

SDN entry schema stored in SQLite:
```sql
sdn_entries (
  uid INTEGER PRIMARY KEY,
  entry_type TEXT,  -- Individual | Entity | Vessel | Aircraft
  name TEXT NOT NULL,
  program TEXT,
  aliases TEXT,  -- JSON array of alternate names
  addresses TEXT,  -- JSON array
  id_numbers TEXT,  -- JSON array (passport, tax ID, etc.)
  remarks TEXT
);
```

Index on `name` for fast lookup. Store aliases as JSON array for fuzzy matching across all known name variants.

**Test scenarios:** (`backend/tests/test_ofac_downloader.py`)
- Parse sample SDN XML (use a small fixture, not live download) extracts entries correctly
- Parsed entries have name, type, aliases fields populated
- Load to SQLite creates entries retrievable by UID
- Name index exists after loading
- Handle malformed XML gracefully (warning, skip bad entries)

**Verify:** `cd backend && pytest tests/test_ofac_downloader.py -v`

#### 5.2 Implement OFAC fuzzy screening tool

**Depends on:** 5.1, 4.1
**Files:** `backend/redthread/ofac/screener.py`, `backend/redthread/agent/tools/ofac.py`, `backend/tests/test_ofac_screener.py`

Screening engine that checks a name against the local SDN list:

```python
@dataclass
class ScreeningHit:
    sdn_uid: int
    sdn_name: str
    match_score: float
    confidence: str  # confirmed | probable | possible
    matched_alias: str | None  # which alias matched, if not primary name
    sdn_entry_type: str
    program: str

def screen_entity(name: str, db: SQLiteDB, top_n: int = 10) -> list[ScreeningHit]: ...
```

Screening approach:
1. Normalize input name (lowercase, strip suffixes, normalize whitespace)
2. Query all SDN entries (cached in memory after first load for speed — SDN list is ~30K entries, fits easily in RAM)
3. For each SDN entry, compare primary name + all aliases using `compare_entities()` from 4.1
4. Return top N matches above the "possible" threshold, sorted by score descending
5. Map scores to confidence tiers

Agent SDK tool wrapper:

```python
@tool
def screen_ofac(
    entity_name: str,
    investigation_id: str = "",
) -> str:
    """Screen an entity name against the OFAC/SDN sanctions list.
    Returns matches with confidence levels. Results are for analyst review,
    not automated decisioning."""
```

The tool response explicitly notes that results require analyst review — consistent with OFAC compliance expectations. (Satisfies R5 acceptance criteria.)

**Test scenarios:** (`backend/tests/test_ofac_screener.py`)
- Exact match against known SDN name returns confirmed hit
- Fuzzy match against name variant returns probable/possible hit
- Name with no SDN matches returns empty list
- Screening checks aliases, not just primary name
- Results sorted by score descending
- Tool response includes "analyst review required" language
- Empty name input returns error message

**Verify:** `cd backend && pytest tests/test_ofac_screener.py -v`

---

## 6. Web Search

#### 6.1 Implement Exa web search tool

**Depends on:** 1.1
**Files:** `backend/redthread/search/exa.py`, `backend/redthread/agent/tools/search.py`, `backend/tests/test_search.py`

Port the existing Exa API client from `agent/tools.py:807-847` (web_search) and `agent/tools.py:849-888` (fetch_url) into the new structure. Modernize to use `httpx` (async HTTP client) instead of `urllib`.

```python
class ExaClient:
    def __init__(self, api_key: str, base_url: str = "https://api.exa.ai"): ...
    async def search(self, query: str, num_results: int = 10, include_text: bool = False) -> SearchResult: ...
    async def fetch_urls(self, urls: list[str]) -> list[PageContent]: ...
```

Agent SDK tools:

```python
@tool
def web_search(query: str, num_results: int = 10) -> str:
    """Search the web for information about entities, public records, news, or
    supplementary data. Returns titles, URLs, and snippets."""

@tool
def fetch_url(url: str) -> str:
    """Fetch and extract text content from a specific URL. Useful for reading
    public records, news articles, or corporate filings found via web_search."""
```

Pattern: Follow the existing Exa integration pattern from `agent/tools.py` — same API endpoints (`/search`, `/contents`), same payload structure. Key difference: use `httpx.AsyncClient` instead of `urllib.request`. (Satisfies R6.)

**Test scenarios:** (`backend/tests/test_search.py`)
- Search with mocked Exa API returns parsed results
- Search with empty query returns error
- Fetch URL with mocked API returns page content
- HTTP error from Exa API returns user-friendly error message
- Rate limit / timeout handled gracefully

**Verify:** `cd backend && pytest tests/test_search.py -v`

---

## 7. Evidence Chains & SAR Narrative

#### 7.1 Implement evidence chain recording tool

**Depends on:** 2.3
**Files:** `backend/redthread/agent/tools/evidence.py`, `backend/tests/test_tool_evidence.py`

Agent SDK tool for the agent to record findings as structured evidence chain entries:

```python
@tool
def record_evidence(
    investigation_id: str,
    claim: str,
    supporting_evidence: str,
    source_record_id: str,
    source_dataset_id: str,
    confidence: str,
    entity_id: str = "",
) -> str:
    """Record a finding as a structured evidence chain entry. Every claim must
    trace to a specific record in a specific dataset. Confidence must be one of:
    confirmed, probable, possible, unresolved."""

@tool
def query_evidence(
    investigation_id: str,
    entity_id: str = "",
    confidence: str = "",
) -> str:
    """Query accumulated evidence chains. Filter by entity and/or confidence level.
    Returns all matching evidence chain entries with their source citations."""
```

`record_evidence` validates:
- Confidence is one of the four valid values
- source_record_id and source_dataset_id reference existing records (warn if not, but still record — the agent may be recording evidence from web search, not just ingested files)
- claim and supporting_evidence are non-empty

(Satisfies R8 acceptance criteria — each entry contains claim, supporting evidence, source record identifier, source dataset, and confidence level. Queryable by entity and confidence.)

**Test scenarios:** (`backend/tests/test_tool_evidence.py`)
- Record evidence with all fields creates entry in DB
- Query evidence by entity_id returns only matching entries
- Query evidence by confidence returns only matching entries
- Record evidence with invalid confidence returns error
- Record evidence with empty claim returns error
- Query all evidence for investigation returns complete list

**Verify:** `cd backend && pytest tests/test_tool_evidence.py -v`

#### 7.2 Implement SAR narrative generation tool

**Depends on:** 7.1
**Files:** `backend/redthread/agent/tools/sar.py`, `backend/tests/test_tool_sar.py`

Agent SDK tool that generates a draft SAR narrative from accumulated evidence:

```python
@tool
def generate_sar_narrative(
    investigation_id: str,
    subject_entity_ids: str = "",
) -> str:
    """Generate a draft SAR (Suspicious Activity Report) narrative from accumulated
    evidence. The narrative is assembled from evidence chains and formatted following
    standard SAR narrative structure.

    IMPORTANT: The output is clearly labeled as a DRAFT requiring analyst review
    and editing before any regulatory submission."""
```

The tool does NOT use the LLM to generate the narrative — it assembles the evidence chains into a structured template that the agent then uses as context for its narrative response. This separation ensures the agent has all evidence available and clearly labeled.

Template structure:
1. Subject information (entities under investigation)
2. Summary of suspicious activity (from confirmed + probable evidence)
3. Detailed narrative (chronological, citing evidence chain IDs)
4. Supporting evidence appendix (all evidence chains with source citations)
5. **DRAFT NOTICE** header and footer

Each section references specific evidence chain entry IDs so the analyst can trace every statement back to source data. (Satisfies R7 acceptance criteria.)

**Test scenarios:** (`backend/tests/test_tool_sar.py`)
- Generate narrative with evidence produces non-empty output
- Output includes DRAFT notice
- Output references evidence chain entry IDs
- Output includes subject entity information
- Generate narrative with no evidence returns appropriate message
- Evidence entries appear in chronological order

**Verify:** `cd backend && pytest tests/test_tool_sar.py -v`

#### 7.3 Implement timeline event recording tool

**Depends on:** 2.3
**Files:** `backend/redthread/agent/tools/timeline.py`, `backend/tests/test_tool_timeline.py`

Agent SDK tool for the agent to record dated events for the timeline visualization:

```python
@tool
def record_timeline_event(
    investigation_id: str,
    entity_id: str,
    entity_name: str,
    event_date: str,
    amount: float = 0.0,
    description: str = "",
    source_record_id: str = "",
    source_dataset_id: str = "",
) -> str:
    """Record a transaction or event for the timeline visualization.
    Call this when you identify dated transactions, transfers, or significant
    events during investigation."""
```

The tool:
1. Validates `event_date` is a valid ISO 8601 date string
2. Creates a `TimelineEvent` record via `TimelineEventRepo`
3. Returns confirmation with the event ID and summary

This is the data producer for the `/investigations/{id}/timeline` endpoint (9.1). The agent calls this tool whenever it encounters dated financial activity during ingestion analysis, entity resolution, or evidence recording.

**Test scenarios:** (`backend/tests/test_tool_timeline.py`)
- Record event with all fields creates entry in DB
- Record event with minimal fields (investigation_id, entity_id, entity_name, event_date) succeeds
- Record event with invalid date format returns error
- Events are retrievable from TimelineEventRepo filtered by investigation_id
- Events are retrievable filtered by entity_id

**Verify:** `cd backend && pytest tests/test_tool_timeline.py -v`

---

## 8. Agent Core

#### 8.0 Validate Agent SDK API and create adapter interface

**Depends on:** 1.1
**Files:** `backend/redthread/agent/sdk_adapter.py`, `backend/tests/test_sdk_adapter.py`

Create a thin adapter layer that wraps the Agent SDK's actual API surface. This isolates all tool definitions and the agent client from SDK-specific imports. If the SDK's actual class names or function signatures differ from what's documented in this plan, only this file needs to change.

The adapter defines:
- `ToolDecorator` — wraps `@tool` (or whatever the actual decorator is)
- `create_tool_server()` — wraps `create_sdk_mcp_server()`
- `AgentClient` — wraps `ClaudeSDKClient` with `chat()` and `stream()` methods
- `StreamEvent` type alias

First step of this subtask: `pip install claude-agent-sdk` (or discover the actual package name), import the module, and inspect the actual API surface. Document any deviations from the plan's assumptions in the adapter file.

**Test scenarios:** (`backend/tests/test_sdk_adapter.py`)
- SDK package installs successfully
- `ToolDecorator` wraps a function without errors
- `create_tool_server()` creates a server instance
- `AgentClient` initializes with API key and model

**Verify:** `cd backend && pytest tests/test_sdk_adapter.py -v`

#### 8.1 Adapt system prompt from existing prompts.py

**Depends on:** 1.1
**Files:** `backend/redthread/agent/prompts.py`

Port the investigation methodology from `agent/prompts.py` into the new system prompt. The existing prompt has valuable sections that must be preserved:

**Sections to port (adapted for Agent SDK context):**
- EPISTEMIC DISCIPLINE (lines 29-56) — core skepticism principles. Remove terminal-specific advice (empty output, capture mechanism). Keep: verify before concluding, cross-check, memory is unreliable.
- DATA INGESTION AND MANAGEMENT (lines 88-96) — ingest and verify before analyzing. Keep as-is, it's tool-agnostic.
- ENTITY RESOLUTION AND CROSS-DATASET LINKING (lines 98-107) — systematic name variant handling, entity maps, linking documentation. Keep as-is.
- EVIDENCE CHAINS AND SOURCE CITATION (lines 109-117) — every claim traces to source, evidence chain structure. Keep as-is.
- ANALYSIS OUTPUT STANDARDS (lines 119-127) — structured findings, methodology section, grounded narrative. Keep as-is.

**Sections to drop:**
- HOW YOU WORK (lines 16-27) — step-limited loop, terminal capture. Replaced by Agent SDK context.
- HARD RULES (lines 58-76) — heredoc, file overwrite policies. Terminal-specific.
- NON-INTERACTIVE ENVIRONMENT (lines 78-86) — TUI restrictions. Not applicable.
- EXECUTION TACTICS (lines 154-192) — step budgets, shell commands. Terminal-specific.
- WORKING APPROACH (lines 173-192) — tool-specific guidance. Replaced by Agent SDK tool descriptions.
- RECURSIVE_SECTION — subtask delegation. Replaced by Agent SDK sub-agents.
- ACCEPTANCE_CRITERIA_SECTION — verification pattern. The agent can use its tools directly.

**New sections to add:**
- Identity: "You are Redthread, a financial crime investigation agent for BSA/AML analysts."
- Tool guidance: Brief description of available tools and when to use each.
- Investigation methodology: Adapted from PLANNING section — for nontrivial investigations, plan first.
- SAR narrative disclaimer: All generated narratives are drafts requiring analyst review.
- Proactive suggestions: Suggest next investigation steps when appropriate. (Satisfies R13.)

No test file — this is a prompt text file. Validated through integration tests in 8.2.

**Verify:** Manual review that all epistemic discipline, evidence chain, and entity resolution sections are preserved.

#### 8.2 Implement Agent SDK client and tool assembly

**Depends on:** 8.0, 8.1, 3.2, 4.2, 5.2, 6.1, 7.1, 7.2, 7.3
**Files:** `backend/redthread/agent/client.py`, `backend/redthread/agent/tools/__init__.py`, `backend/tests/test_agent_client.py`

Central agent client that wires together all tools and manages conversation:

```python
class RedthreadAgent:
    def __init__(self, settings: Settings, repos: Repositories): ...
    async def chat(self, investigation_id: str, user_message: str) -> AsyncIterator[StreamEvent]: ...
    async def create_sub_investigation(self, investigation_id: str, question: str) -> str: ...
```

`__init__.py` in tools/ creates the MCP server:

```python
from claude_agent_sdk import create_sdk_mcp_server
from .ingest import ingest_file
from .entity import resolve_entity, add_relationship, query_entity_graph
from .ofac import screen_ofac
from .search import web_search, fetch_url
from .evidence import record_evidence, query_evidence
from .sar import generate_sar_narrative
from .timeline import record_timeline_event

mcp_server = create_sdk_mcp_server(
    "redthread",
    tools=[ingest_file, resolve_entity, add_relationship, query_entity_graph,
           screen_ofac, web_search, fetch_url, record_evidence, query_evidence,
           generate_sar_narrative, record_timeline_event],
)
```

`client.py` creates a `ClaudeSDKClient` with:
- System prompt from 8.1
- MCP server from tools/__init__.py
- `include_partial_messages=True` for streaming
- Model: `claude-sonnet-4-6` (cost-effective for interactive use; agent can delegate to opus for complex analysis via sub-agents)

`chat()` method:
1. Loads conversation history from MessageRepo
2. Appends user message
3. Calls `client.send_message()` with streaming
4. Yields `StreamEvent` objects (text deltas, tool calls, tool results)
5. After completion, saves assistant message to MessageRepo

`create_sub_investigation()` method:
- **Synchronous execution:** The main agent waits for the sub-agent to complete before continuing. This keeps the conversation flow predictable for the analyst.
- **Context passed to sub-agent:** The sub-agent receives the specific question, a summary of the investigation so far (entities found, key evidence), and the `investigation_id` for tool access.
- **Shared tool server:** The sub-agent inherits the same MCP tool server instance (passed by reference to `AgentDefinition`), so it can call all investigation tools against the same data.
- **Model:** `claude-sonnet-4-6` (same as main agent — keeps costs predictable).
- **Focused system prompt template:** `"You are a Redthread sub-investigator. Your task is to answer a specific question: {question}. You have access to the same investigation tools. Focus narrowly on this question. When done, summarize your findings with evidence citations."`
- **Output:** The sub-agent's output is returned as a string to the main agent, which can then record findings as evidence chains via the `record_evidence` tool.
- (Satisfies R2 — hybrid interaction model with autonomous sub-investigations)

**Test scenarios:** (`backend/tests/test_agent_client.py`)
- Agent initializes with all tools registered
- MCP server lists all expected tool names
- Chat method yields stream events (mock the SDK client)
- Conversation history is persisted after chat completes
- Sub-investigation creates a scoped agent definition with focused system prompt
- Sub-investigation returns findings string that main agent can use
- Agent handles tool call → tool result flow correctly

**Verify:** `cd backend && pytest tests/test_agent_client.py -v`

---

## 9. Backend API

#### 9.1 Implement REST API routes

**Depends on:** 2.3, 1.3
**Files:** `backend/redthread/api/routes.py`, `backend/tests/test_api_routes.py`

FastAPI router at `/api/v1` with endpoints:

```
POST   /investigations              → Create new investigation
GET    /investigations              → List investigations
GET    /investigations/{id}         → Get investigation details
DELETE /investigations/{id}         → Archive investigation

GET    /investigations/{id}/evidence → Get evidence chains (query params: entity_id, confidence)
GET    /investigations/{id}/graph    → Get entity graph (nodes + edges for visualization)
GET    /investigations/{id}/timeline → Get transaction timeline events
GET    /investigations/{id}/messages → Get chat history

POST   /investigations/{id}/upload   → Upload a file (multipart form)
```

File upload endpoint:
- Accepts multipart file upload
- Validates file extension (csv, json, xlsx)
- Validates file size (< 50 MB)
- Saves to `Settings.UPLOAD_DIR / investigation_id / filename`
- Returns upload confirmation (does not auto-ingest — the agent decides when to ingest via the tool)

Graph endpoint returns data formatted for Cytoscape.js consumption:
```json
{
  "nodes": [{"data": {"id": "...", "label": "...", "type": "..."}}],
  "edges": [{"data": {"source": "...", "target": "...", "type": "..."}}]
}
```

Timeline endpoint queries the `timeline_events` table (populated by the `record_timeline_event` tool in 7.3) and returns data formatted for Recharts:
```json
{
  "events": [{"date": "...", "entity_id": "...", "entity_name": "...", "amount": 0, "description": "..."}]
}
```

(Satisfies R10 — session persistence. Investigations persist in SQLite, resumable across browser sessions.)

**Test scenarios:** (`backend/tests/test_api_routes.py`)
- POST /investigations creates and returns investigation
- GET /investigations lists all investigations
- GET /investigations/{id} returns investigation details
- GET /investigations/{id}/evidence returns evidence chains
- GET /investigations/{id}/evidence?confidence=confirmed filters correctly
- GET /investigations/{id}/graph returns Cytoscape.js-formatted data
- POST /investigations/{id}/upload accepts valid file
- POST /investigations/{id}/upload rejects file > 50 MB
- POST /investigations/{id}/upload rejects unsupported file type
- DELETE archives (not deletes) the investigation

**Verify:** `cd backend && pytest tests/test_api_routes.py -v`

#### 9.2 Implement WebSocket endpoint for chat streaming

**Depends on:** 8.2, 9.1
**Files:** `backend/redthread/api/websocket.py`, `backend/tests/test_websocket.py`

WebSocket endpoint at `/ws/chat/{investigation_id}`:

Protocol (JSON frames):
```
Client → Server: {"type": "message", "content": "user text"}
Client → Server: {"type": "sub_investigate", "question": "specific question"}

Server → Client: {"type": "text_delta", "content": "partial text"}
Server → Client: {"type": "tool_call", "tool": "name", "input": {...}}
Server → Client: {"type": "tool_result", "tool": "name", "output": "..."}
Server → Client: {"type": "message_complete", "content": "full message"}
Server → Client: {"type": "graph_update", "data": {...}}  // entity graph changed
Server → Client: {"type": "evidence_update", "data": {...}}  // new evidence recorded
Server → Client: {"type": "error", "message": "..."}
```

The WebSocket handler:
1. Accepts connection, validates investigation_id exists
2. On "message" frame: calls `RedthreadAgent.chat()`, streams events as JSON frames
3. On "sub_investigate" frame: calls `RedthreadAgent.create_sub_investigation()`, streams result
4. After tool calls that modify the graph or evidence, sends corresponding update frames so the frontend can refresh visualizations without polling
5. Handles disconnection gracefully (no crash on broken pipe)

(Satisfies R11 — real-time token-by-token streaming.)

**Test scenarios:** (`backend/tests/test_websocket.py`)
- WebSocket connection established for valid investigation
- WebSocket connection rejected for nonexistent investigation
- Sending message frame triggers agent response stream
- Text delta frames contain incremental content
- Tool call and tool result frames are sent during agent execution
- Connection closure handled without server error
- graph_update frame sent after entity tool call

**Verify:** `cd backend && pytest tests/test_websocket.py -v`

---

## 10. Frontend Shell & Chat

#### 10.1 Implement WebSocket hook and API client

**Depends on:** 1.4
**Files:** `frontend/src/hooks/useWebSocket.ts`, `frontend/src/lib/api.ts`, `frontend/src/__tests__/useWebSocket.test.ts`

React hook for WebSocket communication:

```typescript
function useWebSocket(investigationId: string): {
  messages: Message[];
  sendMessage: (content: string) => void;
  sendSubInvestigation: (question: string) => void;
  isConnected: boolean;
  isStreaming: boolean;
  graphData: GraphData | null;
  evidenceData: EvidenceChain[];
}
```

Hook manages:
- WebSocket connection lifecycle (connect on mount, reconnect on disconnect with exponential backoff)
- Accumulating text deltas into complete messages
- Tracking tool calls in progress (for UI indicators)
- Updating graph/evidence data from server push events
- Message history state

REST API client (`api.ts`):
- `createInvestigation()`, `listInvestigations()`, `getInvestigation()`
- `uploadFile()` — multipart upload
- `getEvidence()`, `getGraph()`, `getTimeline()`
- Base URL from `NEXT_PUBLIC_API_URL` env var

**Test scenarios:** (`frontend/src/__tests__/useWebSocket.test.ts`)
- Hook connects WebSocket on mount
- Sending message dispatches correct JSON frame
- Text delta frames accumulate into streaming message
- message_complete frame finalizes message
- Disconnection triggers reconnect attempt
- graph_update frame updates graphData state

**Verify:** `cd frontend && npm test`

#### 10.2 Implement chat panel component

**Depends on:** 10.1
**Files:** `frontend/src/components/ChatPanel.tsx`, `frontend/src/components/MessageBubble.tsx`

Chat panel with:
- Message history display (scrollable, auto-scroll to bottom on new messages)
- User input area (textarea with Shift+Enter for newline, Enter to send)
- Streaming indicator (pulsing dot when agent is responding)
- Tool call indicators (show which tool the agent is calling, with a brief status)
- Sub-investigation launcher (button or slash command `/investigate <question>`)
- Message formatting: Markdown rendering for agent messages, code blocks, evidence citations

Dark theme styling consistent with the layout from 1.4.

**Test scenarios:** (manual)
- User can type and send a message
- Agent response streams in character by character
- Tool calls display as inline status indicators
- Message history persists across page refreshes (loaded from REST API)
- Auto-scrolls to newest message

**Verify:** Manual testing with backend running. Send a message, observe streaming response.

#### 10.3 Implement file upload component

**Depends on:** 10.1
**Files:** `frontend/src/components/FileUpload.tsx`

File upload UI:
- Drag-and-drop zone in the chat panel header area
- Click to browse alternative
- Accepts .csv, .json, .xlsx files only
- Shows upload progress bar
- After upload, displays confirmation and file metadata
- Size limit indicator (50 MB max)

Uses the REST API `uploadFile()` from 10.1. After successful upload, sends a chat message to the agent informing it of the new file (e.g., "I've uploaded transactions.csv — please ingest and analyze it").

**Test scenarios:** (manual)
- Drag CSV file onto drop zone triggers upload
- Upload progress bar appears and completes
- Unsupported file type shows error message
- File > 50 MB shows size limit error
- Successful upload appears as a message in chat

**Verify:** Manual testing with backend running. Upload a CSV, verify it appears in uploads directory.

---

## 11. Frontend Visualizations

#### 11.1 Implement entity relationship graph with Cytoscape.js

**Depends on:** 10.1
**Files:** `frontend/src/components/EntityGraph.tsx`

Entity relationship graph visualization using Cytoscape.js (direct integration, not a React wrapper):

- Initialize Cytoscape instance on a `div` ref
- Load graph data from the `graphData` state in `useWebSocket` hook (pushed via `graph_update` frames), with initial load from REST API `getGraph()`
- Incremental updates: when `graph_update` arrives, use `cy.add()` / `cy.remove()` instead of full re-render
- Layout: `cose-bilkent` (force-directed, good for relationship graphs) with option to switch to `dagre` (hierarchical)
- Node styling: Different colors/shapes per entity_type (person=circle/blue, organization=rectangle/green, address=diamond/orange)
- Edge styling: Different line styles per relationship_type (solid for TRANSACTED_WITH, dashed for AFFILIATED_WITH)
- Node labels: Entity name, truncated if long
- Click interaction: Click a node to select it, which filters the evidence panel (R12) and highlights connected edges
- Compound nodes: Group entities by dataset source (optional toggle)
- Zoom/pan controls

(Satisfies R3 — entity relationship graph that updates as investigation progresses.)

**Test scenarios:** (manual)
- Graph renders with sample nodes and edges
- New entity from agent tool call appears on graph without full refresh
- Click node highlights connected edges
- Layout adjusts when new nodes added
- Empty graph shows helpful empty state message

**Verify:** Manual testing with backend running. Run an investigation, observe graph populating.

#### 11.2 Implement transaction timeline with Recharts

**Depends on:** 10.1
**Files:** `frontend/src/components/Timeline.tsx`

Transaction timeline using Recharts:

- `ComposedChart` with:
  - Scatter plot: Individual transactions as dots (x=date, y=amount)
  - Reference areas: Highlight periods of interest (flagged by agent)
  - Custom tooltips: Show transaction details on hover (entity, amount, date, description)
- Load timeline data from REST API `getTimeline()`, with live updates from WebSocket
- `syncId` for coordinated views when multiple entities are selected
- Time range selector (zoom into date ranges)
- Entity color coding: Different scatter colors per entity
- Responsive: Fills available width in the visualization panel

(Satisfies R4 — transaction timeline for entities under investigation.)

**Test scenarios:** (manual)
- Timeline renders with sample transaction data
- Hover shows transaction details tooltip
- Multiple entities display with different colors
- Empty timeline shows helpful empty state
- Time range zoom works

**Verify:** Manual testing with backend running and transaction data ingested.

#### 11.3 Implement evidence panel

**Depends on:** 10.1
**Files:** `frontend/src/components/EvidencePanel.tsx`

Evidence panel showing structured findings:

- List view of evidence chain entries, grouped by entity
- Each entry shows: claim, confidence badge (color-coded), source dataset, source record reference
- Filter controls: By entity (dropdown), by confidence (checkboxes)
- Click-to-expand: Shows full supporting evidence text and source record details
- Drill-down: Click source record reference to view the raw data row
- Link to graph: Click entity name to highlight it in the entity graph
- Sort by: Date (newest first), confidence (highest first)

Loads evidence from `useWebSocket` hook's `evidenceData` state (pushed via `evidence_update` frames), with initial load from REST API `getEvidence()`.

(Satisfies R12 — evidence panel with structured view and drill-down to source records.)

**Test scenarios:** (manual)
- Evidence entries display with confidence badges
- Filter by entity shows only that entity's evidence
- Filter by confidence shows only matching entries
- Expand entry shows supporting evidence detail
- New evidence from agent appears without refresh
- Empty state shows helpful message

**Verify:** Manual testing with backend running and evidence recorded.

---

## 12. Data Security & PII Handling

#### 12.1 Implement data security baseline for PII handling

**Depends on:** 1.2, 2.1
**Files:** `backend/redthread/security.py`, `docker-compose.yml`, `backend/redthread/main.py`

Address the PRD's data sensitivity risk (BSA/AML data contains PII subject to 31 USC 5318(g)(2)):

- SQLite databases stored in `data/` volume with restrictive file permissions (0600). Set via `os.chmod` after creation in the SQLite connection manager.
- Upload directory (`uploads/`) with restrictive permissions (0700).
- Docker volumes bind to host directories only (no named volumes that persist in Docker's opaque storage).
- Docker Compose: bind ports to `127.0.0.1` only (not `0.0.0.0`) to prevent network exposure. E.g., `"127.0.0.1:8000:8000"`.
- Agent tool call logging: sanitize PII from log output. Log tool names and timing, not input/output content containing entity names or financial data.
- No data-at-rest encryption in v1 (local-only deployment; filesystem-level encryption like FileVault is the user's responsibility). Document this limitation.

**Test scenarios:** (`backend/tests/test_security.py`)
- SQLite DB file created with 0600 permissions
- Upload directory created with 0700 permissions
- Docker compose binds to 127.0.0.1 not 0.0.0.0

**Verify:** `ls -la data/*.db` shows restrictive permissions. `docker compose config | grep ports` shows 127.0.0.1 binding.

---

## Testing Strategy

- **Unit tests:** Each module (parsers, entity resolution, OFAC screening, repositories, tools) has dedicated test files. Use pytest with fixtures for database setup/teardown. Mock external APIs (Exa, Agent SDK). Target: All non-UI modules have unit tests.
- **Integration tests:** Test the full flow: upload file → ingest → resolve entities → screen OFAC → record evidence → generate SAR. Uses a real SQLite database (in-memory or temp file) and real LadybugDB instance. Agent SDK client mocked at the API boundary.
- **Manual verification:** Full end-to-end test with Docker Compose running both services. Upload a sample CSV of transactions, interact with the agent via chat, verify graph updates, check timeline, review evidence panel.
- **Frontend tests:** React Testing Library for hook behavior (WebSocket mock). Cytoscape.js and Recharts tested manually (visual output is hard to unit test meaningfully).

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| LadybugDB is pre-1.0 with limited ecosystem | Graph layer abstracted behind Protocol. NetworkX fallback implemented in 2.2. Evaluate LadybugDB in subtask 2.2 before building on it — switch to fallback if blocking issues found. |
| Agent SDK API surface may differ from research findings | Subtask 8.0 validates the SDK API and creates an adapter layer. If SDK patterns differ, only the adapter (8.0) needs adjustment — tool definitions (3.2-7.3) are plain Python functions behind the adapter. |
| Claude Max may not grant programmatic Agent SDK access | Fallback to standard Anthropic API key with usage-based billing. Config supports both auth methods (8.2). |
| 50 MB / 500K row file ingestion may be slow | Streaming parsers (3.1) avoid loading entire file in memory. Batch DB inserts (2.3) use `executemany`. Splink batch resolution (4.3) uses DuckDB for SQL-speed processing. |
| OFAC SDN list changes format or URL | Downloader (5.1) has both XML and CSV fallback paths. Parse errors produce warnings, not crashes. |
| WebSocket reliability for long investigations | Reconnect with exponential backoff (10.1). Message history persisted server-side (9.1), so reconnection doesn't lose context. |

## Open Questions

- **Agent SDK package name and API surface:** The plan references `claude-agent-sdk` with specific imports (`@tool`, `create_sdk_mcp_server`, `ClaudeSDKClient`). These are based on research findings and may differ from the actual SDK. Subtask 8.0 validates this as the first step of agent core work. If the SDK API differs significantly, only the adapter layer (8.0) needs to change.
