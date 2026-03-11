/// Background wiki curator agent.
///
/// Runs as a non-blocking background task after each main agent step.
/// Reads the latest step context, decides if wiki updates are needed,
/// and writes to `.openplanter/wiki/` using a restricted tool set.
use tokio_util::sync::CancellationToken;

use crate::builder::build_model;
use crate::config::AgentConfig;
use crate::model::Message;
use crate::tools::WorkspaceTools;
use crate::tools::defs::build_curator_tool_defs;

/// Result of a curator run.
#[derive(Debug, Clone)]
pub struct CuratorResult {
    pub summary: String,
    pub files_changed: u32,
}

const CURATOR_SYSTEM_PROMPT: &str = r#"You are the Wiki Curator, a background agent that maintains the investigation wiki.

Your ONLY job is to update the wiki at .openplanter/wiki/ based on the main agent's latest step.

== RULES ==
1. You may ONLY modify files under .openplanter/wiki/
2. Read .openplanter/wiki/index.md first to understand existing entries
3. If the main agent discovered a new data source, create a wiki entry using the template format
4. If the main agent found new information about an existing source, update the relevant entry
5. Update .openplanter/wiki/index.md to link any new entries in the correct category table
6. Use EXACT source names in Cross-Reference sections to power the knowledge graph
7. If nothing in the step context is wiki-relevant, respond with ONLY: "No wiki updates needed"
8. Keep entries factual and concise — document what was found, not speculation
9. Never modify files outside .openplanter/wiki/
10. Maximum 8 tool calls — be efficient

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

== STEP CONTEXT ==
Below is the main agent's latest step. Analyze it for wiki-relevant discoveries."#;

/// Maximum number of tool-call steps for the curator.
const MAX_CURATOR_STEPS: usize = 8;

/// Maximum chars of context to extract from the main agent's messages.
const MAX_CONTEXT_CHARS: usize = 8_000;

/// Extract the latest step context from the main conversation.
///
/// Walks backwards from the end to find the last Assistant message,
/// then collects it plus any subsequent Tool messages.
pub fn extract_step_context(messages: &[Message]) -> String {
    let mut context = String::new();

    // Find last Assistant message index
    let assistant_idx = messages
        .iter()
        .rposition(|m| matches!(m, Message::Assistant { .. }));
    let start = match assistant_idx {
        Some(idx) => idx,
        None => return context,
    };

    for msg in &messages[start..] {
        match msg {
            Message::Assistant {
                content,
                tool_calls,
            } => {
                context.push_str("=== Assistant ===\n");
                context.push_str(content);
                context.push('\n');
                if let Some(tcs) = tool_calls {
                    for tc in tcs {
                        context.push_str(&format!("[Tool call: {}]\n", tc.name));
                    }
                }
            }
            Message::Tool { content, .. } => {
                context.push_str("=== Tool Result ===\n");
                context.push_str(content);
                context.push('\n');
            }
            _ => {}
        }
    }

    // Truncate to budget
    if context.len() > MAX_CONTEXT_CHARS {
        let end = context.floor_char_boundary(MAX_CONTEXT_CHARS);
        context.truncate(end);
        context.push_str("\n...[truncated]");
    }

    context
}

/// Curator tool names — the subset of tools the curator is allowed to use.
pub const CURATOR_TOOL_NAMES: &[&str] = &[
    "list_files",
    "search_files",
    "read_file",
    "write_file",
    "edit_file",
    "apply_patch",
    "hashline_edit",
    "think",
];

/// Run the curator agent with the given step context.
///
/// Creates its own model instance and tool set, runs a mini agentic loop
/// with restricted tools, and returns a summary of changes made.
pub async fn run_curator(
    context: &str,
    config: &AgentConfig,
    cancel: CancellationToken,
) -> Result<CuratorResult, String> {
    if context.is_empty() {
        return Ok(CuratorResult {
            summary: "No context to curate".into(),
            files_changed: 0,
        });
    }

    // Build model
    let model = build_model(config).map_err(|e| e.to_string())?;

    let provider = model.provider_name().to_string();
    let tool_defs = build_curator_tool_defs(&provider);
    let mut tools = WorkspaceTools::new(config);

    let mut messages = vec![
        Message::System {
            content: CURATOR_SYSTEM_PROMPT.to_string(),
        },
        Message::User {
            content: context.to_string(),
        },
    ];

    let mut files_changed: u32 = 0;
    let mut summary_parts: Vec<String> = Vec::new();

    // Mini agentic loop
    for _step in 1..=MAX_CURATOR_STEPS {
        if cancel.is_cancelled() {
            return Ok(CuratorResult {
                summary: "Curator cancelled".into(),
                files_changed,
            });
        }

        // Call model (non-streaming — curator runs silently)
        let turn = model
            .chat(&messages, &tool_defs)
            .await
            .map_err(|e| e.to_string())?;

        // Append assistant message
        let tool_calls_opt = if turn.tool_calls.is_empty() {
            None
        } else {
            Some(turn.tool_calls.clone())
        };
        messages.push(Message::Assistant {
            content: turn.text.clone(),
            tool_calls: tool_calls_opt,
        });

        // No tool calls → curator is done
        if turn.tool_calls.is_empty() {
            if turn.text.contains("No wiki updates needed") {
                return Ok(CuratorResult {
                    summary: "No wiki updates needed".into(),
                    files_changed: 0,
                });
            }
            if !turn.text.is_empty() && summary_parts.is_empty() {
                summary_parts.push(turn.text.clone());
            }
            break;
        }

        // Execute tool calls
        for tc in &turn.tool_calls {
            if cancel.is_cancelled() {
                return Ok(CuratorResult {
                    summary: "Curator cancelled".into(),
                    files_changed,
                });
            }

            // Validate tool is in allowed set
            if !CURATOR_TOOL_NAMES.contains(&tc.name.as_str()) {
                messages.push(Message::Tool {
                    tool_call_id: tc.id.clone(),
                    content: format!("Error: tool '{}' is not available to the curator", tc.name),
                });
                continue;
            }

            let result = tools.execute(&tc.name, &tc.arguments).await;

            // Track file modifications
            if matches!(
                tc.name.as_str(),
                "write_file" | "edit_file" | "apply_patch" | "hashline_edit"
            ) && !result.is_error
            {
                files_changed += 1;
                // Extract path for summary
                if let Ok(args) = serde_json::from_str::<serde_json::Value>(&tc.arguments) {
                    if let Some(path) = args.get("path").and_then(|p| p.as_str()) {
                        summary_parts.push(format!("Updated {}", path));
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

    let summary = if summary_parts.is_empty() {
        "Curator completed with no changes".into()
    } else {
        summary_parts.join("; ")
    };

    Ok(CuratorResult {
        summary,
        files_changed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::ToolCall;

    #[test]
    fn test_extract_step_context_empty() {
        let messages: Vec<Message> = vec![];
        assert_eq!(extract_step_context(&messages), "");
    }

    #[test]
    fn test_extract_step_context_no_assistant() {
        let messages = vec![
            Message::System {
                content: "sys".into(),
            },
            Message::User {
                content: "hello".into(),
            },
        ];
        assert_eq!(extract_step_context(&messages), "");
    }

    #[test]
    fn test_extract_step_context_with_tool_calls() {
        let messages = vec![
            Message::System {
                content: "sys".into(),
            },
            Message::User {
                content: "investigate".into(),
            },
            Message::Assistant {
                content: "I'll search for data.".into(),
                tool_calls: Some(vec![ToolCall {
                    id: "t1".into(),
                    name: "web_search".into(),
                    arguments: r#"{"query":"test"}"#.into(),
                }]),
            },
            Message::Tool {
                tool_call_id: "t1".into(),
                content: "Search results here".into(),
            },
        ];
        let ctx = extract_step_context(&messages);
        assert!(ctx.contains("I'll search for data"));
        assert!(ctx.contains("web_search"));
        assert!(ctx.contains("Search results here"));
    }

    #[test]
    fn test_extract_step_context_truncation() {
        let big_content = "x".repeat(MAX_CONTEXT_CHARS + 1000);
        let messages = vec![Message::Assistant {
            content: big_content,
            tool_calls: None,
        }];
        let ctx = extract_step_context(&messages);
        assert!(ctx.len() <= MAX_CONTEXT_CHARS + 50); // +50 for prefix/suffix
        assert!(ctx.contains("[truncated]"));
    }

    #[test]
    fn test_extract_step_context_last_assistant_only() {
        let messages = vec![
            Message::Assistant {
                content: "old step".into(),
                tool_calls: None,
            },
            Message::User {
                content: "continue".into(),
            },
            Message::Assistant {
                content: "new step".into(),
                tool_calls: Some(vec![ToolCall {
                    id: "t2".into(),
                    name: "read_file".into(),
                    arguments: "{}".into(),
                }]),
            },
            Message::Tool {
                tool_call_id: "t2".into(),
                content: "file contents".into(),
            },
        ];
        let ctx = extract_step_context(&messages);
        assert!(!ctx.contains("old step"));
        assert!(ctx.contains("new step"));
        assert!(ctx.contains("file contents"));
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
                    "kill_shell_bg"
                ]
                .contains(name),
                "Curator should not have access to {name}"
            );
        }
    }
}
