/// Shell execution tools: run_shell, run_shell_bg, check_shell_bg, kill_shell_bg.

use std::collections::HashMap;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

use regex::Regex;
use std::sync::LazyLock;

use super::ToolResult;

static HEREDOC_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"<<-?\s*['"]?\w+['"]?"#).unwrap());

static INTERACTIVE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(^|[;&|]\s*)(vim|nano|less|more|top|htop|man)\b").unwrap());

fn clip(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let end = text.floor_char_boundary(max_chars);
    let omitted = text.len() - end;
    format!(
        "{}\n\n...[truncated {omitted} chars]...",
        &text[..end]
    )
}

fn check_shell_policy(command: &str) -> Option<String> {
    if HEREDOC_RE.is_match(command) {
        return Some(
            "BLOCKED: Heredoc syntax (<< EOF) is not allowed by runtime policy. \
             Use write_file/apply_patch for multi-line content."
                .into(),
        );
    }
    if INTERACTIVE_RE.is_match(command) {
        return Some(
            "BLOCKED: Interactive terminal programs are not allowed by runtime policy \
             (vim/nano/less/more/top/htop/man)."
                .into(),
        );
    }
    None
}

/// State for background shell processes.
pub struct BgJobs {
    jobs: HashMap<u32, BgJob>,
    next_id: u32,
}

struct BgJob {
    child: Child,
    output_path: String,
}

impl BgJobs {
    pub fn new() -> Self {
        Self {
            jobs: HashMap::new(),
            next_id: 1,
        }
    }

    pub fn cleanup(&mut self) {
        for (_id, mut job) in self.jobs.drain() {
            let _ = job.child.kill();
            let _ = job.child.wait();
            let _ = std::fs::remove_file(&job.output_path);
        }
    }
}

impl Drop for BgJobs {
    fn drop(&mut self) {
        self.cleanup();
    }
}

pub fn run_shell(
    root: &Path,
    shell: &str,
    command: &str,
    timeout_sec: u64,
    max_output_chars: usize,
) -> ToolResult {
    if let Some(err) = check_shell_policy(command) {
        return ToolResult::error(err);
    }
    let effective_timeout = timeout_sec.max(1).min(600);

    let mut child = match Command::new(shell)
        .args(["-c", command])
        .current_dir(root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => return ToolResult::error(format!("$ {command}\n[failed to start: {e}]")),
    };

    // Wait with timeout
    let timeout = Duration::from_secs(effective_timeout);
    let start = std::time::Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed() > timeout {
                    let _ = child.kill();
                    let _ = child.wait();
                    return ToolResult::ok(format!(
                        "$ {command}\n[timeout after {effective_timeout}s — processes killed]"
                    ));
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                return ToolResult::error(format!("$ {command}\n[wait error: {e}]"));
            }
        }
    }

    let output = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => return ToolResult::error(format!("$ {command}\n[output error: {e}]")),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let code = output.status.code().unwrap_or(-1);

    let merged = format!(
        "$ {command}\n[exit_code={code}]\n[stdout]\n{stdout}\n[stderr]\n{stderr}"
    );
    ToolResult::ok(clip(&merged, max_output_chars))
}

pub fn run_shell_bg(
    root: &Path,
    shell: &str,
    command: &str,
    bg_jobs: &mut BgJobs,
) -> ToolResult {
    if let Some(err) = check_shell_policy(command) {
        return ToolResult::error(err);
    }

    let job_id = bg_jobs.next_id;
    let out_path = format!(
        "{}/op_bg_{job_id}.out",
        std::env::temp_dir().to_string_lossy()
    );

    let outfile = match std::fs::File::create(&out_path) {
        Ok(f) => f,
        Err(e) => return ToolResult::error(format!("Failed to create output file: {e}")),
    };

    let errfile = match outfile.try_clone() {
        Ok(f) => f,
        Err(e) => return ToolResult::error(format!("Failed to clone output file handle: {e}")),
    };

    let child = match Command::new(shell)
        .args(["-c", command])
        .current_dir(root)
        .stdout(Stdio::from(outfile))
        .stderr(Stdio::from(errfile))
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            let _ = std::fs::remove_file(&out_path);
            return ToolResult::error(format!("Failed to start background command: {e}"));
        }
    };

    let pid = child.id();
    bg_jobs.jobs.insert(
        job_id,
        BgJob {
            child,
            output_path: out_path,
        },
    );
    bg_jobs.next_id += 1;

    ToolResult::ok(format!(
        "Background job started: job_id={job_id}, pid={pid}"
    ))
}

pub fn check_shell_bg(
    job_id: u32,
    bg_jobs: &mut BgJobs,
    max_output_chars: usize,
) -> ToolResult {
    let job = match bg_jobs.jobs.get_mut(&job_id) {
        Some(j) => j,
        None => return ToolResult::error(format!("No background job with id {job_id}")),
    };

    let output = std::fs::read_to_string(&job.output_path).unwrap_or_default();
    let output = clip(&output, max_output_chars);

    match job.child.try_wait() {
        Ok(Some(status)) => {
            let code = status.code().unwrap_or(-1);
            let out_path = job.output_path.clone();
            bg_jobs.jobs.remove(&job_id);
            let _ = std::fs::remove_file(&out_path);
            ToolResult::ok(format!(
                "[job {job_id} finished, exit_code={code}]\n{output}"
            ))
        }
        Ok(None) => {
            let pid = job.child.id();
            ToolResult::ok(format!(
                "[job {job_id} still running, pid={pid}]\n{output}"
            ))
        }
        Err(e) => ToolResult::error(format!("Error checking job {job_id}: {e}")),
    }
}

pub fn kill_shell_bg(job_id: u32, bg_jobs: &mut BgJobs) -> ToolResult {
    let mut job = match bg_jobs.jobs.remove(&job_id) {
        Some(j) => j,
        None => return ToolResult::error(format!("No background job with id {job_id}")),
    };

    let _ = job.child.kill();
    let _ = job.child.wait();
    let _ = std::fs::remove_file(&job.output_path);

    ToolResult::ok(format!("Background job {job_id} killed."))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_run_shell_basic() {
        let dir = TempDir::new().unwrap();
        let result = run_shell(dir.path(), "/bin/sh", "echo hello", 10, 16000);
        assert!(!result.is_error);
        assert!(result.content.contains("hello"));
        assert!(result.content.contains("exit_code=0"));
    }

    #[test]
    fn test_run_shell_heredoc_blocked() {
        let dir = TempDir::new().unwrap();
        let result = run_shell(
            dir.path(),
            "/bin/sh",
            "cat << EOF\nhello\nEOF",
            10,
            16000,
        );
        assert!(result.is_error);
        assert!(result.content.contains("BLOCKED"));
    }

    #[test]
    fn test_run_shell_interactive_blocked() {
        let dir = TempDir::new().unwrap();
        let result = run_shell(dir.path(), "/bin/sh", "vim test.txt", 10, 16000);
        assert!(result.is_error);
        assert!(result.content.contains("BLOCKED"));
    }

    #[test]
    fn test_bg_job_lifecycle() {
        let dir = TempDir::new().unwrap();
        let mut bg = BgJobs::new();

        let result = run_shell_bg(dir.path(), "/bin/sh", "echo bg_test", &mut bg);
        assert!(!result.is_error);
        assert!(result.content.contains("job_id=1"));

        // Wait for the command to finish
        std::thread::sleep(Duration::from_millis(200));

        let result = check_shell_bg(1, &mut bg, 16000);
        assert!(!result.is_error);
        assert!(result.content.contains("finished"));
    }

    #[test]
    fn test_kill_shell_bg() {
        let dir = TempDir::new().unwrap();
        let mut bg = BgJobs::new();

        let result = run_shell_bg(dir.path(), "/bin/sh", "sleep 60", &mut bg);
        assert!(!result.is_error);

        let result = kill_shell_bg(1, &mut bg);
        assert!(!result.is_error);
        assert!(result.content.contains("killed"));
    }

    #[test]
    fn test_check_nonexistent_job() {
        let mut bg = BgJobs::new();
        let result = check_shell_bg(999, &mut bg, 16000);
        assert!(result.is_error);
    }
}
