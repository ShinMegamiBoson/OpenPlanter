use std::collections::HashMap;
use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// A bundle of API keys for all supported providers.
///
/// Mirrors the Python `CredentialBundle` dataclass.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CredentialBundle {
    pub openai_api_key: Option<String>,
    pub openai_oauth_token: Option<String>,
    pub anthropic_api_key: Option<String>,
    pub openrouter_api_key: Option<String>,
    pub cerebras_api_key: Option<String>,
    pub zai_api_key: Option<String>,
    pub exa_api_key: Option<String>,
    pub firecrawl_api_key: Option<String>,
    pub brave_api_key: Option<String>,
    pub voyage_api_key: Option<String>,
}

impl CredentialBundle {
    /// Returns `true` if any key has a non-empty value.
    pub fn has_any(&self) -> bool {
        let keys = [
            &self.openai_api_key,
            &self.openai_oauth_token,
            &self.anthropic_api_key,
            &self.openrouter_api_key,
            &self.cerebras_api_key,
            &self.zai_api_key,
            &self.exa_api_key,
            &self.firecrawl_api_key,
            &self.brave_api_key,
            &self.voyage_api_key,
        ];
        keys.iter()
            .any(|k| k.as_ref().map(|v| !v.trim().is_empty()).unwrap_or(false))
    }

    /// Fill in missing keys from `other`.
    pub fn merge_missing(&mut self, other: &CredentialBundle) {
        macro_rules! fill {
            ($field:ident) => {
                if self.$field.is_none() {
                    self.$field = other.$field.clone();
                }
            };
        }
        fill!(openai_api_key);
        fill!(openai_oauth_token);
        fill!(anthropic_api_key);
        fill!(openrouter_api_key);
        fill!(cerebras_api_key);
        fill!(zai_api_key);
        fill!(exa_api_key);
        fill!(firecrawl_api_key);
        fill!(brave_api_key);
        fill!(voyage_api_key);
    }

    /// Serialize to JSON map, omitting `None` values.
    pub fn to_json(&self) -> HashMap<String, String> {
        let mut out = HashMap::new();
        macro_rules! add {
            ($field:ident, $key:expr) => {
                if let Some(ref v) = self.$field {
                    out.insert($key.to_string(), v.clone());
                }
            };
        }
        add!(openai_api_key, "openai_api_key");
        add!(openai_oauth_token, "openai_oauth_token");
        add!(anthropic_api_key, "anthropic_api_key");
        add!(openrouter_api_key, "openrouter_api_key");
        add!(cerebras_api_key, "cerebras_api_key");
        add!(zai_api_key, "zai_api_key");
        add!(exa_api_key, "exa_api_key");
        add!(firecrawl_api_key, "firecrawl_api_key");
        add!(brave_api_key, "brave_api_key");
        add!(voyage_api_key, "voyage_api_key");
        out
    }

    /// Deserialize from a JSON map.
    pub fn from_json(payload: &HashMap<String, serde_json::Value>) -> Self {
        fn get_str(map: &HashMap<String, serde_json::Value>, key: &str) -> Option<String> {
            map.get(key)
                .and_then(|v| v.as_str())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        }
        Self {
            openai_api_key: get_str(payload, "openai_api_key"),
            openai_oauth_token: get_str(payload, "openai_oauth_token"),
            anthropic_api_key: get_str(payload, "anthropic_api_key"),
            openrouter_api_key: get_str(payload, "openrouter_api_key"),
            cerebras_api_key: get_str(payload, "cerebras_api_key"),
            zai_api_key: get_str(payload, "zai_api_key"),
            exa_api_key: get_str(payload, "exa_api_key"),
            firecrawl_api_key: get_str(payload, "firecrawl_api_key"),
            brave_api_key: get_str(payload, "brave_api_key"),
            voyage_api_key: get_str(payload, "voyage_api_key"),
        }
    }
}

/// Strip surrounding quotes from a value.
fn strip_quotes(s: &str) -> &str {
    let trimmed = s.trim();
    if trimmed.len() >= 2 {
        let first = trimmed.as_bytes()[0];
        let last = trimmed.as_bytes()[trimmed.len() - 1];
        if first == last && (first == b'\'' || first == b'"') {
            return &trimmed[1..trimmed.len() - 1];
        }
    }
    trimmed
}

/// Parse a `.env` file and extract credential keys.
pub fn parse_env_file(path: &Path) -> CredentialBundle {
    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return CredentialBundle::default(),
    };

    let mut env_map: HashMap<String, String> = HashMap::new();
    for raw in content.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line).trim();
        if let Some((key, value)) = line.split_once('=') {
            let key = key.trim();
            let value = strip_quotes(value.trim());
            env_map.insert(key.to_string(), value.to_string());
        }
    }

    fn get_key(map: &HashMap<String, String>, primary: &str, secondary: &str) -> Option<String> {
        map.get(primary)
            .or_else(|| map.get(secondary))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    }

    CredentialBundle {
        openai_api_key: get_key(&env_map, "OPENAI_API_KEY", "OPENPLANTER_OPENAI_API_KEY"),
        openai_oauth_token: get_key(
            &env_map,
            "OPENAI_OAUTH_TOKEN",
            "OPENPLANTER_OPENAI_OAUTH_TOKEN",
        ),
        anthropic_api_key: get_key(
            &env_map,
            "ANTHROPIC_API_KEY",
            "OPENPLANTER_ANTHROPIC_API_KEY",
        ),
        openrouter_api_key: get_key(
            &env_map,
            "OPENROUTER_API_KEY",
            "OPENPLANTER_OPENROUTER_API_KEY",
        ),
        cerebras_api_key: get_key(&env_map, "CEREBRAS_API_KEY", "OPENPLANTER_CEREBRAS_API_KEY"),
        zai_api_key: get_key(&env_map, "ZAI_API_KEY", "OPENPLANTER_ZAI_API_KEY"),
        exa_api_key: get_key(&env_map, "EXA_API_KEY", "OPENPLANTER_EXA_API_KEY"),
        firecrawl_api_key: get_key(
            &env_map,
            "FIRECRAWL_API_KEY",
            "OPENPLANTER_FIRECRAWL_API_KEY",
        ),
        brave_api_key: get_key(&env_map, "BRAVE_API_KEY", "OPENPLANTER_BRAVE_API_KEY"),
        voyage_api_key: get_key(&env_map, "VOYAGE_API_KEY", "OPENPLANTER_VOYAGE_API_KEY"),
    }
}

/// Build credentials from process environment variables.
pub fn credentials_from_env() -> CredentialBundle {
    fn env_key(primary: &str, secondary: &str) -> Option<String> {
        env::var(primary)
            .ok()
            .or_else(|| env::var(secondary).ok())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    }

    CredentialBundle {
        openai_api_key: env_key("OPENPLANTER_OPENAI_API_KEY", "OPENAI_API_KEY"),
        openai_oauth_token: env_key("OPENPLANTER_OPENAI_OAUTH_TOKEN", "OPENAI_OAUTH_TOKEN"),
        anthropic_api_key: env_key("OPENPLANTER_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        openrouter_api_key: env_key("OPENPLANTER_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        cerebras_api_key: env_key("OPENPLANTER_CEREBRAS_API_KEY", "CEREBRAS_API_KEY"),
        zai_api_key: env_key("OPENPLANTER_ZAI_API_KEY", "ZAI_API_KEY"),
        exa_api_key: env_key("OPENPLANTER_EXA_API_KEY", "EXA_API_KEY"),
        firecrawl_api_key: env_key("OPENPLANTER_FIRECRAWL_API_KEY", "FIRECRAWL_API_KEY"),
        brave_api_key: env_key("OPENPLANTER_BRAVE_API_KEY", "BRAVE_API_KEY"),
        voyage_api_key: env_key("OPENPLANTER_VOYAGE_API_KEY", "VOYAGE_API_KEY"),
    }
}

/// Discover `.env` file candidates by walking from workspace up to ancestors.
pub fn discover_env_candidates(workspace: &Path) -> Vec<PathBuf> {
    let ws = workspace
        .canonicalize()
        .unwrap_or_else(|_| workspace.to_path_buf());
    let mut candidates = Vec::new();
    let mut dir = Some(ws.as_path());
    while let Some(d) = dir {
        let env_path = d.join(".env");
        if env_path.exists() {
            candidates.push(env_path);
            break; // use the nearest .env
        }
        dir = d.parent();
    }
    candidates
}

/// Workspace-level credential store at `{workspace}/.openplanter/credentials.json`.
pub struct CredentialStore {
    pub credentials_path: PathBuf,
}

impl CredentialStore {
    pub fn new(workspace: &Path, session_root_dir: &str) -> Self {
        let ws = workspace
            .canonicalize()
            .unwrap_or_else(|_| workspace.to_path_buf());
        let root = ws.join(session_root_dir);
        let _ = fs::create_dir_all(&root);
        Self {
            credentials_path: root.join("credentials.json"),
        }
    }

    pub fn load(&self) -> CredentialBundle {
        let content = match fs::read_to_string(&self.credentials_path) {
            Ok(c) => c,
            Err(_) => return CredentialBundle::default(),
        };
        let payload: HashMap<String, serde_json::Value> = match serde_json::from_str(&content) {
            Ok(p) => p,
            Err(_) => return CredentialBundle::default(),
        };
        CredentialBundle::from_json(&payload)
    }

    pub fn save(&self, creds: &CredentialBundle) -> std::io::Result<()> {
        let payload = creds.to_json();
        if let Some(parent) = self.credentials_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let json = serde_json::to_string_pretty(&payload)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&self.credentials_path, json)?;
        // Set permissions to owner-only (0o600)
        #[cfg(unix)]
        {
            let perms = fs::Permissions::from_mode(0o600);
            let _ = fs::set_permissions(&self.credentials_path, perms);
        }
        Ok(())
    }
}

/// User-level credential store at `~/.openplanter/credentials.json`.
pub struct UserCredentialStore {
    pub credentials_path: PathBuf,
}

impl UserCredentialStore {
    pub fn new() -> Self {
        let home = env::var("HOME")
            .or_else(|_| env::var("USERPROFILE"))
            .unwrap_or_else(|_| ".".to_string());
        Self {
            credentials_path: PathBuf::from(home)
                .join(".openplanter")
                .join("credentials.json"),
        }
    }

    pub fn load(&self) -> CredentialBundle {
        let content = match fs::read_to_string(&self.credentials_path) {
            Ok(c) => c,
            Err(_) => return CredentialBundle::default(),
        };
        let payload: HashMap<String, serde_json::Value> = match serde_json::from_str(&content) {
            Ok(p) => p,
            Err(_) => return CredentialBundle::default(),
        };
        CredentialBundle::from_json(&payload)
    }

    pub fn save(&self, creds: &CredentialBundle) -> std::io::Result<()> {
        let payload = creds.to_json();
        if let Some(parent) = self.credentials_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let json = serde_json::to_string_pretty(&payload)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        fs::write(&self.credentials_path, json)?;
        #[cfg(unix)]
        {
            let perms = fs::Permissions::from_mode(0o600);
            let _ = fs::set_permissions(&self.credentials_path, perms);
        }
        Ok(())
    }
}

impl Default for UserCredentialStore {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_credential_bundle_default_has_none() {
        let bundle = CredentialBundle::default();
        assert!(!bundle.has_any());
    }

    #[test]
    fn test_credential_bundle_has_any() {
        let mut bundle = CredentialBundle::default();
        bundle.openai_api_key = Some("sk-test".into());
        assert!(bundle.has_any());
    }

    #[test]
    fn test_credential_bundle_has_any_with_voyage_key() {
        let bundle = CredentialBundle {
            voyage_api_key: Some("voyage-test".into()),
            ..Default::default()
        };
        assert!(bundle.has_any());
    }

    #[test]
    fn test_credential_bundle_whitespace_only_values_do_not_count() {
        let bundle = CredentialBundle {
            voyage_api_key: Some("   ".into()),
            ..Default::default()
        };
        assert!(!bundle.has_any());
    }

    #[test]
    fn test_credential_bundle_merge_missing() {
        let mut a = CredentialBundle {
            openai_api_key: Some("existing".into()),
            ..Default::default()
        };
        let b = CredentialBundle {
            openai_api_key: Some("should-not-overwrite".into()),
            anthropic_api_key: Some("new-key".into()),
            zai_api_key: Some("zai-key".into()),
            ..Default::default()
        };
        a.merge_missing(&b);
        assert_eq!(a.openai_api_key, Some("existing".into()));
        assert_eq!(a.anthropic_api_key, Some("new-key".into()));
        assert_eq!(a.zai_api_key, Some("zai-key".into()));
    }

    #[test]
    fn test_to_json_round_trip() {
        let bundle = CredentialBundle {
            openai_api_key: Some("sk-123".into()),
            anthropic_api_key: None,
            openrouter_api_key: Some("or-456".into()),
            firecrawl_api_key: Some("fc-789".into()),
            brave_api_key: Some("brave-101".into()),
            ..Default::default()
        };
        let json = bundle.to_json();
        assert_eq!(json.get("openai_api_key").unwrap(), "sk-123");
        assert!(!json.contains_key("anthropic_api_key"));
        assert_eq!(json.get("openrouter_api_key").unwrap(), "or-456");
        assert_eq!(json.get("firecrawl_api_key").unwrap(), "fc-789");
        assert_eq!(json.get("brave_api_key").unwrap(), "brave-101");
    }

    #[test]
    fn test_parse_env_file() {
        let dir = tempfile::tempdir().unwrap();
        let env_path = dir.path().join(".env");
        fs::write(
            &env_path,
            r#"
# Comment line
OPENAI_API_KEY=sk-from-env
export ANTHROPIC_API_KEY='ant-key'
EXA_API_KEY="exa-quoted"
ZAI_API_KEY=zai-from-env
OPENPLANTER_FIRECRAWL_API_KEY="firecrawl-quoted"
BRAVE_API_KEY=brave-from-env
UNRELATED_VAR=foo
"#,
        )
        .unwrap();

        let bundle = parse_env_file(&env_path);
        assert_eq!(bundle.openai_api_key, Some("sk-from-env".into()));
        assert_eq!(bundle.anthropic_api_key, Some("ant-key".into()));
        assert_eq!(bundle.exa_api_key, Some("exa-quoted".into()));
        assert_eq!(bundle.zai_api_key, Some("zai-from-env".into()));
        assert_eq!(bundle.firecrawl_api_key, Some("firecrawl-quoted".into()));
        assert_eq!(bundle.brave_api_key, Some("brave-from-env".into()));
        assert!(bundle.cerebras_api_key.is_none());
    }

    #[test]
    fn test_credential_store_save_load() {
        let dir = tempfile::tempdir().unwrap();
        let store = CredentialStore::new(dir.path(), ".openplanter");
        let bundle = CredentialBundle {
            openai_api_key: Some("sk-test".into()),
            anthropic_api_key: Some("ant-test".into()),
            zai_api_key: Some("zai-test".into()),
            brave_api_key: Some("brave-test".into()),
            ..Default::default()
        };
        store.save(&bundle).unwrap();
        let loaded = store.load();
        assert_eq!(loaded.openai_api_key, Some("sk-test".into()));
        assert_eq!(loaded.anthropic_api_key, Some("ant-test".into()));
        assert_eq!(loaded.zai_api_key, Some("zai-test".into()));
        assert_eq!(loaded.brave_api_key, Some("brave-test".into()));
    }

    #[test]
    fn test_credential_store_load_missing() {
        let dir = tempfile::tempdir().unwrap();
        let store = CredentialStore::new(dir.path(), ".openplanter");
        let loaded = store.load();
        assert!(!loaded.has_any());
    }

    #[test]
    fn test_strip_quotes_fn() {
        assert_eq!(strip_quotes("'hello'"), "hello");
        assert_eq!(strip_quotes("\"world\""), "world");
        assert_eq!(strip_quotes("no-quotes"), "no-quotes");
        assert_eq!(strip_quotes("  'spaced'  "), "spaced");
    }
}
