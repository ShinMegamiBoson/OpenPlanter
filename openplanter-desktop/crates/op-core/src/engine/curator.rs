/// Checkpointed wiki curator synthesizer.
///
/// Runs at explicit solve-loop phase boundaries and updates wiki files from
/// typed state deltas rather than raw transcript slices.
use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

use crate::builder::build_model;
use crate::config::AgentConfig;
use crate::events::LoopPhase;
use crate::model::Message;
use crate::tools::WorkspaceTools;
use crate::tools::defs::build_curator_tool_defs;

/// Result of a curator run.
#[derive(Debug, Clone)]
pub struct CuratorResult {
    pub summary: String,
    pub files_changed: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CuratorToolObservation {
    pub tool_call_id: String,
    pub tool_name: String,
    pub arguments_json: String,
    pub output_excerpt: String,
    pub is_error: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CuratorStateDelta {
    pub step: u32,
    pub phase: LoopPhase,
    pub objective: String,
    pub observations: Vec<CuratorToolObservation>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CuratorCheckpoint {
    pub boundary: String,
    pub deltas: Vec<CuratorStateDelta>,
}

const CURATOR_SYSTEM_PROMPT: &str = r#"You are the Wiki Curator Synthesizer.

You run ONLY at explicit solve-loop phase boundaries and receive typed checkpoint
deltas rather than raw transcript slices.

The wiki at `.openplanter/wiki/` is a DERIVED knowledge surface. It is not the
agent's primary memory store.

== RULES ==
1. You may ONLY modify files under `.openplanter/wiki/`.
2. Read `.openplanter/wiki/index.md` before writing so links and exact source names stay consistent.
3. Use ONLY tool-grounded facts from the checkpoint payload. Do not invent or infer unsupported details.
4. Preserve provenance. When adding facts, keep concise evidence anchors using the originating step, tool name, and tool call ID.
5. Eliminate duplicate and noisy updates. Prefer a no-op over restating facts already captured in the wiki.
6. Ignore low-information operational traces unless they reveal durable source facts worth documenting.
7. If the checkpoint contains no wiki-relevant net-new knowledge, respond with EXACTLY: "No wiki updates needed".
8. Keep entries factual and concise. Document what was learned, not speculation.
9. Prefer `edit_file` over whole-file rewrites when possible.
10. Only use `write_file` or `edit_file` for mutations.
11. Maximum 8 tool calls.

== WIKI ENTRY TEMPLATE ==
When creating a new entry, use this format:

# [Source Name]

## Overview
Brief description of what this data source provides.

## Access
- **URL**: [url]
- **Method**: [API/scraping/download/FOIA]
- **Authentication**: [required/none]

## Key Fields
- field1: description
- field2: description

## Coverage
- **Date range**: [range]
- **Geographic scope**: [scope]
- **Update frequency**: [frequency]

## Cross-Reference Potential
- [Other Source Name]: how they connect
- [Another Source]: join key or relationship

== CHECKPOINT PAYLOAD ==
Below is a typed checkpoint payload with per-step tool observations. Analyze it
for durable wiki-relevant discoveries."#;

/// Maximum number of tool-call steps for the curator.
const MAX_CURATOR_STEPS: usize = 8;
const MAX_TOOL_OUTPUT_EXCERPT: usize = 1_200;

fn trim_excerpt(raw: &str) -> String {
    if raw.len() <= MAX_TOOL_OUTPUT_EXCERPT {
        return raw.to_string();
    }

    let end = if raw.is_char_boundary(MAX_TOOL_OUTPUT_EXCERPT) {
        MAX_TOOL_OUTPUT_EXCERPT
    } else {
        raw.char_indices()
            .map(|(idx, _)| idx)
            .take_while(|idx| *idx < MAX_TOOL_OUTPUT_EXCERPT)
            .last()
            .unwrap_or(0)
    };

    let mut trimmed = raw[..end].to_string();
    trimmed.push_str("\n...[truncated]");
    trimmed
}

pub fn build_state_delta(
    step: u32,
    phase: LoopPhase,
    objective: &str,
    tools: &[(String, String, String, String, bool)],
) -> Option<CuratorStateDelta> {
    let observations = tools
        .iter()
        .filter_map(|(id, name, args, content, is_error)| {
            if content.trim().is_empty() && !*is_error {
                return None;
            }

            Some(CuratorToolObservation {
                tool_call_id: id.clone(),
                tool_name: name.clone(),
                arguments_json: args.clone(),
                output_excerpt: trim_excerpt(content),
                is_error: *is_error,
            })
        })
        .collect::<Vec<_>>();

    if observations.is_empty() {
        return None;
    }

    Some(CuratorStateDelta {
        step,
        phase,
        objective: objective.to_string(),
        observations,
    })
}

/// Curator tool names — the subset of tools the curator is allowed to use.
pub const CURATOR_TOOL_NAMES: &[&str] = &[
    "list_files",
    "search_files",
    "read_file",
    "write_file",
    "edit_file",
    "think",
];

/// Legacy context entry point retained for migration and initialization flows.
pub async fn run_curator(
    context: &str,
    config: &AgentConfig,
    cancel: CancellationToken,
) -> Result<CuratorResult, String> {
    if context.trim().is_empty() {
        return Ok(CuratorResult {
            summary: "No checkpoint deltas to curate".into(),
            files_changed: 0,
        });
    }

    let checkpoint = CuratorCheckpoint {
        boundary: "migration_context".to_string(),
        deltas: vec![CuratorStateDelta {
            step: 0,
            phase: LoopPhase::Iterate,
            objective: "workspace initialization wiki rewrite".to_string(),
            observations: vec![CuratorToolObservation {
                tool_call_id: "migration_context".to_string(),
                tool_name: "workspace_init".to_string(),
                arguments_json: "{}".to_string(),
                output_excerpt: trim_excerpt(context),
                is_error: false,
            }],
        }],
    };
    run_curator_checkpoint(&checkpoint, config, cancel).await
}

/// Run the curator agent with an explicit checkpoint payload.
pub async fn run_curator_checkpoint(
    checkpoint: &CuratorCheckpoint,
    config: &AgentConfig,
    cancel: CancellationToken,
) -> Result<CuratorResult, String> {
    if checkpoint.deltas.is_empty() {
        return Ok(CuratorResult {
            summary: "No checkpoint deltas to curate".into(),
            files_changed: 0,
        });
    }

    let model = build_model(config).map_err(|e| e.to_string())?;
    let provider = model.provider_name().to_string();
    let tool_defs = build_curator_tool_defs(&provider);
    let mut tools = WorkspaceTools::new_curator(config);

    let mut messages = vec![
        Message::System {
            content: CURATOR_SYSTEM_PROMPT.to_string(),
        },
        Message::User {
            content: serde_json::to_string_pretty(checkpoint)
                .map_err(|e| format!("failed to serialize checkpoint: {e}"))?,
        },
    ];

    let mut touched_paths = BTreeSet::new();
    let mut summary_parts = Vec::new();

    for _ in 1..=MAX_CURATOR_STEPS {
        if cancel.is_cancelled() {
            tools.cleanup();
            return Ok(CuratorResult {
                summary: "Curator cancelled".into(),
                files_changed: touched_paths.len() as u32,
            });
        }

        let turn = model
            .chat(&messages, &tool_defs)
            .await
            .map_err(|e| e.to_string())?;

        let tool_calls_opt = if turn.tool_calls.is_empty() {
            None
        } else {
            Some(turn.tool_calls.clone())
        };
        messages.push(Message::Assistant {
            content: turn.text.clone(),
            tool_calls: tool_calls_opt,
        });

        if turn.tool_calls.is_empty() {
            if turn.text.trim() == "No wiki updates needed" {
                tools.cleanup();
                return Ok(CuratorResult {
                    summary: "No wiki updates needed".into(),
                    files_changed: 0,
                });
            }
            if !turn.text.trim().is_empty() {
                summary_parts.push(turn.text.trim().to_string());
            }
            break;
        }

        for tc in &turn.tool_calls {
            if cancel.is_cancelled() {
                tools.cleanup();
                return Ok(CuratorResult {
                    summary: "Curator cancelled".into(),
                    files_changed: touched_paths.len() as u32,
                });
            }

            if !CURATOR_TOOL_NAMES.contains(&tc.name.as_str()) {
                messages.push(Message::Tool {
                    tool_call_id: tc.id.clone(),
                    content: format!("Error: tool '{}' is not available to the curator", tc.name),
                });
                continue;
            }

            let result = tools.execute(&tc.name, &tc.arguments).await;
            if matches!(tc.name.as_str(), "write_file" | "edit_file") && !result.is_error {
                if let Ok(args) = serde_json::from_str::<serde_json::Value>(&tc.arguments) {
                    if let Some(path) = args.get("path").and_then(|value| value.as_str()) {
                        touched_paths.insert(path.to_string());
                    }
                }
            }

            messages.push(Message::Tool {
                tool_call_id: tc.id.clone(),
                content: result.content,
            });
        }
    }

    tools.cleanup();

    if !touched_paths.is_empty() {
        summary_parts.push(format!("Updated {} wiki file(s)", touched_paths.len()));
    }

    let summary = if summary_parts.is_empty() {
        "Curator completed with no changes".into()
    } else {
        summary_parts.join("; ")
    };

    Ok(CuratorResult {
        summary,
        files_changed: touched_paths.len() as u32,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_state_delta_trims_tool_output() {
        let tools = vec![(
            "call-1".to_string(),
            "read_file".to_string(),
            "{\"path\":\"a.md\"}".to_string(),
            "x".repeat(MAX_TOOL_OUTPUT_EXCERPT + 64),
            false,
        )];

        let delta =
            build_state_delta(3, LoopPhase::Investigate, "Investigate sources", &tools).unwrap();

        assert_eq!(delta.step, 3);
        assert_eq!(delta.phase, LoopPhase::Investigate);
        assert_eq!(delta.observations.len(), 1);
        assert!(delta.observations[0].output_excerpt.contains("[truncated]"));
    }

    #[test]
    fn test_build_state_delta_skips_empty_success_observations() {
        let tools = vec![(
            "call-1".to_string(),
            "read_file".to_string(),
            "{}".to_string(),
            String::new(),
            false,
        )];

        assert!(build_state_delta(1, LoopPhase::Investigate, "Investigate", &tools).is_none());
    }

    #[test]
    fn test_curator_tool_names_no_dangerous_tools() {
        for name in CURATOR_TOOL_NAMES {
            assert!(
                ![
                    "web_search",
                    "fetch_url",
                    "run_shell",
                    "run_shell_bg",
                    "check_shell_bg",
                    "kill_shell_bg",
                    "apply_patch",
                    "hashline_edit"
                ]
                .contains(name),
                "Curator should not have access to {name}"
            );
        }
    }
}
