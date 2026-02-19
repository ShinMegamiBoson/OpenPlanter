from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .engine import ContentDeltaCallback, ExternalContext, RLMEngine, StepCallback
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


@dataclass
class SessionRuntime:
    engine: RLMEngine
    store: SessionStore
    session_id: str
    context: ExternalContext
    max_persisted_observations: int = 400

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
        sid, state, created_new = store.open_session(session_id=session_id, resume=resume)
        persisted = state.get("external_observations", [])
        obs = [str(x) for x in persisted] if isinstance(persisted, list) else []
        max_obs = max(1, config.max_persisted_observations)
        context = ExternalContext(observations=obs[-max_obs:])

        engine.session_dir = store._session_dir(sid)
        engine.session_id = sid

        runtime = cls(
            engine=engine,
            store=store,
            session_id=sid,
            context=context,
            max_persisted_observations=max_obs,
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

        result, updated_context = self.engine.solve_with_context(
            objective=objective,
            context=self.context,
            on_event=_on_event,
            on_step=_combined_on_step,
            on_content_delta=on_content_delta,
            replay_logger=replay_logger,
        )
        self.context = updated_context
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
        state = {
            "session_id": self.session_id,
            "saved_at": _utc_now(),
            "external_observations": self.context.observations,
        }
        self.store.save_state(self.session_id, state)

