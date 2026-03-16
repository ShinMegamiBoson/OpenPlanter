from __future__ import annotations

import ast
import base64
import copy
import fnmatch
import html as _html
import json
import mimetypes
import os
import signal
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import re as _re
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_MAX_WALK_ENTRIES = 50_000

from .patching import (
    AddFileOp,
    DeleteFileOp,
    PatchApplyError,
    UpdateFileOp,
    apply_agent_patch,
    parse_agent_patch,
)

_WS_RE = _re.compile(r"\s+")
_HASHLINE_PREFIX_RE = _re.compile(r"^\d+:[0-9a-f]{2}\|")
_HEREDOC_RE = _re.compile(r"<<-?\s*['\"]?\w+['\"]?")
_INTERACTIVE_RE = _re.compile(r"(^|[;&|]\s*)(vim|nano|less|more|top|htop|man)\b")
_TOKEN_NORMALIZE_RE = _re.compile(r"[^a-z0-9]+")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = True
            return
        if lowered in {"article", "br", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "p", "section", "td", "th", "tr"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = False
            return
        if lowered in {"article", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "p", "section", "td", "th", "tr"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)

    def title(self) -> str:
        return _WS_RE.sub(" ", _html.unescape("".join(self._title_parts))).strip()

    def text(self) -> str:
        return _WS_RE.sub(" ", _html.unescape(" ".join(self._text_parts))).strip()


def _extract_html_text(raw_html: str) -> tuple[str, str]:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw_html)
        parser.close()
        return parser.title(), parser.text()
    except Exception:
        stripped = _WS_RE.sub(" ", _re.sub(r"(?is)<[^>]+>", " ", raw_html)).strip()
        return "", _html.unescape(stripped)


def _line_hash(line: str) -> str:
    """2-char hex hash, whitespace-invariant."""
    return format(zlib.crc32(_WS_RE.sub("", line).encode("utf-8")) & 0xFF, "02x")


class ToolError(RuntimeError):
    pass


@dataclass
class WorkspaceTools:
    root: Path
    shell: str = "/bin/sh"
    command_timeout_sec: int = 45
    max_shell_output_chars: int = 16000
    max_file_chars: int = 20000
    max_observation_chars: int = 6000
    max_files_listed: int = 400
    max_search_hits: int = 200
    web_search_provider: str = "exa"
    exa_api_key: str | None = None
    exa_base_url: str = "https://api.exa.ai"
    firecrawl_api_key: str | None = None
    firecrawl_base_url: str = "https://api.firecrawl.dev/v1"
    brave_api_key: str | None = None
    brave_base_url: str = "https://api.search.brave.com/res/v1"
    tavily_api_key: str | None = None
    tavily_base_url: str = "https://api.tavily.com"
    mistral_transcription_api_key: str | None = None
    mistral_transcription_base_url: str = "https://api.mistral.ai"
    mistral_transcription_model: str = "voxtral-mini-latest"
    mistral_transcription_max_bytes: int = 100 * 1024 * 1024
    mistral_transcription_chunk_max_seconds: int = 900
    mistral_transcription_chunk_overlap_seconds: float = 2.0
    mistral_transcription_max_chunks: int = 48
    mistral_transcription_request_timeout_sec: int = 180

    def __post_init__(self) -> None:
        self.root = self.root.expanduser().resolve()
        if not self.root.exists():
            raise ToolError(f"Workspace does not exist: {self.root}")
        if not self.root.is_dir():
            raise ToolError(f"Workspace is not a directory: {self.root}")
        self._bg_jobs: dict[int, tuple[subprocess.Popen, Any, str]] = {}
        self._bg_next_id: int = 1
        # Runtime policy state.
        self._files_read: set[Path] = set()
        self._parallel_write_claims: dict[str, dict[Path, str]] = {}
        self._parallel_lock = threading.Lock()
        self._scope_local = threading.local()

    def _clip(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        omitted = len(text) - max_chars
        return f"{text[:max_chars]}\n\n...[truncated {omitted} chars]..."

    def _resolve_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.expanduser().resolve()
        root = self.root
        if resolved == root:
            return resolved
        if root not in resolved.parents:
            raise ToolError(f"Path escapes workspace: {raw_path}")
        return resolved

    def _check_shell_policy(self, command: str) -> str | None:
        if _HEREDOC_RE.search(command):
            return (
                "BLOCKED: Heredoc syntax (<< EOF) is not allowed by runtime policy. "
                "Use write_file/apply_patch for multi-line content."
            )
        if _INTERACTIVE_RE.search(command):
            return (
                "BLOCKED: Interactive terminal programs are not allowed by runtime policy "
                "(vim/nano/less/more/top/htop/man)."
            )
        return None

    def begin_parallel_write_group(self, group_id: str) -> None:
        with self._parallel_lock:
            self._parallel_write_claims[group_id] = {}

    def end_parallel_write_group(self, group_id: str) -> None:
        with self._parallel_lock:
            self._parallel_write_claims.pop(group_id, None)

    @contextmanager
    def execution_scope(self, group_id: str | None, owner_id: str | None):
        prev_group = getattr(self._scope_local, "group_id", None)
        prev_owner = getattr(self._scope_local, "owner_id", None)
        self._scope_local.group_id = group_id
        self._scope_local.owner_id = owner_id
        try:
            yield
        finally:
            self._scope_local.group_id = prev_group
            self._scope_local.owner_id = prev_owner

    def _register_write_target(self, resolved: Path) -> None:
        group_id = getattr(self._scope_local, "group_id", None)
        owner_id = getattr(self._scope_local, "owner_id", None)
        if not group_id or not owner_id:
            return
        with self._parallel_lock:
            claims = self._parallel_write_claims.setdefault(group_id, {})
            owner = claims.get(resolved)
            if owner is None:
                claims[resolved] = owner_id
                return
            if owner != owner_id:
                rel = resolved.relative_to(self.root).as_posix()
                raise ToolError(
                    f"Parallel write conflict: '{rel}' is already claimed by sibling task {owner}."
                )

    def run_shell(self, command: str, timeout: int | None = None) -> str:
        policy_error = self._check_shell_policy(command)
        if policy_error:
            return policy_error
        effective_timeout = max(1, min(timeout or self.command_timeout_sec, 600))
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                executable=self.shell,
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            return f"$ {command}\n[failed to start: {exc}]"
        try:
            out, err = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait()
            return f"$ {command}\n[timeout after {effective_timeout}s — processes killed]"
        merged = (
            f"$ {command}\n"
            f"[exit_code={proc.returncode}]\n"
            f"[stdout]\n{out}\n"
            f"[stderr]\n{err}"
        )
        return self._clip(merged, self.max_shell_output_chars)

    def run_shell_bg(self, command: str) -> str:
        policy_error = self._check_shell_policy(command)
        if policy_error:
            return policy_error
        out_path = os.path.join(tempfile.gettempdir(), f".rlm_bg_{self._bg_next_id}.out")
        fh = open(out_path, "w+")
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                executable=self.shell,
                cwd=self.root,
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            fh.close()
            os.unlink(out_path)
            return f"Failed to start background command: {exc}"
        job_id = self._bg_next_id
        self._bg_next_id += 1
        self._bg_jobs[job_id] = (proc, fh, out_path)
        return f"Background job started: job_id={job_id}, pid={proc.pid}"

    def check_shell_bg(self, job_id: int) -> str:
        entry = self._bg_jobs.get(job_id)
        if entry is None:
            return f"No background job with id {job_id}"
        proc, fh, out_path = entry
        returncode = proc.poll()
        try:
            with open(out_path, "r") as f:
                output = f.read()
        except OSError:
            output = ""
        output = self._clip(output, self.max_shell_output_chars)
        if returncode is not None:
            fh.close()
            try:
                os.unlink(out_path)
            except OSError:
                pass
            del self._bg_jobs[job_id]
            return f"[job {job_id} finished, exit_code={returncode}]\n{output}"
        return f"[job {job_id} still running, pid={proc.pid}]\n{output}"

    def kill_shell_bg(self, job_id: int) -> str:
        entry = self._bg_jobs.get(job_id)
        if entry is None:
            return f"No background job with id {job_id}"
        proc, fh, out_path = entry
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()
        fh.close()
        try:
            os.unlink(out_path)
        except OSError:
            pass
        del self._bg_jobs[job_id]
        return f"Background job {job_id} killed."

    def cleanup_bg_jobs(self) -> None:
        for job_id in list(self._bg_jobs):
            proc, fh, out_path = self._bg_jobs[job_id]
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            fh.close()
            try:
                os.unlink(out_path)
            except OSError:
                pass
        self._bg_jobs.clear()

    def list_files(self, glob: str | None = None) -> str:
        lines: list[str]
        if shutil.which("rg"):
            cmd = ["rg", "--files", "--hidden", "-g", "!.git"]
            if glob:
                cmd.extend(["-g", glob])
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=self.command_timeout_sec,
                    start_new_session=True,
                )
            except subprocess.TimeoutExpired:
                return "(list_files timed out)"
            lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        else:
            all_paths: list[str] = []
            count = 0
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                count += len(filenames)
                if count > _MAX_WALK_ENTRIES:
                    break
                for fn in filenames:
                    full = Path(dirpath) / fn
                    rel = full.relative_to(self.root).as_posix()
                    all_paths.append(rel)
            lines = sorted(all_paths)

        if not lines:
            return "(no files)"
        clipped = lines[: self.max_files_listed]
        suffix = ""
        if len(lines) > len(clipped):
            suffix = f"\n...[omitted {len(lines) - len(clipped)} files]..."
        return "\n".join(clipped) + suffix

    def search_files(self, query: str, glob: str | None = None) -> str:
        if not query.strip():
            return "query cannot be empty"
        if shutil.which("rg"):
            cmd = ["rg", "-n", "--hidden", "-S", query, "."]
            if glob:
                cmd.extend(["-g", glob])
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=self.command_timeout_sec,
                    start_new_session=True,
                )
            except subprocess.TimeoutExpired:
                return "(search_files timed out)"
            out_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
            if not out_lines:
                return "(no matches)"
            clipped = out_lines[: self.max_search_hits]
            suffix = ""
            if len(out_lines) > len(clipped):
                suffix = f"\n...[omitted {len(out_lines) - len(clipped)} matches]..."
            return "\n".join(clipped) + suffix

        # Fallback path if ripgrep is unavailable.
        matches: list[str] = []
        lower_query = query.lower()
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            count += len(filenames)
            if count > _MAX_WALK_ENTRIES:
                break
            for fn in filenames:
                full = Path(dirpath) / fn
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for idx, line in enumerate(text.splitlines(), start=1):
                    if lower_query in line.lower():
                        rel = full.relative_to(self.root).as_posix()
                        matches.append(f"{rel}:{idx}:{line}")
                        if len(matches) >= self.max_search_hits:
                            return "\n".join(matches) + "\n...[match limit reached]..."
        return "\n".join(matches) if matches else "(no matches)"

    def _repo_files(self, glob: str | None, max_files: int) -> list[str]:
        lines: list[str]
        if shutil.which("rg"):
            cmd = ["rg", "--files", "--hidden", "-g", "!.git"]
            if glob:
                cmd.extend(["-g", glob])
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=self.root,
                    capture_output=True,
                    text=True,
                    timeout=self.command_timeout_sec,
                    start_new_session=True,
                )
            except subprocess.TimeoutExpired:
                return []
            lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        else:
            lines = []
            count = 0
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                count += len(filenames)
                if count > _MAX_WALK_ENTRIES:
                    break
                for fn in filenames:
                    rel = (Path(dirpath) / fn).relative_to(self.root).as_posix()
                    if glob and not fnmatch.fnmatch(rel, glob):
                        continue
                    lines.append(rel)
        return lines[:max_files]

    def _python_symbols(self, text: str) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        symbols: list[dict[str, Any]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({"kind": "function", "name": node.name, "line": int(node.lineno)})
            elif isinstance(node, ast.ClassDef):
                symbols.append({"kind": "class", "name": node.name, "line": int(node.lineno)})
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            {
                                "kind": "method",
                                "name": f"{node.name}.{child.name}",
                                "line": int(child.lineno),
                            }
                        )
        return symbols

    def _generic_symbols(self, text: str) -> list[dict[str, Any]]:
        patterns = [
            (_re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", _re.MULTILINE), "function"),
            (_re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b", _re.MULTILINE), "class"),
            (_re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\(", _re.MULTILINE), "function"),
        ]
        symbols: list[dict[str, Any]] = []
        for regex, kind in patterns:
            for match in regex.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                symbols.append({"kind": kind, "name": match.group(1), "line": line})
        symbols.sort(key=lambda s: int(s["line"]))
        return symbols

    def repo_map(self, glob: str | None = None, max_files: int = 200) -> str:
        clamped = max(1, min(int(max_files), 500))
        candidates = self._repo_files(glob=glob, max_files=clamped)
        if not candidates:
            return "(no files)"

        language_by_suffix = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "shell",
        }

        files: list[dict[str, Any]] = []
        for rel in candidates:
            suffix = Path(rel).suffix.lower()
            language = language_by_suffix.get(suffix)
            if not language:
                continue
            resolved = self._resolve_path(rel)
            if not resolved.exists() or resolved.is_dir():
                continue
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            symbols: list[dict[str, Any]]
            if language == "python":
                symbols = self._python_symbols(text)
            else:
                symbols = self._generic_symbols(text)
            files.append(
                {
                    "path": rel,
                    "language": language,
                    "lines": len(text.splitlines()),
                    "symbols": symbols[:200],
                }
            )

        output = {
            "root": str(self.root),
            "files": files,
            "total": len(files),
        }
        return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

    def read_file(self, path: str, hashline: bool = True) -> str:
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {path}"
        if resolved.is_dir():
            return f"Path is a directory, not a file: {path}"
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Failed to read file {path}: {exc}"
        self._files_read.add(resolved)
        clipped = self._clip(text, self.max_file_chars)
        rel = resolved.relative_to(self.root).as_posix()
        if hashline:
            numbered = "\n".join(
                f"{i}:{_line_hash(line)}|{line}"
                for i, line in enumerate(clipped.splitlines(), 1)
            )
        else:
            numbered = "\n".join(
                f"{i}|{line}" for i, line in enumerate(clipped.splitlines(), 1)
            )
        return f"# {rel}\n{numbered}"

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    _MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
    _MEDIA_TYPES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    def read_image(self, path: str) -> tuple[str, str | None, str | None]:
        """Read an image file. Returns (text_description, base64_data, media_type)."""
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {path}", None, None
        if resolved.is_dir():
            return f"Path is a directory, not a file: {path}", None, None
        ext = resolved.suffix.lower()
        if ext not in self._IMAGE_EXTENSIONS:
            return (
                f"Unsupported image format: {ext}. "
                f"Supported: {', '.join(sorted(self._IMAGE_EXTENSIONS))}"
            ), None, None
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            return f"Failed to read image {path}: {exc}", None, None
        if size > self._MAX_IMAGE_BYTES:
            return (
                f"Image too large: {size:,} bytes "
                f"(max {self._MAX_IMAGE_BYTES:,} bytes)"
            ), None, None
        try:
            raw = resolved.read_bytes()
        except OSError as exc:
            return f"Failed to read image {path}: {exc}", None, None
        b64 = base64.b64encode(raw).decode("ascii")
        media_type = self._MEDIA_TYPES[ext]
        rel = resolved.relative_to(self.root).as_posix()
        text = f"Image {rel} ({len(raw):,} bytes, {media_type})"
        return text, b64, media_type

    _AUDIO_EXTENSIONS = {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".mpeg",
        ".mpga",
        ".oga",
        ".ogg",
        ".opus",
        ".wav",
    }
    _VIDEO_EXTENSIONS = {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".webm",
    }
    _TIMESTAMP_GRANULARITIES = {"segment", "word"}
    _AUDIO_CHUNKING_MODES = {"auto", "force", "off"}
    _AUDIO_CHUNK_TARGET_FILL_RATIO = 0.85
    _AUDIO_CHUNK_BYTES_PER_SECOND = 32000
    _AUDIO_MIN_CHUNK_SECONDS = 30.0
    _AUDIO_MAX_CHUNK_SECONDS = 1800.0
    _AUDIO_MAX_CHUNK_OVERLAP_SECONDS = 15.0
    _AUDIO_MAX_CHUNKS = 200
    _AUDIO_SPEAKER_FIELDS = {"speaker", "speaker_id", "speaker_label"}

    def _mistral_transcription_url(self) -> str:
        base = self.mistral_transcription_base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/audio/transcriptions"
        return f"{base}/v1/audio/transcriptions"

    def _encode_multipart_form_data(
        self,
        *,
        fields: list[tuple[str, str]],
        file_field_name: str,
        file_name: str,
        file_bytes: bytes,
        media_type: str,
    ) -> tuple[bytes, str]:
        boundary = f"----OpenPlanter{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields:
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(
                    "utf-8"
                )
            )
            chunks.append(value.encode("utf-8"))
            chunks.append(b"\r\n")
        safe_name = Path(file_name).name.replace('"', "")
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{safe_name}"\r\n'
            ).encode("utf-8")
        )
        chunks.append(f"Content-Type: {media_type}\r\n\r\n".encode("utf-8"))
        chunks.append(file_bytes)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), boundary

    def _mistral_transcription_request(
        self,
        *,
        resolved: Path,
        model: str,
        diarize: bool | None,
        timestamp_granularities: list[str] | None,
        context_bias: list[str] | None,
        language: str | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        if not (
            self.mistral_transcription_api_key
            and self.mistral_transcription_api_key.strip()
        ):
            raise ToolError("Mistral transcription API key not configured")
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            raise ToolError(f"Failed to inspect audio file {resolved.name}: {exc}") from exc
        if size > self.mistral_transcription_max_bytes:
            raise ToolError(
                f"Audio file too large: {size:,} bytes "
                f"(max {self.mistral_transcription_max_bytes:,} bytes)"
            )
        try:
            file_bytes = resolved.read_bytes()
        except OSError as exc:
            raise ToolError(f"Failed to read audio file {resolved.name}: {exc}") from exc

        media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        fields: list[tuple[str, str]] = [
            ("model", model),
            ("stream", "false"),
        ]
        if diarize is not None:
            fields.append(("diarize", "true" if diarize else "false"))
        if language:
            fields.append(("language", language))
        if temperature is not None:
            fields.append(("temperature", str(temperature)))
        for granularity in timestamp_granularities or []:
            fields.append(("timestamp_granularities", granularity))
        for phrase in context_bias or []:
            fields.append(("context_bias", phrase))

        body, boundary = self._encode_multipart_form_data(
            fields=fields,
            file_field_name="file",
            file_name=resolved.name,
            file_bytes=file_bytes,
            media_type=media_type,
        )
        req = urllib.request.Request(
            url=self._mistral_transcription_url(),
            data=body,
            headers={
                "Authorization": f"Bearer {self.mistral_transcription_api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.mistral_transcription_request_timeout_sec
            ) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"Mistral transcription HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ToolError(f"Mistral transcription connection error: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"Mistral transcription network error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(
                f"Mistral transcription returned non-JSON payload: {raw[:500]}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ToolError(
                f"Mistral transcription returned non-object response: {type(parsed)!r}"
            )
        return parsed

    def _audio_transcribe_max_chars(self) -> int:
        return min(self.max_file_chars, self.max_observation_chars)

    def _audio_transcribe_options(
        self,
        *,
        diarize: bool | None,
        timestamp_granularities: list[str] | None,
        context_bias: list[str] | None,
        language: str | None,
        temperature: float | None,
        chunking: str,
        chunk_max_seconds: int | None,
        chunk_overlap_seconds: float | None,
        max_chunks: int | None,
        continue_on_chunk_error: bool | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"chunking": chunking}
        if diarize is not None:
            options["diarize"] = diarize
        if timestamp_granularities:
            options["timestamp_granularities"] = timestamp_granularities
        if context_bias:
            options["context_bias"] = context_bias
        if language:
            options["language"] = language
        if temperature is not None:
            options["temperature"] = temperature
        if chunk_max_seconds is not None:
            options["chunk_max_seconds"] = chunk_max_seconds
        if chunk_overlap_seconds is not None:
            options["chunk_overlap_seconds"] = chunk_overlap_seconds
        if max_chunks is not None:
            options["max_chunks"] = max_chunks
        if continue_on_chunk_error is not None:
            options["continue_on_chunk_error"] = continue_on_chunk_error
        return options

    def _ensure_media_tools(self) -> None:
        missing = [
            name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None
        ]
        if missing:
            joined = ", ".join(missing)
            raise ToolError(
                f"Long-form transcription requires {joined}. Install ffmpeg/ffprobe and retry."
            )

    def _run_media_command(self, argv: list[str]) -> str:
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.command_timeout_sec,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ToolError(f"Media tooling not available: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"{argv[0]} timed out after {self.command_timeout_sec}s") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise ToolError(f"{argv[0]} failed: {stderr or 'unknown error'}")
        return completed.stdout

    def _probe_media_duration(self, source: Path) -> float:
        raw = self._run_media_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                str(source),
            ]
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"ffprobe returned invalid JSON for {source.name}") from exc
        duration_value = (
            parsed.get("format", {}).get("duration")
            if isinstance(parsed, dict)
            else None
        )
        try:
            duration = float(duration_value)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"ffprobe did not return a valid duration for {source.name}") from exc
        if duration <= 0:
            raise ToolError(f"ffprobe reported non-positive duration for {source.name}")
        return duration

    def _extract_audio_source(self, source: Path, output: Path) -> None:
        self._run_media_command(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )

    def _extract_audio_chunk(
        self,
        source: Path,
        output: Path,
        *,
        start_sec: float,
        duration_sec: float,
    ) -> None:
        self._run_media_command(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-ss",
                f"{start_sec:.3f}",
                "-i",
                str(source),
                "-t",
                f"{duration_sec:.3f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ]
        )

    def _audio_chunk_seconds_budget(self, requested_seconds: float) -> float:
        safe_seconds = (
            self.mistral_transcription_max_bytes
            * self._AUDIO_CHUNK_TARGET_FILL_RATIO
            / self._AUDIO_CHUNK_BYTES_PER_SECOND
        )
        if safe_seconds <= 0:
            raise ToolError("Mistral transcription max-bytes budget is too small to chunk audio")
        return min(requested_seconds, safe_seconds)

    def _plan_audio_chunks(
        self,
        *,
        duration_sec: float,
        chunk_seconds: float,
        overlap_seconds: float,
        max_chunks: int,
    ) -> list[dict[str, float]]:
        if duration_sec <= 0:
            raise ToolError("Cannot chunk media with non-positive duration")
        chunk_seconds = max(1.0, chunk_seconds)
        overlap_seconds = min(max(0.0, overlap_seconds), max(0.0, chunk_seconds - 0.001))
        chunks: list[dict[str, float]] = []
        start = 0.0
        while start < duration_sec - 1e-6:
            end = min(duration_sec, start + chunk_seconds)
            index = len(chunks)
            chunks.append(
                {
                    "index": float(index),
                    "start_sec": round(start, 3),
                    "end_sec": round(end, 3),
                    "duration_sec": round(end - start, 3),
                    "leading_overlap_sec": 0.0 if index == 0 else round(overlap_seconds, 3),
                }
            )
            if len(chunks) > max_chunks:
                raise ToolError(
                    f"Chunk plan would create {len(chunks)} chunks (max {max_chunks})"
                )
            if end >= duration_sec - 1e-6:
                break
            next_start = end - overlap_seconds
            if next_start <= start + 1e-6:
                next_start = end
            start = next_start
        return chunks

    def _is_video_extension(self, ext: str) -> bool:
        return ext in self._VIDEO_EXTENSIONS

    def _normalized_audio_token(self, token: str) -> str:
        return _TOKEN_NORMALIZE_RE.sub("", token.lower())

    def _dedupe_audio_overlap_text(self, existing_text: str, incoming_text: str) -> str:
        if not existing_text.strip():
            return incoming_text.strip()
        current_tokens = incoming_text.split()
        if not current_tokens:
            return ""
        previous_tokens = existing_text.split()
        max_window = min(len(previous_tokens), len(current_tokens), 80)
        if max_window < 5:
            return incoming_text.strip()
        previous_norm = [
            self._normalized_audio_token(token)
            for token in previous_tokens[-max_window:]
        ]
        current_norm = [
            self._normalized_audio_token(token)
            for token in current_tokens[:max_window]
        ]
        for match_len in range(max_window, 4, -1):
            if previous_norm[-match_len:] == current_norm[:match_len]:
                return " ".join(current_tokens[match_len:]).strip()
        return incoming_text.strip()

    def _entry_time_bounds(self, entry: dict[str, Any]) -> tuple[float, float] | None:
        start = entry.get("start")
        end = entry.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            return float(start), float(end)
        timestamps = entry.get("timestamps")
        if (
            isinstance(timestamps, list)
            and len(timestamps) >= 2
            and isinstance(timestamps[0], (int, float))
            and isinstance(timestamps[1], (int, float))
        ):
            return float(timestamps[0]), float(timestamps[1])
        return None

    def _set_entry_time_bounds(
        self,
        entry: dict[str, Any],
        *,
        start: float,
        end: float,
    ) -> None:
        if "start" in entry or "end" in entry:
            entry["start"] = round(start, 3)
            entry["end"] = round(end, 3)
        elif isinstance(entry.get("timestamps"), list):
            timestamps = list(entry.get("timestamps", []))
            while len(timestamps) < 2:
                timestamps.append(0.0)
            timestamps[0] = round(start, 3)
            timestamps[1] = round(end, 3)
            entry["timestamps"] = timestamps

    def _prefix_audio_speakers(self, value: Any, prefix: str) -> Any:
        if isinstance(value, list):
            return [self._prefix_audio_speakers(item, prefix) for item in value]
        if isinstance(value, dict):
            copied: dict[str, Any] = {}
            for key, item in value.items():
                if (
                    key in self._AUDIO_SPEAKER_FIELDS
                    and isinstance(item, str)
                    and item.strip()
                ):
                    copied[key] = f"{prefix}{item.strip()}"
                else:
                    copied[key] = self._prefix_audio_speakers(item, prefix)
            return copied
        return value

    def _shift_audio_items(
        self,
        items: list[Any],
        *,
        chunk_start_sec: float,
        leading_overlap_sec: float,
        speaker_prefix: str,
    ) -> list[Any]:
        shifted: list[Any] = []
        for item in items:
            copied = self._prefix_audio_speakers(copy.deepcopy(item), speaker_prefix)
            if isinstance(copied, dict):
                bounds = self._entry_time_bounds(copied)
                if bounds is not None:
                    start, end = bounds
                    if end <= leading_overlap_sec + 1e-6:
                        continue
                    if start < leading_overlap_sec:
                        start = leading_overlap_sec
                    self._set_entry_time_bounds(
                        copied,
                        start=start + chunk_start_sec,
                        end=end + chunk_start_sec,
                    )
            shifted.append(copied)
        return shifted

    def _collect_chunk_metadata(
        self,
        parsed: dict[str, Any],
        *,
        chunk_start_sec: float,
        leading_overlap_sec: float,
        speaker_prefix: str,
    ) -> dict[str, list[Any]]:
        aggregated: dict[str, list[Any]] = {}
        if isinstance(parsed.get("segments"), list):
            aggregated["segments"] = self._shift_audio_items(
                parsed["segments"],
                chunk_start_sec=chunk_start_sec,
                leading_overlap_sec=leading_overlap_sec,
                speaker_prefix=speaker_prefix,
            )
        elif isinstance(parsed.get("chunks"), list):
            aggregated["segments"] = self._shift_audio_items(
                parsed["chunks"],
                chunk_start_sec=chunk_start_sec,
                leading_overlap_sec=leading_overlap_sec,
                speaker_prefix=speaker_prefix,
            )
        if isinstance(parsed.get("words"), list):
            aggregated["words"] = self._shift_audio_items(
                parsed["words"],
                chunk_start_sec=chunk_start_sec,
                leading_overlap_sec=leading_overlap_sec,
                speaker_prefix=speaker_prefix,
            )
        if isinstance(parsed.get("diarization"), list):
            aggregated["diarization"] = self._shift_audio_items(
                parsed["diarization"],
                chunk_start_sec=chunk_start_sec,
                leading_overlap_sec=leading_overlap_sec,
                speaker_prefix=speaker_prefix,
            )
        return aggregated

    def _audio_json_length(self, payload: dict[str, Any]) -> int:
        return len(json.dumps(payload, indent=2, ensure_ascii=True))

    def _truncate_audio_text(
        self,
        payload: dict[str, Any],
        *,
        max_chars: int,
    ) -> None:
        text = str(payload.get("text", ""))
        if not text:
            return
        base = copy.deepcopy(payload)
        base["text"] = ""
        if self._audio_json_length(base) > max_chars:
            payload["text"] = ""
            payload.setdefault("truncation", {})["text_truncated_chars"] = len(text)
            return
        low = 0
        high = len(text)
        while low < high:
            mid = (low + high + 1) // 2
            base["text"] = text[:mid]
            if self._audio_json_length(base) <= max_chars:
                low = mid
            else:
                high = mid - 1
        payload["text"] = text[:low]
        omitted = len(text) - low
        if omitted > 0:
            payload.setdefault("truncation", {})["text_truncated_chars"] = omitted

    def _serialize_audio_envelope(
        self,
        envelope: dict[str, Any],
        *,
        max_chars: int,
    ) -> str:
        payload = copy.deepcopy(envelope)
        payload.setdefault("truncation", {"applied": False})
        if self._audio_json_length(payload) <= max_chars:
            return json.dumps(payload, indent=2, ensure_ascii=True)

        truncation = payload.setdefault("truncation", {})
        truncation["applied"] = True
        response = payload.get("response")
        omitted_response_fields: dict[str, int] = {}

        if isinstance(response, dict):
            removal_order = ["words", "diarization", "segments"]
            if payload.get("mode") != "chunked":
                removal_order.append("chunks")
            for key in removal_order:
                value = response.get(key)
                if isinstance(value, list) and value:
                    omitted_response_fields[key] = len(value)
                    response.pop(key, None)
                    if self._audio_json_length(payload) <= max_chars:
                        break
            if omitted_response_fields:
                truncation["omitted_response_fields"] = omitted_response_fields
            if (
                payload.get("mode") == "chunked"
                and isinstance(response.get("chunks"), list)
                and self._audio_json_length(payload) > max_chars
            ):
                chunk_summaries = response["chunks"]
                keep = min(len(chunk_summaries), 12)
                omitted = len(chunk_summaries) - keep
                if omitted > 0:
                    response["chunks"] = chunk_summaries[:keep]
                    truncation["omitted_chunk_statuses"] = omitted

        if self._audio_json_length(payload) > max_chars:
            self._truncate_audio_text(payload, max_chars=max_chars)

        if (
            isinstance(payload.get("response"), dict)
            and isinstance(payload["response"].get("chunks"), list)
            and self._audio_json_length(payload) > max_chars
        ):
            while (
                len(payload["response"]["chunks"]) > 3
                and self._audio_json_length(payload) > max_chars
            ):
                payload["response"]["chunks"].pop()
                truncation["omitted_chunk_statuses"] = truncation.get(
                    "omitted_chunk_statuses", 0
                ) + 1

        if self._audio_json_length(payload) > max_chars and isinstance(
            payload.get("options"), dict
        ):
            if isinstance(payload["options"].get("context_bias"), list):
                truncation["omitted_context_bias_phrases"] = len(
                    payload["options"]["context_bias"]
                )
                payload["options"].pop("context_bias", None)

        return json.dumps(payload, indent=2, ensure_ascii=True)

    def audio_transcribe(
        self,
        path: str,
        diarize: bool | None = None,
        timestamp_granularities: list[str] | None = None,
        context_bias: list[str] | None = None,
        language: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        chunking: str | None = None,
        chunk_max_seconds: int | None = None,
        chunk_overlap_seconds: float | None = None,
        max_chunks: int | None = None,
        continue_on_chunk_error: bool | None = None,
    ) -> str:
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {path}"
        if resolved.is_dir():
            return f"Path is a directory, not a file: {path}"
        ext = resolved.suffix.lower()
        if ext not in self._AUDIO_EXTENSIONS and ext not in self._VIDEO_EXTENSIONS:
            return (
                f"Unsupported audio format: {ext or '(none)'}. "
                f"Supported: {', '.join(sorted(self._AUDIO_EXTENSIONS | self._VIDEO_EXTENSIONS))}"
            )
        if language and timestamp_granularities:
            return (
                "language cannot be combined with timestamp_granularities for "
                "Mistral offline transcription"
            )
        chunk_mode = (chunking or "auto").strip().lower()
        if chunk_mode not in self._AUDIO_CHUNKING_MODES:
            return "chunking must be one of auto, off, or force"
        if chunk_max_seconds is not None and not (
            self._AUDIO_MIN_CHUNK_SECONDS
            <= float(chunk_max_seconds)
            <= self._AUDIO_MAX_CHUNK_SECONDS
        ):
            return (
                "chunk_max_seconds must be between "
                f"{int(self._AUDIO_MIN_CHUNK_SECONDS)} and {int(self._AUDIO_MAX_CHUNK_SECONDS)}"
            )
        if chunk_overlap_seconds is not None and not (
            0.0 <= float(chunk_overlap_seconds) <= self._AUDIO_MAX_CHUNK_OVERLAP_SECONDS
        ):
            return (
                "chunk_overlap_seconds must be between 0 and "
                f"{int(self._AUDIO_MAX_CHUNK_OVERLAP_SECONDS)}"
            )
        if max_chunks is not None and not (1 <= max_chunks <= self._AUDIO_MAX_CHUNKS):
            return f"max_chunks must be between 1 and {self._AUDIO_MAX_CHUNKS}"
        normalized_timestamps: list[str] | None = None
        if timestamp_granularities:
            seen: set[str] = set()
            normalized_timestamps = []
            for item in timestamp_granularities:
                value = item.strip().lower()
                if not value:
                    continue
                if value not in self._TIMESTAMP_GRANULARITIES:
                    return (
                        "timestamp_granularities must be drawn from "
                        f"{', '.join(sorted(self._TIMESTAMP_GRANULARITIES))}"
                    )
                if value not in seen:
                    normalized_timestamps.append(value)
                    seen.add(value)
        normalized_bias = [item.strip() for item in (context_bias or []) if item.strip()]
        if len(normalized_bias) > 100:
            return "context_bias supports at most 100 phrases"
        chosen_model = (model or self.mistral_transcription_model or "").strip()
        if not chosen_model:
            return "No Mistral transcription model configured"
        self._files_read.add(resolved)
        rel = resolved.relative_to(self.root).as_posix()
        options = self._audio_transcribe_options(
            diarize=diarize,
            timestamp_granularities=normalized_timestamps,
            context_bias=normalized_bias,
            language=language,
            temperature=temperature,
            chunking=chunk_mode,
            chunk_max_seconds=chunk_max_seconds,
            chunk_overlap_seconds=chunk_overlap_seconds,
            max_chunks=max_chunks,
            continue_on_chunk_error=continue_on_chunk_error,
        )

        try:
            with tempfile.TemporaryDirectory(prefix="openplanter-audio-") as temp_root:
                temp_dir = Path(temp_root)
                upload_source = resolved
                if self._is_video_extension(ext):
                    self._ensure_media_tools()
                    upload_source = temp_dir / "video-source.wav"
                    self._extract_audio_source(resolved, upload_source)

                try:
                    upload_size = upload_source.stat().st_size
                except OSError as exc:
                    raise ToolError(
                        f"Failed to inspect audio file {upload_source.name}: {exc}"
                    ) from exc

                chunk_requested = chunk_mode == "force" or (
                    chunk_mode == "auto"
                    and upload_size > self.mistral_transcription_max_bytes
                )

                if not chunk_requested:
                    parsed = self._mistral_transcription_request(
                        resolved=upload_source,
                        model=chosen_model,
                        diarize=diarize,
                        timestamp_granularities=normalized_timestamps,
                        context_bias=normalized_bias,
                        language=language,
                        temperature=temperature,
                    )
                    envelope = {
                        "provider": "mistral",
                        "service": "transcription",
                        "path": rel,
                        "model": chosen_model,
                        "options": options,
                        "text": str(parsed.get("text", "")),
                        "response": parsed,
                    }
                    return self._serialize_audio_envelope(
                        envelope, max_chars=self._audio_transcribe_max_chars()
                    )

                self._ensure_media_tools()
                duration_sec = self._probe_media_duration(upload_source)
                requested_chunk_seconds = float(
                    chunk_max_seconds or self.mistral_transcription_chunk_max_seconds
                )
                requested_chunk_seconds = min(
                    requested_chunk_seconds, self._AUDIO_MAX_CHUNK_SECONDS
                )
                effective_chunk_seconds = self._audio_chunk_seconds_budget(
                    requested_chunk_seconds
                )
                effective_overlap_seconds = min(
                    float(
                        chunk_overlap_seconds
                        if chunk_overlap_seconds is not None
                        else self.mistral_transcription_chunk_overlap_seconds
                    ),
                    max(0.0, effective_chunk_seconds - 0.001),
                )
                effective_max_chunks = max_chunks or self.mistral_transcription_max_chunks
                chunk_plan = self._plan_audio_chunks(
                    duration_sec=duration_sec,
                    chunk_seconds=effective_chunk_seconds,
                    overlap_seconds=effective_overlap_seconds,
                    max_chunks=effective_max_chunks,
                )
                warnings: list[str] = []
                chunk_statuses: list[dict[str, Any]] = []
                stitched_text = ""
                partial = False
                aggregated_response: dict[str, Any] = {
                    "speaker_scope": (
                        "chunk_local_prefixed" if diarize else "not_requested"
                    ),
                    "chunks": chunk_statuses,
                }

                for plan_entry in chunk_plan:
                    index = int(plan_entry["index"])
                    start_sec = float(plan_entry["start_sec"])
                    end_sec = float(plan_entry["end_sec"])
                    duration_value = float(plan_entry["duration_sec"])
                    leading_overlap_sec = float(plan_entry["leading_overlap_sec"])
                    chunk_path = temp_dir / f"chunk-{index:03d}.wav"
                    try:
                        self._extract_audio_chunk(
                            upload_source,
                            chunk_path,
                            start_sec=start_sec,
                            duration_sec=duration_value,
                        )
                        parsed = self._mistral_transcription_request(
                            resolved=chunk_path,
                            model=chosen_model,
                            diarize=diarize,
                            timestamp_granularities=normalized_timestamps,
                            context_bias=normalized_bias,
                            language=language,
                            temperature=temperature,
                        )
                    except ToolError as exc:
                        partial = True
                        message = f"chunk {index} failed: {exc}"
                        chunk_statuses.append(
                            {
                                "index": index,
                                "start_sec": start_sec,
                                "end_sec": end_sec,
                                "status": "error",
                                "error": str(exc),
                            }
                        )
                        if continue_on_chunk_error:
                            warnings.append(message)
                            continue
                        return f"audio_transcribe failed in chunk {index}: {exc}"

                    chunk_text = str(parsed.get("text", "")).strip()
                    deduped_text = self._dedupe_audio_overlap_text(
                        stitched_text, chunk_text
                    )
                    if deduped_text:
                        stitched_text = (
                            f"{stitched_text} {deduped_text}".strip()
                            if stitched_text
                            else deduped_text
                        )

                    metadata = self._collect_chunk_metadata(
                        parsed,
                        chunk_start_sec=start_sec,
                        leading_overlap_sec=leading_overlap_sec,
                        speaker_prefix=f"c{index}_",
                    )
                    for key, values in metadata.items():
                        if values:
                            aggregated_response.setdefault(key, []).extend(values)

                    chunk_statuses.append(
                        {
                            "index": index,
                            "start_sec": start_sec,
                            "end_sec": end_sec,
                            "status": "ok",
                            "text_chars": len(chunk_text),
                        }
                    )

                if not any(
                    chunk.get("status") == "ok" for chunk in chunk_statuses
                ):
                    return "audio_transcribe failed: no chunk completed successfully"

                envelope = {
                    "provider": "mistral",
                    "service": "transcription",
                    "mode": "chunked",
                    "path": rel,
                    "model": chosen_model,
                    "options": options,
                    "chunking": {
                        "strategy": "overlap_window",
                        "chunk_seconds": round(effective_chunk_seconds, 3),
                        "overlap_seconds": round(effective_overlap_seconds, 3),
                        "total_chunks": len(chunk_plan),
                        "failed_chunks": sum(
                            1 for chunk in chunk_statuses if chunk["status"] != "ok"
                        ),
                        "partial": partial,
                    },
                    "text": stitched_text,
                    "response": aggregated_response,
                }
                if warnings:
                    envelope["warnings"] = warnings
                return self._serialize_audio_envelope(
                    envelope, max_chars=self._audio_transcribe_max_chars()
                )
        except ToolError as exc:
            return str(exc)

    def write_file(self, path: str, content: str) -> str:
        resolved = self._resolve_path(path)
        if resolved.exists() and resolved.is_file() and resolved not in self._files_read:
            return (
                f"BLOCKED: {path} already exists but has not been read. "
                f"Use read_file('{path}') first, then edit via apply_patch or write_file."
            )
        try:
            self._register_write_target(resolved)
        except ToolError as exc:
            return f"Blocked by policy: {exc}"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"Failed to write {path}: {exc}"
        self._files_read.add(resolved)
        rel = resolved.relative_to(self.root).as_posix()
        return f"Wrote {len(content)} chars to {rel}"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {path}"
        if resolved.is_dir():
            return f"Path is a directory, not a file: {path}"
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Failed to read file {path}: {exc}"
        self._files_read.add(resolved)
        if old_text not in content:
            # Fuzzy fallback: try whitespace-normalized match
            norm_old = " ".join(old_text.split())
            old_lines = old_text.splitlines(keepends=True)
            lines = content.splitlines(keepends=True)
            found = False
            for i in range(len(lines) - len(old_lines) + 1):
                candidate = "".join(lines[i:i + len(old_lines)])
                if " ".join(candidate.split()) == norm_old:
                    before = "".join(lines[:i])
                    after = "".join(lines[i + len(old_lines):])
                    content = before + new_text + after
                    found = True
                    break
            if not found:
                return f"edit_file failed: old_text not found in {path}"
        else:
            count = content.count(old_text)
            if count > 1:
                return f"edit_file failed: old_text appears {count} times in {path}. Provide more context to make it unique."
            content = content.replace(old_text, new_text, 1)
        try:
            self._register_write_target(resolved)
        except ToolError as exc:
            return f"Blocked by policy: {exc}"
        try:
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"Failed to write {path}: {exc}"
        self._files_read.add(resolved)
        rel = resolved.relative_to(self.root).as_posix()
        return f"Edited {rel}"

    def _validate_anchor(
        self,
        anchor: str,
        line_hashes: dict[int, str],
        lines: list[str],
    ) -> tuple[int, str | None]:
        """Parse ``"N:HH"`` anchor, return ``(lineno, error_or_None)``."""
        parts = anchor.split(":", 1)
        if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) != 2:
            return -1, f"Invalid anchor format: {anchor!r} (expected N:HH)"
        lineno = int(parts[0])
        expected_hash = parts[1]
        if lineno < 1 or lineno > len(lines):
            return -1, f"Line {lineno} out of range (file has {len(lines)} lines)"
        actual_hash = line_hashes[lineno]
        if actual_hash != expected_hash:
            ctx_start = max(1, lineno - 2)
            ctx_end = min(len(lines), lineno + 2)
            ctx_lines = [
                f"  {i}:{line_hashes[i]}|{lines[i - 1]}"
                for i in range(ctx_start, ctx_end + 1)
            ]
            return -1, (
                f"Hash mismatch at line {lineno}: expected {expected_hash}, "
                f"got {actual_hash}. Current context:\n" + "\n".join(ctx_lines)
            )
        return lineno, None

    def hashline_edit(self, path: str, edits: list[dict]) -> str:
        """Edit a file using hash-anchored line references."""
        resolved = self._resolve_path(path)
        if not resolved.exists():
            return f"File not found: {path}"
        if resolved.is_dir():
            return f"Path is a directory, not a file: {path}"
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Failed to read file {path}: {exc}"
        self._files_read.add(resolved)

        lines = content.splitlines()
        line_hashes: dict[int, str] = {
            i: _line_hash(line) for i, line in enumerate(lines, 1)
        }

        # Parse and validate all edits upfront
        parsed: list[tuple[str, int, int, list[str]]] = []
        for edit in edits:
            if "set_line" in edit:
                anchor = str(edit["set_line"])
                lineno, err = self._validate_anchor(anchor, line_hashes, lines)
                if err:
                    return err
                raw = str(edit.get("content", ""))
                new_line = _HASHLINE_PREFIX_RE.sub("", raw)
                parsed.append(("set", lineno, lineno, [new_line]))
            elif "replace_lines" in edit:
                rng = edit["replace_lines"]
                start_anchor = str(rng.get("start", ""))
                end_anchor = str(rng.get("end", ""))
                start, err = self._validate_anchor(start_anchor, line_hashes, lines)
                if err:
                    return err
                end, err = self._validate_anchor(end_anchor, line_hashes, lines)
                if err:
                    return err
                if end < start:
                    return f"End line {end} is before start line {start}"
                raw_content = str(edit.get("content", ""))
                new_lines = [
                    _HASHLINE_PREFIX_RE.sub("", ln)
                    for ln in raw_content.splitlines()
                ]
                parsed.append(("replace", start, end, new_lines))
            elif "insert_after" in edit:
                anchor = str(edit["insert_after"])
                lineno, err = self._validate_anchor(anchor, line_hashes, lines)
                if err:
                    return err
                raw_content = str(edit.get("content", ""))
                new_lines = [
                    _HASHLINE_PREFIX_RE.sub("", ln)
                    for ln in raw_content.splitlines()
                ]
                parsed.append(("insert", lineno, lineno, new_lines))
            else:
                return f"Unknown edit operation: {edit!r}. Use set_line, replace_lines, or insert_after."

        # Sort by line number descending so bottom-up application doesn't shift indices
        parsed.sort(key=lambda t: t[1], reverse=True)

        # Apply edits
        changed = 0
        for op, start, end, new_lines in parsed:
            if op == "set":
                if lines[start - 1] != new_lines[0]:
                    lines[start - 1] = new_lines[0]
                    changed += 1
            elif op == "replace":
                old_slice = lines[start - 1 : end]
                if old_slice != new_lines:
                    lines[start - 1 : end] = new_lines
                    changed += 1
            elif op == "insert":
                lines[start:start] = new_lines
                changed += 1

        if changed == 0:
            return f"No changes needed in {path}"

        new_content = "\n".join(lines)
        if content.endswith("\n"):
            new_content += "\n"
        try:
            self._register_write_target(resolved)
        except ToolError as exc:
            return f"Blocked by policy: {exc}"
        try:
            resolved.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return f"Failed to write {path}: {exc}"
        self._files_read.add(resolved)
        rel = resolved.relative_to(self.root).as_posix()
        return f"Edited {rel} ({changed} edit(s) applied)"

    def apply_patch(self, patch_text: str) -> str:
        if not patch_text.strip():
            return "apply_patch requires non-empty patch text"
        try:
            ops = parse_agent_patch(patch_text)
        except PatchApplyError as exc:
            return f"Patch failed: {exc}"
        try:
            for op in ops:
                if isinstance(op, AddFileOp):
                    self._register_write_target(self._resolve_path(op.path))
                elif isinstance(op, DeleteFileOp):
                    self._register_write_target(self._resolve_path(op.path))
                elif isinstance(op, UpdateFileOp):
                    self._register_write_target(self._resolve_path(op.path))
                    if op.move_to:
                        self._register_write_target(self._resolve_path(op.move_to))
        except (ToolError, OSError) as exc:
            return f"Blocked by policy: {exc}"
        try:
            report = apply_agent_patch(
                patch_text=patch_text,
                resolve_path=self._resolve_path,
            )
        except (PatchApplyError, OSError) as exc:
            return f"Patch failed: {exc}"
        for rel_path in report.added + report.updated:
            try:
                self._files_read.add(self._resolve_path(rel_path))
            except ToolError:
                pass
        return report.render()

    def _exa_request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not (self.exa_api_key and self.exa_api_key.strip()):
            raise ToolError("EXA_API_KEY not configured")
        url = self.exa_base_url.rstrip("/") + endpoint
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.exa_api_key,
                "Content-Type": "application/json",
                "User-Agent": "exa-py 1.0.18",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.command_timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"Exa API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ToolError(f"Exa API connection error: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"Exa API network error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Exa API returned non-JSON payload: {raw[:500]}") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"Exa API returned non-object response: {type(parsed)!r}")
        return parsed

    def _firecrawl_request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not (self.firecrawl_api_key and self.firecrawl_api_key.strip()):
            raise ToolError("FIRECRAWL_API_KEY not configured")
        url = self.firecrawl_base_url.rstrip("/") + endpoint
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.firecrawl_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.command_timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"Firecrawl API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ToolError(f"Firecrawl API connection error: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"Firecrawl API network error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Firecrawl API returned non-JSON payload: {raw[:500]}") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"Firecrawl API returned non-object response: {type(parsed)!r}")
        return parsed

    def _brave_request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if not (self.brave_api_key and self.brave_api_key.strip()):
            raise ToolError("BRAVE_API_KEY not configured")
        query = urllib.parse.urlencode(params, doseq=True)
        url = self.brave_base_url.rstrip("/") + endpoint
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(
            url=url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.brave_api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.command_timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"Brave API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ToolError(f"Brave API connection error: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"Brave API network error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Brave API returned non-JSON payload: {raw[:500]}") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"Brave API returned non-object response: {type(parsed)!r}")
        return parsed

    def _tavily_request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not (self.tavily_api_key and self.tavily_api_key.strip()):
            raise ToolError("TAVILY_API_KEY not configured")
        url = self.tavily_base_url.rstrip("/") + endpoint
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.tavily_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.command_timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"Tavily API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ToolError(f"Tavily API connection error: {exc}") from exc
        except OSError as exc:
            raise ToolError(f"Tavily API network error: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Tavily API returned non-JSON payload: {raw[:500]}") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"Tavily API returned non-object response: {type(parsed)!r}")
        return parsed

    def _fetch_url_direct(self, url: str) -> dict[str, str]:
        req = urllib.request.Request(
            url=url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "OpenPlanter/1.0",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.command_timeout_sec) as resp:
                resolved_url = resp.geturl()
                charset = resp.headers.get_content_charset() or "utf-8"
                raw = resp.read().decode(charset, errors="replace")
                content_type = (resp.headers.get("Content-Type") or "").lower()
        except urllib.error.HTTPError as exc:
            return {
                "url": url,
                "title": "",
                "text": f"Direct fetch failed: HTTP {exc.code}",
            }
        except urllib.error.URLError as exc:
            return {
                "url": url,
                "title": "",
                "text": f"Direct fetch failed: {exc}",
            }
        except OSError as exc:
            return {
                "url": url,
                "title": "",
                "text": f"Direct fetch failed: {exc}",
            }

        if "html" in content_type:
            title, text = _extract_html_text(raw)
        else:
            title, text = "", raw
        return {
            "url": resolved_url,
            "title": title,
            "text": self._clip(text or raw, 8000),
        }

    def web_search(
        self,
        query: str,
        num_results: int = 10,
        include_text: bool = False,
    ) -> str:
        query = query.strip()
        if not query:
            return "web_search requires non-empty query"
        clamped_results = max(1, min(int(num_results), 20))
        provider = (self.web_search_provider or "exa").strip().lower()
        if provider not in {"exa", "firecrawl", "brave", "tavily"}:
            provider = "exa"

        if provider == "firecrawl":
            payload: dict[str, Any] = {
                "query": query,
                "limit": clamped_results,
            }
            if include_text:
                payload["scrapeOptions"] = {"formats": ["markdown"]}

            try:
                parsed = self._firecrawl_request("/search", payload)
            except Exception as exc:
                return f"Web search failed: {exc}"

            data = parsed.get("data")
            rows: list[Any] = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                web_rows = data.get("web")
                if isinstance(web_rows, list):
                    rows = web_rows

            out_results: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                metadata = row.get("metadata")
                meta_title = ""
                if isinstance(metadata, dict):
                    meta_title = str(metadata.get("title", ""))
                item: dict[str, Any] = {
                    "url": str(row.get("url", "")),
                    "title": str(row.get("title", "") or meta_title),
                    "snippet": str(row.get("description", "") or row.get("snippet", "")),
                }
                if include_text:
                    text_value = row.get("markdown") or row.get("text") or ""
                    if isinstance(text_value, str) and text_value:
                        item["text"] = self._clip(text_value, 4000)
                out_results.append(item)

            output = {
                "query": query,
                "provider": provider,
                "results": out_results,
                "total": len(out_results),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        if provider == "brave":
            params: dict[str, Any] = {
                "q": query,
                "count": clamped_results,
            }
            if include_text:
                params["extra_snippets"] = "true"

            try:
                parsed = self._brave_request("/web/search", params)
            except Exception as exc:
                return f"Web search failed: {exc}"

            rows: list[Any] = []
            web = parsed.get("web")
            if isinstance(web, dict):
                web_rows = web.get("results")
                if isinstance(web_rows, list):
                    rows = web_rows
            elif isinstance(parsed.get("results"), list):
                rows = parsed["results"]

            out_results: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                description = str(row.get("description", "") or row.get("snippet", ""))
                extra_snippets = row.get("extra_snippets")
                extra_texts = [
                    snippet
                    for snippet in extra_snippets
                    if isinstance(snippet, str) and snippet
                ] if isinstance(extra_snippets, list) else []
                item: dict[str, Any] = {
                    "url": str(row.get("url", "")),
                    "title": str(row.get("title", "")),
                    "snippet": description or (extra_texts[0] if extra_texts else ""),
                }
                if include_text:
                    text_parts = [part for part in [description, *extra_texts] if part]
                    if text_parts:
                        item["text"] = self._clip("\n\n".join(text_parts), 4000)
                out_results.append(item)

            output = {
                "query": query,
                "provider": provider,
                "results": out_results,
                "total": len(out_results),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        if provider == "tavily":
            payload = {
                "query": query,
                "max_results": clamped_results,
            }
            if include_text:
                payload["include_raw_content"] = "markdown"

            try:
                parsed = self._tavily_request("/search", payload)
            except Exception as exc:
                return f"Web search failed: {exc}"

            rows = parsed.get("results")
            out_results: list[dict[str, Any]] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                snippet = str(row.get("content", "") or row.get("snippet", ""))
                text_value = row.get("raw_content") or row.get("content") or ""
                item: dict[str, Any] = {
                    "url": str(row.get("url", "")),
                    "title": str(row.get("title", "")),
                    "snippet": snippet,
                }
                if include_text and isinstance(text_value, str) and text_value:
                    item["text"] = self._clip(text_value, 4000)
                out_results.append(item)

            output = {
                "query": query,
                "provider": provider,
                "results": out_results,
                "total": len(out_results),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        payload: dict[str, Any] = {
            "query": query,
            "numResults": clamped_results,
        }
        if include_text:
            payload["contents"] = {"text": {"maxCharacters": 4000}}

        try:
            parsed = self._exa_request("/search", payload)
        except Exception as exc:
            return f"Web search failed: {exc}"

        out_results: list[dict[str, Any]] = []
        for row in parsed.get("results", []) if isinstance(parsed.get("results"), list) else []:
            if not isinstance(row, dict):
                continue
            item: dict[str, Any] = {
                "url": str(row.get("url", "")),
                "title": str(row.get("title", "")),
                "snippet": str(row.get("highlight", "") or row.get("snippet", "")),
            }
            if include_text and isinstance(row.get("text"), str):
                item["text"] = self._clip(str(row["text"]), 4000)
            out_results.append(item)

        output = {
            "query": query,
            "provider": provider,
            "results": out_results,
            "total": len(out_results),
        }
        return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

    def fetch_url(self, urls: list[str]) -> str:
        if not isinstance(urls, list):
            return "fetch_url requires a list of URL strings"
        normalized: list[str] = []
        for raw in urls:
            if not isinstance(raw, str):
                continue
            text = raw.strip()
            if text:
                normalized.append(text)
        if not normalized:
            return "fetch_url requires at least one valid URL"
        normalized = normalized[:10]
        provider = (self.web_search_provider or "exa").strip().lower()
        if provider not in {"exa", "firecrawl", "brave", "tavily"}:
            provider = "exa"

        if provider == "firecrawl":
            pages: list[dict[str, Any]] = []
            for url in normalized:
                payload: dict[str, Any] = {
                    "url": url,
                    "formats": ["markdown"],
                }
                try:
                    parsed = self._firecrawl_request("/scrape", payload)
                except Exception as exc:
                    return f"Fetch URL failed: {exc}"
                data = parsed.get("data")
                if not isinstance(data, dict):
                    continue
                metadata = data.get("metadata")
                title = ""
                if isinstance(metadata, dict):
                    title = str(metadata.get("title", ""))
                text = data.get("markdown") or data.get("text") or data.get("html") or ""
                pages.append(
                    {
                        "url": str(data.get("url", "") or url),
                        "title": title,
                        "text": self._clip(str(text), 8000),
                    }
                )
            output = {
                "provider": provider,
                "pages": pages,
                "total": len(pages),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        if provider == "brave":
            pages = [self._fetch_url_direct(url) for url in normalized]
            output = {
                "provider": provider,
                "pages": pages,
                "total": len(pages),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        if provider == "tavily":
            payload = {
                "urls": normalized,
                "extract_depth": "basic",
                "include_images": False,
            }
            try:
                parsed = self._tavily_request("/extract", payload)
            except Exception as exc:
                return f"Fetch URL failed: {exc}"

            pages: list[dict[str, Any]] = []
            rows = parsed.get("results")
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                text = row.get("raw_content") or row.get("content") or ""
                pages.append(
                    {
                        "url": str(row.get("url", "")),
                        "title": str(row.get("title", "") or ""),
                        "text": self._clip(str(text), 8000),
                    }
                )
            output = {
                "provider": provider,
                "pages": pages,
                "total": len(pages),
            }
            return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)

        payload: dict[str, Any] = {
            "ids": normalized,
            "text": {"maxCharacters": 8000},
        }
        try:
            parsed = self._exa_request("/contents", payload)
        except Exception as exc:
            return f"Fetch URL failed: {exc}"

        pages: list[dict[str, Any]] = []
        for row in parsed.get("results", []) if isinstance(parsed.get("results"), list) else []:
            if not isinstance(row, dict):
                continue
            pages.append(
                {
                    "url": str(row.get("url", "")),
                    "title": str(row.get("title", "")),
                    "text": self._clip(str(row.get("text", "")), 8000),
                }
            )

        output = {
            "provider": provider,
            "pages": pages,
            "total": len(pages),
        }
        return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)
