from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
ONTOLOGY_NAMESPACE = "openplanter.core"
ONTOLOGY_VERSION = "2026-03"
LOW_CONFIDENCE_THRESHOLD = 0.60
VERY_LOW_CONFIDENCE_THRESHOLD = 0.40
MAX_CANDIDATE_ACTIONS = 24
REQUIRED_EVIDENCE_COUNT = 1
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SUGGESTED_TOOLS = {
    "search": ["web_search", "fetch_url", "search_files", "read_file"],
    "verify_claim": ["web_search", "fetch_url", "read_file", "search_files"],
}
_LEGACY_KNOWN_KEYS = {
    "session_id",
    "saved_at",
    "external_observations",
    "observations",
    "turn_history",
    "loop_metrics",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state(session_id: str, now: str | None = None) -> dict[str, Any]:
    ts = now or utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created_at": ts,
        "updated_at": ts,
        "objective": "",
        "ontology": {
            "namespace": ONTOLOGY_NAMESPACE,
            "version": ONTOLOGY_VERSION,
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
            "by_tag": {},
        },
        "legacy": {
            "external_observations": [],
            "turn_history": [],
            "loop_metrics": {},
            "extra_fields": {},
        },
    }


def normalize_legacy_state(session_id: str, raw_state: dict[str, Any]) -> dict[str, Any]:
    state = raw_state if isinstance(raw_state, dict) else {}
    observations = state.get("external_observations")
    if not isinstance(observations, list):
        observations = _observations_from_rust_state(state)

    normalized = {
        "session_id": str(state.get("session_id") or session_id),
        "saved_at": str(state.get("saved_at") or utc_now_iso()),
        "external_observations": _string_list(observations),
        "turn_history": _json_list(state.get("turn_history")),
        "loop_metrics": _json_object(state.get("loop_metrics")),
    }
    normalized.update(_extra_fields_from_legacy_state(state))
    return normalized


def migrate_legacy_state(
    session_id: str,
    legacy_state: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_legacy_state(session_id, legacy_state)
    ts = now or str(normalized.get("saved_at") or utc_now_iso())
    migrated = default_state(session_id=session_id, now=ts)
    migrated["updated_at"] = ts
    migrated["legacy"] = {
        "external_observations": list(normalized.get("external_observations", [])),
        "turn_history": _json_list(normalized.get("turn_history")),
        "loop_metrics": _json_object(normalized.get("loop_metrics")),
        "extra_fields": {
            key: value
            for key, value in normalized.items()
            if key not in {"session_id", "saved_at", "external_observations", "turn_history", "loop_metrics"}
        },
    }
    return upsert_legacy_observations(migrated, migrated["legacy"]["external_observations"], now=ts)


def state_to_legacy_projection(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    legacy = state.get("legacy", {})
    legacy_dict = legacy if isinstance(legacy, dict) else {}
    projected = {
        "session_id": str(state.get("session_id") or session_id),
        "saved_at": str(state.get("updated_at") or utc_now_iso()),
        "external_observations": _legacy_observations_from_state(state),
        "turn_history": _json_list(legacy_dict.get("turn_history")),
        "loop_metrics": _json_object(legacy_dict.get("loop_metrics")),
    }
    extras = legacy_dict.get("extra_fields")
    if isinstance(extras, dict):
        projected.update(copy.deepcopy(extras))
    return projected


def upsert_legacy_observations(
    state: dict[str, Any],
    observations: list[str],
    now: str | None = None,
) -> dict[str, Any]:
    ts = now or utc_now_iso()
    out = copy.deepcopy(state)
    out.setdefault("schema_version", SCHEMA_VERSION)
    out.setdefault("session_id", "")
    out.setdefault("created_at", ts)
    out["updated_at"] = ts
    out.setdefault(
        "ontology",
        {
            "namespace": ONTOLOGY_NAMESPACE,
            "version": ONTOLOGY_VERSION,
        },
    )
    out.setdefault("entities", {})
    out.setdefault("links", {})
    out.setdefault("claims", {})
    out.setdefault("hypotheses", {})
    out.setdefault("questions", {})
    out.setdefault("tasks", {})
    out.setdefault("actions", {})
    out.setdefault("provenance_nodes", {})
    out.setdefault("confidence_profiles", {})
    out.setdefault("timeline", [])

    indexes = out.setdefault("indexes", {})
    if not isinstance(indexes, dict):
        indexes = {}
        out["indexes"] = indexes
    by_external_ref = indexes.setdefault("by_external_ref", {})
    if not isinstance(by_external_ref, dict):
        by_external_ref = {}
        indexes["by_external_ref"] = by_external_ref
    indexes.setdefault("by_tag", {})

    legacy = out.setdefault("legacy", {})
    if not isinstance(legacy, dict):
        legacy = {}
        out["legacy"] = legacy
    legacy["external_observations"] = [str(item) for item in observations]
    legacy.setdefault("turn_history", [])
    legacy.setdefault("loop_metrics", {})
    legacy.setdefault("extra_fields", {})

    evidence = out.setdefault("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
        out["evidence"] = evidence

    for index, observation in enumerate(observations):
        evidence_id = _legacy_evidence_id(index)
        source_uri = _legacy_source_uri(index)
        existing = evidence.get(evidence_id)
        record = existing if isinstance(existing, dict) else {}
        created_at = str(record.get("created_at") or ts)
        record.update(
            {
                "id": evidence_id,
                "evidence_type": "legacy_observation",
                "content": str(observation),
                "source_uri": source_uri,
                "normalization": {
                    "kind": "legacy_observation",
                    "normalization_version": "legacy-v1",
                },
                "provenance_ids": [],
                "confidence_id": None,
                "created_at": created_at,
                "updated_at": ts,
            }
        )
        evidence[evidence_id] = record
        by_external_ref[source_uri] = evidence_id

    keep_ids = {_legacy_evidence_id(index) for index in range(len(observations))}
    for evidence_id in list(evidence.keys()):
        record = evidence.get(evidence_id)
        if _is_legacy_evidence(evidence_id, record) and evidence_id not in keep_ids:
            del evidence[evidence_id]

    for key in list(by_external_ref.keys()):
        value = by_external_ref.get(key)
        if (
            isinstance(key, str)
            and key.startswith("state.json#external_observations[")
            and isinstance(value, str)
            and value.startswith("ev_legacy_")
            and value not in keep_ids
        ):
            del by_external_ref[key]

    return out


def load_investigation_state(path: Path) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise json.JSONDecodeError("Investigation state must be a JSON object", str(path), 0)
    return state


def save_investigation_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def build_question_reasoning_packet(
    state: dict[str, Any],
    *,
    max_questions: int = 8,
    max_evidence_per_item: int = 6,
) -> dict[str, Any]:
    """Build a question-centric reasoning packet from canonical typed state."""

    questions = state.get("questions") if isinstance(state.get("questions"), dict) else {}
    claims = state.get("claims") if isinstance(state.get("claims"), dict) else {}
    evidence = state.get("evidence") if isinstance(state.get("evidence"), dict) else {}
    provenance_nodes = state.get("provenance_nodes") if isinstance(state.get("provenance_nodes"), dict) else {}
    entities = state.get("entities") if isinstance(state.get("entities"), dict) else {}
    links = state.get("links") if isinstance(state.get("links"), dict) else {}

    unresolved_questions: list[dict[str, Any]] = []
    question_records: dict[str, dict[str, Any]] = {}
    for question_id, raw_question in questions.items():
        if not isinstance(raw_question, dict):
            continue
        origin = raw_question.get("origin") if isinstance(raw_question.get("origin"), dict) else {}
        status = str(raw_question.get("status") or "open").lower()
        if status in {"resolved", "closed", "wont_fix", "won't_fix"}:
            continue

        normalized_question = {
            "id": str(raw_question.get("id") or question_id),
            "question": str(raw_question.get("question_text") or raw_question.get("question") or ""),
            "status": status,
            "priority": str(raw_question.get("priority") or "medium").lower(),
            "claim_ids": _id_list(raw_question.get("claim_ids") or raw_question.get("claims") or origin.get("claim_ids")),
            "evidence_ids": _id_list(raw_question.get("evidence_ids") or origin.get("evidence_ids"))[:max_evidence_per_item],
            "triggers": _id_list(
                raw_question.get("trigger")
                or raw_question.get("triggers")
                or origin.get("trigger")
                or origin.get("triggers")
            ),
            "updated_at": str(raw_question.get("updated_at") or ""),
        }
        unresolved_questions.append(normalized_question)
        question_records[normalized_question["id"]] = raw_question

    unresolved_questions.sort(key=_question_priority_sort_key)
    focus_questions = unresolved_questions[: max(1, max_questions)]

    supported: list[dict[str, Any]] = []
    contested: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    claim_records: dict[str, dict[str, Any]] = {}
    claim_summaries: dict[str, dict[str, Any]] = {}

    for claim_id, raw_claim in claims.items():
        if not isinstance(raw_claim, dict):
            continue
        normalized_claim_id = str(raw_claim.get("id") or claim_id)
        claim_status = str(raw_claim.get("status") or "unresolved").lower()
        support_ids = _id_list(
            raw_claim.get("support_evidence_ids")
            or raw_claim.get("evidence_support_ids")
            or raw_claim.get("evidence_ids")
        )
        contradiction_ids = _id_list(
            raw_claim.get("contradiction_evidence_ids")
            or raw_claim.get("evidence_contra_ids")
            or raw_claim.get("contradict_evidence_ids")
        )
        confidence = raw_claim.get("confidence")
        if confidence is None:
            confidence = raw_claim.get("confidence_score")

        claim_summary = {
            "id": normalized_claim_id,
            "claim": str(raw_claim.get("claim_text") or raw_claim.get("text") or ""),
            "status": claim_status,
            "confidence": confidence,
            "support_evidence_ids": support_ids[:max_evidence_per_item],
            "contradiction_evidence_ids": contradiction_ids[:max_evidence_per_item],
        }
        claim_records[normalized_claim_id] = raw_claim
        claim_summaries[normalized_claim_id] = claim_summary

        if contradiction_ids:
            contradictions.append(
                {
                    "claim_id": normalized_claim_id,
                    "support_evidence_ids": support_ids[:max_evidence_per_item],
                    "contradiction_evidence_ids": contradiction_ids[:max_evidence_per_item],
                }
            )

        if claim_status == "supported":
            supported.append(claim_summary)
        elif claim_status == "contested" or contradiction_ids:
            contested.append(claim_summary)
        else:
            unresolved.append(claim_summary)

    evidence_index: dict[str, dict[str, Any]] = {}
    for evidence_id in _collect_evidence_ids(focus_questions, supported, contested, unresolved):
        record = evidence.get(evidence_id)
        if not isinstance(record, dict):
            continue
        evidence_index[evidence_id] = {
            "evidence_type": record.get("evidence_type"),
            "provenance_ids": _id_list(record.get("provenance_ids")),
            "source_uri": record.get("source_uri"),
            "confidence_id": record.get("confidence_id"),
        }

    question_ids_by_claim: dict[str, list[str]] = {}
    for question in unresolved_questions:
        for claim_id in question["claim_ids"]:
            question_ids_by_claim.setdefault(claim_id, []).append(question["id"])

    candidate_actions = _build_candidate_actions(
        focus_questions=focus_questions,
        unresolved_questions=unresolved_questions,
        question_records=question_records,
        question_ids_by_claim=question_ids_by_claim,
        claim_records=claim_records,
        claim_summaries=claim_summaries,
        evidence=evidence,
        evidence_index=evidence_index,
        provenance_nodes=provenance_nodes,
        entities=entities,
        links=links,
        max_evidence_per_item=max_evidence_per_item,
    )

    return {
        "reasoning_mode": "question_centric",
        "loop": [
            "select_unresolved_question",
            "gather_discriminating_evidence",
            "update_claim_status_and_confidence",
            "record_contradictions",
            "synthesize_supported_contested_unresolved",
        ],
        "focus_question_ids": [item["id"] for item in focus_questions],
        "unresolved_questions": focus_questions,
        "findings": {
            "supported": supported,
            "contested": contested,
            "unresolved": unresolved,
        },
        "contradictions": contradictions,
        "evidence_index": evidence_index,
        "candidate_actions": candidate_actions,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _json_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return copy.deepcopy(value)


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return copy.deepcopy(value)


def _id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _question_priority_sort_key(question: dict[str, Any]) -> tuple[int, str]:
    priority = str(question.get("priority") or "medium").lower()
    question_id = str(question.get("id") or "")
    return (_PRIORITY_RANK.get(priority, 9), question_id)


def _build_candidate_actions(
    *,
    focus_questions: list[dict[str, Any]],
    unresolved_questions: list[dict[str, Any]],
    question_records: dict[str, dict[str, Any]],
    question_ids_by_claim: dict[str, list[str]],
    claim_records: dict[str, dict[str, Any]],
    claim_summaries: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    evidence_index: dict[str, dict[str, Any]],
    provenance_nodes: dict[str, Any],
    entities: dict[str, Any],
    links: dict[str, Any],
    max_evidence_per_item: int,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for question in focus_questions:
        question_id = question["id"]
        linked_claim_ids = [claim_id for claim_id in question["claim_ids"] if claim_id in claim_summaries]
        action_type = "verify_claim" if linked_claim_ids else "search"
        evidence_ids = _limit_unique_ids(
            question["evidence_ids"]
            + [
                evidence_id
                for claim_id in linked_claim_ids
                for evidence_id in _claim_evidence_ids(claim_summaries[claim_id])
            ],
            max_evidence_per_item,
        )
        claim_statuses = [str(claim_summaries[claim_id]["status"]) for claim_id in linked_claim_ids]
        reason_codes = ["question_unresolved"]
        if any(status in {"unresolved", "proposed"} for status in claim_statuses):
            reason_codes.append("claim_unresolved")
        if any(_claim_is_low_confidence(claim_summaries[claim_id]) for claim_id in linked_claim_ids):
            reason_codes.append("claim_low_confidence")
        action = {
            "id": f"ca_q_{question_id}",
            "action_type": action_type,
            "status": "proposed",
            "priority": _normalize_priority(question.get("priority")),
            "opened_by_question_id": question_id,
            "target_question_ids": [question_id],
            "target_claim_ids": linked_claim_ids,
            "rationale": {
                "reason_codes": _dedupe_strings(reason_codes),
                "question_status": question.get("status"),
                "claim_statuses": sorted(set(claim_statuses)),
                "current_evidence_count": len(evidence_ids),
                "blocking": True,
            },
            "required_inputs": {
                "question_ids": [question_id],
                "claim_ids": linked_claim_ids,
                "evidence_ids": evidence_ids,
                "entity_ids": _limit_unique_ids(
                    _collect_related_entity_ids(
                        question_records.get(question_id, {}),
                        *[claim_records.get(claim_id, {}) for claim_id in linked_claim_ids],
                    ),
                    max_evidence_per_item,
                ),
                "external_dependencies": [],
            },
            "required_sources": _collect_required_sources(
                question_records.get(question_id, {}),
                *[claim_records.get(claim_id, {}) for claim_id in linked_claim_ids],
                evidence_ids=evidence_ids,
                evidence=evidence,
                provenance_nodes=provenance_nodes,
            ),
            "suggested_tools": list(_SUGGESTED_TOOLS[action_type]),
            "expected_payoff": _build_expected_payoff(action_type, _normalize_priority(question.get("priority"))),
            "evidence_gap_refs": _dedupe_gap_refs(
                _build_question_gap_refs(question_id, evidence_ids)
                + [
                    gap
                    for claim_id in linked_claim_ids
                    for gap in _build_claim_gap_refs(
                        claim_id=claim_id,
                        opened_by_question_id=question_id,
                        claim_summary=claim_summaries[claim_id],
                    )
                ]
            ),
            "ontology_object_refs": _dedupe_object_refs(
                _build_ontology_object_refs(
                    question_ids=[question_id],
                    claim_ids=linked_claim_ids,
                    evidence_ids=evidence_ids,
                    question_records=question_records,
                    claim_records=claim_records,
                    evidence=evidence,
                    provenance_nodes=provenance_nodes,
                    entities=entities,
                    links=links,
                )
            ),
        }
        if action["id"] not in seen_ids:
            seen_ids.add(action["id"])
            actions.append(action)

    for claim_id, claim_summary in claim_summaries.items():
        claim_status = str(claim_summary.get("status") or "unresolved").lower()
        confidence = _parse_confidence(claim_summary.get("confidence"))
        if claim_status in {"retracted", "resolved", "closed"}:
            continue
        if not (
            claim_status in {"unresolved", "proposed"}
            or confidence is None
            or confidence < LOW_CONFIDENCE_THRESHOLD
        ):
            continue
        opened_by_question_id = next(iter(question_ids_by_claim.get(claim_id, [])), None)
        question_priority = None
        if opened_by_question_id is not None:
            question_priority = _question_priority(unresolved_questions, opened_by_question_id)
        priority = _merge_priority(_claim_priority(claim_status, confidence), question_priority)
        evidence_ids = _claim_evidence_ids(claim_summary)
        action = {
            "id": f"ca_c_{claim_id}",
            "action_type": "verify_claim",
            "status": "proposed",
            "priority": priority,
            "opened_by_question_id": opened_by_question_id,
            "target_question_ids": [opened_by_question_id] if opened_by_question_id else [],
            "target_claim_ids": [claim_id],
            "rationale": {
                "reason_codes": _dedupe_strings(
                    _claim_reason_codes(claim_status, confidence)
                    + (["question_unresolved"] if opened_by_question_id else [])
                ),
                "claim_status": claim_status,
                "confidence": confidence,
                "current_evidence_count": len(evidence_ids),
                "blocking": True,
            },
            "required_inputs": {
                "question_ids": [opened_by_question_id] if opened_by_question_id else [],
                "claim_ids": [claim_id],
                "evidence_ids": evidence_ids,
                "entity_ids": _limit_unique_ids(
                    _collect_related_entity_ids(
                        claim_records.get(claim_id, {}),
                        question_records.get(opened_by_question_id, {}) if opened_by_question_id else {},
                    ),
                    max_evidence_per_item,
                ),
                "external_dependencies": [],
            },
            "required_sources": _collect_required_sources(
                claim_records.get(claim_id, {}),
                question_records.get(opened_by_question_id, {}) if opened_by_question_id else {},
                evidence_ids=evidence_ids,
                evidence=evidence,
                provenance_nodes=provenance_nodes,
            ),
            "suggested_tools": list(_SUGGESTED_TOOLS["verify_claim"]),
            "expected_payoff": _build_expected_payoff("verify_claim", priority),
            "evidence_gap_refs": _dedupe_gap_refs(
                _build_claim_gap_refs(
                    claim_id=claim_id,
                    opened_by_question_id=opened_by_question_id,
                    claim_summary=claim_summary,
                )
            ),
            "ontology_object_refs": _dedupe_object_refs(
                _build_ontology_object_refs(
                    question_ids=[opened_by_question_id] if opened_by_question_id else [],
                    claim_ids=[claim_id],
                    evidence_ids=evidence_ids,
                    question_records=question_records,
                    claim_records=claim_records,
                    evidence=evidence,
                    provenance_nodes=provenance_nodes,
                    entities=entities,
                    links=links,
                )
            ),
        }
        if action["id"] not in seen_ids:
            seen_ids.add(action["id"])
            actions.append(action)

    actions.sort(key=_candidate_action_sort_key)
    return actions[:MAX_CANDIDATE_ACTIONS]


def _normalize_priority(priority: Any) -> str:
    value = str(priority or "medium").lower()
    return value if value in _PRIORITY_RANK else "medium"


def _question_priority(questions: list[dict[str, Any]], question_id: str) -> str | None:
    for question in questions:
        if question.get("id") == question_id:
            return _normalize_priority(question.get("priority"))
    return None


def _merge_priority(*priorities: str | None) -> str:
    normalized = [_normalize_priority(priority) for priority in priorities if priority]
    if not normalized:
        return "medium"
    return min(normalized, key=lambda value: (_PRIORITY_RANK.get(value, 9), value))


def _claim_priority(claim_status: str, confidence: float | None) -> str:
    if claim_status in {"unresolved", "proposed"}:
        return "high"
    if confidence is None:
        return "high"
    if confidence <= VERY_LOW_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def _parse_confidence(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, parsed))


def _claim_evidence_ids(claim_summary: dict[str, Any]) -> list[str]:
    return _limit_unique_ids(
        _id_list(claim_summary.get("support_evidence_ids"))
        + _id_list(claim_summary.get("contradiction_evidence_ids")),
        10_000,
    )


def _claim_reason_codes(claim_status: str, confidence: float | None) -> list[str]:
    reason_codes: list[str] = []
    if claim_status in {"unresolved", "proposed"}:
        reason_codes.append("claim_unresolved")
    if confidence is None:
        reason_codes.append("claim_missing_confidence")
    elif confidence < LOW_CONFIDENCE_THRESHOLD:
        reason_codes.append("claim_low_confidence")
    return reason_codes


def _claim_is_low_confidence(claim_summary: dict[str, Any]) -> bool:
    confidence = _parse_confidence(claim_summary.get("confidence"))
    return confidence is None or confidence < LOW_CONFIDENCE_THRESHOLD


def _limit_unique_ids(values: list[str], max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= max_items:
            break
    return out


def _dedupe_strings(values: list[str]) -> list[str]:
    return _limit_unique_ids(values, len(values) or 1)


def _build_expected_payoff(action_type: str, priority: str) -> dict[str, float]:
    base = {
        "critical": 0.90,
        "high": 0.75,
        "medium": 0.55,
        "low": 0.35,
    }.get(priority, 0.55)
    graph_expansion_value = 0.40 if action_type == "search" else 0.30
    payoff_score = round((0.45 * base) + (0.35 * base) + (0.20 * graph_expansion_value), 4)
    return {
        "uncertainty_reduction": round(base, 4),
        "decision_impact": round(base, 4),
        "graph_expansion_value": round(graph_expansion_value, 4),
        "payoff_score": payoff_score,
    }


def _build_question_gap_refs(question_id: str, evidence_ids: list[str]) -> list[dict[str, Any]]:
    if evidence_ids:
        return []
    return [
        {
            "gap_id": f"gap:question:{question_id}:missing_evidence",
            "kind": "missing_evidence",
            "scope": "question",
            "question_id": question_id,
            "current_evidence_ids": [],
            "current_evidence_count": 0,
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": True,
        }
    ]


def _build_claim_gap_refs(
    *,
    claim_id: str,
    opened_by_question_id: str | None,
    claim_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    support_ids = _id_list(claim_summary.get("support_evidence_ids"))
    contradiction_ids = _id_list(claim_summary.get("contradiction_evidence_ids"))
    evidence_ids = _limit_unique_ids(support_ids + contradiction_ids, 10_000)
    confidence = _parse_confidence(claim_summary.get("confidence"))
    claim_status = str(claim_summary.get("status") or "unresolved").lower()
    refs: list[dict[str, Any]] = []
    if not evidence_ids:
        refs.append(
            {
                "gap_id": f"gap:claim:{claim_id}:missing_evidence",
                "kind": "missing_evidence",
                "scope": "claim",
                "question_id": opened_by_question_id,
                "claim_id": claim_id,
                "current_evidence_ids": [],
                "current_evidence_count": 0,
                "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
                "blocking": True,
            }
        )
    if claim_status in {"unresolved", "contested", "proposed"} and evidence_ids and (not support_ids or not contradiction_ids):
        refs.append(
            {
                "gap_id": f"gap:claim:{claim_id}:missing_counter_evidence",
                "kind": "missing_counter_evidence",
                "scope": "claim",
                "question_id": opened_by_question_id,
                "claim_id": claim_id,
                "current_evidence_ids": evidence_ids,
                "current_evidence_count": len(evidence_ids),
                "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
                "blocking": True,
            }
        )
    if confidence is None:
        refs.append(
            {
                "gap_id": f"gap:claim:{claim_id}:missing_confidence",
                "kind": "missing_confidence",
                "scope": "claim",
                "question_id": opened_by_question_id,
                "claim_id": claim_id,
                "current_evidence_ids": evidence_ids,
                "current_evidence_count": len(evidence_ids),
                "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
                "blocking": True,
            }
        )
    elif confidence < LOW_CONFIDENCE_THRESHOLD:
        refs.append(
            {
                "gap_id": f"gap:claim:{claim_id}:low_confidence",
                "kind": "low_confidence",
                "scope": "claim",
                "question_id": opened_by_question_id,
                "claim_id": claim_id,
                "current_evidence_ids": evidence_ids,
                "current_evidence_count": len(evidence_ids),
                "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
                "blocking": True,
            }
        )
    return refs


def _dedupe_gap_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        gap_id = str(ref.get("gap_id") or "")
        if not gap_id or gap_id in seen:
            continue
        seen.add(gap_id)
        out.append(ref)
    return out


def _build_ontology_object_refs(
    *,
    question_ids: list[str],
    claim_ids: list[str],
    evidence_ids: list[str],
    question_records: dict[str, dict[str, Any]],
    claim_records: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    provenance_nodes: dict[str, Any],
    entities: dict[str, Any],
    links: dict[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for question_id in question_ids:
        record = question_records.get(question_id, {})
        refs.append(
            _object_ref(
                object_id=question_id,
                object_type="question",
                relation="opened_by",
                label=str(record.get("question_text") or record.get("question") or question_id),
            )
        )
        refs.extend(_entity_and_link_refs(record, entities=entities, links=links))
    for claim_id in claim_ids:
        record = claim_records.get(claim_id, {})
        refs.append(
            _object_ref(
                object_id=claim_id,
                object_type="claim",
                relation="targets",
                label=str(record.get("claim_text") or record.get("text") or claim_id),
            )
        )
        refs.extend(_entity_and_link_refs(record, entities=entities, links=links))
    for evidence_id in evidence_ids:
        record = evidence.get(evidence_id)
        if not isinstance(record, dict):
            continue
        refs.append(
            _object_ref(
                object_id=evidence_id,
                object_type="evidence",
                relation="depends_on",
                label=str(record.get("source_uri") or record.get("evidence_type") or evidence_id),
            )
        )
        refs.extend(_entity_and_link_refs(record, entities=entities, links=links))
        for provenance_id in _id_list(record.get("provenance_ids")):
            provenance = provenance_nodes.get(provenance_id) if isinstance(provenance_nodes.get(provenance_id), dict) else {}
            refs.append(
                _object_ref(
                    object_id=provenance_id,
                    object_type="provenance_node",
                    relation="supported_by",
                    label=str(
                        provenance.get("title")
                        or provenance.get("name")
                        or provenance.get("source_uri")
                        or provenance_id
                    ),
                )
            )
        confidence_id = record.get("confidence_id")
        if confidence_id is not None:
            refs.append(
                _object_ref(
                    object_id=str(confidence_id),
                    object_type="confidence_profile",
                    relation="depends_on",
                )
            )
    return refs


def _entity_and_link_refs(
    record: dict[str, Any],
    *,
    entities: dict[str, Any],
    links: dict[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for entity_id in _collect_related_entity_ids(record):
        entity = entities.get(entity_id) if isinstance(entities.get(entity_id), dict) else {}
        refs.append(
            _object_ref(
                object_id=entity_id,
                object_type="entity",
                relation="about",
                label=str(entity.get("name") or entity.get("label") or entity_id),
            )
        )
    for link_id in _collect_related_link_ids(record):
        link = links.get(link_id) if isinstance(links.get(link_id), dict) else {}
        refs.append(
            _object_ref(
                object_id=link_id,
                object_type="link",
                relation="about",
                label=str(link.get("label") or link.get("type") or link_id),
            )
        )
    return refs


def _object_ref(
    *,
    object_id: str,
    object_type: str,
    relation: str,
    label: str | None = None,
) -> dict[str, Any]:
    ref = {
        "object_id": object_id,
        "object_type": object_type,
        "relation": relation,
    }
    if label:
        ref["label"] = label
    return ref


def _dedupe_object_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        object_id = str(ref.get("object_id") or "")
        relation = str(ref.get("relation") or "")
        if not object_id:
            continue
        key = (object_id, relation)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _collect_related_entity_ids(*records: dict[str, Any]) -> list[str]:
    keys = (
        "subject_refs",
        "related_entity_ids",
        "entity_ids",
        "entities",
        "about_entity_ids",
        "subject_entity_ids",
        "object_entity_ids",
        "target_entity_ids",
    )
    return _collect_nested_ids(keys, *records)


def _collect_related_link_ids(*records: dict[str, Any]) -> list[str]:
    return _collect_nested_ids(("link_ids", "links"), *records)


def _collect_nested_ids(keys: tuple[str, ...], *records: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            raw_value = record.get(key)
            if isinstance(raw_value, list):
                values.extend(str(item) for item in raw_value if item is not None)
            elif raw_value is not None and not isinstance(raw_value, dict):
                values.append(str(raw_value))
    return _limit_unique_ids(values, 10_000)


def _collect_required_sources(
    *records: dict[str, Any],
    evidence_ids: list[str],
    evidence: dict[str, Any],
    provenance_nodes: dict[str, Any],
) -> list[str]:
    sources: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        sources.extend(_extract_source_values(record))
        for provenance_id in _id_list(record.get("provenance_ids")):
            provenance = provenance_nodes.get(provenance_id)
            if isinstance(provenance, dict):
                sources.extend(_extract_source_values(provenance))
    for evidence_id in evidence_ids:
        record = evidence.get(evidence_id)
        if not isinstance(record, dict):
            continue
        sources.extend(_extract_source_values(record))
        for provenance_id in _id_list(record.get("provenance_ids")):
            provenance = provenance_nodes.get(provenance_id)
            if isinstance(provenance, dict):
                sources.extend(_extract_source_values(provenance))
    return _limit_unique_ids(sources, 32)


def _extract_source_values(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("source_uri", "canonical_source_uri", "url"):
        value = record.get(key)
        if value:
            values.append(str(value))
    for key in ("source_uris", "required_sources", "sources", "urls"):
        value = record.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
    return _limit_unique_ids(values, 32)


def _candidate_action_sort_key(action: dict[str, Any]) -> tuple[int, int, str]:
    action_id = str(action.get("id") or "")
    kind_rank = 0 if action_id.startswith("ca_q_") else 1
    priority = _normalize_priority(action.get("priority"))
    return (_PRIORITY_RANK.get(priority, 9), kind_rank, action_id)


def _collect_evidence_ids(*collections: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for collection in collections:
        for item in collection:
            if not isinstance(item, dict):
                continue
            for key in ("evidence_ids", "support_evidence_ids", "contradiction_evidence_ids"):
                values = item.get(key)
                if not isinstance(values, list):
                    continue
                for value in values:
                    evidence_id = str(value)
                    if evidence_id in seen:
                        continue
                    seen.add(evidence_id)
                    out.append(evidence_id)
    return out


def _observations_from_rust_state(state: dict[str, Any]) -> list[str]:
    observations = state.get("observations")
    if not isinstance(observations, list):
        return []

    out: list[str] = []
    for item in observations:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            out.append(content)
    return out


def _extra_fields_from_legacy_state(state: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key, value in state.items():
        if key not in _LEGACY_KNOWN_KEYS:
            extras[key] = copy.deepcopy(value)
    return extras


def _legacy_observations_from_state(state: dict[str, Any]) -> list[str]:
    legacy = state.get("legacy", {})
    if isinstance(legacy, dict):
        persisted = legacy.get("external_observations")
        if isinstance(persisted, list):
            return [str(item) for item in persisted]

    evidence = state.get("evidence", {})
    if isinstance(evidence, dict):
        legacy_records: list[tuple[str, str]] = []
        for evidence_id, record in evidence.items():
            if not _is_legacy_evidence(str(evidence_id), record):
                continue
            content = record.get("content") if isinstance(record, dict) else None
            if isinstance(content, str):
                legacy_records.append((str(evidence_id), content))
        legacy_records.sort(key=lambda item: item[0])
        return [content for _, content in legacy_records]

    return []


def _legacy_evidence_id(index: int) -> str:
    return f"ev_legacy_{index + 1:06d}"


def _legacy_source_uri(index: int) -> str:
    return f"state.json#external_observations[{index}]"


def _is_legacy_evidence(evidence_id: str, record: Any) -> bool:
    if not evidence_id.startswith("ev_legacy_") or not isinstance(record, dict):
        return False
    normalization = record.get("normalization")
    return isinstance(normalization, dict) and normalization.get("kind") == "legacy_observation"
