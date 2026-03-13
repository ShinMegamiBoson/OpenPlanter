# RFC 0001: Typed `InvestigationState` (Ontology-First Session Memory)

- **Status:** Proposed
- **Authors:** OpenPlanter team
- **Created:** 2026-03-13
- **Target release:** staged rollout over 3 milestones
- **Scope:** session persistence (`state.json` successor), event/replay projection, runtime APIs for Python + Rust

## 1. Summary

This RFC defines an implementation-ready, typed `InvestigationState` to replace today’s mostly append-only text memory model with an ontology-first graph model centered on:

- entities
- links
- claims
- evidence
- hypotheses
- open questions
- tasks/actions
- provenance
- confidence

The current session state is predominantly `external_observations: string[]` with optional turn summaries and loop metrics, which biases memory toward late synthesis and makes structured reasoning (e.g., “which evidence supports this claim?”) difficult to perform incrementally. The new state introduces typed records with stable IDs, lifecycle fields, and confidence/provenance semantics that can be updated throughout the investigation.

## 2. Motivation and Current Gaps

## 2.1 Current Python session state is string-heavy and late-structured

`SessionRuntime._persist_state()` persists `external_observations` as plain strings, plus `turn_history` and `loop_metrics`; no typed entities/claims/evidence graph exists in persisted state. The runtime loads this into `ExternalContext(observations=list[str])`, then injects summaries into prompts for later synthesis. This is useful for continuity, but it is not ontology-native. 

## 2.2 Current events and replay logs are rich but not canonicalized into typed state

- `events.jsonl` captures `objective`, `trace`, `step`, `result`, and artifacts.
- `replay.jsonl` captures model call records (`header`, `call`, message snapshots/deltas, responses, token usage).

These logs provide temporal traceability, but they are not normalized into first-class analytical objects (claims/evidence/hypotheses/tasks) that can be reasoned over directly.

## 2.3 Python/Rust state model divergence

Rust’s `ExternalContext` currently expects `observations: Vec<Observation{source,timestamp,content}>` from `state.json`, while Python writes `external_observations: string[]`. This creates an interoperability mismatch and makes cross-runtime typed state consumption brittle.

## 2.4 Consequences

- hard to query support/opposition relationships for claims
- weak provenance granularity (source spans, extraction method, derived-from chain)
- confidence tracked informally in text, not as updateable fields
- poor lifecycle tracking for open questions, hypotheses, and tasks
- expensive/fragile “read all logs, then synthesize” behavior

## 3. Goals and Non-Goals

### 3.1 Goals

1. Define a versioned, typed, ontology-first `InvestigationState` schema.
2. Preserve append-only logs (`events.jsonl`, `replay.jsonl`) as immutable trace, while introducing a mutable canonical state projection.
3. Provide deterministic migration from legacy `state.json` and optional bootstrap from replay/events logs.
4. Define runtime consumption contracts for both Python and Rust.
5. Enable incremental updates throughout the loop (investigate/build/iterate/finalize), not only final summarization.

### 3.2 Non-Goals

1. Replacing replay/events logging.
2. Building a global cross-session knowledge graph in this RFC.
3. Defining UI-level rendering details beyond data contract implications.

## 4. Proposed Data Model

## 4.1 File layout

Within each session directory:

- `investigation_state.json` (**new canonical typed state**)
- `state.json` (legacy compatibility; transitional)
- `events.jsonl` (append-only trace, unchanged)
- `replay.jsonl` (append-only model transcript, unchanged)

## 4.2 Top-level schema

```json
{
  "schema_version": "1.0.0",
  "session_id": "20260313-120000-abc123",
  "created_at": "2026-03-13T12:00:00Z",
  "updated_at": "2026-03-13T12:05:00Z",
  "objective": "Investigate relationships between X and Y",
  "ontology": {
    "namespace": "openplanter.core",
    "version": "2026-03"
  },
  "entities": {},
  "links": {},
  "claims": {},
  "evidence": {},
  "hypotheses": {},
  "questions": {},
  "tasks": {},
  "actions": {},
  "provenance_nodes": {},
  "confidence_profiles": {},
  "timeline": [],
  "indexes": {
    "by_external_ref": {},
    "by_tag": {}
  },
  "legacy": {
    "external_observations": [],
    "turn_history": [],
    "loop_metrics": {}
  }
}
```

Design choice: object maps keyed by stable IDs (`ent_`, `clm_`, `ev_`, etc.) rather than only arrays to allow O(1) merge/update and conflict resolution.

## 4.3 Core record types

### 4.3.1 Entity

Represents person/org/location/asset/document/event/concept.

Required fields:

- `id`, `kind`, `canonical_name`, `status`
- `created_at`, `updated_at`
- `provenance_ids[]`
- `confidence_id`

Optional:

- aliases, attributes, external_refs, tags

```json
{
  "id": "ent_01H...",
  "kind": "organization",
  "canonical_name": "Acme Holdings LLC",
  "aliases": ["Acme Holdings"],
  "attributes": {"jurisdiction": "DE"},
  "external_refs": [{"system": "sec_cik", "value": "0000123456"}],
  "status": "active",
  "provenance_ids": ["prov_..."],
  "confidence_id": "conf_...",
  "created_at": "...",
  "updated_at": "..."
}
```

### 4.3.2 Link

Typed relationship between two entities (or entity↔claim where needed).

- `source_entity_id`, `target_entity_id`, `predicate`
- `directional` (bool), `valid_time` (optional interval)
- provenance + confidence

### 4.3.3 Claim

Atomic proposition that may be supported or contradicted.

- `text`, `claim_type` (`factual`, `attribution`, `quantitative`, etc.)
- `subject_refs[]` (entity/link IDs)
- `status` (`proposed`, `supported`, `contested`, `retracted`)
- `evidence_support_ids[]`, `evidence_contra_ids[]`
- provenance + confidence

### 4.3.4 Evidence

Observation/excerpt/document-derived fact unit.

- `evidence_type` (`document`, `api_response`, `tool_output`, `human_note`)
- `content` (normalized value or excerpt)
- `source_uri`/`artifact_path`/`event_ref`
- `extraction` metadata (`method`, `extractor_version`, `span`)
- `hash` (optional dedupe)
- provenance + confidence

### 4.3.5 Hypothesis

Testable explanatory model composed of one or more claims.

- `statement`
- `claim_ids[]`
- `status` (`open`, `plausible`, `weakened`, `rejected`, `accepted`)
- `test_plan_task_ids[]`
- provenance + confidence

### 4.3.6 Open Question

Resolvable question with lifecycle.

- `question_text`
- `priority` (`low|medium|high|critical`)
- `status` (`open|in_progress|blocked|resolved|won't_fix`)
- `resolution_claim_id` (optional)
- `related_entity_ids[]`, `related_hypothesis_ids[]`
- provenance + confidence

### 4.3.7 Task / Action

Task = planned unit of work. Action = executed step/tool invocation.

Task fields:

- `title`, `description`, `status`, `assignee` (agent/human/system)
- `depends_on_task_ids[]`, `produced_ids[]`, `consumed_ids[]`
- `opened_by_question_id`/`opened_by_hypothesis_id`

Action fields:

- `task_id`, `action_type` (`tool_call`, `manual_edit`, `analysis_step`)
- `started_at`, `ended_at`, `outcome`
- `event_refs[]`, `replay_refs[]`, `artifact_paths[]`

### 4.3.8 Provenance node

First-class provenance object for source and transformation lineage.

- `source_kind` (`event_log`, `replay_log`, `artifact`, `external_api`, `user_input`)
- `source_ref` (e.g., `events.jsonl#line:120`, URI, file path)
- `captured_at`
- `derived_from_ids[]`
- `method` (parser/model/tool), `method_version`

### 4.3.9 Confidence profile

Shared representation for confidence + rationale.

- `score` (0.0-1.0)
- `grade` (`very_low|low|medium|high|very_high`)
- `dimensions` (source reliability, corroboration, recency, extraction certainty)
- `rationale` (short text)
- `updated_by` (agent/tool/user)

## 4.4 Cross-object invariants

1. All referenced IDs MUST exist.
2. `updated_at >= created_at`.
3. Closed objects (`resolved/rejected/retracted`) MUST include closure metadata (`closed_at`, `closed_reason`).
4. Claim status transition to `supported` requires at least one support evidence reference.
5. Evidence used by claims MUST include provenance.
6. Confidence profile referenced by object MUST exist (or explicit `null` if unknown is allowed by configuration).

## 5. Lifecycle Model

Each turn updates typed state continuously:

1. **Ingest**: parse tool outputs/events into candidate evidence/entities.
2. **Normalize**: dedupe, entity resolution, link extraction.
3. **Assert**: create/update claims and hypothesis weights.
4. **Plan**: open/close questions; generate/update tasks.
5. **Act**: execute actions and attach provenance/replay refs.
6. **Review**: recompute confidence and status transitions.
7. **Persist**: atomic write of `investigation_state.json` + event emission.

State updates are **idempotent upserts** keyed by IDs or deterministic signatures.

## 6. Migration Plan

## 6.1 Legacy inputs

- `state.json` (primary): `external_observations`, `turn_history`, `loop_metrics`
- `events.jsonl` (optional enrichment)
- `replay.jsonl` (optional deep enrichment)

## 6.2 Migration phases

### Phase A (compatibility + scaffold)

- Introduce writer for `investigation_state.json` with top-level metadata and `legacy` block copied from current `state.json`.
- Build pseudo-evidence from each legacy observation:
  - `evidence_type = "legacy_observation"`
  - content = observation string
  - provenance source = `state.json#external_observations[i]`
  - confidence = default baseline (e.g., 0.4, low)

### Phase B (log projection backfill)

- Parse `events.jsonl` to synthesize tasks/actions timeline:
  - `objective` -> task roots
  - `step` -> action nodes
  - `result` -> claim/hypothesis candidate notes
- Parse `replay.jsonl` for optional high-fidelity provenance edges:
  - map model/tool turns to `action.replay_refs`
  - attach token/time diagnostics to action metadata

### Phase C (native typed operation)

- Runtime writes typed objects directly during investigation loop.
- Legacy `state.json` becomes derived compatibility projection (or frozen fallback).

## 6.3 Deterministic ID strategy

Use ULID/UUIDv7 for new runtime objects; for migrated objects optionally derive stable hash IDs from `(session_id, source_ref, normalized_content)` to avoid duplicate backfills.

## 6.4 Conflict handling

- If object exists: merge by field precedence (`new structured parse` > `legacy text parse` > `defaults`).
- If confidence differs: keep latest score and append to confidence history (optional extension field).

## 7. Runtime Consumption Contracts

## 7.1 Python runtime contract

Add a typed state layer in Python:

- `InvestigationState` dataclasses / pydantic models.
- Loader order:
  1. load `investigation_state.json` if present and version-compatible
  2. else migrate from `state.json` (+ optional logs)
- During `solve()`, update typed graph incrementally from steps/results.
- Persist both:
  - canonical `investigation_state.json`
  - compatibility `state.json` (minimal projection for older consumers)

Recommended module boundaries:

- `agent/investigation_state/schema.py`
- `agent/investigation_state/store.py`
- `agent/investigation_state/migrate.py`
- `agent/investigation_state/projectors.py` (events/replay -> typed)

## 7.2 Rust runtime contract

Replace/extend `engine::context::ExternalContext` usage with typed equivalents:

- `InvestigationState` serde structs mirroring schema version 1.
- tolerant deserialization with `#[serde(default)]` for forward-compatible additive fields.
- loader order identical to Python.
- provide read APIs for prompt assembly:
  - high-confidence active claims
  - unresolved high-priority questions
  - active hypotheses + recent supporting evidence

Recommended modules:

- `op-core/src/engine/investigation_state.rs`
- `op-core/src/engine/investigation_migrate.rs`
- keep `context.rs` as compatibility facade during transition

## 7.3 Interop guarantees

1. Shared JSON schema version and semantic rules.
2. Unknown fields ignored, known fields validated.
3. Both runtimes can round-trip without lossy deletion of unknown extension fields.

## 8. Schema Governance and Validation

- Publish JSON Schema at `docs/schemas/investigation_state.schema.json` (follow-up RFC task).
- Enforce `schema_version` and migration matrix.
- Add golden session fixtures (legacy + migrated + native typed) for Python/Rust parity tests.

## 9. Rollout Plan

### Milestone 1 (1-2 sprints)

- Write/read scaffold + migration from `state.json`.
- No prompt changes required yet.

### Milestone 2 (1-2 sprints)

- Event/replay projector for tasks/actions/provenance.
- Prompt/context assembly begins consuming typed slices.

### Milestone 3 (2+ sprints)

- Full ontology-native loop updates and confidence lifecycle.
- `state.json` reduced to compatibility export; deprecation notice.

## 10. Backward Compatibility

- Existing sessions remain readable.
- If only `state.json` exists, runtime auto-migrates in-memory and writes typed file.
- Legacy clients can continue reading `state.json` until formal removal.

## 11. Risks and Mitigations

- **Risk:** schema over-complexity slows iteration.
  - **Mitigation:** strict v1 core + extension points.
- **Risk:** noisy auto-extraction creates low-quality entities/claims.
  - **Mitigation:** confidence gating and status `proposed` until corroborated.
- **Risk:** Python/Rust drift.
  - **Mitigation:** shared fixture suite + contract tests in CI.

## 12. Open Design Questions

1. Should confidence history be first-class now or deferred to v1.1?
2. Should we store denormalized indexes on disk or rebuild at load?
3. What minimum evidence requirements are needed before a claim can influence final answers?

## 13. Implementation Checklist

- [ ] Add canonical typed state file and loader in Python
- [ ] Add migration path from legacy `state.json`
- [ ] Add optional projectors from `events.jsonl` and `replay.jsonl`
- [ ] Add canonical typed state structs and loader in Rust
- [ ] Add compatibility projection writer to legacy `state.json`
- [ ] Add schema validation + fixtures + parity tests
- [ ] Update prompt/context assembly to consume typed state slices

