use op_core::config::AgentConfig;
use op_core::config_hydration::{apply_settings_to_config, merge_credentials_into_config};
use op_core::credentials::CredentialBundle;
use op_core::credentials::{
    credentials_from_env, discover_env_candidates, parse_env_assignments, parse_env_file,
};
#[cfg(test)]
use op_core::settings::PersistentSettings;
use op_core::settings::SettingsStore;
use op_core::workspace_init;
use std::env;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

const WORKSPACE_ENV_KEY: &str = "OPENPLANTER_WORKSPACE";

#[derive(Debug, Clone, PartialEq, Eq)]
enum WorkspaceSource {
    EnvOverride,
    DotEnv,
    GitRoot,
    CurrentDir,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum GuardrailAction {
    None,
    RedirectedToWorkspace,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ResolvedWorkspace {
    path: PathBuf,
    source: WorkspaceSource,
    dotenv_path: Option<PathBuf>,
    invalid_override: Option<String>,
    invalid_dotenv_value: Option<String>,
    guardrail_action: GuardrailAction,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct LegacyMigrationReport {
    source: Option<PathBuf>,
    copied_files: u64,
    skipped_existing: u64,
    errors: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StartupWorkspaceError {
    RepoRootDisallowed { repo_root: PathBuf },
}

impl fmt::Display for StartupWorkspaceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StartupWorkspaceError::RepoRootDisallowed { repo_root } => write!(
                f,
                "Refusing to use repository root as the workspace: {}. Set {} in the nearest .env or use a non-root workspace override.",
                repo_root.display(),
                WORKSPACE_ENV_KEY
            ),
        }
    }
}

fn canonicalize_or_self(path: &Path) -> PathBuf {
    path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

fn find_git_root(start: &Path) -> Option<PathBuf> {
    let mut current = Some(canonicalize_or_self(start));
    while let Some(dir) = current {
        if dir.join(".git").exists() {
            return Some(dir);
        }
        current = dir.parent().map(|parent| parent.to_path_buf());
    }
    None
}

fn resolve_candidate_path(raw_value: &str, base_dir: &Path) -> PathBuf {
    let candidate = PathBuf::from(raw_value.trim());
    let joined = if candidate.is_absolute() {
        candidate
    } else {
        base_dir.join(candidate)
    };
    canonicalize_or_self(&joined)
}

fn apply_repo_root_guardrail(
    candidate: &Path,
) -> Result<(PathBuf, GuardrailAction), StartupWorkspaceError> {
    let candidate = canonicalize_or_self(candidate);
    if candidate.join(".git").exists() {
        let workspace_dir = candidate.join("workspace");
        if workspace_dir.is_dir() {
            return Ok((
                canonicalize_or_self(&workspace_dir),
                GuardrailAction::RedirectedToWorkspace,
            ));
        }
        return Err(StartupWorkspaceError::RepoRootDisallowed {
            repo_root: candidate,
        });
    }

    Ok((candidate, GuardrailAction::None))
}

fn resolve_startup_workspace_from(
    current_dir: &Path,
    env_override: Option<&str>,
) -> Result<ResolvedWorkspace, StartupWorkspaceError> {
    let dotenv_path = discover_env_candidates(current_dir).into_iter().next();
    let mut invalid_override = None;
    let mut invalid_dotenv_value = None;

    if let Some(raw_override) = env_override
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let candidate = resolve_candidate_path(raw_override, current_dir);
        if candidate.is_dir() {
            let (path, guardrail_action) = apply_repo_root_guardrail(&candidate)?;
            return Ok(ResolvedWorkspace {
                path,
                source: WorkspaceSource::EnvOverride,
                dotenv_path: None,
                invalid_override: None,
                invalid_dotenv_value: None,
                guardrail_action,
            });
        }
        invalid_override = Some(raw_override.to_string());
    }

    if let Some(path) = dotenv_path.as_ref() {
        let env_map = parse_env_assignments(path);
        if let Some(raw_value) = env_map
            .get(WORKSPACE_ENV_KEY)
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
        {
            let candidate = resolve_candidate_path(raw_value, path.parent().unwrap_or(current_dir));
            if candidate.is_dir() {
                let (path, guardrail_action) = apply_repo_root_guardrail(&candidate)?;
                return Ok(ResolvedWorkspace {
                    path,
                    source: WorkspaceSource::DotEnv,
                    dotenv_path,
                    invalid_override,
                    invalid_dotenv_value: None,
                    guardrail_action,
                });
            }
            invalid_dotenv_value = Some(raw_value.to_string());
        }
    }

    if let Some(git_root) = find_git_root(current_dir) {
        let (path, guardrail_action) = apply_repo_root_guardrail(&git_root)?;
        return Ok(ResolvedWorkspace {
            path,
            source: WorkspaceSource::GitRoot,
            dotenv_path,
            invalid_override,
            invalid_dotenv_value,
            guardrail_action,
        });
    }

    let (path, guardrail_action) = apply_repo_root_guardrail(current_dir)?;
    Ok(ResolvedWorkspace {
        path,
        source: WorkspaceSource::CurrentDir,
        dotenv_path,
        invalid_override,
        invalid_dotenv_value,
        guardrail_action,
    })
}

fn resolve_desktop_workspace() -> Result<ResolvedWorkspace, StartupWorkspaceError> {
    let current_dir = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let env_override = env::var(WORKSPACE_ENV_KEY).ok();
    resolve_startup_workspace_from(&current_dir, env_override.as_deref())
}

fn legacy_state_candidates(workspace: &Path, session_root_dir: &str) -> Vec<PathBuf> {
    vec![
        workspace
            .join("openplanter-desktop")
            .join("crates")
            .join("op-tauri")
            .join(session_root_dir),
        workspace
            .join("crates")
            .join("op-tauri")
            .join(session_root_dir),
    ]
}

fn copy_missing_file(src: &Path, dst: &Path, report: &mut LegacyMigrationReport) {
    if !src.exists() || !src.is_file() {
        return;
    }

    if dst.exists() {
        report.skipped_existing += 1;
        return;
    }

    if let Some(parent) = dst.parent() {
        if let Err(err) = fs::create_dir_all(parent) {
            report
                .errors
                .push(format!("failed to create {}: {err}", parent.display()));
            return;
        }
    }

    match fs::copy(src, dst) {
        Ok(_) => report.copied_files += 1,
        Err(err) => report.errors.push(format!(
            "failed to copy {} -> {}: {err}",
            src.display(),
            dst.display()
        )),
    }
}

fn copy_missing_tree(src: &Path, dst: &Path, report: &mut LegacyMigrationReport) {
    if !src.exists() {
        return;
    }
    if src.is_file() {
        copy_missing_file(src, dst, report);
        return;
    }
    if !src.is_dir() {
        return;
    }

    if let Err(err) = fs::create_dir_all(dst) {
        report
            .errors
            .push(format!("failed to create {}: {err}", dst.display()));
        return;
    }

    let entries = match fs::read_dir(src) {
        Ok(entries) => entries,
        Err(err) => {
            report
                .errors
                .push(format!("failed to read {}: {err}", src.display()));
            return;
        }
    };

    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(err) => {
                report.errors.push(format!(
                    "failed to read entry under {}: {err}",
                    src.display()
                ));
                continue;
            }
        };
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if src_path.is_dir() {
            copy_missing_tree(&src_path, &dst_path, report);
        } else {
            copy_missing_file(&src_path, &dst_path, report);
        }
    }
}

fn migrate_legacy_desktop_state(workspace: &Path, session_root_dir: &str) -> LegacyMigrationReport {
    let mut report = LegacyMigrationReport::default();
    let destination_root = workspace.join(session_root_dir);

    for candidate in legacy_state_candidates(workspace, session_root_dir) {
        if !candidate.exists() {
            continue;
        }

        report.source = Some(candidate.clone());
        copy_missing_file(
            &candidate.join("settings.json"),
            &destination_root.join("settings.json"),
            &mut report,
        );
        copy_missing_file(
            &candidate.join("credentials.json"),
            &destination_root.join("credentials.json"),
            &mut report,
        );
        copy_missing_tree(
            &candidate.join("sessions"),
            &destination_root.join("sessions"),
            &mut report,
        );
        break;
    }

    report
}

fn format_startup_trace(
    current_dir: &Path,
    resolved: &ResolvedWorkspace,
    migration: &LegacyMigrationReport,
) -> String {
    let source = match resolved.source {
        WorkspaceSource::EnvOverride => "env_override",
        WorkspaceSource::DotEnv => "dotenv",
        WorkspaceSource::GitRoot => "git_root",
        WorkspaceSource::CurrentDir => "current_dir",
    };
    let dotenv_path = resolved
        .dotenv_path
        .as_ref()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "<none>".to_string());
    let invalid_override = resolved.invalid_override.as_deref().unwrap_or("<none>");
    let invalid_dotenv_value = resolved.invalid_dotenv_value.as_deref().unwrap_or("<none>");
    let guardrail_action = match resolved.guardrail_action {
        GuardrailAction::None => "none",
        GuardrailAction::RedirectedToWorkspace => "redirected_to_workspace",
    };
    let migration_source = migration
        .source
        .as_ref()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|| "<none>".to_string());

    format!(
        "pid={} cwd={} workspace={} source={} dotenv_path={} invalid_override={} invalid_dotenv_value={} guardrail_action={} migration_source={} migration_copied={} migration_skipped={} migration_errors={}",
        std::process::id(),
        current_dir.display(),
        resolved.path.display(),
        source,
        dotenv_path,
        invalid_override,
        invalid_dotenv_value,
        guardrail_action,
        migration_source,
        migration.copied_files,
        migration.skipped_existing,
        migration.errors.len()
    )
}

/// Application state shared across Tauri commands.
pub struct AppState {
    pub config: Arc<Mutex<AgentConfig>>,
    pub session_id: Arc<Mutex<Option<String>>>,
    pub cancel_token: Arc<Mutex<CancellationToken>>,
    pub agent_running: Arc<Mutex<bool>>,
    pub init_lock: Arc<Mutex<()>>,
    startup_trace: String,
}

impl AppState {
    pub fn try_new() -> Result<Self, StartupWorkspaceError> {
        let current_dir = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let resolved_workspace = resolve_desktop_workspace()?;
        let mut cfg = AgentConfig::from_env(&resolved_workspace.path);
        let migration = migrate_legacy_desktop_state(&cfg.workspace, &cfg.session_root_dir);
        if let Err(err) =
            workspace_init::run_standard_init(&cfg.workspace, &cfg.session_root_dir, false)
        {
            eprintln!("[startup:init] {err}");
        }

        // Load .env files and merge credentials into config
        let env_creds = credentials_from_env();
        let candidates = discover_env_candidates(&cfg.workspace);
        for candidate in &candidates {
            let file_creds = parse_env_file(candidate);
            merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        }

        // If no .env candidates found, still merge from process env
        if candidates.is_empty() {
            let empty = CredentialBundle::default();
            merge_credentials_into_config(&mut cfg, &env_creds, &empty);
        }

        let settings = SettingsStore::new(&cfg.workspace, &cfg.session_root_dir).load();
        apply_settings_to_config(&mut cfg, &settings);

        Ok(Self {
            config: Arc::new(Mutex::new(cfg)),
            session_id: Arc::new(Mutex::new(None)),
            cancel_token: Arc::new(Mutex::new(CancellationToken::new())),
            agent_running: Arc::new(Mutex::new(false)),
            init_lock: Arc::new(Mutex::new(())),
            startup_trace: format_startup_trace(&current_dir, &resolved_workspace, &migration),
        })
    }

    pub fn startup_trace(&self) -> &str {
        &self.startup_trace
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use tempfile::tempdir;

    fn empty_cfg() -> AgentConfig {
        let mut cfg = AgentConfig::from_env("/nonexistent");
        cfg.openai_api_key = None;
        cfg.openai_oauth_token = None;
        cfg.anthropic_api_key = None;
        cfg.openrouter_api_key = None;
        cfg.cerebras_api_key = None;
        cfg.zai_api_key = None;
        cfg.exa_api_key = None;
        cfg.firecrawl_api_key = None;
        cfg.brave_api_key = None;
        cfg.tavily_api_key = None;
        cfg.voyage_api_key = None;
        cfg
    }

    #[test]
    fn test_merge_fills_missing() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            openai_api_key: Some("env-key".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle::default();
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.openai_api_key, Some("env-key".to_string()));
    }

    #[test]
    fn test_merge_preserves_existing() {
        let mut cfg = empty_cfg();
        cfg.openai_api_key = Some("existing".to_string());
        let env_creds = CredentialBundle {
            openai_api_key: Some("env-key".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle::default();
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.openai_api_key, Some("existing".to_string()));
    }

    #[test]
    fn test_merge_prefers_real_openai_key_over_oauth() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            openai_api_key: Some("env-key".to_string()),
            openai_oauth_token: Some("oauth-token".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &CredentialBundle::default());
        assert_eq!(cfg.openai_oauth_token, Some("oauth-token".to_string()));
        assert_eq!(cfg.openai_api_key, Some("env-key".to_string()));
        assert_eq!(cfg.api_key, Some("env-key".to_string()));
    }

    #[test]
    fn test_merge_uses_oauth_when_only_placeholder_exists() {
        let mut cfg = AgentConfig::default();
        let env_creds = CredentialBundle {
            openai_oauth_token: Some("oauth-token".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &CredentialBundle::default());
        assert_eq!(cfg.openai_oauth_token, Some("oauth-token".to_string()));
        assert_eq!(cfg.openai_api_key, Some("oauth-token".to_string()));
        assert_eq!(cfg.api_key, Some("oauth-token".to_string()));
    }

    #[test]
    fn test_merge_env_over_file() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            anthropic_api_key: Some("env-ant".to_string()),
            ..Default::default()
        };
        let file_creds = CredentialBundle {
            anthropic_api_key: Some("file-ant".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.anthropic_api_key, Some("env-ant".to_string()));
    }

    #[test]
    fn test_merge_file_fills_when_env_missing() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle::default();
        let file_creds = CredentialBundle {
            cerebras_api_key: Some("file-cer".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &file_creds);
        assert_eq!(cfg.cerebras_api_key, Some("file-cer".to_string()));
    }

    #[test]
    fn test_merge_includes_zai_firecrawl_brave_tavily_and_voyage() {
        let mut cfg = empty_cfg();
        let env_creds = CredentialBundle {
            zai_api_key: Some("zai-env".to_string()),
            firecrawl_api_key: Some("fc-env".to_string()),
            brave_api_key: Some("brave-env".to_string()),
            tavily_api_key: Some("tavily-env".to_string()),
            voyage_api_key: Some("voyage-env".to_string()),
            ..Default::default()
        };
        merge_credentials_into_config(&mut cfg, &env_creds, &CredentialBundle::default());
        assert_eq!(cfg.zai_api_key, Some("zai-env".to_string()));
        assert_eq!(cfg.firecrawl_api_key, Some("fc-env".to_string()));
        assert_eq!(cfg.brave_api_key, Some("brave-env".to_string()));
        assert_eq!(cfg.tavily_api_key, Some("tavily-env".to_string()));
        assert_eq!(cfg.voyage_api_key, Some("voyage-env".to_string()));
    }

    #[test]
    fn test_apply_settings_to_config_sets_model_and_web_search() {
        let keys = [
            "OPENPLANTER_MODEL",
            "OPENPLANTER_REASONING_EFFORT",
            "OPENPLANTER_ZAI_PLAN",
            "OPENPLANTER_ZAI_BASE_URL",
            "OPENPLANTER_WEB_SEARCH_PROVIDER",
        ];
        let saved: Vec<_> = keys.iter().map(|key| (*key, env::var(key).ok())).collect();
        unsafe {
            for key in &keys {
                env::remove_var(key);
            }
        }

        let mut cfg = empty_cfg();
        cfg.provider = "zai".to_string();
        let settings = PersistentSettings {
            default_model_zai: Some("glm-5".to_string()),
            default_reasoning_effort: Some("medium".to_string()),
            zai_plan: Some("coding".to_string()),
            web_search_provider: Some("brave".to_string()),
            ..Default::default()
        };
        apply_settings_to_config(&mut cfg, &settings);
        assert_eq!(cfg.model, "glm-5");
        assert_eq!(cfg.reasoning_effort, Some("medium".to_string()));
        assert_eq!(cfg.zai_plan, "coding");
        assert_eq!(cfg.zai_base_url, op_core::config::ZAI_CODING_BASE_URL);
        assert_eq!(cfg.web_search_provider, "brave");

        for (key, value) in saved {
            unsafe {
                match value {
                    Some(value) => env::set_var(key, value),
                    None => env::remove_var(key),
                }
            }
        }
    }

    #[test]
    fn test_resolve_startup_workspace_prefers_env_override() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        fs::create_dir_all(repo.join(".git")).unwrap();
        let override_dir = temp.path().join("override");
        fs::create_dir_all(&override_dir).unwrap();

        let resolved =
            resolve_startup_workspace_from(&repo, Some(override_dir.to_str().unwrap())).unwrap();

        assert_eq!(resolved.source, WorkspaceSource::EnvOverride);
        assert_eq!(resolved.path, canonicalize_or_self(&override_dir));
        assert!(resolved.invalid_override.is_none());
        assert_eq!(resolved.guardrail_action, GuardrailAction::None);
    }

    #[test]
    fn test_resolve_startup_workspace_prefers_dotenv_before_git_root() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        let workspace = repo.join("workspace");
        let nested = repo
            .join("openplanter-desktop")
            .join("crates")
            .join("op-tauri");
        fs::create_dir_all(repo.join(".git")).unwrap();
        fs::create_dir_all(&workspace).unwrap();
        fs::create_dir_all(&nested).unwrap();
        fs::write(repo.join(".env"), "OPENPLANTER_WORKSPACE=workspace\n").unwrap();

        let resolved = resolve_startup_workspace_from(&nested, None).unwrap();

        assert_eq!(resolved.source, WorkspaceSource::DotEnv);
        assert_eq!(resolved.path, canonicalize_or_self(&workspace));
        assert_eq!(
            resolved.dotenv_path,
            Some(canonicalize_or_self(&repo.join(".env")))
        );
    }

    #[test]
    fn test_resolve_startup_workspace_redirects_repo_root_to_workspace() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        let workspace = repo.join("workspace");
        let nested = repo
            .join("openplanter-desktop")
            .join("crates")
            .join("op-tauri");
        fs::create_dir_all(repo.join(".git")).unwrap();
        fs::create_dir_all(&workspace).unwrap();
        fs::create_dir_all(&nested).unwrap();

        let resolved = resolve_startup_workspace_from(&nested, None).unwrap();

        assert_eq!(resolved.source, WorkspaceSource::GitRoot);
        assert_eq!(resolved.path, canonicalize_or_self(&workspace));
        assert_eq!(
            resolved.guardrail_action,
            GuardrailAction::RedirectedToWorkspace
        );
    }

    #[test]
    fn test_resolve_startup_workspace_rejects_repo_root_when_workspace_dir_missing() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        fs::create_dir_all(repo.join(".git")).unwrap();

        let err = resolve_startup_workspace_from(&repo, None).unwrap_err();

        assert_eq!(
            err,
            StartupWorkspaceError::RepoRootDisallowed {
                repo_root: canonicalize_or_self(&repo),
            }
        );
    }

    #[test]
    fn test_resolve_startup_workspace_invalid_override_falls_back_cleanly() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        let workspace = repo.join("workspace");
        let invalid = temp.path().join("missing");
        fs::create_dir_all(repo.join(".git")).unwrap();
        fs::create_dir_all(&workspace).unwrap();

        let resolved =
            resolve_startup_workspace_from(&repo, Some(invalid.to_str().unwrap())).unwrap();

        assert_eq!(resolved.source, WorkspaceSource::GitRoot);
        assert_eq!(resolved.path, canonicalize_or_self(&workspace));
        assert_eq!(
            resolved.invalid_override,
            Some(invalid.display().to_string())
        );
    }

    #[test]
    fn test_resolve_startup_workspace_file_override_is_treated_as_invalid() {
        let temp = tempdir().unwrap();
        let repo = temp.path().join("repo");
        let workspace = repo.join("workspace");
        let invalid = repo.join("workspace.txt");
        fs::create_dir_all(repo.join(".git")).unwrap();
        fs::create_dir_all(&workspace).unwrap();
        fs::write(&invalid, "not a directory\n").unwrap();

        let resolved =
            resolve_startup_workspace_from(&repo, Some(invalid.to_str().unwrap())).unwrap();

        assert_eq!(resolved.source, WorkspaceSource::GitRoot);
        assert_eq!(resolved.path, canonicalize_or_self(&workspace));
        assert_eq!(
            resolved.invalid_override,
            Some(invalid.display().to_string())
        );
    }

    #[test]
    fn test_migrate_legacy_desktop_state_copies_missing_and_preserves_existing() {
        let temp = tempdir().unwrap();
        let workspace = temp.path().join("repo");
        let legacy = workspace
            .join("openplanter-desktop")
            .join("crates")
            .join("op-tauri")
            .join(".openplanter");
        let destination = workspace.join(".openplanter");

        fs::create_dir_all(legacy.join("sessions").join("session-a")).unwrap();
        fs::write(legacy.join("settings.json"), "{\"legacy\":true}").unwrap();
        fs::write(legacy.join("credentials.json"), "{\"key\":\"legacy\"}").unwrap();
        fs::write(
            legacy
                .join("sessions")
                .join("session-a")
                .join("replay.jsonl"),
            "legacy-session",
        )
        .unwrap();

        fs::create_dir_all(&destination).unwrap();
        fs::write(destination.join("settings.json"), "{\"keep\":true}").unwrap();

        let report = migrate_legacy_desktop_state(&workspace, ".openplanter");

        assert_eq!(report.source, Some(legacy));
        assert_eq!(
            fs::read_to_string(destination.join("settings.json")).unwrap(),
            "{\"keep\":true}"
        );
        assert_eq!(
            fs::read_to_string(destination.join("credentials.json")).unwrap(),
            "{\"key\":\"legacy\"}"
        );
        assert_eq!(
            fs::read_to_string(
                destination
                    .join("sessions")
                    .join("session-a")
                    .join("replay.jsonl")
            )
            .unwrap(),
            "legacy-session"
        );
        assert_eq!(report.copied_files, 2);
        assert_eq!(report.skipped_existing, 1);
        assert!(report.errors.is_empty());
    }

    #[test]
    fn test_startup_trace_uses_informational_migration_labels() {
        let temp = tempdir().unwrap();
        let workspace = temp.path().join("repo");
        let current_dir = workspace
            .join("openplanter-desktop")
            .join("crates")
            .join("op-tauri");
        fs::create_dir_all(workspace.join(".git")).unwrap();
        fs::create_dir_all(&current_dir).unwrap();

        let workspace_dir = workspace.join("workspace");
        fs::create_dir_all(&workspace_dir).unwrap();

        let resolved = resolve_startup_workspace_from(&current_dir, None).unwrap();
        let migration = LegacyMigrationReport {
            source: Some(workspace.join("legacy-state")),
            copied_files: 2,
            skipped_existing: 3,
            errors: vec!["copy failed".to_string()],
        };

        let trace = format_startup_trace(&current_dir, &resolved, &migration);

        assert!(trace.contains("pid="));
        assert!(trace.contains(&format!("cwd={}", current_dir.display())));
        assert!(trace.contains(&format!("workspace={}", resolved.path.display())));
        assert!(trace.contains("source=git_root"));
        assert!(trace.contains("dotenv_path=<none>"));
        assert!(trace.contains("invalid_override=<none>"));
        assert!(trace.contains("invalid_dotenv_value=<none>"));
        assert!(trace.contains("guardrail_action=redirected_to_workspace"));
        assert!(trace.contains(&format!(
            "migration_source={}",
            workspace.join("legacy-state").display()
        )));
        assert!(trace.contains("migration_copied=2"));
        assert!(trace.contains("migration_skipped=3"));
        assert!(trace.contains("migration_errors=1"));
        assert!(!trace.contains(" copied="));
        assert!(!trace.contains(" skipped="));
        assert!(!trace.contains(" errors="));
    }
}
