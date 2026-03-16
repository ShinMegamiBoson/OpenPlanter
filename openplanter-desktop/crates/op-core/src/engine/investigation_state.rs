use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

const SCHEMA_VERSION: &str = "1.0.0";
const ONTOLOGY_NAMESPACE: &str = "openplanter.core";
const ONTOLOGY_VERSION: &str = "2026-03";
const LOW_CONFIDENCE_THRESHOLD: f64 = 0.60;
const VERY_LOW_CONFIDENCE_THRESHOLD: f64 = 0.40;
const MAX_CANDIDATE_ACTIONS: usize = 24;
const REQUIRED_EVIDENCE_COUNT: usize = 1;
const PLANNER_GENERATED_BY: &str = "question_reasoning_packet.v1";
const LEGACY_KNOWN_KEYS: &[&str] = &[
    "session_id",
    "saved_at",
    "external_observations",
    "observations",
    "turn_history",
    "loop_metrics",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InvestigationState {
    #[serde(default = "default_schema_version")]
    pub schema_version: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub updated_at: String,
    #[serde(default)]
    pub objective: String,
    #[serde(default)]
    pub ontology: Ontology,
    #[serde(default)]
    pub entities: BTreeMap<String, Value>,
    #[serde(default)]
    pub links: BTreeMap<String, Value>,
    #[serde(default)]
    pub claims: BTreeMap<String, Value>,
    #[serde(default)]
    pub evidence: BTreeMap<String, Value>,
    #[serde(default)]
    pub hypotheses: BTreeMap<String, Value>,
    #[serde(default)]
    pub questions: BTreeMap<String, Value>,
    #[serde(default)]
    pub tasks: BTreeMap<String, Value>,
    #[serde(default)]
    pub actions: BTreeMap<String, Value>,
    #[serde(default)]
    pub provenance_nodes: BTreeMap<String, Value>,
    #[serde(default)]
    pub confidence_profiles: BTreeMap<String, Value>,
    #[serde(default)]
    pub timeline: Vec<Value>,
    #[serde(default)]
    pub indexes: Indexes,
    #[serde(default)]
    pub legacy: LegacyState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ontology {
    #[serde(default = "default_ontology_namespace")]
    pub namespace: String,
    #[serde(default = "default_ontology_version")]
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LegacyState {
    #[serde(default)]
    pub external_observations: Vec<String>,
    #[serde(default)]
    pub turn_history: Vec<Value>,
    #[serde(default)]
    pub loop_metrics: Map<String, Value>,
    #[serde(default)]
    pub extra_fields: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Indexes {
    #[serde(default)]
    pub by_external_ref: BTreeMap<String, Value>,
    #[serde(default)]
    pub by_tag: BTreeMap<String, Value>,
}

impl Default for InvestigationState {
    fn default() -> Self {
        Self::new("")
    }
}

impl Default for Ontology {
    fn default() -> Self {
        Self {
            namespace: default_ontology_namespace(),
            version: default_ontology_version(),
        }
    }
}

impl InvestigationState {
    pub fn new(session_id: &str) -> Self {
        let ts = now();
        Self {
            schema_version: default_schema_version(),
            session_id: session_id.to_string(),
            created_at: ts.clone(),
            updated_at: ts,
            objective: String::new(),
            ontology: Ontology::default(),
            entities: BTreeMap::new(),
            links: BTreeMap::new(),
            claims: BTreeMap::new(),
            evidence: BTreeMap::new(),
            hypotheses: BTreeMap::new(),
            questions: BTreeMap::new(),
            tasks: BTreeMap::new(),
            actions: BTreeMap::new(),
            provenance_nodes: BTreeMap::new(),
            confidence_profiles: BTreeMap::new(),
            timeline: vec![],
            indexes: Indexes::default(),
            legacy: LegacyState::default(),
        }
    }

    pub fn from_legacy_python_state(session_id: &str, legacy_json: &Value) -> Self {
        let mut state = Self::new(session_id);
        let Some(obj) = legacy_json.as_object() else {
            return state;
        };

        if let Some(saved_at) = obj.get("saved_at").and_then(Value::as_str) {
            state.updated_at = saved_at.to_string();
            state.created_at = saved_at.to_string();
        }
        if let Some(session_id) = obj.get("session_id").and_then(Value::as_str) {
            state.session_id = session_id.to_string();
        }
        state.legacy.external_observations = obj
            .get("external_observations")
            .and_then(Value::as_array)
            .map(|items| string_vec(items))
            .unwrap_or_default();
        state.legacy.turn_history = obj
            .get("turn_history")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        state.legacy.loop_metrics = obj
            .get("loop_metrics")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        state.legacy.extra_fields = extra_fields_from_object(obj);
        let observations = state.legacy.external_observations.clone();
        state.merge_legacy_updates(
            &observations,
            Some(&state.legacy.turn_history.clone()),
            Some(&state.legacy.loop_metrics.clone()),
            Some(&state.legacy.extra_fields.clone()),
        );
        state
    }

    pub fn from_legacy_rust_state(session_id: &str, legacy_json: &Value) -> Self {
        let mut state = Self::new(session_id);
        let Some(obj) = legacy_json.as_object() else {
            return state;
        };

        state.legacy.external_observations = obj
            .get("observations")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| item.get("content").and_then(Value::as_str))
                    .map(ToString::to_string)
                    .collect()
            })
            .unwrap_or_default();
        state.legacy.extra_fields = extra_fields_from_object(obj);
        let observations = state.legacy.external_observations.clone();
        state.merge_legacy_updates(
            &observations,
            Some(&state.legacy.turn_history.clone()),
            Some(&state.legacy.loop_metrics.clone()),
            Some(&state.legacy.extra_fields.clone()),
        );
        state
    }

    pub fn legacy_observations(&self) -> Vec<String> {
        if !self.legacy.external_observations.is_empty() {
            return self.legacy.external_observations.clone();
        }

        let mut observations: Vec<(String, String)> = self
            .evidence
            .iter()
            .filter_map(|(evidence_id, record)| {
                if !is_legacy_evidence(evidence_id, record) {
                    return None;
                }
                record
                    .get("content")
                    .and_then(Value::as_str)
                    .map(|content| (evidence_id.clone(), content.to_string()))
            })
            .collect();
        observations.sort_by(|left, right| left.0.cmp(&right.0));
        observations
            .into_iter()
            .map(|(_, content)| content)
            .collect()
    }

    pub fn merge_legacy_updates(
        &mut self,
        observations: &[String],
        turn_history: Option<&[Value]>,
        loop_metrics: Option<&Map<String, Value>>,
        extra_fields: Option<&BTreeMap<String, Value>>,
    ) {
        let ts = now();
        if self.created_at.is_empty() {
            self.created_at = ts.clone();
        }
        self.updated_at = ts.clone();
        self.schema_version = default_schema_version();
        self.legacy.external_observations = observations.to_vec();
        if let Some(turn_history) = turn_history {
            self.legacy.turn_history = turn_history.to_vec();
        }
        if let Some(loop_metrics) = loop_metrics {
            self.legacy.loop_metrics = loop_metrics.clone();
        }
        if let Some(extra_fields) = extra_fields {
            self.legacy.extra_fields = extra_fields.clone();
        }

        for (index, observation) in observations.iter().enumerate() {
            let evidence_id = legacy_evidence_id(index);
            let source_uri = legacy_source_uri(index);
            let created_at = self
                .evidence
                .get(&evidence_id)
                .and_then(|value| value.get("created_at"))
                .and_then(Value::as_str)
                .unwrap_or(ts.as_str())
                .to_string();
            self.evidence.insert(
                evidence_id.clone(),
                serde_json::json!({
                    "id": evidence_id,
                    "evidence_type": "legacy_observation",
                    "content": observation,
                    "source_uri": source_uri,
                    "normalization": {
                        "kind": "legacy_observation",
                        "normalization_version": "legacy-v1",
                    },
                    "provenance_ids": [],
                    "confidence_id": Value::Null,
                    "created_at": created_at,
                    "updated_at": ts,
                }),
            );
            self.indexes
                .by_external_ref
                .insert(source_uri, Value::String(legacy_evidence_id(index)));
        }

        let keep_ids: BTreeSet<String> = (0..observations.len()).map(legacy_evidence_id).collect();
        self.evidence.retain(|evidence_id, record| {
            !is_legacy_evidence(evidence_id, record) || keep_ids.contains(evidence_id)
        });
        self.indexes.by_external_ref.retain(|source_ref, target| {
            if !source_ref.starts_with("state.json#external_observations[") {
                return true;
            }
            target
                .as_str()
                .map(|target| keep_ids.contains(target))
                .unwrap_or(false)
        });
    }

    pub fn to_legacy_python_projection(&self) -> Value {
        let mut projected = Map::new();
        projected.insert(
            "session_id".to_string(),
            Value::String(self.session_id.clone()),
        );
        projected.insert(
            "saved_at".to_string(),
            Value::String(self.updated_at.clone()),
        );
        projected.insert(
            "external_observations".to_string(),
            Value::Array(
                self.legacy_observations()
                    .into_iter()
                    .map(Value::String)
                    .collect(),
            ),
        );
        projected.insert(
            "turn_history".to_string(),
            Value::Array(self.legacy.turn_history.clone()),
        );
        projected.insert(
            "loop_metrics".to_string(),
            Value::Object(self.legacy.loop_metrics.clone()),
        );
        for (key, value) in &self.legacy.extra_fields {
            projected
                .entry(key.clone())
                .or_insert_with(|| value.clone());
        }
        Value::Object(projected)
    }
}

pub fn build_question_reasoning_packet(
    state: &InvestigationState,
    max_questions: usize,
    max_evidence_per_item: usize,
) -> Value {
    let mut unresolved_questions: Vec<Value> = state
        .questions
        .iter()
        .filter_map(|(question_id, raw_question)| {
            let question = raw_question.as_object()?;
            let status = question
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("open")
                .to_ascii_lowercase();
            if matches!(
                status.as_str(),
                "resolved" | "closed" | "wont_fix" | "won't_fix"
            ) {
                return None;
            }

            Some(normalize_unresolved_question(
                question_id,
                question,
                &status,
                max_evidence_per_item,
            ))
        })
        .collect();
    unresolved_questions.sort_by(question_priority_sort_key);
    unresolved_questions.truncate(std::cmp::max(1, max_questions));
    let focus_question_ids = unresolved_questions
        .iter()
        .filter_map(|item| {
            item.get("id")
                .and_then(Value::as_str)
                .map(ToString::to_string)
        })
        .collect::<Vec<_>>();

    let mut supported = Vec::new();
    let mut contested = Vec::new();
    let mut unresolved = Vec::new();
    let mut contradictions = Vec::new();

    for (claim_id, raw_claim) in &state.claims {
        let Some(claim) = raw_claim.as_object() else {
            continue;
        };
        let claim_status = claim
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unresolved")
            .to_ascii_lowercase();
        let support_ids = claim_support_evidence_ids(claim, max_evidence_per_item);
        let contradiction_ids = claim_contradiction_evidence_ids(claim, max_evidence_per_item);
        let has_contradictions = !contradiction_ids.is_empty();
        let confidence = claim
            .get("confidence")
            .cloned()
            .or_else(|| claim.get("confidence_score").cloned())
            .unwrap_or(Value::Null);
        let claim_summary = serde_json::json!({
            "id": claim.get("id").and_then(Value::as_str).unwrap_or(claim_id),
            "claim": claim
                .get("claim_text")
                .and_then(Value::as_str)
                .or_else(|| claim.get("text").and_then(Value::as_str))
                .unwrap_or_default(),
            "status": claim_status,
            "confidence": confidence,
            "support_evidence_ids": support_ids,
            "contradiction_evidence_ids": contradiction_ids,
        });

        if has_contradictions {
            contradictions.push(serde_json::json!({
                "claim_id": claim.get("id").and_then(Value::as_str).unwrap_or(claim_id),
                "support_evidence_ids": claim_summary["support_evidence_ids"].clone(),
                "contradiction_evidence_ids": claim_summary["contradiction_evidence_ids"].clone(),
            }));
        }

        if claim_status == "supported" {
            supported.push(claim_summary);
        } else if claim_status == "contested" || has_contradictions {
            contested.push(claim_summary);
        } else {
            unresolved.push(claim_summary);
        }
    }

    let mut evidence_index = Map::new();
    for evidence_id in
        collect_evidence_ids(&[&unresolved_questions, &supported, &contested, &unresolved])
    {
        let Some(record) = state.evidence.get(&evidence_id).and_then(Value::as_object) else {
            continue;
        };
        evidence_index.insert(
            evidence_id.clone(),
            serde_json::json!({
                "evidence_type": record.get("evidence_type").cloned().unwrap_or(Value::Null),
                "provenance_ids": id_list(record.get("provenance_ids")),
                "source_uri": record.get("source_uri").cloned().unwrap_or(Value::Null),
                "confidence_id": record.get("confidence_id").cloned().unwrap_or(Value::Null),
            }),
        );
    }
    let candidate_actions = build_candidate_actions(
        state,
        &unresolved_questions,
        &focus_question_ids,
        max_evidence_per_item,
    );

    serde_json::json!({
        "reasoning_mode": "question_centric",
        "loop": [
            "select_unresolved_question",
            "gather_discriminating_evidence",
            "update_claim_status_and_confidence",
            "record_contradictions",
            "synthesize_supported_contested_unresolved",
        ],
        "focus_question_ids": focus_question_ids,
        "unresolved_questions": unresolved_questions,
        "findings": {
            "supported": supported,
            "contested": contested,
            "unresolved": unresolved,
        },
        "contradictions": contradictions,
        "evidence_index": evidence_index,
        "candidate_actions": candidate_actions,
    })
}

pub fn has_reasoning_content(packet: &Value) -> bool {
    let Some(obj) = packet.as_object() else {
        return false;
    };
    if obj
        .get("candidate_actions")
        .and_then(Value::as_array)
        .is_some_and(|items| !items.is_empty())
    {
        return true;
    }
    if obj
        .get("focus_question_ids")
        .and_then(Value::as_array)
        .is_some_and(|items| !items.is_empty())
    {
        return true;
    }
    if obj
        .get("contradictions")
        .and_then(Value::as_array)
        .is_some_and(|items| !items.is_empty())
    {
        return true;
    }
    obj.get("findings")
        .and_then(Value::as_object)
        .is_some_and(|findings| {
            ["supported", "contested", "unresolved"].iter().any(|key| {
                findings
                    .get(*key)
                    .and_then(Value::as_array)
                    .is_some_and(|items| !items.is_empty())
            })
        })
}

fn build_candidate_actions(
    state: &InvestigationState,
    focus_questions: &[Value],
    focus_question_ids: &[String],
    max_evidence_per_item: usize,
) -> Vec<Value> {
    let mut actions = Vec::new();
    let mut seen = BTreeSet::new();

    for question in focus_questions {
        let Some(question_obj) = question.as_object() else {
            continue;
        };
        let question_id = question_obj
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if question_id.is_empty() {
            continue;
        }
        let question_record = find_question_record(state, question_id).unwrap_or(question_obj);
        let claim_ids = question_claim_ids(question_obj);
        let question_evidence_ids = question_evidence_ids(question_obj, max_evidence_per_item);
        let linked_claim_evidence_ids = claim_ids
            .iter()
            .flat_map(|claim_id| claim_evidence_ids(state, claim_id, max_evidence_per_item))
            .collect::<Vec<_>>();
        let evidence_ids = dedupe_strings(
            question_evidence_ids
                .iter()
                .chain(linked_claim_evidence_ids.iter())
                .cloned()
                .collect(),
        );
        let entity_ids = question_entity_ids(state, question_record, &claim_ids, &evidence_ids);
        let mut reason_codes = vec!["question_unresolved".to_string()];
        for claim_id in &claim_ids {
            for code in claim_reason_codes(state, claim_id) {
                if !reason_codes.contains(&code) {
                    reason_codes.push(code);
                }
            }
        }
        let evidence_gap_refs = build_question_gap_refs(
            state,
            question_id,
            question_record,
            &claim_ids,
            &question_evidence_ids,
            max_evidence_per_item,
        );
        let dependency_refs = gap_ids(&evidence_gap_refs);
        let ontology_object_refs = build_ontology_object_refs(
            state,
            Some(question_id),
            &claim_ids,
            &evidence_ids,
            &entity_ids,
            &dependency_refs,
        );
        let mut source_records = vec![question_record];
        for claim_id in &claim_ids {
            let Some(claim) = state.claims.get(claim_id).and_then(Value::as_object) else {
                continue;
            };
            source_records.push(claim);
        }
        let required_sources = collect_required_sources(state, &source_records, &evidence_ids);
        let action_type = if claim_ids.is_empty() {
            "search"
        } else {
            "verify_claim"
        };
        let priority = normalize_priority(
            question_obj
                .get("priority")
                .and_then(Value::as_str)
                .unwrap_or("medium"),
        );
        let action_id = format!("ca_q_{question_id}");
        if seen.insert(action_id.clone()) {
            actions.push(serde_json::json!({
                "id": action_id,
                "action_type": action_type,
                "status": "proposed",
                "priority": priority,
                "title": format!("Resolve question {question_id}"),
                "description": format!("Advance question {question_id} using discriminating evidence tied to canonical state refs."),
                "opened_by_question_id": question_id,
                "target_question_ids": [question_id],
                "target_claim_ids": claim_ids,
                "reason_codes": reason_codes.clone(),
                "rationale": {
                    "summary": "question_unresolved",
                    "reason_codes": reason_codes,
                    "blocking_gap_ids": dependency_refs,
                },
                "required_sources": required_sources,
                "required_inputs": {
                    "question_ids": [question_id],
                    "claim_ids": claim_ids,
                    "evidence_ids": evidence_ids,
                    "entity_ids": entity_ids,
                    "external_dependencies": Vec::<String>::new(),
                },
                "expected_payoff": payoff_for_priority(priority, action_type),
                "suggested_tools": suggested_tools(action_type),
                "evidence_gap_refs": evidence_gap_refs,
                "ontology_object_refs": ontology_object_refs,
                "generated_by": PLANNER_GENERATED_BY,
            }));
        }
    }

    for (claim_id, raw_claim) in &state.claims {
        let Some(claim) = raw_claim.as_object() else {
            continue;
        };
        let claim_status = claim_status(claim);
        if matches!(claim_status.as_str(), "retracted" | "resolved" | "closed") {
            continue;
        }
        let confidence = claim_confidence(claim);
        let reason_codes = claim_reason_codes(state, claim_id);
        if reason_codes.is_empty() {
            continue;
        }
        let evidence_ids = claim_evidence_ids(state, claim_id, max_evidence_per_item);
        let entity_ids = claim_entity_ids(state, claim, &evidence_ids);
        let evidence_gap_refs = build_claim_gap_refs(
            state,
            claim_id,
            &claim_status,
            confidence,
            &evidence_ids,
            max_evidence_per_item,
        );
        let dependency_refs = gap_ids(&evidence_gap_refs);
        let opened_by_question_id = focus_questions
            .iter()
            .filter_map(Value::as_object)
            .find(|question| {
                question_claim_ids(question)
                    .iter()
                    .any(|candidate| candidate == claim_id)
            })
            .and_then(|question| question.get("id").and_then(Value::as_str))
            .map(ToString::to_string);
        let target_question_ids = opened_by_question_id
            .clone()
            .into_iter()
            .filter(|question_id| {
                focus_question_ids
                    .iter()
                    .any(|candidate| candidate == question_id)
            })
            .collect::<Vec<_>>();
        let ontology_object_refs = build_ontology_object_refs(
            state,
            opened_by_question_id.as_deref(),
            &[claim_id.clone()],
            &evidence_ids,
            &entity_ids,
            &dependency_refs,
        );
        let mut source_records = vec![claim];
        if let Some(question_id) = opened_by_question_id.as_deref() {
            if let Some(question) = find_question_record(state, question_id) {
                source_records.push(question);
            }
        }
        let required_sources = collect_required_sources(state, &source_records, &evidence_ids);
        let priority = claim_candidate_priority(&claim_status, confidence);
        let action_id = format!("ca_c_{claim_id}");
        if seen.insert(action_id.clone()) {
            actions.push(serde_json::json!({
                "id": action_id,
                "action_type": "verify_claim",
                "status": "proposed",
                "priority": priority,
                "title": format!("Verify claim {claim_id}"),
                "description": format!("Raise confidence for claim {claim_id} with additional cited evidence and contradiction tracking."),
                "opened_by_question_id": opened_by_question_id,
                "target_question_ids": target_question_ids,
                "target_claim_ids": [claim_id],
                "reason_codes": reason_codes.clone(),
                "rationale": {
                    "summary": "claim_requires_verification",
                    "reason_codes": reason_codes,
                    "blocking_gap_ids": dependency_refs,
                },
                "required_sources": required_sources,
                "required_inputs": {
                    "question_ids": target_question_ids,
                    "claim_ids": [claim_id],
                    "evidence_ids": evidence_ids,
                    "entity_ids": entity_ids,
                    "external_dependencies": Vec::<String>::new(),
                },
                "expected_payoff": payoff_for_priority(priority, "verify_claim"),
                "suggested_tools": suggested_tools("verify_claim"),
                "evidence_gap_refs": evidence_gap_refs,
                "ontology_object_refs": ontology_object_refs,
                "generated_by": PLANNER_GENERATED_BY,
            }));
        }
    }

    actions.sort_by(candidate_action_sort_key);
    actions.truncate(MAX_CANDIDATE_ACTIONS);
    actions
}

fn candidate_action_sort_key(left: &Value, right: &Value) -> std::cmp::Ordering {
    let left_priority = question_priority_rank(left.get("priority").and_then(Value::as_str));
    let right_priority = question_priority_rank(right.get("priority").and_then(Value::as_str));
    left_priority
        .cmp(&right_priority)
        .then_with(|| candidate_action_origin_rank(left).cmp(&candidate_action_origin_rank(right)))
        .then_with(|| {
            left.get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .cmp(right.get("id").and_then(Value::as_str).unwrap_or_default())
        })
}

fn candidate_action_origin_rank(action: &Value) -> u8 {
    match action
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .starts_with("ca_q_")
    {
        true => 0,
        false => 1,
    }
}

fn normalize_priority(priority: &str) -> &'static str {
    match priority.to_ascii_lowercase().as_str() {
        "critical" => "critical",
        "high" => "high",
        "medium" => "medium",
        "low" => "low",
        _ => "medium",
    }
}

fn claim_candidate_priority(claim_status: &str, confidence: Option<f64>) -> &'static str {
    if matches!(claim_status, "unresolved" | "proposed") {
        "high"
    } else if confidence.is_some_and(|value| value <= VERY_LOW_CONFIDENCE_THRESHOLD) {
        "high"
    } else {
        "medium"
    }
}

fn claim_status(claim: &Map<String, Value>) -> String {
    claim
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unresolved")
        .to_ascii_lowercase()
}

fn claim_confidence(claim: &Map<String, Value>) -> Option<f64> {
    parse_confidence(
        claim
            .get("confidence")
            .or_else(|| claim.get("confidence_score")),
    )
}

fn find_question_record<'a>(
    state: &'a InvestigationState,
    question_id: &str,
) -> Option<&'a Map<String, Value>> {
    state
        .questions
        .get(question_id)
        .and_then(Value::as_object)
        .or_else(|| {
            state
                .questions
                .values()
                .filter_map(Value::as_object)
                .find(|record| record.get("id").and_then(Value::as_str) == Some(question_id))
        })
}

fn question_claim_ids(question: &Map<String, Value>) -> Vec<String> {
    id_list(
        question
            .get("claim_ids")
            .or_else(|| question.get("claims"))
            .or_else(|| {
                question
                    .get("origin")
                    .and_then(Value::as_object)
                    .and_then(|origin| origin.get("claim_ids"))
            }),
    )
}

fn question_trigger_ids(question: &Map<String, Value>) -> Vec<String> {
    let origin = question.get("origin").and_then(Value::as_object);
    id_list(
        question
            .get("trigger")
            .or_else(|| question.get("triggers"))
            .or_else(|| origin.and_then(|origin| origin.get("trigger")))
            .or_else(|| origin.and_then(|origin| origin.get("triggers"))),
    )
}

fn question_evidence_ids(
    question: &Map<String, Value>,
    max_evidence_per_item: usize,
) -> Vec<String> {
    limit_ids(
        question.get("evidence_ids").or_else(|| {
            question
                .get("origin")
                .and_then(Value::as_object)
                .and_then(|origin| origin.get("evidence_ids"))
        }),
        max_evidence_per_item,
    )
}

fn normalize_unresolved_question(
    question_id: &str,
    question: &Map<String, Value>,
    status: &str,
    max_evidence_per_item: usize,
) -> Value {
    serde_json::json!({
        "id": question.get("id").and_then(Value::as_str).unwrap_or(question_id),
        "question": question
            .get("question_text")
            .and_then(Value::as_str)
            .or_else(|| question.get("question").and_then(Value::as_str))
            .unwrap_or_default(),
        "status": status,
        "priority": question
            .get("priority")
            .and_then(Value::as_str)
            .unwrap_or("medium")
            .to_ascii_lowercase(),
        "claim_ids": question_claim_ids(question),
        "evidence_ids": question_evidence_ids(question, max_evidence_per_item),
        "triggers": question_trigger_ids(question),
        "updated_at": question
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or_default(),
    })
}

fn claim_evidence_ids(
    state: &InvestigationState,
    claim_id: &str,
    max_evidence_per_item: usize,
) -> Vec<String> {
    let Some(claim) = state.claims.get(claim_id).and_then(Value::as_object) else {
        return Vec::new();
    };
    dedupe_strings(
        claim_support_evidence_ids(claim, max_evidence_per_item)
            .into_iter()
            .chain(claim_contradiction_evidence_ids(
                claim,
                max_evidence_per_item,
            ))
            .collect(),
    )
}

fn claim_support_evidence_ids(
    claim: &Map<String, Value>,
    max_evidence_per_item: usize,
) -> Vec<String> {
    limit_ids(
        claim
            .get("support_evidence_ids")
            .or_else(|| claim.get("evidence_support_ids"))
            .or_else(|| claim.get("evidence_ids")),
        max_evidence_per_item,
    )
}

fn claim_contradiction_evidence_ids(
    claim: &Map<String, Value>,
    max_evidence_per_item: usize,
) -> Vec<String> {
    limit_ids(
        claim
            .get("contradiction_evidence_ids")
            .or_else(|| claim.get("evidence_contra_ids"))
            .or_else(|| claim.get("contradict_evidence_ids")),
        max_evidence_per_item,
    )
}

fn claim_reason_codes(state: &InvestigationState, claim_id: &str) -> Vec<String> {
    let Some(claim) = state.claims.get(claim_id).and_then(Value::as_object) else {
        return Vec::new();
    };
    let claim_status = claim_status(claim);
    let confidence = claim_confidence(claim);
    let mut reason_codes = Vec::new();
    if matches!(claim_status.as_str(), "unresolved" | "proposed") {
        reason_codes.push("claim_unresolved".to_string());
    }
    if confidence.is_none() {
        reason_codes.push("claim_missing_confidence".to_string());
    } else if confidence.is_some_and(|value| value < LOW_CONFIDENCE_THRESHOLD) {
        reason_codes.push("claim_low_confidence".to_string());
    }
    reason_codes
}

fn build_question_gap_refs(
    state: &InvestigationState,
    question_id: &str,
    question: &Map<String, Value>,
    claim_ids: &[String],
    question_evidence_ids: &[String],
    max_evidence_per_item: usize,
) -> Vec<Value> {
    let mut refs = Vec::new();
    if question_evidence_ids.is_empty() {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:question:{question_id}:missing_evidence"),
            "kind": "missing_evidence",
            "scope": "question",
            "question_id": question_id,
            "claim_id": Value::Null,
            "current_evidence_ids": [],
            "current_evidence_count": 0,
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    }
    let related_entity_ids = id_list(question.get("related_entity_ids"));
    if !related_entity_ids.is_empty() && question_evidence_ids.is_empty() {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:question:{question_id}:missing_entity_evidence"),
            "kind": "missing_evidence",
            "scope": "question",
            "question_id": question_id,
            "claim_id": Value::Null,
            "current_evidence_ids": question_evidence_ids,
            "current_evidence_count": question_evidence_ids.len(),
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    }
    for claim_id in claim_ids {
        refs.extend(build_claim_gap_refs(
            state,
            claim_id,
            &state
                .claims
                .get(claim_id)
                .and_then(Value::as_object)
                .map(claim_status)
                .unwrap_or_else(|| "unresolved".to_string()),
            state
                .claims
                .get(claim_id)
                .and_then(Value::as_object)
                .and_then(claim_confidence),
            &claim_evidence_ids(state, claim_id, max_evidence_per_item),
            max_evidence_per_item,
        ));
    }
    dedupe_objects_by_id(refs, "gap_id")
}

fn build_claim_gap_refs(
    state: &InvestigationState,
    claim_id: &str,
    claim_status: &str,
    confidence: Option<f64>,
    evidence_ids: &[String],
    max_evidence_per_item: usize,
) -> Vec<Value> {
    let Some(claim) = state.claims.get(claim_id).and_then(Value::as_object) else {
        return Vec::new();
    };
    let support_ids = claim_support_evidence_ids(claim, max_evidence_per_item);
    let contradiction_ids = claim_contradiction_evidence_ids(claim, max_evidence_per_item);
    let mut refs = Vec::new();
    if evidence_ids.is_empty() {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:claim:{claim_id}:missing_evidence"),
            "kind": "missing_evidence",
            "scope": "claim",
            "question_id": Value::Null,
            "claim_id": claim_id,
            "current_evidence_ids": [],
            "current_evidence_count": 0,
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    }
    if matches!(
        claim_status.to_ascii_lowercase().as_str(),
        "unresolved" | "contested" | "proposed"
    ) && (!support_ids.is_empty() || !contradiction_ids.is_empty())
        && (support_ids.is_empty() || contradiction_ids.is_empty())
    {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:claim:{claim_id}:missing_counter_evidence"),
            "kind": "missing_counter_evidence",
            "scope": "claim",
            "question_id": Value::Null,
            "claim_id": claim_id,
            "current_evidence_ids": evidence_ids,
            "current_evidence_count": evidence_ids.len(),
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    }
    if confidence.is_none() {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:claim:{claim_id}:missing_confidence"),
            "kind": "missing_confidence",
            "scope": "claim",
            "question_id": Value::Null,
            "claim_id": claim_id,
            "current_evidence_ids": evidence_ids,
            "current_evidence_count": evidence_ids.len(),
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    } else if confidence.is_some_and(|value| value < LOW_CONFIDENCE_THRESHOLD) {
        refs.push(serde_json::json!({
            "gap_id": format!("gap:claim:{claim_id}:low_confidence"),
            "kind": "low_confidence",
            "scope": "claim",
            "question_id": Value::Null,
            "claim_id": claim_id,
            "current_evidence_ids": evidence_ids,
            "current_evidence_count": evidence_ids.len(),
            "required_evidence_count": REQUIRED_EVIDENCE_COUNT,
            "blocking": true,
        }));
    }
    refs
}

fn gap_ids(gap_refs: &[Value]) -> Vec<String> {
    gap_refs
        .iter()
        .filter_map(|item| {
            item.get("gap_id")
                .and_then(Value::as_str)
                .map(ToString::to_string)
        })
        .collect()
}

fn suggested_tools(action_type: &str) -> Vec<&'static str> {
    match action_type {
        "search" => vec!["web_search", "fetch_url", "search_files", "read_file"],
        _ => vec!["web_search", "fetch_url", "read_file", "search_files"],
    }
}

fn payoff_for_priority(priority: &str, action_type: &str) -> Value {
    let base = match priority {
        "critical" => 0.90,
        "high" => 0.75,
        "medium" => 0.55,
        "low" => 0.35,
        _ => 0.55,
    };
    let graph_expansion_value = if action_type == "search" { 0.40 } else { 0.30 };
    let estimated_cost = 0.0;
    let payoff_score =
        (0.45 * base) + (0.35 * base) + (0.20 * graph_expansion_value) - estimated_cost;
    serde_json::json!({
        "uncertainty_reduction": base,
        "decision_impact": base,
        "graph_expansion_value": graph_expansion_value,
        "estimated_cost": estimated_cost,
        "payoff_score": payoff_score,
    })
}

fn collect_required_sources(
    state: &InvestigationState,
    records: &[&Map<String, Value>],
    evidence_ids: &[String],
) -> Vec<String> {
    let mut sources = BTreeSet::new();
    for record in records {
        for candidate in source_values_from_record(record) {
            sources.insert(candidate);
        }
        for provenance_id in id_list(record.get("provenance_ids")) {
            let Some(provenance) = state
                .provenance_nodes
                .get(&provenance_id)
                .and_then(Value::as_object)
            else {
                continue;
            };
            for candidate in source_values_from_record(provenance) {
                sources.insert(candidate);
            }
        }
    }
    for evidence_id in evidence_ids {
        let Some(record) = state.evidence.get(evidence_id).and_then(Value::as_object) else {
            continue;
        };
        for candidate in source_values_from_record(record) {
            sources.insert(candidate);
        }
        for provenance_id in id_list(record.get("provenance_ids")) {
            let Some(provenance) = state
                .provenance_nodes
                .get(&provenance_id)
                .and_then(Value::as_object)
            else {
                continue;
            };
            for candidate in source_values_from_record(provenance) {
                sources.insert(candidate);
            }
        }
    }
    sources.into_iter().collect()
}

fn source_values_from_record(record: &Map<String, Value>) -> Vec<String> {
    let mut values = Vec::new();
    for key in ["source_uri", "canonical_source_uri", "url"] {
        if let Some(source) = record.get(key).and_then(Value::as_str) {
            if !source.trim().is_empty() {
                values.push(source.to_string());
            }
        }
    }
    for key in ["source_uris", "required_sources", "sources", "urls"] {
        values.extend(id_list(record.get(key)));
    }
    values
}

fn build_ontology_object_refs(
    state: &InvestigationState,
    question_id: Option<&str>,
    claim_ids: &[String],
    evidence_ids: &[String],
    entity_ids: &[String],
    dependency_refs: &[String],
) -> Vec<Value> {
    let mut refs = Vec::new();
    let mut seen = BTreeSet::new();
    if let Some(question_id) = question_id {
        add_object_ref(
            &mut refs,
            &mut seen,
            question_id,
            "question",
            "opened_by",
            state.questions.get(question_id),
        );
    }
    for claim_id in claim_ids {
        add_object_ref(
            &mut refs,
            &mut seen,
            claim_id,
            "claim",
            "targets",
            state.claims.get(claim_id),
        );
    }
    for evidence_id in evidence_ids {
        add_object_ref(
            &mut refs,
            &mut seen,
            evidence_id,
            "evidence",
            "depends_on",
            state.evidence.get(evidence_id),
        );
        let Some(record) = state.evidence.get(evidence_id).and_then(Value::as_object) else {
            continue;
        };
        for provenance_id in id_list(record.get("provenance_ids")) {
            add_object_ref(
                &mut refs,
                &mut seen,
                &provenance_id,
                "provenance_node",
                "supported_by",
                state.provenance_nodes.get(&provenance_id),
            );
        }
        if let Some(confidence_id) = record.get("confidence_id").and_then(Value::as_str) {
            add_object_ref(
                &mut refs,
                &mut seen,
                confidence_id,
                "confidence_profile",
                "scored_by",
                state.confidence_profiles.get(confidence_id),
            );
        }
    }
    for entity_id in entity_ids {
        add_object_ref(
            &mut refs,
            &mut seen,
            entity_id,
            "entity",
            "about",
            state.entities.get(entity_id),
        );
    }
    for dependency_ref in dependency_refs {
        add_object_ref(
            &mut refs,
            &mut seen,
            dependency_ref,
            "evidence_gap",
            "blocked_by",
            None,
        );
    }
    refs
}

fn add_object_ref(
    refs: &mut Vec<Value>,
    seen: &mut BTreeSet<String>,
    object_id: &str,
    object_type: &str,
    relation: &str,
    record: Option<&Value>,
) {
    let key = format!("{object_type}:{object_id}:{relation}");
    if !seen.insert(key) {
        return;
    }
    refs.push(serde_json::json!({
        "object_id": object_id,
        "object_type": object_type,
        "relation": relation,
        "label": record.and_then(object_label),
    }));
}

fn object_label(record: &Value) -> Option<String> {
    let obj = record.as_object()?;
    for key in [
        "title",
        "label",
        "name",
        "question_text",
        "question",
        "claim_text",
        "text",
        "content",
    ] {
        if let Some(value) = obj.get(key).and_then(Value::as_str) {
            if !value.trim().is_empty() {
                return Some(safe_label(value));
            }
        }
    }
    obj.get("source_uri")
        .and_then(Value::as_str)
        .map(safe_label)
}

fn safe_label(value: &str) -> String {
    let trimmed = value.trim();
    let end = trimmed.floor_char_boundary(trimmed.len().min(96));
    trimmed[..end].to_string()
}

fn question_entity_ids(
    state: &InvestigationState,
    question: &Map<String, Value>,
    claim_ids: &[String],
    evidence_ids: &[String],
) -> Vec<String> {
    let mut ids = collect_related_object_ids(
        question,
        &[
            "related_entity_ids",
            "entity_ids",
            "entities",
            "target_entity_ids",
        ],
    );
    for claim_id in claim_ids {
        let Some(claim) = state.claims.get(claim_id).and_then(Value::as_object) else {
            continue;
        };
        ids.extend(claim_entity_ids(state, claim, evidence_ids));
    }
    dedupe_strings(ids)
}

fn claim_entity_ids(
    state: &InvestigationState,
    claim: &Map<String, Value>,
    evidence_ids: &[String],
) -> Vec<String> {
    let mut ids = collect_related_object_ids(
        claim,
        &[
            "subject_refs",
            "related_entity_ids",
            "entity_ids",
            "entities",
            "subject_entity_ids",
            "object_entity_ids",
            "about_entity_ids",
        ],
    );
    for evidence_id in evidence_ids {
        let Some(evidence) = state.evidence.get(evidence_id).and_then(Value::as_object) else {
            continue;
        };
        ids.extend(collect_related_object_ids(
            evidence,
            &[
                "related_entity_ids",
                "entity_ids",
                "entities",
                "subject_entity_ids",
                "object_entity_ids",
                "about_entity_ids",
            ],
        ));
    }
    dedupe_strings(ids)
}

fn collect_related_object_ids(record: &Map<String, Value>, keys: &[&str]) -> Vec<String> {
    let mut ids = Vec::new();
    for key in keys {
        ids.extend(id_list(record.get(*key)));
    }
    ids
}

fn dedupe_strings(items: Vec<String>) -> Vec<String> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for item in items {
        if item.trim().is_empty() || !seen.insert(item.clone()) {
            continue;
        }
        out.push(item);
    }
    out
}

fn dedupe_objects_by_id(items: Vec<Value>, key: &str) -> Vec<Value> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for item in items {
        let Some(id) = item.get(key).and_then(Value::as_str) else {
            continue;
        };
        if seen.insert(id.to_string()) {
            out.push(item);
        }
    }
    out
}

fn parse_confidence(value: Option<&Value>) -> Option<f64> {
    let value = value?;
    let parsed = if let Some(number) = value.as_f64() {
        Some(number)
    } else {
        value
            .as_str()
            .and_then(|text| text.trim().parse::<f64>().ok())
    }?;
    Some(parsed.clamp(0.0, 1.0))
}

fn default_schema_version() -> String {
    SCHEMA_VERSION.to_string()
}

fn default_ontology_namespace() -> String {
    ONTOLOGY_NAMESPACE.to_string()
}

fn default_ontology_version() -> String {
    ONTOLOGY_VERSION.to_string()
}

fn now() -> String {
    Utc::now().to_rfc3339()
}

fn legacy_evidence_id(index: usize) -> String {
    format!("ev_legacy_{:06}", index + 1)
}

fn legacy_source_uri(index: usize) -> String {
    format!("state.json#external_observations[{index}]")
}

fn string_vec(items: &[Value]) -> Vec<String> {
    items
        .iter()
        .filter_map(Value::as_str)
        .map(ToString::to_string)
        .collect()
}

fn extra_fields_from_object(obj: &Map<String, Value>) -> BTreeMap<String, Value> {
    obj.iter()
        .filter(|(key, _)| !LEGACY_KNOWN_KEYS.contains(&key.as_str()))
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect()
}

fn is_legacy_evidence(evidence_id: &str, record: &Value) -> bool {
    if !evidence_id.starts_with("ev_legacy_") {
        return false;
    }
    record
        .get("normalization")
        .and_then(Value::as_object)
        .and_then(|normalization| normalization.get("kind"))
        .and_then(Value::as_str)
        == Some("legacy_observation")
}

fn id_list(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter(|item| !item.is_null())
                .map(stringify_value)
                .collect()
        })
        .unwrap_or_default()
}

fn limit_ids(value: Option<&Value>, max_items: usize) -> Vec<String> {
    let mut ids = id_list(value);
    ids.truncate(max_items);
    ids
}

fn stringify_value(value: &Value) -> String {
    value
        .as_str()
        .map(ToString::to_string)
        .unwrap_or_else(|| value.to_string())
}

fn question_priority_sort_key(left: &Value, right: &Value) -> std::cmp::Ordering {
    let left_rank = question_priority_rank(left.get("priority").and_then(Value::as_str));
    let right_rank = question_priority_rank(right.get("priority").and_then(Value::as_str));
    left_rank.cmp(&right_rank).then_with(|| {
        left.get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .cmp(right.get("id").and_then(Value::as_str).unwrap_or_default())
    })
}

fn question_priority_rank(priority: Option<&str>) -> u8 {
    match priority.unwrap_or("medium").to_ascii_lowercase().as_str() {
        "critical" => 0,
        "high" => 1,
        "medium" => 2,
        "low" => 3,
        _ => 9,
    }
}

fn collect_evidence_ids(collections: &[&Vec<Value>]) -> Vec<String> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for collection in collections {
        for item in *collection {
            let Some(obj) = item.as_object() else {
                continue;
            };
            for key in [
                "evidence_ids",
                "support_evidence_ids",
                "contradiction_evidence_ids",
            ] {
                let Some(values) = obj.get(key).and_then(Value::as_array) else {
                    continue;
                };
                for value in values {
                    let evidence_id = stringify_value(value);
                    if seen.insert(evidence_id.clone()) {
                        out.push(evidence_id);
                    }
                }
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrates_legacy_python_state_with_extra_fields() {
        let legacy = serde_json::json!({
            "session_id": "sid",
            "saved_at": "2026-03-13T00:00:00Z",
            "external_observations": ["obs-a", "obs-b"],
            "turn_history": [{"turn_number": 1}],
            "loop_metrics": {"turns": 1},
            "custom_field": "keep-me"
        });

        let state = InvestigationState::from_legacy_python_state("sid", &legacy);
        assert_eq!(state.legacy.external_observations, vec!["obs-a", "obs-b"]);
        assert_eq!(
            state.legacy.extra_fields.get("custom_field"),
            Some(&Value::String("keep-me".to_string()))
        );
        assert_eq!(
            state.evidence["ev_legacy_000001"]["source_uri"],
            Value::String("state.json#external_observations[0]".to_string())
        );
    }

    #[test]
    fn merge_legacy_updates_preserves_non_legacy_fields_and_prunes_old_legacy_entries() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_1".to_string(),
            serde_json::json!({"id": "q_1", "question_text": "keep me"}),
        );
        state.evidence.insert(
            "ev_other".to_string(),
            serde_json::json!({
                "id": "ev_other",
                "content": "keep me",
                "normalization": {"kind": "web_fetch"}
            }),
        );
        state.evidence.insert(
            "ev_legacy_000002".to_string(),
            serde_json::json!({
                "id": "ev_legacy_000002",
                "content": "remove me",
                "normalization": {"kind": "legacy_observation"}
            }),
        );
        let extra_fields = BTreeMap::from([(
            "custom_field".to_string(),
            Value::String("after".to_string()),
        )]);

        state.merge_legacy_updates(&[String::from("fresh")], None, None, Some(&extra_fields));

        assert!(state.questions.contains_key("q_1"));
        assert!(state.evidence.contains_key("ev_other"));
        assert!(!state.evidence.contains_key("ev_legacy_000002"));
        assert_eq!(
            state.evidence["ev_legacy_000001"]["content"],
            Value::String("fresh".to_string())
        );
        assert_eq!(
            state.legacy.extra_fields.get("custom_field"),
            Some(&Value::String("after".to_string()))
        );
    }

    #[test]
    fn build_question_reasoning_packet_groups_findings_and_contradictions() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_2".to_string(),
            serde_json::json!({
                "id": "q_2",
                "question_text": "Is claim 2 true?",
                "status": "open",
                "priority": "high",
                "claim_ids": ["cl_2"],
                "evidence_ids": ["ev_2"],
            }),
        );
        state.questions.insert(
            "q_1".to_string(),
            serde_json::json!({
                "id": "q_1",
                "question_text": "Is claim 1 true?",
                "status": "open",
                "priority": "critical",
                "claim_ids": ["cl_1"],
                "evidence_ids": ["ev_1", "ev_3"],
            }),
        );
        state.questions.insert(
            "q_done".to_string(),
            serde_json::json!({
                "id": "q_done",
                "question_text": "Ignore",
                "status": "resolved",
            }),
        );
        state.claims.insert(
            "cl_1".to_string(),
            serde_json::json!({
                "claim_text": "Claim supported",
                "status": "supported",
                "support_evidence_ids": ["ev_1"],
                "confidence": 0.91,
            }),
        );
        state.claims.insert(
            "cl_2".to_string(),
            serde_json::json!({
                "claim_text": "Claim contested",
                "status": "contested",
                "support_evidence_ids": ["ev_2"],
                "contradiction_evidence_ids": ["ev_3"],
                "confidence_score": 0.4,
            }),
        );
        state.claims.insert(
            "cl_3".to_string(),
            serde_json::json!({
                "claim_text": "Claim unresolved",
                "status": "unresolved",
                "evidence_ids": ["ev_4"],
            }),
        );
        state.evidence.insert(
            "ev_1".to_string(),
            serde_json::json!({"evidence_type": "doc", "provenance_ids": ["pv_1"], "source_uri": "s1"}),
        );
        state.evidence.insert(
            "ev_2".to_string(),
            serde_json::json!({"evidence_type": "doc", "provenance_ids": ["pv_2"], "source_uri": "s2"}),
        );
        state.evidence.insert(
            "ev_3".to_string(),
            serde_json::json!({"evidence_type": "doc", "provenance_ids": ["pv_3"], "source_uri": "s3"}),
        );
        state.evidence.insert(
            "ev_4".to_string(),
            serde_json::json!({"evidence_type": "doc", "provenance_ids": ["pv_4"], "source_uri": "s4"}),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);

        assert_eq!(
            packet["reasoning_mode"],
            Value::String("question_centric".to_string())
        );
        assert_eq!(
            packet["focus_question_ids"],
            serde_json::json!(["q_1", "q_2"])
        );
        assert_eq!(
            packet["findings"]["supported"][0]["id"],
            Value::String("cl_1".to_string())
        );
        assert_eq!(
            packet["findings"]["contested"][0]["id"],
            Value::String("cl_2".to_string())
        );
        assert_eq!(
            packet["findings"]["unresolved"][0]["id"],
            Value::String("cl_3".to_string())
        );
        assert_eq!(
            packet["contradictions"][0]["claim_id"],
            Value::String("cl_2".to_string())
        );
        assert!(packet["evidence_index"].get("ev_3").is_some());
        assert_eq!(
            packet["candidate_actions"][0]["id"],
            Value::String("ca_q_q_1".to_string())
        );
        assert_eq!(
            packet["candidate_actions"][0]["required_sources"],
            serde_json::json!(["s1", "s3"])
        );
        assert_eq!(
            packet["candidate_actions"][1]["id"],
            Value::String("ca_q_q_2".to_string())
        );
        assert_eq!(
            packet["candidate_actions"][2]["reason_codes"],
            serde_json::json!(["claim_low_confidence"])
        );
        assert_eq!(
            packet["candidate_actions"][2]["evidence_gap_refs"][0]["kind"],
            Value::String("low_confidence".to_string())
        );
        assert_eq!(
            packet["candidate_actions"][3]["id"],
            Value::String("ca_c_cl_3".to_string())
        );
        assert_eq!(
            packet["candidate_actions"][3]["evidence_gap_refs"][0]["kind"],
            Value::String("missing_counter_evidence".to_string())
        );
        assert!(has_reasoning_content(&packet));
    }

    #[test]
    fn candidate_actions_keep_entity_inputs_entity_only_and_collect_question_sources() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_1".to_string(),
            serde_json::json!({
                "id": "q_1",
                "question_text": "What source confirms the claim?",
                "status": "open",
                "priority": "high",
                "claim_ids": ["cl_1"],
                "resolution_claim_id": "cl_resolution",
                "provenance_ids": ["pv_q_1"],
            }),
        );
        state.claims.insert(
            "cl_1".to_string(),
            serde_json::json!({
                "id": "cl_1",
                "claim_text": "Needs evidence",
                "status": "proposed",
                "evidence_ids": [],
                "confidence": 0.2,
            }),
        );
        state.provenance_nodes.insert(
            "pv_q_1".to_string(),
            serde_json::json!({
                "id": "pv_q_1",
                "source_uri": "https://question-source.test",
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);
        let action = packet["candidate_actions"]
            .as_array()
            .and_then(|items| {
                items
                    .iter()
                    .find(|item| item.get("id") == Some(&Value::String("ca_q_q_1".to_string())))
            })
            .expect("question action");

        assert_eq!(
            action["required_inputs"]["entity_ids"],
            serde_json::json!([])
        );
        assert_eq!(
            action["required_sources"],
            serde_json::json!(["https://question-source.test"])
        );
        assert!(
            !action["ontology_object_refs"]
                .as_array()
                .is_some_and(|refs| refs
                    .iter()
                    .any(|item| item.get("object_type")
                        == Some(&Value::String("entity".to_string()))))
        );
    }

    #[test]
    fn question_normalization_falls_back_to_origin_claims_and_evidence() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_origin".to_string(),
            serde_json::json!({
                "id": "q_origin",
                "question_text": "Origin-backed question",
                "status": "open",
                "priority": "high",
                "origin": {
                    "claim_ids": ["cl_origin"],
                    "evidence_ids": ["ev_origin_1", "ev_origin_2"],
                },
            }),
        );
        state.claims.insert(
            "cl_origin".to_string(),
            serde_json::json!({
                "id": "cl_origin",
                "claim_text": "Origin-backed claim",
                "status": "supported",
                "support_evidence_ids": ["ev_claim"],
                "confidence": 0.8,
            }),
        );
        state.evidence.insert(
            "ev_origin_1".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://origin-question-1.test",
            }),
        );
        state.evidence.insert(
            "ev_origin_2".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://origin-question-2.test",
            }),
        );
        state.evidence.insert(
            "ev_claim".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://origin-claim.test",
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 1);
        let normalized_question = packet["unresolved_questions"]
            .as_array()
            .and_then(|items| items.first())
            .expect("normalized question");
        let question_action = packet["candidate_actions"]
            .as_array()
            .and_then(|items| {
                items.iter().find(|item| {
                    item.get("id") == Some(&Value::String("ca_q_q_origin".to_string()))
                })
            })
            .expect("question action");

        assert_eq!(
            packet["focus_question_ids"],
            serde_json::json!(["q_origin"])
        );
        assert_eq!(
            normalized_question["claim_ids"],
            serde_json::json!(["cl_origin"])
        );
        assert_eq!(
            normalized_question["evidence_ids"],
            serde_json::json!(["ev_origin_1"])
        );
        assert_eq!(
            question_action["target_claim_ids"],
            serde_json::json!(["cl_origin"])
        );
        assert_eq!(
            question_action["required_inputs"]["evidence_ids"],
            serde_json::json!(["ev_origin_1", "ev_claim"])
        );
        assert!(packet["evidence_index"].get("ev_origin_1").is_some());
        assert!(packet["evidence_index"].get("ev_claim").is_some());
        assert!(packet["evidence_index"].get("ev_origin_2").is_none());
    }

    #[test]
    fn question_normalization_uses_origin_trigger_aliases() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_origin_trigger".to_string(),
            serde_json::json!({
                "id": "q_origin_trigger",
                "question_text": "Origin trigger question",
                "status": "open",
                "priority": "high",
                "origin": {
                    "trigger": ["trigger_a"],
                },
            }),
        );
        state.questions.insert(
            "q_origin_triggers".to_string(),
            serde_json::json!({
                "id": "q_origin_triggers",
                "question_text": "Origin triggers question",
                "status": "open",
                "priority": "medium",
                "origin": {
                    "triggers": ["trigger_b", "trigger_c"],
                },
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);
        let questions = packet["unresolved_questions"]
            .as_array()
            .expect("unresolved questions");
        let trigger_question = questions
            .iter()
            .find(|item| item.get("id") == Some(&Value::String("q_origin_trigger".to_string())))
            .expect("origin trigger question");
        let triggers_question = questions
            .iter()
            .find(|item| item.get("id") == Some(&Value::String("q_origin_triggers".to_string())))
            .expect("origin triggers question");

        assert_eq!(
            trigger_question["triggers"],
            serde_json::json!(["trigger_a"])
        );
        assert_eq!(
            triggers_question["triggers"],
            serde_json::json!(["trigger_b", "trigger_c"])
        );
    }

    #[test]
    fn question_normalization_prefers_top_level_values_over_origin() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_override".to_string(),
            serde_json::json!({
                "id": "q_override",
                "question_text": "Override question",
                "status": "open",
                "priority": "high",
                "claim_ids": ["cl_top"],
                "evidence_ids": ["ev_top"],
                "trigger": ["trigger_top"],
                "origin": {
                    "claim_ids": ["cl_origin"],
                    "evidence_ids": ["ev_origin"],
                    "trigger": ["trigger_origin"],
                    "triggers": ["trigger_origin_fallback"],
                },
            }),
        );
        state.claims.insert(
            "cl_top".to_string(),
            serde_json::json!({
                "id": "cl_top",
                "claim_text": "Top-level claim",
                "status": "supported",
                "support_evidence_ids": ["ev_claim_top"],
                "confidence": 0.9,
            }),
        );
        state.claims.insert(
            "cl_origin".to_string(),
            serde_json::json!({
                "id": "cl_origin",
                "claim_text": "Origin claim",
                "status": "supported",
                "support_evidence_ids": ["ev_claim_origin"],
                "confidence": 0.9,
            }),
        );
        state.evidence.insert(
            "ev_top".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://top-level-question.test",
            }),
        );
        state.evidence.insert(
            "ev_claim_top".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://top-level-claim.test",
            }),
        );
        state.evidence.insert(
            "ev_claim_origin".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://origin-claim.test",
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);
        let normalized_question = packet["unresolved_questions"]
            .as_array()
            .and_then(|items| items.first())
            .expect("normalized question");
        let question_action = packet["candidate_actions"]
            .as_array()
            .and_then(|items| {
                items.iter().find(|item| {
                    item.get("id") == Some(&Value::String("ca_q_q_override".to_string()))
                })
            })
            .expect("question action");

        assert_eq!(
            normalized_question["claim_ids"],
            serde_json::json!(["cl_top"])
        );
        assert_eq!(
            normalized_question["evidence_ids"],
            serde_json::json!(["ev_top"])
        );
        assert_eq!(
            normalized_question["triggers"],
            serde_json::json!(["trigger_top"])
        );
        assert_eq!(
            question_action["target_claim_ids"],
            serde_json::json!(["cl_top"])
        );
        assert_eq!(
            question_action["required_inputs"]["evidence_ids"],
            serde_json::json!(["ev_top", "ev_claim_top"])
        );
        assert_eq!(
            question_action["required_sources"],
            serde_json::json!([
                "https://top-level-claim.test",
                "https://top-level-question.test"
            ])
        );
    }

    #[test]
    fn reasoning_packet_uses_canonical_claim_evidence_aliases_in_findings_and_sources() {
        let mut state = InvestigationState::new("sid");
        state.questions.insert(
            "q_alias".to_string(),
            serde_json::json!({
                "id": "q_alias",
                "question_text": "What evidence supports the alias-backed claim?",
                "status": "open",
                "priority": "high",
                "claim_ids": ["cl_alias"],
                "evidence_ids": [],
            }),
        );
        state.claims.insert(
            "cl_alias".to_string(),
            serde_json::json!({
                "id": "cl_alias",
                "claim_text": "Alias-backed claim",
                "status": "contested",
                "evidence_support_ids": ["ev_support_alias"],
                "evidence_contra_ids": ["ev_contra_alias"],
                "confidence": 0.4,
            }),
        );
        state.evidence.insert(
            "ev_support_alias".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://support.test",
            }),
        );
        state.evidence.insert(
            "ev_contra_alias".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://contra.test",
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);

        assert_eq!(
            packet["findings"]["contested"][0]["support_evidence_ids"],
            serde_json::json!(["ev_support_alias"])
        );
        assert_eq!(
            packet["findings"]["contested"][0]["contradiction_evidence_ids"],
            serde_json::json!(["ev_contra_alias"])
        );
        assert_eq!(
            packet["contradictions"][0]["support_evidence_ids"],
            serde_json::json!(["ev_support_alias"])
        );
        assert_eq!(
            packet["contradictions"][0]["contradiction_evidence_ids"],
            serde_json::json!(["ev_contra_alias"])
        );
        assert!(packet["evidence_index"].get("ev_support_alias").is_some());
        assert!(packet["evidence_index"].get("ev_contra_alias").is_some());

        let actions = packet["candidate_actions"]
            .as_array()
            .expect("candidate actions");
        let question_action = actions
            .iter()
            .find(|action| action.get("id") == Some(&Value::String("ca_q_q_alias".to_string())))
            .expect("question action");
        let claim_action = actions
            .iter()
            .find(|action| action.get("id") == Some(&Value::String("ca_c_cl_alias".to_string())))
            .expect("claim action");

        assert_eq!(
            question_action["required_sources"],
            serde_json::json!(["https://contra.test", "https://support.test"])
        );
        assert_eq!(
            claim_action["required_sources"],
            serde_json::json!(["https://contra.test", "https://support.test"])
        );
    }

    #[test]
    fn candidate_actions_skip_resolved_and_closed_claims() {
        let mut state = InvestigationState::new("sid");
        state.claims.insert(
            "cl_resolved".to_string(),
            serde_json::json!({
                "id": "cl_resolved",
                "claim_text": "Resolved claim",
                "status": "resolved",
                "confidence": 0.2,
                "support_evidence_ids": ["ev_resolved"],
            }),
        );
        state.claims.insert(
            "cl_closed".to_string(),
            serde_json::json!({
                "id": "cl_closed",
                "claim_text": "Closed claim",
                "status": "closed",
                "support_evidence_ids": ["ev_closed"],
            }),
        );
        state.claims.insert(
            "cl_retracted".to_string(),
            serde_json::json!({
                "id": "cl_retracted",
                "claim_text": "Retracted claim",
                "status": "retracted",
                "confidence": 0.1,
            }),
        );
        state.claims.insert(
            "cl_control".to_string(),
            serde_json::json!({
                "id": "cl_control",
                "claim_text": "Low-confidence supported claim",
                "status": "supported",
                "confidence": 0.2,
                "support_evidence_ids": ["ev_control"],
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);
        let ids = packet["candidate_actions"]
            .as_array()
            .expect("candidate actions")
            .iter()
            .filter_map(|action| action.get("id").and_then(Value::as_str))
            .map(ToString::to_string)
            .collect::<Vec<_>>();

        assert!(ids.contains(&"ca_c_cl_control".to_string()));
        assert!(!ids.contains(&"ca_c_cl_resolved".to_string()));
        assert!(!ids.contains(&"ca_c_cl_closed".to_string()));
        assert!(!ids.contains(&"ca_c_cl_retracted".to_string()));
    }

    #[test]
    fn proposed_claims_emit_missing_counter_evidence_gap() {
        let mut state = InvestigationState::new("sid");
        state.claims.insert(
            "cl_proposed".to_string(),
            serde_json::json!({
                "id": "cl_proposed",
                "claim_text": "Proposed claim",
                "status": "proposed",
                "support_evidence_ids": ["ev_proposed"],
                "confidence": 0.2,
            }),
        );
        state.evidence.insert(
            "ev_proposed".to_string(),
            serde_json::json!({
                "evidence_type": "doc",
                "source_uri": "https://proposed.test",
            }),
        );

        let packet = build_question_reasoning_packet(&state, 8, 6);
        let claim_action = packet["candidate_actions"]
            .as_array()
            .and_then(|items| {
                items.iter().find(|item| {
                    item.get("id") == Some(&Value::String("ca_c_cl_proposed".to_string()))
                })
            })
            .expect("proposed claim action");

        assert!(
            claim_action["evidence_gap_refs"]
                .as_array()
                .is_some_and(|refs| refs.iter().any(|gap| {
                    gap.get("kind") == Some(&Value::String("missing_counter_evidence".to_string()))
                }))
        );
    }

    #[test]
    fn has_reasoning_content_returns_false_for_empty_packet() {
        let packet = serde_json::json!({
            "focus_question_ids": [],
            "findings": {
                "supported": [],
                "contested": [],
                "unresolved": [],
            },
            "contradictions": [],
        });
        assert!(!has_reasoning_content(&packet));
    }

    #[test]
    fn has_reasoning_content_returns_true_for_candidate_actions_only() {
        let packet = serde_json::json!({
            "focus_question_ids": [],
            "findings": {
                "supported": [],
                "contested": [],
                "unresolved": [],
            },
            "contradictions": [],
            "candidate_actions": [
                {"id": "ca_c_cl_9", "action_type": "verify_claim", "status": "proposed"}
            ],
        });
        assert!(has_reasoning_content(&packet));
    }
}
