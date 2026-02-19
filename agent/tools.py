from __future__ import annotations

import ast
import fnmatch
import json
import os
import signal
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import re as _re
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
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
    max_files_listed: int = 400
    max_search_hits: int = 200
    exa_api_key: str | None = None
    exa_base_url: str = "https://api.exa.ai"

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
            "pages": pages,
            "total": len(pages),
        }
        return self._clip(json.dumps(output, indent=2, ensure_ascii=True), self.max_file_chars)
