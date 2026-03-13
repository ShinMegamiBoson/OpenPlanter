use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

const SCHEMA_VERSION: &str = "1.0.0";
const ONTOLOGY_NAMESPACE: &str = "openplanter.core";
const ONTOLOGY_VERSION: &str = "2026-03";
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

            Some(serde_json::json!({
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
                "claim_ids": id_list(question.get("claim_ids").or_else(|| question.get("claims"))),
                "evidence_ids": limit_ids(question.get("evidence_ids"), max_evidence_per_item),
                "triggers": id_list(question.get("trigger").or_else(|| question.get("triggers"))),
                "updated_at": question
                    .get("updated_at")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            }))
        })
        .collect();
    unresolved_questions.sort_by(question_priority_sort_key);
    unresolved_questions.truncate(std::cmp::max(1, max_questions));

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
        let support_ids = limit_ids(
            claim
                .get("support_evidence_ids")
                .or_else(|| claim.get("evidence_ids")),
            max_evidence_per_item,
        );
        let contradiction_ids = limit_ids(
            claim
                .get("contradiction_evidence_ids")
                .or_else(|| claim.get("contradict_evidence_ids")),
            max_evidence_per_item,
        );
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

    serde_json::json!({
        "reasoning_mode": "question_centric",
        "loop": [
            "select_unresolved_question",
            "gather_discriminating_evidence",
            "update_claim_status_and_confidence",
            "record_contradictions",
            "synthesize_supported_contested_unresolved",
        ],
        "focus_question_ids": unresolved_questions
            .iter()
            .filter_map(|item| item.get("id").and_then(Value::as_str).map(ToString::to_string))
            .collect::<Vec<_>>(),
        "unresolved_questions": unresolved_questions,
        "findings": {
            "supported": supported,
            "contested": contested,
            "unresolved": unresolved,
        },
        "contradictions": contradictions,
        "evidence_index": evidence_index,
    })
}

pub fn has_reasoning_content(packet: &Value) -> bool {
    let Some(obj) = packet.as_object() else {
        return false;
    };
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
        assert!(has_reasoning_content(&packet));
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
}
