from __future__ import annotations

import json
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .engine import ContentDeltaCallback, ExternalContext, RLMEngine, StepCallback, TurnSummary
from .replay_log import ReplayLogger

EventCallback = Callable[[str], None]


class SessionError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(3)}"


def _safe_component(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "artifact"


@dataclass
class SessionStore:
    workspace: Path
    session_root_dir: str = ".openplanter"

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        self.root = (self.workspace / self.session_root_dir).resolve()
        self.sessions = self.root / "sessions"
        self.sessions.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions / session_id

    def _metadata_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "metadata.json"

    def _state_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "state.json"

    def _events_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "events.jsonl"

    def _artifacts_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "artifacts"

    def _plan_dir(self, session_id: str) -> Path:
        """Directory where *.plan.md files live (same as session dir)."""
        return self._session_dir(session_id)

    def latest_session_id(self) -> str | None:
        session_dirs = [p for p in self.sessions.iterdir() if p.is_dir()]
        if not session_dirs:
            return None
        latest = max(session_dirs, key=lambda p: p.stat().st_mtime)
        return latest.name

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        session_dirs = sorted(
            (p for p in self.sessions.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for path in session_dirs[:limit]:
            meta_path = path / "metadata.json"
            meta: dict[str, Any] = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            out.append(
                {
                    "session_id": path.name,
                    "path": str(path),
                    "created_at": meta.get("created_at"),
                    "updated_at": meta.get("updated_at"),
                }
            )
        return out

    def open_session(
        self, session_id: str | None = None, resume: bool = False
    ) -> tuple[str, dict[str, Any], bool]:
        sid = session_id
        if resume and sid is None:
            sid = self.latest_session_id()
            if sid is None:
                raise SessionError("No previous sessions found to resume.")
        if sid is None:
            sid = _new_session_id()

        session_dir = self._session_dir(sid)
        created_new = False
        if resume:
            if not session_dir.exists():
                raise SessionError(f"Cannot resume missing session: {sid}")
        else:
            if session_dir.exists():
                sid = f"{sid}-{secrets.token_hex(2)}"
                session_dir = self._session_dir(sid)
            session_dir.mkdir(parents=True, exist_ok=True)
            created_new = True

        session_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir(sid).mkdir(parents=True, exist_ok=True)

        meta_path = self._metadata_path(sid)
        if not meta_path.exists():
            meta = {
                "session_id": sid,
                "workspace": str(self.workspace),
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        state = self.load_state(sid)
        return sid, state, created_new

    def load_state(self, session_id: str) -> dict[str, Any]:
        state_path = self._state_path(session_id)
        if not state_path.exists():
            return {
                "session_id": session_id,
                "external_observations": [],
            }
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SessionError(f"Session state is invalid JSON: {state_path}") from exc

    def save_state(self, session_id: str, state: dict[str, Any]) -> None:
        state_path = self._state_path(session_id)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        self._touch_metadata(session_id)

    def append_event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event_path = self._events_path(session_id)
        event = {
            "ts": _utc_now(),
            "type": event_type,
            "payload": payload,
        }
        with event_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        self._touch_metadata(session_id)

    def write_artifact(
        self, session_id: str, category: str, name: str, content: str
    ) -> str:
        category_safe = _safe_component(category)
        name_safe = _safe_component(name)
        artifact_rel = Path("artifacts") / category_safe / name_safe
        artifact_abs = self._session_dir(session_id) / artifact_rel
        artifact_abs.parent.mkdir(parents=True, exist_ok=True)
        artifact_abs.write_text(content, encoding="utf-8")
        self._touch_metadata(session_id)
        return artifact_rel.as_posix()

    def _touch_metadata(self, session_id: str) -> None:
        meta_path = self._metadata_path(session_id)
        base: dict[str, Any] = {}
        if meta_path.exists():
            try:
                base = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                base = {}
        base["session_id"] = session_id
        base["workspace"] = str(self.workspace)
        base.setdefault("created_at", _utc_now())
        base["updated_at"] = _utc_now()
        meta_path.write_text(json.dumps(base, indent=2), encoding="utf-8")


def _seed_wiki(workspace: Path, session_root_dir: str) -> None:
    """Copy baseline wiki/ into the runtime .openplanter/wiki/ directory.

    On first run, copies the entire tree. On subsequent runs, copies only
    new baseline files — never overwrites agent-modified entries.
    """
    baseline = workspace / "wiki"
    if not baseline.is_dir():
        return
    runtime_wiki = workspace / session_root_dir / "wiki"
    if not runtime_wiki.exists():
        shutil.copytree(
            baseline,
            runtime_wiki,
            ignore=shutil.ignore_patterns(".*", "__pycache__"),
        )
        return
    # Incremental: copy only new baseline files
    for src in baseline.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(baseline)
        if any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
            continue
        dst = runtime_wiki / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


@dataclass
class SessionRuntime:
    engine: RLMEngine
    store: SessionStore
    session_id: str
    context: ExternalContext
    max_persisted_observations: int = 400
    turn_history: list[TurnSummary] | None = None
    max_turn_summaries: int = 50
    loop_metrics: dict[str, Any] | None = None

    @classmethod
    def bootstrap(
        cls,
        engine: RLMEngine,
        config: AgentConfig,
        session_id: str | None = None,
        resume: bool = False,
    ) -> "SessionRuntime":
        store = SessionStore(
            workspace=config.workspace,
            session_root_dir=config.session_root_dir,
        )
        try:
            _seed_wiki(config.workspace, config.session_root_dir)
        except OSError:
            pass
        sid, state, created_new = store.open_session(session_id=session_id, resume=resume)
        persisted = state.get("external_observations", [])
        obs = [str(x) for x in persisted] if isinstance(persisted, list) else []
        max_obs = max(1, config.max_persisted_observations)
        context = ExternalContext(observations=obs[-max_obs:])

        engine.session_dir = store._session_dir(sid)
        engine.session_id = sid

        # Load turn history from persisted state
        raw_history = state.get("turn_history", [])
        turn_history: list[TurnSummary] = []
        if isinstance(raw_history, list):
            for item in raw_history:
                if isinstance(item, dict):
                    try:
                        turn_history.append(TurnSummary.from_dict(item))
                    except (KeyError, TypeError):
                        pass
        max_turns = max(1, config.max_turn_summaries)
        raw_loop_metrics = state.get("loop_metrics", {})
        loop_metrics: dict[str, Any] = raw_loop_metrics if isinstance(raw_loop_metrics, dict) else {}
        loop_metrics.setdefault("turns", 0)
        loop_metrics.setdefault("steps", 0)
        loop_metrics.setdefault("model_turns", 0)
        loop_metrics.setdefault("tool_calls", 0)
        loop_metrics.setdefault("guardrail_warnings", 0)
        loop_metrics.setdefault("final_rejections", 0)
        loop_metrics.setdefault("phase_counts", {})
        if not isinstance(loop_metrics["phase_counts"], dict):
            loop_metrics["phase_counts"] = {}
        for phase in ("investigate", "build", "iterate", "finalize"):
            loop_metrics["phase_counts"].setdefault(phase, 0)

        runtime = cls(
            engine=engine,
            store=store,
            session_id=sid,
            context=context,
            max_persisted_observations=max_obs,
            turn_history=turn_history[-max_turns:],
            max_turn_summaries=max_turns,
            loop_metrics=loop_metrics,
        )
        try:
            runtime.store.append_event(
                sid,
                "session_started",
                {"resume": resume, "created_new": created_new},
            )
        except OSError:
            pass
        try:
            runtime._persist_state()
        except OSError:
            pass
        return runtime

    def solve(
        self,
        objective: str,
        on_event: EventCallback | None = None,
        on_step: StepCallback | None = None,
        on_content_delta: ContentDeltaCallback | None = None,
    ) -> str:
        objective = objective.strip()
        if not objective:
            return "No objective provided."

        try:
            self.store.append_event(
                self.session_id,
                "objective",
                {"text": objective},
            )
        except OSError:
            pass
        patch_counter = 0

        def _on_event(msg: str) -> None:
            try:
                self.store.append_event(
                    self.session_id,
                    "trace",
                    {"message": msg},
                )
            except OSError:
                pass
            if on_event:
                on_event(msg)

        def _combined_on_step(step_event: dict[str, Any]) -> None:
            nonlocal patch_counter
            try:
                self.store.append_event(self.session_id, "step", step_event)
            except OSError:
                pass
            action = step_event.get("action")
            if isinstance(action, dict) and action.get("name") == "apply_patch":
                patch_text = str(action.get("arguments", {}).get("patch", ""))
                if patch_text.strip():
                    patch_counter += 1
                    name = (
                        f"patch-d{step_event.get('depth', 0)}"
                        f"-s{step_event.get('step', 0)}-{patch_counter}.patch"
                    )
                    try:
                        artifact_rel = self.store.write_artifact(
                            self.session_id,
                            category="patches",
                            name=name,
                            content=patch_text,
                        )
                        self.store.append_event(
                            self.session_id,
                            "artifact",
                            {"kind": "patch", "path": artifact_rel},
                        )
                    except OSError:
                        pass
            # Forward to external on_step callback
            if on_step:
                try:
                    on_step(step_event)
                except Exception:
                    pass

        replay_path = self.store._session_dir(self.session_id) / "replay.jsonl"
        replay_logger = ReplayLogger(path=replay_path)
        replay_seq_start = replay_logger._seq

        result, updated_context = self.engine.solve_with_context(
            objective=objective,
            context=self.context,
            on_event=_on_event,
            on_step=_combined_on_step,
            on_content_delta=on_content_delta,
            replay_logger=replay_logger,
            turn_history=self.turn_history,
        )
        self.context = updated_context

        latest_loop_metrics = self.engine.last_loop_metrics if isinstance(self.engine.last_loop_metrics, dict) else {}
        if self.loop_metrics is None:
            self.loop_metrics = {
                "turns": 0,
                "steps": 0,
                "model_turns": 0,
                "tool_calls": 0,
                "guardrail_warnings": 0,
                "final_rejections": 0,
                "phase_counts": {"investigate": 0, "build": 0, "iterate": 0, "finalize": 0},
            }
        self.loop_metrics["turns"] = int(self.loop_metrics.get("turns", 0)) + 1
        self.loop_metrics["steps"] = int(self.loop_metrics.get("steps", 0)) + int(latest_loop_metrics.get("steps", 0))
        self.loop_metrics["model_turns"] = int(self.loop_metrics.get("model_turns", 0)) + int(latest_loop_metrics.get("model_turns", 0))
        self.loop_metrics["tool_calls"] = int(self.loop_metrics.get("tool_calls", 0)) + int(latest_loop_metrics.get("tool_calls", 0))
        self.loop_metrics["guardrail_warnings"] = int(self.loop_metrics.get("guardrail_warnings", 0)) + int(latest_loop_metrics.get("guardrail_warnings", 0))
        self.loop_metrics["final_rejections"] = int(self.loop_metrics.get("final_rejections", 0)) + int(latest_loop_metrics.get("final_rejections", 0))
        phase_counts = self.loop_metrics.setdefault("phase_counts", {})
        latest_phase_counts = latest_loop_metrics.get("phase_counts", {})
        if not isinstance(phase_counts, dict):
            phase_counts = {}
            self.loop_metrics["phase_counts"] = phase_counts
        if not isinstance(latest_phase_counts, dict):
            latest_phase_counts = {}
        for phase in ("investigate", "build", "iterate", "finalize"):
            phase_counts[phase] = int(phase_counts.get(phase, 0)) + int(latest_phase_counts.get(phase, 0))
        self.loop_metrics["last_turn"] = latest_loop_metrics

        # Generate turn summary
        if self.turn_history is None:
            self.turn_history = []
        turn_number = (self.turn_history[-1].turn_number + 1) if self.turn_history else 1
        result_preview = result[:200] + "..." if len(result) > 200 else result
        steps_used = replay_logger._seq - replay_seq_start
        summary = TurnSummary(
            turn_number=turn_number,
            objective=objective,
            result_preview=result_preview,
            timestamp=_utc_now(),
            steps_used=steps_used,
            replay_seq_start=replay_seq_start,
        )
        self.turn_history.append(summary)
        if len(self.turn_history) > self.max_turn_summaries:
            self.turn_history = self.turn_history[-self.max_turn_summaries:]
        try:
            self.store.append_event(
                self.session_id,
                "result",
                {"text": result},
            )
        except OSError:
            pass
        try:
            self._persist_state()
        except OSError:
            pass
        return result

    def _persist_state(self) -> None:
        if len(self.context.observations) > self.max_persisted_observations:
            self.context.observations = self.context.observations[-self.max_persisted_observations :]
        state: dict[str, Any] = {
            "session_id": self.session_id,
            "saved_at": _utc_now(),
            "external_observations": self.context.observations,
        }
        if self.turn_history:
            state["turn_history"] = [t.to_dict() for t in self.turn_history]
        if self.loop_metrics:
            state["loop_metrics"] = self.loop_metrics
        self.store.save_state(self.session_id, state)
