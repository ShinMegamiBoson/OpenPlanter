/// Workspace tools — filesystem, shell, web, patching.
///
/// The `WorkspaceTools` struct is the central dispatcher that owns tool state
/// (files-read set, background jobs) and routes tool calls to the appropriate module.
pub mod defs;
pub mod filesystem;
pub mod patching;
pub mod shell;
pub mod web;

use std::collections::HashSet;
use std::path::PathBuf;

use crate::config::{AgentConfig, normalize_web_search_provider};

/// Result of executing a tool call.
#[derive(Debug, Clone)]
pub struct ToolResult {
    pub content: String,
    pub is_error: bool,
}

impl ToolResult {
    pub fn ok(content: String) -> Self {
        Self {
            content,
            is_error: false,
        }
    }

    pub fn error(content: String) -> Self {
        Self {
            content,
            is_error: true,
        }
    }
}

/// Central dispatcher for workspace tools.
pub struct WorkspaceTools {
    root: PathBuf,
    shell_path: String,
    command_timeout_sec: u64,
    max_shell_output_chars: usize,
    max_file_chars: usize,
    max_files_listed: usize,
    max_search_hits: usize,
    max_observation_chars: usize,
    web_search_provider: String,
    exa_api_key: Option<String>,
    exa_base_url: String,
    firecrawl_api_key: Option<String>,
    firecrawl_base_url: String,
    files_read: HashSet<PathBuf>,
    bg_jobs: shell::BgJobs,
}

impl WorkspaceTools {
    pub fn new(config: &AgentConfig) -> Self {
        Self {
            root: config.workspace.clone(),
            shell_path: config.shell.clone(),
            command_timeout_sec: config.command_timeout_sec as u64,
            max_shell_output_chars: config.max_shell_output_chars as usize,
            max_file_chars: config.max_file_chars as usize,
            max_files_listed: config.max_files_listed as usize,
            max_search_hits: config.max_search_hits as usize,
            max_observation_chars: config.max_observation_chars as usize,
            web_search_provider: normalize_web_search_provider(Some(&config.web_search_provider)),
            exa_api_key: config.exa_api_key.clone(),
            exa_base_url: config.exa_base_url.clone(),
            firecrawl_api_key: config.firecrawl_api_key.clone(),
            firecrawl_base_url: config.firecrawl_base_url.clone(),
            files_read: HashSet::new(),
            bg_jobs: shell::BgJobs::new(),
        }
    }

    /// Execute a tool by name with JSON arguments string.
    /// Returns the tool result, clipped to max_observation_chars.
    pub async fn execute(&mut self, name: &str, args_json: &str) -> ToolResult {
        let args: serde_json::Value = serde_json::from_str(args_json)
            .unwrap_or(serde_json::Value::Object(Default::default()));

        let result = match name {
            // Filesystem
            "read_file" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let hashline = args
                    .get("hashline")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(true);
                filesystem::read_file(
                    &self.root,
                    path,
                    hashline,
                    self.max_file_chars,
                    &mut self.files_read,
                )
            }
            "write_file" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let content = args.get("content").and_then(|v| v.as_str()).unwrap_or("");
                filesystem::write_file(&self.root, path, content, &mut self.files_read)
            }
            "edit_file" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let old_text = args.get("old_text").and_then(|v| v.as_str()).unwrap_or("");
                let new_text = args.get("new_text").and_then(|v| v.as_str()).unwrap_or("");
                filesystem::edit_file(&self.root, path, old_text, new_text, &mut self.files_read)
            }
            "list_files" => {
                let glob = args.get("glob").and_then(|v| v.as_str());
                filesystem::list_files(
                    &self.root,
                    glob,
                    self.max_files_listed,
                    self.command_timeout_sec,
                )
            }
            "search_files" => {
                let query = args.get("query").and_then(|v| v.as_str()).unwrap_or("");
                let glob = args.get("glob").and_then(|v| v.as_str());
                filesystem::search_files(
                    &self.root,
                    query,
                    glob,
                    self.max_search_hits,
                    self.command_timeout_sec,
                )
            }

            // Shell
            "run_shell" => {
                let command = args.get("command").and_then(|v| v.as_str()).unwrap_or("");
                let timeout = args
                    .get("timeout")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(self.command_timeout_sec);
                shell::run_shell(
                    &self.root,
                    &self.shell_path,
                    command,
                    timeout,
                    self.max_shell_output_chars,
                )
            }
            "run_shell_bg" => {
                let command = args.get("command").and_then(|v| v.as_str()).unwrap_or("");
                shell::run_shell_bg(&self.root, &self.shell_path, command, &mut self.bg_jobs)
            }
            "check_shell_bg" => {
                let job_id = args.get("job_id").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                shell::check_shell_bg(job_id, &mut self.bg_jobs, self.max_shell_output_chars)
            }
            "kill_shell_bg" => {
                let job_id = args.get("job_id").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                shell::kill_shell_bg(job_id, &mut self.bg_jobs)
            }

            // Web
            "web_search" => {
                let query = args.get("query").and_then(|v| v.as_str()).unwrap_or("");
                let num_results = args
                    .get("num_results")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(10);
                let include_text = args
                    .get("include_text")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);
                web::web_search(
                    &self.web_search_provider,
                    self.exa_api_key.as_deref(),
                    &self.exa_base_url,
                    self.firecrawl_api_key.as_deref(),
                    &self.firecrawl_base_url,
                    query,
                    num_results,
                    include_text,
                    self.max_file_chars,
                    self.command_timeout_sec,
                )
                .await
            }
            "fetch_url" => {
                let urls: Vec<String> = args
                    .get("urls")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                web::fetch_url(
                    &self.web_search_provider,
                    self.exa_api_key.as_deref(),
                    &self.exa_base_url,
                    self.firecrawl_api_key.as_deref(),
                    &self.firecrawl_base_url,
                    &urls,
                    self.max_file_chars,
                    self.command_timeout_sec,
                )
                .await
            }

            // Patching
            "apply_patch" => {
                let patch = args.get("patch").and_then(|v| v.as_str()).unwrap_or("");
                patching::apply_patch(&self.root, patch, &mut self.files_read)
            }
            "hashline_edit" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let edits: Vec<serde_json::Value> = args
                    .get("edits")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                patching::hashline_edit(&self.root, path, &edits, &mut self.files_read)
            }

            // Meta
            "think" => {
                let note = args.get("note").and_then(|v| v.as_str()).unwrap_or("");
                ToolResult::ok(format!("Noted: {note}"))
            }

            _ => ToolResult::error(format!("Unknown tool: {name}")),
        };

        // Clip observation to max_observation_chars
        if result.content.len() > self.max_observation_chars {
            let omitted = result.content.len() - self.max_observation_chars;
            ToolResult {
                content: format!(
                    "{}\n\n...[truncated {omitted} chars]...",
                    &result.content[..self.max_observation_chars]
                ),
                is_error: result.is_error,
            }
        } else {
            result
        }
    }

    /// Clean up background jobs on shutdown.
    pub fn cleanup(&mut self) {
        self.bg_jobs.cleanup();
    }
}
