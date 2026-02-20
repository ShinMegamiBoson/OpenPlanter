from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class PatchApplyError(RuntimeError):
    pass


def _normalize_ws(line: str) -> str:
    """Collapse all whitespace runs to single space and strip."""
    return " ".join(line.split())


ResolvePathFn = Callable[[str], Path]


@dataclass
class PatchChunk:
    lines: list[str] = field(default_factory=list)


@dataclass
class AddFileOp:
    path: str
    plus_lines: list[str]


@dataclass
class DeleteFileOp:
    path: str


@dataclass
class UpdateFileOp:
    path: str
    raw_lines: list[str]
    move_to: str | None = None


PatchOp = AddFileOp | DeleteFileOp | UpdateFileOp


@dataclass
class ApplyReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["Patch applied successfully."]
        if self.added:
            lines.append("Added:")
            lines.extend(f"- {p}" for p in self.added)
        if self.updated:
            lines.append("Updated:")
            lines.extend(f"- {p}" for p in self.updated)
        if self.deleted:
            lines.append("Deleted:")
            lines.extend(f"- {p}" for p in self.deleted)
        if self.moved:
            lines.append("Moved:")
            lines.extend(f"- {p}" for p in self.moved)
        return "\n".join(lines)


def parse_agent_patch(patch_text: str) -> list[PatchOp]:
    lines = patch_text.splitlines()
    if not lines:
        raise PatchApplyError("patch is empty")
    if lines[0].strip() != "*** Begin Patch":
        raise PatchApplyError("patch must start with '*** Begin Patch'")
    if lines[-1].strip() != "*** End Patch":
        raise PatchApplyError("patch must end with '*** End Patch'")

    ops: list[PatchOp] = []
    i = 1
    while i < len(lines) - 1:
        line = lines[i]
        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            i += 1
            plus_lines: list[str] = []
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                row = lines[i]
                if not row.startswith("+"):
                    raise PatchApplyError(
                        f"add file '{path}' contains non '+' line: {row!r}"
                    )
                plus_lines.append(row[1:])
                i += 1
            ops.append(AddFileOp(path=path, plus_lines=plus_lines))
            continue

        if line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            ops.append(DeleteFileOp(path=path))
            i += 1
            continue

        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: ") :].strip()
            i += 1
            move_to: str | None = None
            if i < len(lines) - 1 and lines[i].startswith("*** Move to: "):
                move_to = lines[i][len("*** Move to: ") :].strip()
                i += 1
            raw_lines: list[str] = []
            while i < len(lines) - 1 and not lines[i].startswith("*** "):
                raw_lines.append(lines[i])
                i += 1
            ops.append(UpdateFileOp(path=path, raw_lines=raw_lines, move_to=move_to))
            continue

        if line.strip() == "":
            i += 1
            continue

        raise PatchApplyError(f"unexpected patch line: {line!r}")

    if not ops:
        raise PatchApplyError("patch contains no operations")
    return ops


def _parse_chunks(raw_lines: list[str]) -> list[PatchChunk]:
    chunks: list[PatchChunk] = []
    current: list[str] = []
    for row in raw_lines:
        if row.startswith("@@"):
            if current:
                chunks.append(PatchChunk(lines=current))
                current = []
            continue
        if row == "*** End of File":
            continue
        if row.startswith((" ", "+", "-")):
            current.append(row)
            continue
        raise PatchApplyError(f"invalid update patch row: {row!r}")
    if current:
        chunks.append(PatchChunk(lines=current))
    if not chunks:
        raise PatchApplyError("update operation contains no hunks")
    return chunks


def _chunk_to_old_new(chunk: PatchChunk) -> tuple[list[str], list[str]]:
    old_seq: list[str] = []
    new_seq: list[str] = []
    for row in chunk.lines:
        prefix = row[0]
        payload = row[1:]
        if prefix == " ":
            old_seq.append(payload)
            new_seq.append(payload)
        elif prefix == "-":
            old_seq.append(payload)
        elif prefix == "+":
            new_seq.append(payload)
        else:
            raise PatchApplyError(f"invalid row prefix: {prefix!r}")
    return old_seq, new_seq


def _find_subsequence(
    haystack: list[str], needle: list[str], start_idx: int = 0
) -> int:
    if not needle:
        return min(max(start_idx, 0), len(haystack))
    max_start = len(haystack) - len(needle)
    # Pass 1: exact match
    for i in range(max(start_idx, 0), max_start + 1):
        if haystack[i : i + len(needle)] == needle:
            return i
    # Pass 2: whitespace-normalized match
    norm_needle = [_normalize_ws(ln) for ln in needle]
    for i in range(max(start_idx, 0), max_start + 1):
        if [_normalize_ws(h) for h in haystack[i : i + len(needle)]] == norm_needle:
            return i
    return -1


def _render_lines(lines: list[str], prefer_trailing_newline: bool) -> str:
    if not lines:
        return ""
    text = "\n".join(lines)
    if prefer_trailing_newline:
        text += "\n"
    return text


def apply_agent_patch(
    patch_text: str,
    resolve_path: ResolvePathFn,
) -> ApplyReport:
    ops = parse_agent_patch(patch_text)
    report = ApplyReport()

    for op in ops:
        if isinstance(op, AddFileOp):
            target = resolve_path(op.path)
            if target.exists():
                raise PatchApplyError(f"cannot add existing file: {op.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            content = _render_lines(op.plus_lines, prefer_trailing_newline=True)
            target.write_text(content, encoding="utf-8")
            report.added.append(op.path)
            continue

        if isinstance(op, DeleteFileOp):
            target = resolve_path(op.path)
            if not target.exists():
                raise PatchApplyError(f"cannot delete missing file: {op.path}")
            if target.is_dir():
                raise PatchApplyError(f"cannot delete directory with patch: {op.path}")
            target.unlink()
            report.deleted.append(op.path)
            continue

        if isinstance(op, UpdateFileOp):
            source = resolve_path(op.path)
            if not source.exists():
                raise PatchApplyError(f"cannot update missing file: {op.path}")
            if source.is_dir():
                raise PatchApplyError(f"cannot update directory: {op.path}")
            original_text = source.read_text(encoding="utf-8", errors="replace")
            old_lines = original_text.splitlines()
            had_trailing_nl = original_text.endswith("\n")
            working = list(old_lines)

            cursor = 0
            chunks = _parse_chunks(op.raw_lines)
            for chunk in chunks:
                old_seq, new_seq = _chunk_to_old_new(chunk)
                idx = _find_subsequence(working, old_seq, cursor)
                if idx < 0:
                    idx = _find_subsequence(working, old_seq, 0)
                if idx < 0:
                    preview = "\n".join(old_seq[:8])
                    raise PatchApplyError(
                        f"failed applying chunk to {op.path}; could not locate:\n{preview}"
                    )
                working = working[:idx] + new_seq + working[idx + len(old_seq) :]
                cursor = idx + len(new_seq)

            output = _render_lines(working, prefer_trailing_newline=had_trailing_nl)
            destination = source
            if op.move_to:
                destination = resolve_path(op.move_to)
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.unlink()
                report.moved.append(f"{op.path} -> {op.move_to}")

            destination.write_text(output, encoding="utf-8")
            report.updated.append(op.move_to or op.path)
            continue

    return report
