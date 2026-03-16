/// Workspace tools — filesystem, shell, web, patching.
///
/// The `WorkspaceTools` struct is the central dispatcher that owns tool state
/// (files-read set, background jobs) and routes tool calls to the appropriate module.
pub mod audio;
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

#[derive(Debug, Clone)]
enum ToolScope {
    FullWorkspace,
    CuratorWikiOnly { allowed_root: PathBuf },
}

/// Central dispatcher for workspace tools.
pub struct WorkspaceTools {
    root: PathBuf,
    scope: ToolScope,
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
    brave_api_key: Option<String>,
    brave_base_url: String,
    tavily_api_key: Option<String>,
    tavily_base_url: String,
    mistral_transcription_api_key: Option<String>,
    mistral_transcription_base_url: String,
    mistral_transcription_model: String,
    mistral_transcription_max_bytes: usize,
    mistral_transcription_chunk_max_seconds: i64,
    mistral_transcription_chunk_overlap_seconds: f64,
    mistral_transcription_max_chunks: i64,
    mistral_transcription_request_timeout_sec: u64,
    files_read: HashSet<PathBuf>,
    bg_jobs: shell::BgJobs,
}

fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!("{}\n\n...[truncated {omitted} chars]...", &text[..end])
}

impl WorkspaceTools {
    pub fn new(config: &AgentConfig) -> Self {
        Self {
            root: config.workspace.clone(),
            scope: ToolScope::FullWorkspace,
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
            brave_api_key: config.brave_api_key.clone(),
            brave_base_url: config.brave_base_url.clone(),
            tavily_api_key: config.tavily_api_key.clone(),
            tavily_base_url: config.tavily_base_url.clone(),
            mistral_transcription_api_key: config.mistral_transcription_api_key.clone(),
            mistral_transcription_base_url: config.mistral_transcription_base_url.clone(),
            mistral_transcription_model: config.mistral_transcription_model.clone(),
            mistral_transcription_max_bytes: config.mistral_transcription_max_bytes as usize,
            mistral_transcription_chunk_max_seconds: config.mistral_transcription_chunk_max_seconds,
            mistral_transcription_chunk_overlap_seconds: config
                .mistral_transcription_chunk_overlap_seconds,
            mistral_transcription_max_chunks: config.mistral_transcription_max_chunks,
            mistral_transcription_request_timeout_sec: config
                .mistral_transcription_request_timeout_sec
                as u64,
            files_read: HashSet::new(),
            bg_jobs: shell::BgJobs::new(),
        }
    }

    pub fn new_curator(config: &AgentConfig) -> Self {
        let allowed_root = filesystem::resolve_path(
            &config.workspace,
            &format!("{}/wiki", config.session_root_dir),
        )
        .unwrap_or_else(|_| config.workspace.join(&config.session_root_dir).join("wiki"));
        Self {
            root: config.workspace.clone(),
            scope: ToolScope::CuratorWikiOnly { allowed_root },
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
            brave_api_key: config.brave_api_key.clone(),
            brave_base_url: config.brave_base_url.clone(),
            tavily_api_key: config.tavily_api_key.clone(),
            tavily_base_url: config.tavily_base_url.clone(),
            mistral_transcription_api_key: config.mistral_transcription_api_key.clone(),
            mistral_transcription_base_url: config.mistral_transcription_base_url.clone(),
            mistral_transcription_model: config.mistral_transcription_model.clone(),
            mistral_transcription_max_bytes: config.mistral_transcription_max_bytes as usize,
            mistral_transcription_chunk_max_seconds: config.mistral_transcription_chunk_max_seconds,
            mistral_transcription_chunk_overlap_seconds: config
                .mistral_transcription_chunk_overlap_seconds,
            mistral_transcription_max_chunks: config.mistral_transcription_max_chunks,
            mistral_transcription_request_timeout_sec: config
                .mistral_transcription_request_timeout_sec
                as u64,
            files_read: HashSet::new(),
            bg_jobs: shell::BgJobs::new(),
        }
    }

    fn enforce_write_scope(&self, raw_path: &str) -> Result<(), ToolResult> {
        match &self.scope {
            ToolScope::FullWorkspace => Ok(()),
            ToolScope::CuratorWikiOnly { allowed_root } => {
                let resolved =
                    filesystem::resolve_path(&self.root, raw_path).map_err(ToolResult::error)?;
                if resolved == *allowed_root || resolved.starts_with(allowed_root) {
                    Ok(())
                } else {
                    Err(ToolResult::error(
                        "Curator writes are restricted to .openplanter/wiki/**".to_string(),
                    ))
                }
            }
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
                if let Err(result) = self.enforce_write_scope(path) {
                    return result;
                }
                filesystem::write_file(&self.root, path, content, &mut self.files_read)
            }
            "edit_file" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let old_text = args.get("old_text").and_then(|v| v.as_str()).unwrap_or("");
                let new_text = args.get("new_text").and_then(|v| v.as_str()).unwrap_or("");
                if let Err(result) = self.enforce_write_scope(path) {
                    return result;
                }
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
            "audio_transcribe" => {
                let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let diarize = args.get("diarize").and_then(|v| v.as_bool());
                let timestamp_granularities: Option<Vec<String>> = args
                    .get("timestamp_granularities")
                    .and_then(|v| {
                        if let Some(values) = v.as_array() {
                            Some(
                                values
                                    .iter()
                                    .filter_map(|value| {
                                        value.as_str().map(|s| s.trim().to_string())
                                    })
                                    .filter(|value| !value.is_empty())
                                    .collect::<Vec<_>>(),
                            )
                        } else {
                            v.as_str().map(|value| vec![value.trim().to_string()])
                        }
                    })
                    .filter(|values| !values.is_empty());
                let context_bias: Option<Vec<String>> = args
                    .get("context_bias")
                    .and_then(|v| {
                        if let Some(values) = v.as_array() {
                            Some(
                                values
                                    .iter()
                                    .filter_map(|value| {
                                        value.as_str().map(|s| s.trim().to_string())
                                    })
                                    .filter(|value| !value.is_empty())
                                    .collect::<Vec<_>>(),
                            )
                        } else {
                            v.as_str().map(|value| {
                                value
                                    .split(',')
                                    .map(str::trim)
                                    .filter(|part| !part.is_empty())
                                    .map(ToString::to_string)
                                    .collect::<Vec<_>>()
                            })
                        }
                    })
                    .filter(|values| !values.is_empty());
                let language = args
                    .get("language")
                    .and_then(|v| v.as_str())
                    .filter(|value| !value.trim().is_empty());
                let model = args
                    .get("model")
                    .and_then(|v| v.as_str())
                    .filter(|value| !value.trim().is_empty());
                let temperature = args.get("temperature").and_then(|v| v.as_f64());
                let chunking = args
                    .get("chunking")
                    .and_then(|v| v.as_str())
                    .map(str::trim)
                    .filter(|value| !value.is_empty());
                let chunk_max_seconds = args.get("chunk_max_seconds").and_then(|v| v.as_i64());
                let chunk_overlap_seconds =
                    args.get("chunk_overlap_seconds").and_then(|v| v.as_f64());
                let max_chunks = args.get("max_chunks").and_then(|v| v.as_i64());
                let continue_on_chunk_error = args
                    .get("continue_on_chunk_error")
                    .and_then(|v| v.as_bool());
                audio::audio_transcribe(
                    &self.root,
                    self.mistral_transcription_api_key.as_deref(),
                    &self.mistral_transcription_base_url,
                    &self.mistral_transcription_model,
                    self.mistral_transcription_max_bytes,
                    self.mistral_transcription_chunk_max_seconds,
                    self.mistral_transcription_chunk_overlap_seconds,
                    self.mistral_transcription_max_chunks,
                    path,
                    diarize,
                    timestamp_granularities.as_deref(),
                    context_bias.as_deref(),
                    language,
                    model,
                    temperature,
                    chunking,
                    chunk_max_seconds,
                    chunk_overlap_seconds,
                    max_chunks,
                    continue_on_chunk_error,
                    self.max_file_chars.min(self.max_observation_chars),
                    self.command_timeout_sec,
                    self.mistral_transcription_request_timeout_sec,
                    &mut self.files_read,
                )
                .await
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
                    self.brave_api_key.as_deref(),
                    &self.brave_base_url,
                    self.tavily_api_key.as_deref(),
                    &self.tavily_base_url,
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
                    self.brave_api_key.as_deref(),
                    &self.brave_base_url,
                    self.tavily_api_key.as_deref(),
                    &self.tavily_base_url,
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
            ToolResult {
                content: clip(&result.content, self.max_observation_chars),
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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn test_config(root: &std::path::Path) -> AgentConfig {
        AgentConfig::from_env(root)
    }

    #[tokio::test]
    async fn test_curator_scope_allows_wiki_writes() {
        let tmp = tempdir().unwrap();
        let cfg = test_config(tmp.path());
        let mut tools = WorkspaceTools::new_curator(&cfg);

        let result = tools
            .execute(
                "write_file",
                r#"{"path":".openplanter/wiki/source.md","content":"hello"}"#,
            )
            .await;

        assert!(!result.is_error, "unexpected error: {}", result.content);
        assert_eq!(
            std::fs::read_to_string(tmp.path().join(".openplanter/wiki/source.md")).unwrap(),
            "hello"
        );
    }

    #[tokio::test]
    async fn test_curator_scope_rejects_non_wiki_writes() {
        let tmp = tempdir().unwrap();
        let cfg = test_config(tmp.path());
        let mut tools = WorkspaceTools::new_curator(&cfg);

        let result = tools
            .execute("write_file", r#"{"path":"notes.md","content":"nope"}"#)
            .await;

        assert!(result.is_error);
        assert!(result.content.contains(".openplanter/wiki"));
        assert!(!tmp.path().join("notes.md").exists());
    }

    #[tokio::test]
    async fn test_curator_scope_rejects_traversal() {
        let tmp = tempdir().unwrap();
        let cfg = test_config(tmp.path());
        let mut tools = WorkspaceTools::new_curator(&cfg);

        let result = tools
            .execute(
                "write_file",
                r#"{"path":".openplanter/wiki/../../escape.md","content":"nope"}"#,
            )
            .await;

        assert!(result.is_error);
        assert!(!tmp.path().join("escape.md").exists());
    }

    #[tokio::test]
    async fn test_full_workspace_scope_unchanged() {
        let tmp = tempdir().unwrap();
        let cfg = test_config(tmp.path());
        let mut tools = WorkspaceTools::new(&cfg);

        let result = tools
            .execute("write_file", r#"{"path":"notes.md","content":"allowed"}"#)
            .await;

        assert!(!result.is_error, "unexpected error: {}", result.content);
        assert_eq!(
            std::fs::read_to_string(tmp.path().join("notes.md")).unwrap(),
            "allowed"
        );
    }

    #[tokio::test]
    async fn test_execute_clips_observations_on_char_boundary() {
        let tmp = tempdir().unwrap();
        let mut cfg = test_config(tmp.path());
        cfg.max_observation_chars = 6000;
        let mut tools = WorkspaceTools::new(&cfg);

        let mut content = "a".repeat(5999);
        content.push('─');
        std::fs::write(tmp.path().join("unicode.txt"), content).unwrap();

        let result = tools
            .execute("read_file", r#"{"path":"unicode.txt","hashline":false}"#)
            .await;

        assert!(!result.is_error, "unexpected error: {}", result.content);
        assert!(result.content.contains("[truncated"));
        assert!(std::str::from_utf8(result.content.as_bytes()).is_ok());
    }
}
