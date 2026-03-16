use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use reqwest::multipart::{Form, Part};
use serde_json::{Map, Value, json};
use tokio::process::Command;
use tokio::time::timeout;
use uuid::Uuid;

use super::{ToolResult, filesystem};

const AUDIO_EXTENSIONS: &[&str] = &[
    ".aac", ".flac", ".m4a", ".mp3", ".mpeg", ".mpga", ".oga", ".ogg", ".opus", ".wav",
];
const VIDEO_EXTENSIONS: &[&str] = &[".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"];
const TIMESTAMP_GRANULARITIES: &[&str] = &["segment", "word"];
const CHUNKING_MODES: &[&str] = &["auto", "force", "off"];
const AUDIO_CHUNK_TARGET_FILL_RATIO: f64 = 0.85;
const AUDIO_CHUNK_BYTES_PER_SECOND: f64 = 32_000.0;
const AUDIO_MIN_CHUNK_SECONDS: f64 = 30.0;
const AUDIO_MAX_CHUNK_SECONDS: f64 = 1800.0;
const AUDIO_MAX_CHUNK_OVERLAP_SECONDS: f64 = 15.0;
const AUDIO_MAX_CHUNKS: i64 = 200;
const SPEAKER_FIELDS: &[&str] = &["speaker", "speaker_id", "speaker_label"];

#[derive(Debug, Clone)]
struct ChunkPlan {
    index: usize,
    start_sec: f64,
    end_sec: f64,
    duration_sec: f64,
    leading_overlap_sec: f64,
}

struct TempAudioDir {
    path: PathBuf,
}

impl TempAudioDir {
    fn new() -> Result<Self, String> {
        let path = std::env::temp_dir().join(format!("openplanter-audio-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&path)
            .map_err(|error| format!("Failed to create temp audio directory: {error}"))?;
        Ok(Self { path })
    }
}

impl Drop for TempAudioDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn transcription_endpoint(base_url: &str) -> String {
    let trimmed = base_url.trim().trim_end_matches('/');
    if trimmed.ends_with("/v1") {
        format!("{trimmed}/audio/transcriptions")
    } else {
        format!("{trimmed}/v1/audio/transcriptions")
    }
}

fn audio_media_type(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .as_deref()
    {
        Some("aac") => "audio/aac",
        Some("flac") => "audio/flac",
        Some("m4a") => "audio/mp4",
        Some("mp3") | Some("mpga") => "audio/mpeg",
        Some("mpeg") => "audio/mpeg",
        Some("oga") | Some("ogg") | Some("opus") => "audio/ogg",
        Some("wav") => "audio/wav",
        _ => "application/octet-stream",
    }
}

fn rel_path(root: &Path, path: &Path) -> String {
    let canon_root = std::fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
    path.strip_prefix(&canon_root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn is_video_extension(ext: &str) -> bool {
    VIDEO_EXTENSIONS.iter().any(|value| *value == ext)
}

fn is_supported_extension(ext: &str) -> bool {
    AUDIO_EXTENSIONS.iter().any(|value| *value == ext) || is_video_extension(ext)
}

fn json_length(payload: &Value) -> usize {
    serde_json::to_string_pretty(payload)
        .unwrap_or_else(|_| payload.to_string())
        .len()
}

fn build_options(
    diarize: Option<bool>,
    timestamp_granularities: Option<&[String]>,
    context_bias: Option<&[String]>,
    language: Option<&str>,
    temperature: Option<f64>,
    chunking: &str,
    chunk_max_seconds: Option<i64>,
    chunk_overlap_seconds: Option<f64>,
    max_chunks: Option<i64>,
    continue_on_chunk_error: Option<bool>,
) -> Value {
    let mut options = Map::new();
    options.insert("chunking".into(), Value::String(chunking.to_string()));
    if let Some(value) = diarize {
        options.insert("diarize".into(), Value::Bool(value));
    }
    if let Some(values) = timestamp_granularities.filter(|values| !values.is_empty()) {
        options.insert(
            "timestamp_granularities".into(),
            Value::Array(values.iter().cloned().map(Value::String).collect()),
        );
    }
    if let Some(values) = context_bias.filter(|values| !values.is_empty()) {
        options.insert(
            "context_bias".into(),
            Value::Array(values.iter().cloned().map(Value::String).collect()),
        );
    }
    if let Some(value) = language.filter(|value| !value.trim().is_empty()) {
        options.insert("language".into(), Value::String(value.to_string()));
    }
    if let Some(value) = temperature {
        if let Some(number) = serde_json::Number::from_f64(value) {
            options.insert("temperature".into(), Value::Number(number));
        }
    }
    if let Some(value) = chunk_max_seconds {
        options.insert("chunk_max_seconds".into(), Value::Number(value.into()));
    }
    if let Some(value) = chunk_overlap_seconds {
        if let Some(number) = serde_json::Number::from_f64(value) {
            options.insert("chunk_overlap_seconds".into(), Value::Number(number));
        }
    }
    if let Some(value) = max_chunks {
        options.insert("max_chunks".into(), Value::Number(value.into()));
    }
    if let Some(value) = continue_on_chunk_error {
        options.insert("continue_on_chunk_error".into(), Value::Bool(value));
    }
    Value::Object(options)
}

fn normalize_audio_token(token: &str) -> String {
    token
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn dedupe_audio_overlap_text(existing: &str, incoming: &str) -> String {
    if existing.trim().is_empty() {
        return incoming.trim().to_string();
    }
    let current_tokens: Vec<&str> = incoming.split_whitespace().collect();
    if current_tokens.is_empty() {
        return String::new();
    }
    let previous_tokens: Vec<&str> = existing.split_whitespace().collect();
    let max_window = previous_tokens.len().min(current_tokens.len()).min(80);
    if max_window < 5 {
        return incoming.trim().to_string();
    }
    let previous_norm: Vec<String> = previous_tokens[previous_tokens.len() - max_window..]
        .iter()
        .map(|token| normalize_audio_token(token))
        .collect();
    let current_norm: Vec<String> = current_tokens[..max_window]
        .iter()
        .map(|token| normalize_audio_token(token))
        .collect();
    for match_len in (5..=max_window).rev() {
        if previous_norm[max_window - match_len..] == current_norm[..match_len] {
            return current_tokens[match_len..].join(" ").trim().to_string();
        }
    }
    incoming.trim().to_string()
}

fn which_binary(name: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| {
            std::env::split_paths(&paths).any(|path| {
                let candidate = path.join(name);
                let executable = candidate.is_file();
                if executable {
                    return true;
                }
                #[cfg(windows)]
                {
                    return path.join(format!("{name}.exe")).is_file();
                }
                #[cfg(not(windows))]
                {
                    false
                }
            })
        })
        .unwrap_or(false)
}

fn ensure_media_tools() -> Result<(), String> {
    let missing: Vec<&str> = ["ffmpeg", "ffprobe"]
        .into_iter()
        .filter(|name| !which_binary(name))
        .collect();
    if missing.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "Long-form transcription requires {}. Install ffmpeg/ffprobe and retry.",
            missing.join(", ")
        ))
    }
}

async fn run_media_command(
    program: &str,
    args: &[String],
    timeout_sec: u64,
) -> Result<String, String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::null());
    let output = timeout(Duration::from_secs(timeout_sec), command.output())
        .await
        .map_err(|_| format!("{program} timed out after {timeout_sec}s"))?
        .map_err(|error| format!("Media tooling not available: {program}: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(format!(
            "{program} failed: {}",
            if !stderr.is_empty() {
                stderr
            } else if !stdout.is_empty() {
                stdout
            } else {
                "unknown error".to_string()
            }
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

async fn probe_media_duration(path: &Path, timeout_sec: u64) -> Result<f64, String> {
    let stdout = run_media_command(
        "ffprobe",
        &[
            "-v".to_string(),
            "error".to_string(),
            "-print_format".to_string(),
            "json".to_string(),
            "-show_format".to_string(),
            path.display().to_string(),
        ],
        timeout_sec,
    )
    .await?;
    let parsed: Value = serde_json::from_str(&stdout)
        .map_err(|error| format!("ffprobe returned invalid JSON: {error}"))?;
    let duration_value = parsed
        .get("format")
        .and_then(Value::as_object)
        .and_then(|format| format.get("duration"))
        .cloned()
        .ok_or_else(|| {
            format!(
                "ffprobe did not return a valid duration for {}",
                path.display()
            )
        })?;
    let parsed_duration = match duration_value {
        Value::String(value) => value
            .parse::<f64>()
            .map_err(|error| format!("ffprobe did not return a valid duration: {error}"))?,
        Value::Number(value) => value
            .as_f64()
            .ok_or_else(|| "ffprobe did not return a valid numeric duration".to_string())?,
        _ => {
            return Err(format!(
                "ffprobe did not return a valid duration for {}",
                path.display()
            ));
        }
    };
    if parsed_duration <= 0.0 {
        return Err(format!(
            "ffprobe reported non-positive duration for {}",
            path.display()
        ));
    }
    Ok(parsed_duration)
}

async fn extract_audio_source(
    source: &Path,
    output: &Path,
    timeout_sec: u64,
) -> Result<(), String> {
    run_media_command(
        "ffmpeg",
        &[
            "-nostdin".to_string(),
            "-y".to_string(),
            "-i".to_string(),
            source.display().to_string(),
            "-vn".to_string(),
            "-ac".to_string(),
            "1".to_string(),
            "-ar".to_string(),
            "16000".to_string(),
            "-c:a".to_string(),
            "pcm_s16le".to_string(),
            output.display().to_string(),
        ],
        timeout_sec,
    )
    .await
    .map(|_| ())
}

async fn extract_audio_chunk(
    source: &Path,
    output: &Path,
    start_sec: f64,
    duration_sec: f64,
    timeout_sec: u64,
) -> Result<(), String> {
    run_media_command(
        "ffmpeg",
        &[
            "-nostdin".to_string(),
            "-y".to_string(),
            "-ss".to_string(),
            format!("{start_sec:.3}"),
            "-i".to_string(),
            source.display().to_string(),
            "-t".to_string(),
            format!("{duration_sec:.3}"),
            "-vn".to_string(),
            "-ac".to_string(),
            "1".to_string(),
            "-ar".to_string(),
            "16000".to_string(),
            "-c:a".to_string(),
            "pcm_s16le".to_string(),
            output.display().to_string(),
        ],
        timeout_sec,
    )
    .await
    .map(|_| ())
}

fn audio_chunk_seconds_budget(max_bytes: usize, requested_seconds: f64) -> Result<f64, String> {
    let safe_seconds =
        (max_bytes as f64 * AUDIO_CHUNK_TARGET_FILL_RATIO) / AUDIO_CHUNK_BYTES_PER_SECOND;
    if safe_seconds <= 0.0 {
        return Err("Mistral transcription max-bytes budget is too small to chunk audio".into());
    }
    Ok(requested_seconds.min(safe_seconds))
}

fn plan_audio_chunks(
    duration_sec: f64,
    chunk_seconds: f64,
    overlap_seconds: f64,
    max_chunks: i64,
) -> Result<Vec<ChunkPlan>, String> {
    if duration_sec <= 0.0 {
        return Err("Cannot chunk media with non-positive duration".into());
    }
    let chunk_seconds = chunk_seconds.max(1.0);
    let overlap_seconds = overlap_seconds
        .max(0.0)
        .min((chunk_seconds - 0.001).max(0.0));
    let mut chunks = Vec::new();
    let mut start = 0.0;
    while start < duration_sec - 1e-6 {
        let end = (start + chunk_seconds).min(duration_sec);
        let index = chunks.len();
        chunks.push(ChunkPlan {
            index,
            start_sec: (start * 1000.0).round() / 1000.0,
            end_sec: (end * 1000.0).round() / 1000.0,
            duration_sec: ((end - start) * 1000.0).round() / 1000.0,
            leading_overlap_sec: if index == 0 {
                0.0
            } else {
                (overlap_seconds * 1000.0).round() / 1000.0
            },
        });
        if chunks.len() as i64 > max_chunks {
            return Err(format!(
                "Chunk plan would create {} chunks (max {max_chunks})",
                chunks.len()
            ));
        }
        if end >= duration_sec - 1e-6 {
            break;
        }
        let mut next_start = end - overlap_seconds;
        if next_start <= start + 1e-6 {
            next_start = end;
        }
        start = next_start;
    }
    Ok(chunks)
}

fn entry_time_bounds(entry: &Map<String, Value>) -> Option<(f64, f64)> {
    if let (Some(start), Some(end)) = (
        entry.get("start").and_then(Value::as_f64),
        entry.get("end").and_then(Value::as_f64),
    ) {
        return Some((start, end));
    }
    let timestamps = entry.get("timestamps")?.as_array()?;
    if timestamps.len() < 2 {
        return None;
    }
    Some((timestamps[0].as_f64()?, timestamps[1].as_f64()?))
}

fn set_entry_time_bounds(entry: &mut Map<String, Value>, start: f64, end: f64) {
    if entry.contains_key("start") || entry.contains_key("end") {
        entry.insert("start".into(), json!(((start * 1000.0).round() / 1000.0)));
        entry.insert("end".into(), json!(((end * 1000.0).round() / 1000.0)));
    } else if let Some(timestamps) = entry.get_mut("timestamps").and_then(Value::as_array_mut) {
        while timestamps.len() < 2 {
            timestamps.push(json!(0.0));
        }
        timestamps[0] = json!(((start * 1000.0).round() / 1000.0));
        timestamps[1] = json!(((end * 1000.0).round() / 1000.0));
    }
}

fn prefix_audio_speakers(value: &Value, prefix: &str) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| prefix_audio_speakers(item, prefix))
                .collect(),
        ),
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, item)| {
                    let value = if SPEAKER_FIELDS.contains(&key.as_str()) {
                        item.as_str()
                            .map(|speaker| Value::String(format!("{prefix}{speaker}")))
                            .unwrap_or_else(|| prefix_audio_speakers(item, prefix))
                    } else {
                        prefix_audio_speakers(item, prefix)
                    };
                    (key.clone(), value)
                })
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn shift_audio_items(
    items: &[Value],
    chunk_start_sec: f64,
    leading_overlap_sec: f64,
    speaker_prefix: &str,
) -> Vec<Value> {
    let mut shifted = Vec::new();
    for item in items {
        let mut copied = prefix_audio_speakers(item, speaker_prefix);
        if let Some(object) = copied.as_object_mut() {
            if let Some((mut start, end)) = entry_time_bounds(object) {
                if end <= leading_overlap_sec + 1e-6 {
                    continue;
                }
                if start < leading_overlap_sec {
                    start = leading_overlap_sec;
                }
                set_entry_time_bounds(object, start + chunk_start_sec, end + chunk_start_sec);
            }
        }
        shifted.push(copied);
    }
    shifted
}

fn collect_chunk_metadata(
    parsed: &Value,
    chunk_start_sec: f64,
    leading_overlap_sec: f64,
    speaker_prefix: &str,
) -> Map<String, Value> {
    let mut aggregated = Map::new();
    if let Some(items) = parsed.get("segments").and_then(Value::as_array) {
        aggregated.insert(
            "segments".into(),
            Value::Array(shift_audio_items(
                items,
                chunk_start_sec,
                leading_overlap_sec,
                speaker_prefix,
            )),
        );
    } else if let Some(items) = parsed.get("chunks").and_then(Value::as_array) {
        aggregated.insert(
            "segments".into(),
            Value::Array(shift_audio_items(
                items,
                chunk_start_sec,
                leading_overlap_sec,
                speaker_prefix,
            )),
        );
    }
    if let Some(items) = parsed.get("words").and_then(Value::as_array) {
        aggregated.insert(
            "words".into(),
            Value::Array(shift_audio_items(
                items,
                chunk_start_sec,
                leading_overlap_sec,
                speaker_prefix,
            )),
        );
    }
    if let Some(items) = parsed.get("diarization").and_then(Value::as_array) {
        aggregated.insert(
            "diarization".into(),
            Value::Array(shift_audio_items(
                items,
                chunk_start_sec,
                leading_overlap_sec,
                speaker_prefix,
            )),
        );
    }
    aggregated
}

fn truncate_audio_text(payload: &mut Value, max_chars: usize) {
    let original = payload
        .get("text")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if original.is_empty() {
        return;
    }
    let mut base = payload.clone();
    base["text"] = Value::String(String::new());
    if json_length(&base) > max_chars {
        payload["text"] = Value::String(String::new());
        payload["truncation"]["text_truncated_chars"] = json!(original.len());
        return;
    }

    let mut low = 0usize;
    let mut high = original.len();
    while low < high {
        let mid = (low + high + 1) / 2;
        let idx = original.floor_char_boundary(mid);
        base["text"] = Value::String(original[..idx].to_string());
        if json_length(&base) <= max_chars {
            low = idx;
        } else if idx == 0 {
            high = 0;
        } else {
            high = idx - 1;
        }
    }
    let final_idx = original.floor_char_boundary(low);
    payload["text"] = Value::String(original[..final_idx].to_string());
    let omitted = original.len().saturating_sub(final_idx);
    if omitted > 0 {
        payload["truncation"]["text_truncated_chars"] = json!(omitted);
    }
}

fn serialize_audio_envelope(mut payload: Value, max_chars: usize) -> String {
    if payload.get("truncation").is_none() {
        payload["truncation"] = json!({"applied": false});
    }
    if json_length(&payload) <= max_chars {
        return serde_json::to_string_pretty(&payload).unwrap_or_else(|_| payload.to_string());
    }

    payload["truncation"]["applied"] = Value::Bool(true);
    let mode = payload
        .get("mode")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();

    let mut omitted_response_fields = Map::new();
    let mut removal_order = vec!["words", "diarization", "segments"];
    if mode != "chunked" {
        removal_order.push("chunks");
    }
    for key in removal_order {
        let removed = payload
            .get_mut("response")
            .and_then(Value::as_object_mut)
            .and_then(|response| response.remove(key));
        if let Some(value) = removed {
            if let Some(items) = value.as_array() {
                if !items.is_empty() {
                    omitted_response_fields.insert(key.into(), json!(items.len()));
                }
            }
            if json_length(&payload) <= max_chars {
                break;
            }
        }
    }
    if !omitted_response_fields.is_empty() {
        payload["truncation"]["omitted_response_fields"] = Value::Object(omitted_response_fields);
    }

    if mode == "chunked" && json_length(&payload) > max_chars {
        let omitted = payload
            .get_mut("response")
            .and_then(Value::as_object_mut)
            .and_then(|response| response.get_mut("chunks"))
            .and_then(Value::as_array_mut)
            .map(|chunks| {
                let keep = chunks.len().min(12);
                let omitted = chunks.len().saturating_sub(keep);
                if omitted > 0 {
                    chunks.truncate(keep);
                }
                omitted
            })
            .unwrap_or(0);
        if omitted > 0 {
            payload["truncation"]["omitted_chunk_statuses"] = json!(omitted);
        }
    }

    if json_length(&payload) > max_chars {
        truncate_audio_text(&mut payload, max_chars);
    }

    if json_length(&payload) > max_chars {
        while json_length(&payload) > max_chars {
            let popped = payload
                .get_mut("response")
                .and_then(Value::as_object_mut)
                .and_then(|response| response.get_mut("chunks"))
                .and_then(Value::as_array_mut)
                .map(|chunks| {
                    if chunks.len() > 3 {
                        chunks.pop();
                        true
                    } else {
                        false
                    }
                })
                .unwrap_or(false);
            if !popped {
                break;
            }
            let current = payload["truncation"]
                .get("omitted_chunk_statuses")
                .and_then(Value::as_u64)
                .unwrap_or(0);
            payload["truncation"]["omitted_chunk_statuses"] = json!(current + 1);
        }
    }

    if json_length(&payload) > max_chars {
        if let Some(options) = payload.get_mut("options").and_then(Value::as_object_mut) {
            if let Some(context_bias) = options.remove("context_bias") {
                if let Some(items) = context_bias.as_array() {
                    payload["truncation"]["omitted_context_bias_phrases"] = json!(items.len());
                }
            }
        }
    }

    serde_json::to_string_pretty(&payload).unwrap_or_else(|_| payload.to_string())
}

async fn mistral_transcription_request(
    api_key: &str,
    base_url: &str,
    resolved: &Path,
    model: &str,
    diarize: Option<bool>,
    timestamp_granularities: Option<&[String]>,
    context_bias: Option<&[String]>,
    language: Option<&str>,
    temperature: Option<f64>,
    max_bytes: usize,
    request_timeout_sec: u64,
) -> Result<Value, String> {
    let metadata = std::fs::metadata(resolved).map_err(|error| {
        format!(
            "Failed to inspect audio file {}: {error}",
            resolved.display()
        )
    })?;
    if metadata.len() as usize > max_bytes {
        return Err(format!(
            "Audio file too large: {} bytes (max {} bytes)",
            metadata.len(),
            max_bytes
        ));
    }
    let bytes = std::fs::read(resolved)
        .map_err(|error| format!("Failed to read audio file {}: {error}", resolved.display()))?;
    let filename = resolved
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("audio");
    let mut form = Form::new()
        .text("model", model.to_string())
        .text("stream", "false")
        .part(
            "file",
            Part::bytes(bytes)
                .file_name(filename.to_string())
                .mime_str(audio_media_type(resolved))
                .expect("audio_media_type always returns a valid MIME type"),
        );
    if let Some(value) = diarize {
        form = form.text("diarize", if value { "true" } else { "false" });
    }
    if let Some(value) = language.filter(|value| !value.trim().is_empty()) {
        form = form.text("language", value.to_string());
    }
    if let Some(value) = temperature {
        form = form.text("temperature", value.to_string());
    }
    if let Some(values) = timestamp_granularities {
        for value in values {
            form = form.text("timestamp_granularities", value.clone());
        }
    }
    if let Some(values) = context_bias {
        for value in values {
            form = form.text("context_bias", value.clone());
        }
    }

    let client = reqwest::Client::new();
    let response = client
        .post(transcription_endpoint(base_url))
        .bearer_auth(api_key)
        .timeout(Duration::from_secs(request_timeout_sec))
        .multipart(form)
        .send()
        .await
        .map_err(|error| format!("Mistral transcription request failed: {error}"))?;
    let status = response.status();
    let raw = response
        .text()
        .await
        .map_err(|error| format!("Mistral transcription returned unreadable body: {error}"))?;
    if !status.is_success() {
        return Err(format!(
            "Mistral transcription HTTP {}: {}",
            status.as_u16(),
            raw
        ));
    }
    serde_json::from_str(&raw).map_err(|error| {
        format!(
            "Mistral transcription returned non-JSON payload: {error}: {}",
            filesystem::clip(&raw, 500)
        )
    })
}

#[allow(clippy::too_many_arguments)]
pub async fn audio_transcribe(
    root: &Path,
    api_key: Option<&str>,
    base_url: &str,
    default_model: &str,
    max_bytes: usize,
    default_chunk_max_seconds: i64,
    default_chunk_overlap_seconds: f64,
    default_max_chunks: i64,
    path: &str,
    diarize: Option<bool>,
    timestamp_granularities: Option<&[String]>,
    context_bias: Option<&[String]>,
    language: Option<&str>,
    model: Option<&str>,
    temperature: Option<f64>,
    chunking: Option<&str>,
    chunk_max_seconds: Option<i64>,
    chunk_overlap_seconds: Option<f64>,
    max_chunks: Option<i64>,
    continue_on_chunk_error: Option<bool>,
    max_chars: usize,
    command_timeout_sec: u64,
    request_timeout_sec: u64,
    files_read: &mut HashSet<PathBuf>,
) -> ToolResult {
    let resolved = match filesystem::resolve_path(root, path) {
        Ok(value) => value,
        Err(error) => return ToolResult::error(error),
    };
    if !resolved.exists() {
        return ToolResult::error(format!("File not found: {path}"));
    }
    if resolved.is_dir() {
        return ToolResult::error(format!("Path is a directory, not a file: {path}"));
    }
    let ext = resolved
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| format!(".{}", value.to_ascii_lowercase()))
        .unwrap_or_default();
    if !is_supported_extension(&ext) {
        let mut supported: Vec<&str> = AUDIO_EXTENSIONS.iter().copied().collect();
        supported.extend(VIDEO_EXTENSIONS.iter().copied());
        supported.sort_unstable();
        return ToolResult::error(format!(
            "Unsupported audio format: {}. Supported: {}",
            if ext.is_empty() { "(none)" } else { &ext },
            supported.join(", ")
        ));
    }
    if language.is_some() && timestamp_granularities.is_some() {
        return ToolResult::error(
            "language cannot be combined with timestamp_granularities for Mistral offline transcription"
                .into(),
        );
    }
    let chunk_mode = chunking.unwrap_or("auto").trim().to_ascii_lowercase();
    if !CHUNKING_MODES.iter().any(|value| *value == chunk_mode) {
        return ToolResult::error("chunking must be one of auto, off, or force".into());
    }
    if chunk_max_seconds
        .map(|value| {
            !(AUDIO_MIN_CHUNK_SECONDS as i64..=AUDIO_MAX_CHUNK_SECONDS as i64).contains(&value)
        })
        .unwrap_or(false)
    {
        return ToolResult::error(format!(
            "chunk_max_seconds must be between {} and {}",
            AUDIO_MIN_CHUNK_SECONDS as i64, AUDIO_MAX_CHUNK_SECONDS as i64
        ));
    }
    if chunk_overlap_seconds
        .map(|value| !(0.0..=AUDIO_MAX_CHUNK_OVERLAP_SECONDS).contains(&value))
        .unwrap_or(false)
    {
        return ToolResult::error(format!(
            "chunk_overlap_seconds must be between 0 and {}",
            AUDIO_MAX_CHUNK_OVERLAP_SECONDS as i64
        ));
    }
    if max_chunks
        .map(|value| !(1..=AUDIO_MAX_CHUNKS).contains(&value))
        .unwrap_or(false)
    {
        return ToolResult::error(format!(
            "max_chunks must be between 1 and {AUDIO_MAX_CHUNKS}"
        ));
    }

    let api_key = match api_key {
        Some(value) if !value.trim().is_empty() => value,
        _ => return ToolResult::error("Mistral transcription API key not configured".into()),
    };
    let chosen_model = model.unwrap_or(default_model).trim();
    if chosen_model.is_empty() {
        return ToolResult::error("No Mistral transcription model configured".into());
    }
    let normalized_timestamps = timestamp_granularities.map(|values| {
        values
            .iter()
            .map(|value| value.trim().to_ascii_lowercase())
            .filter(|value| !value.is_empty())
            .collect::<Vec<_>>()
    });
    if normalized_timestamps.as_ref().is_some_and(|values| {
        values
            .iter()
            .any(|value| !TIMESTAMP_GRANULARITIES.contains(&value.as_str()))
    }) {
        return ToolResult::error(format!(
            "timestamp_granularities must be drawn from {}",
            TIMESTAMP_GRANULARITIES.join(", ")
        ));
    }
    let normalized_bias = context_bias.map(|values| {
        values
            .iter()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .collect::<Vec<_>>()
    });
    if normalized_bias
        .as_ref()
        .is_some_and(|values| values.len() > 100)
    {
        return ToolResult::error("context_bias supports at most 100 phrases".into());
    }

    let options = build_options(
        diarize,
        normalized_timestamps.as_deref(),
        normalized_bias.as_deref(),
        language,
        temperature,
        &chunk_mode,
        chunk_max_seconds,
        chunk_overlap_seconds,
        max_chunks,
        continue_on_chunk_error,
    );

    let temp_dir = match TempAudioDir::new() {
        Ok(value) => value,
        Err(error) => return ToolResult::error(error),
    };
    let mut upload_source = resolved.clone();
    if is_video_extension(&ext) {
        if let Err(error) = ensure_media_tools() {
            return ToolResult::error(error);
        }
        let extracted = temp_dir.path.join("video-source.wav");
        if let Err(error) = extract_audio_source(&resolved, &extracted, command_timeout_sec).await {
            return ToolResult::error(error);
        }
        upload_source = extracted;
    }

    let upload_size = match std::fs::metadata(&upload_source) {
        Ok(value) => value.len() as usize,
        Err(error) => {
            return ToolResult::error(format!(
                "Failed to inspect audio file {}: {error}",
                upload_source.display()
            ));
        }
    };
    files_read.insert(resolved.clone());

    let chunk_requested =
        chunk_mode == "force" || (chunk_mode == "auto" && upload_size > max_bytes);

    if !chunk_requested {
        let parsed = match mistral_transcription_request(
            api_key,
            base_url,
            &upload_source,
            chosen_model,
            diarize,
            normalized_timestamps.as_deref(),
            normalized_bias.as_deref(),
            language,
            temperature,
            max_bytes,
            request_timeout_sec,
        )
        .await
        {
            Ok(value) => value,
            Err(error) => return ToolResult::error(error),
        };
        let envelope = json!({
            "provider": "mistral",
            "service": "transcription",
            "path": rel_path(root, &resolved),
            "model": chosen_model,
            "options": options,
            "text": parsed.get("text").and_then(Value::as_str).unwrap_or_default(),
            "response": parsed,
        });
        return ToolResult::ok(serialize_audio_envelope(envelope, max_chars));
    }

    if let Err(error) = ensure_media_tools() {
        return ToolResult::error(error);
    }

    let duration_sec = match probe_media_duration(&upload_source, command_timeout_sec).await {
        Ok(value) => value,
        Err(error) => return ToolResult::error(error),
    };
    let requested_chunk_seconds = (chunk_max_seconds.unwrap_or(default_chunk_max_seconds) as f64)
        .min(AUDIO_MAX_CHUNK_SECONDS);
    let effective_chunk_seconds =
        match audio_chunk_seconds_budget(max_bytes, requested_chunk_seconds) {
            Ok(value) => value,
            Err(error) => return ToolResult::error(error),
        };
    let effective_overlap_seconds = chunk_overlap_seconds
        .unwrap_or(default_chunk_overlap_seconds)
        .min((effective_chunk_seconds - 0.001).max(0.0));
    let effective_max_chunks = max_chunks.unwrap_or(default_max_chunks);
    let chunk_plan = match plan_audio_chunks(
        duration_sec,
        effective_chunk_seconds,
        effective_overlap_seconds,
        effective_max_chunks,
    ) {
        Ok(value) => value,
        Err(error) => return ToolResult::error(error),
    };

    let mut chunk_statuses: Vec<Value> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();
    let mut stitched_text = String::new();
    let mut aggregated_response = Map::new();
    aggregated_response.insert(
        "speaker_scope".into(),
        Value::String(if diarize.unwrap_or(false) {
            "chunk_local_prefixed".into()
        } else {
            "not_requested".into()
        }),
    );
    aggregated_response.insert("chunks".into(), Value::Array(Vec::new()));
    let mut partial = false;
    let continue_on_chunk_error = continue_on_chunk_error.unwrap_or(false);

    for chunk in &chunk_plan {
        let chunk_path = temp_dir.path.join(format!("chunk-{:03}.wav", chunk.index));
        if let Err(error) = extract_audio_chunk(
            &upload_source,
            &chunk_path,
            chunk.start_sec,
            chunk.duration_sec,
            command_timeout_sec,
        )
        .await
        {
            partial = true;
            chunk_statuses.push(json!({
                "index": chunk.index,
                "start_sec": chunk.start_sec,
                "end_sec": chunk.end_sec,
                "status": "error",
                "error": error,
            }));
            if continue_on_chunk_error {
                warnings.push(format!("chunk {} failed: {error}", chunk.index));
                continue;
            }
            return ToolResult::error(format!(
                "audio_transcribe failed in chunk {}: {error}",
                chunk.index
            ));
        }

        let parsed = match mistral_transcription_request(
            api_key,
            base_url,
            &chunk_path,
            chosen_model,
            diarize,
            normalized_timestamps.as_deref(),
            normalized_bias.as_deref(),
            language,
            temperature,
            max_bytes,
            request_timeout_sec,
        )
        .await
        {
            Ok(value) => value,
            Err(error) => {
                partial = true;
                chunk_statuses.push(json!({
                    "index": chunk.index,
                    "start_sec": chunk.start_sec,
                    "end_sec": chunk.end_sec,
                    "status": "error",
                    "error": error,
                }));
                if continue_on_chunk_error {
                    warnings.push(format!("chunk {} failed: {error}", chunk.index));
                    continue;
                }
                return ToolResult::error(format!(
                    "audio_transcribe failed in chunk {}: {error}",
                    chunk.index
                ));
            }
        };

        let chunk_text = parsed
            .get("text")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let deduped_text = dedupe_audio_overlap_text(&stitched_text, chunk_text);
        if !deduped_text.is_empty() {
            if stitched_text.is_empty() {
                stitched_text = deduped_text;
            } else {
                stitched_text = format!("{stitched_text} {deduped_text}");
            }
        }

        let metadata = collect_chunk_metadata(
            &parsed,
            chunk.start_sec,
            chunk.leading_overlap_sec,
            &format!("c{}_", chunk.index),
        );
        for (key, value) in metadata {
            if let Some(existing) = aggregated_response
                .get_mut(&key)
                .and_then(Value::as_array_mut)
            {
                if let Some(items) = value.as_array() {
                    existing.extend(items.iter().cloned());
                }
            } else {
                aggregated_response.insert(key, value);
            }
        }

        chunk_statuses.push(json!({
            "index": chunk.index,
            "start_sec": chunk.start_sec,
            "end_sec": chunk.end_sec,
            "status": "ok",
            "text_chars": chunk_text.len(),
        }));
    }

    if !chunk_statuses
        .iter()
        .any(|chunk| chunk.get("status").and_then(Value::as_str) == Some("ok"))
    {
        return ToolResult::error(
            "audio_transcribe failed: no chunk completed successfully".into(),
        );
    }

    aggregated_response.insert("chunks".into(), Value::Array(chunk_statuses.clone()));
    let mut envelope = json!({
        "provider": "mistral",
        "service": "transcription",
        "mode": "chunked",
        "path": rel_path(root, &resolved),
        "model": chosen_model,
        "options": options,
        "chunking": {
            "strategy": "overlap_window",
            "chunk_seconds": ((effective_chunk_seconds * 1000.0).round() / 1000.0),
            "overlap_seconds": ((effective_overlap_seconds * 1000.0).round() / 1000.0),
            "total_chunks": chunk_plan.len(),
            "failed_chunks": chunk_statuses.iter().filter(|chunk| {
                chunk.get("status").and_then(Value::as_str) != Some("ok")
            }).count(),
            "partial": partial,
        },
        "text": stitched_text.trim(),
        "response": Value::Object(aggregated_response),
    });
    if !warnings.is_empty() {
        envelope["warnings"] = Value::Array(warnings.into_iter().map(Value::String).collect());
    }
    ToolResult::ok(serialize_audio_envelope(envelope, max_chars))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{Json, Router, body::Bytes, routing::post};
    use std::sync::{Arc, Mutex};
    use tempfile::tempdir;
    use tokio::net::TcpListener;

    async fn capture_transcription(body: Bytes) -> Json<Value> {
        Json(json!({
            "text": "hello world",
            "chunks": [{"text": "hello world", "timestamps": [0.0, 1.0]}],
            "raw_body": String::from_utf8_lossy(&body).to_string(),
        }))
    }

    async fn spawn_server() -> String {
        let app = Router::new().route("/v1/audio/transcriptions", post(capture_transcription));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        format!("http://{}", addr)
    }

    fn install_fake_media_tools(root: &Path) {
        let ffprobe = root.join("ffprobe");
        let ffmpeg = root.join("ffmpeg");
        std::fs::write(
            &ffprobe,
            "#!/bin/sh\nprintf '{\"format\":{\"duration\":\"50.0\"}}'\n",
        )
        .unwrap();
        std::fs::write(
            &ffmpeg,
            "#!/bin/sh\nout=\"\"\nfor arg in \"$@\"; do out=\"$arg\"; done\nprintf 'chunk' > \"$out\"\n",
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&ffprobe, std::fs::Permissions::from_mode(0o755)).unwrap();
            std::fs::set_permissions(&ffmpeg, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
    }

    fn install_budget_sensitive_media_tools(root: &Path, duration_seconds: f64) {
        let ffprobe = root.join("ffprobe");
        let ffmpeg = root.join("ffmpeg");
        std::fs::write(
            &ffprobe,
            format!("#!/bin/sh\nprintf '{{\"format\":{{\"duration\":\"{duration_seconds}\"}}}}'\n"),
        )
        .unwrap();
        std::fs::write(
            &ffmpeg,
            "#!/bin/sh\nout=\"\"\nduration=\"\"\nprev=\"\"\nfor arg in \"$@\"; do\n  if [ \"$prev\" = \"-t\" ]; then duration=\"$arg\"; fi\n  prev=\"$arg\"\n  out=\"$arg\"\ndone\nif [ -n \"$duration\" ]; then\n  bytes=$(awk \"BEGIN { printf \\\"%d\\\", $duration * 32000 }\")\n  dd if=/dev/zero of=\"$out\" bs=1 count=\"$bytes\" status=none\nelse\n  printf 'chunk' > \"$out\"\nfi\n",
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&ffprobe, std::fs::Permissions::from_mode(0o755)).unwrap();
            std::fs::set_permissions(&ffmpeg, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
    }

    #[tokio::test]
    async fn test_audio_transcribe_success() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("clip.wav");
        std::fs::write(&audio, b"RIFF\x00\x00\x00\x00WAVEfmt ").unwrap();
        let root = dir.path().to_path_buf();
        let base_url = spawn_server().await;
        let mut files_read = HashSet::new();

        let result = audio_transcribe(
            &root,
            Some("mistral-key"),
            &base_url,
            "voxtral-mini-latest",
            1024 * 1024,
            900,
            2.0,
            48,
            "clip.wav",
            Some(true),
            Some(&["segment".to_string()]),
            Some(&["OpenPlanter".to_string()]),
            None,
            None,
            Some(0.2),
            None,
            None,
            None,
            None,
            None,
            20_000,
            5,
            5,
            &mut files_read,
        )
        .await;

        assert!(!result.is_error, "unexpected error: {}", result.content);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["provider"], "mistral");
        assert_eq!(parsed["path"], "clip.wav");
        assert_eq!(parsed["text"], "hello world");
        assert_eq!(parsed["options"]["diarize"], true);
        let raw_body = parsed["response"]["raw_body"].as_str().unwrap();
        assert!(raw_body.contains("name=\"model\""));
        assert!(raw_body.contains("name=\"timestamp_granularities\""));
        assert!(raw_body.contains("name=\"context_bias\""));
    }

    #[tokio::test]
    async fn test_audio_transcribe_rejects_language_and_timestamps() {
        let dir = tempdir().unwrap();
        let audio = dir.path().join("clip.wav");
        std::fs::write(&audio, b"RIFF\x00\x00\x00\x00WAVEfmt ").unwrap();
        let root = dir.path().to_path_buf();
        let mut files_read = HashSet::new();

        let result = audio_transcribe(
            &root,
            Some("mistral-key"),
            "https://api.mistral.ai",
            "voxtral-mini-latest",
            1024 * 1024,
            900,
            2.0,
            48,
            "clip.wav",
            None,
            Some(&["word".to_string()]),
            None,
            Some("en"),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            20_000,
            5,
            5,
            &mut files_read,
        )
        .await;

        assert!(result.is_error);
        assert!(result.content.contains("cannot be combined"));
    }

    #[tokio::test]
    async fn test_audio_transcribe_chunks_oversize_audio() {
        let dir = tempdir().unwrap();
        install_fake_media_tools(dir.path());
        let original_path = std::env::var_os("PATH");
        unsafe {
            let mut parts = vec![dir.path().to_path_buf()];
            if let Some(existing) = &original_path {
                parts.extend(std::env::split_paths(existing));
            }
            std::env::set_var("PATH", std::env::join_paths(parts).unwrap());
        }

        let counter = Arc::new(Mutex::new(0usize));
        let counter_clone = counter.clone();
        let app = Router::new().route(
            "/v1/audio/transcriptions",
            post(move |_body: Bytes| {
                let counter = counter_clone.clone();
                async move {
                    let mut state = counter.lock().unwrap();
                    let response = if *state == 0 {
                        json!({
                            "text": "hello there general kenobi from tatooine",
                            "segments": [{"text":"hello there general kenobi from tatooine","start":0.0,"end":4.0,"speaker":"speaker_a"}]
                        })
                    } else {
                        json!({
                            "text": "there general kenobi from tatooine today",
                            "segments": [{"text":"there general kenobi from tatooine today","start":0.0,"end":4.0,"speaker":"speaker_a"}]
                        })
                    };
                    *state += 1;
                    Json(response)
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let audio = dir.path().join("clip.wav");
        std::fs::write(&audio, vec![b'x'; 1_200_000]).unwrap();
        let root = dir.path().to_path_buf();
        let mut files_read = HashSet::new();

        let result = audio_transcribe(
            &root,
            Some("mistral-key"),
            &format!("http://{}", addr),
            "voxtral-mini-latest",
            1_100_000,
            900,
            2.0,
            48,
            "clip.wav",
            Some(true),
            None,
            None,
            None,
            None,
            None,
            Some("auto"),
            Some(30),
            Some(2.0),
            None,
            None,
            20_000,
            5,
            5,
            &mut files_read,
        )
        .await;

        if let Some(value) = original_path {
            unsafe { std::env::set_var("PATH", value) };
        }

        assert!(!result.is_error, "unexpected error: {}", result.content);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["mode"], "chunked");
        assert_eq!(
            parsed["text"],
            "hello there general kenobi from tatooine today"
        );
        assert_eq!(parsed["chunking"]["total_chunks"], 2);
        assert_eq!(parsed["response"]["segments"][0]["speaker"], "c0_speaker_a");
        assert_eq!(parsed["response"]["segments"][1]["speaker"], "c1_speaker_a");
    }

    #[tokio::test]
    async fn test_audio_transcribe_preserves_byte_budgeted_chunk_size() {
        let dir = tempdir().unwrap();
        install_budget_sensitive_media_tools(dir.path(), 35.0);
        let original_path = std::env::var_os("PATH");
        unsafe {
            let mut parts = vec![dir.path().to_path_buf()];
            if let Some(existing) = &original_path {
                parts.extend(std::env::split_paths(existing));
            }
            std::env::set_var("PATH", std::env::join_paths(parts).unwrap());
        }

        let counter = Arc::new(Mutex::new(0usize));
        let counter_clone = counter.clone();
        let app = Router::new().route(
            "/v1/audio/transcriptions",
            post(move |_body: Bytes| {
                let counter = counter_clone.clone();
                async move {
                    let mut state = counter.lock().unwrap();
                    *state += 1;
                    Json(json!({
                        "text": format!("chunk {}", *state),
                    }))
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let audio = dir.path().join("clip.wav");
        std::fs::write(&audio, vec![b'x'; 512]).unwrap();
        let root = dir.path().to_path_buf();
        let mut files_read = HashSet::new();

        let result = audio_transcribe(
            &root,
            Some("mistral-key"),
            &format!("http://{}", addr),
            "voxtral-mini-latest",
            300_000,
            900,
            0.0,
            48,
            "clip.wav",
            None,
            None,
            None,
            None,
            None,
            None,
            Some("force"),
            Some(30),
            Some(0.0),
            None,
            None,
            20_000,
            5,
            5,
            &mut files_read,
        )
        .await;

        if let Some(value) = original_path {
            unsafe { std::env::set_var("PATH", value) };
        }

        assert!(!result.is_error, "unexpected error: {}", result.content);
        let parsed: Value = serde_json::from_str(&result.content).unwrap();
        assert_eq!(parsed["mode"], "chunked");
        assert!(parsed["chunking"]["chunk_seconds"].as_f64().unwrap() < 30.0);
        assert!(parsed["chunking"]["total_chunks"].as_u64().unwrap() >= 5);
    }
}
