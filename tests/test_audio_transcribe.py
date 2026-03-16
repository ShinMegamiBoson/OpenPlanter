from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.tool_defs import TOOL_DEFINITIONS
from agent.tools import ToolError, WorkspaceTools


def _write_audio(path: Path, payload: bytes = b"RIFF\x00\x00\x00\x00WAVEfmt ") -> None:
    path.write_bytes(payload)


def _make_tools(tmp_path: Path, **overrides: object) -> WorkspaceTools:
    defaults: dict[str, object] = {
        "root": tmp_path,
        "mistral_transcription_api_key": "mistral-key",
        "max_file_chars": 20_000,
        "max_observation_chars": 20_000,
    }
    defaults.update(overrides)
    return WorkspaceTools(**defaults)


class TestAudioTranscribeTool:
    def test_audio_transcribe_success_returns_wrapped_response(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio)
        tools = _make_tools(tmp_path)
        mocked = {
            "text": "hello world",
            "chunks": [{"text": "hello world", "timestamps": [0.0, 1.0]}],
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tools,
                "_mistral_transcription_request",
                lambda **_: mocked,
            )
            raw = tools.audio_transcribe(
                "clip.wav",
                diarize=True,
                timestamp_granularities=["segment"],
                context_bias=["OpenPlanter", "Mistral"],
                model="voxtral-mini-latest",
                temperature=0.2,
            )

        parsed = json.loads(raw)
        assert parsed["provider"] == "mistral"
        assert parsed["path"] == "clip.wav"
        assert parsed["text"] == "hello world"
        assert parsed["options"]["diarize"] is True
        assert parsed["options"]["timestamp_granularities"] == ["segment"]
        assert parsed["options"]["context_bias"] == ["OpenPlanter", "Mistral"]
        assert parsed["response"]["chunks"][0]["text"] == "hello world"

    def test_audio_transcribe_requires_key(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio)
        tools = WorkspaceTools(root=tmp_path)
        out = tools.audio_transcribe("clip.wav")
        assert "Mistral transcription API key not configured" in out

    def test_audio_transcribe_rejects_language_with_timestamps(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio)
        tools = _make_tools(tmp_path)
        out = tools.audio_transcribe(
            "clip.wav",
            language="en",
            timestamp_granularities=["word"],
        )
        assert "cannot be combined" in out

    def test_audio_transcribe_rejects_non_audio_extension(self, tmp_path: Path) -> None:
        note = tmp_path / "notes.txt"
        note.write_text("hello", encoding="utf-8")
        tools = _make_tools(tmp_path)
        out = tools.audio_transcribe("notes.txt")
        assert "Unsupported audio format" in out

    def test_audio_transcribe_path_escape_blocked(self, tmp_path: Path) -> None:
        tools = _make_tools(tmp_path)
        with pytest.raises(ToolError, match="escapes workspace"):
            tools.audio_transcribe("../../etc/passwd.wav")

    def test_audio_transcribe_auto_chunks_oversize_files(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 1_200_000)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=1_100_000,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)
            mp.setattr(tools, "_probe_media_duration", lambda _: 50.0)

            def fake_extract(
                source: Path,
                output: Path,
                *,
                start_sec: float,
                duration_sec: float,
            ) -> None:
                output.write_bytes(b"chunk")

            responses = iter(
                [
                    {
                        "text": "hello there general kenobi from tatooine",
                        "segments": [
                            {
                                "text": "hello there general kenobi from tatooine",
                                "start": 0.0,
                                "end": 4.0,
                                "speaker": "speaker_a",
                            }
                        ],
                    },
                    {
                        "text": "there general kenobi from tatooine today",
                        "segments": [
                            {
                                "text": "there general kenobi from tatooine today",
                                "start": 0.0,
                                "end": 4.0,
                                "speaker": "speaker_a",
                            }
                        ],
                    },
                ]
            )
            mp.setattr(tools, "_extract_audio_chunk", fake_extract)
            mp.setattr(
                tools,
                "_mistral_transcription_request",
                lambda **_: next(responses),
            )

            raw = tools.audio_transcribe(
                "clip.wav",
                diarize=True,
                chunk_max_seconds=30,
                chunk_overlap_seconds=2,
            )

        parsed = json.loads(raw)
        assert parsed["mode"] == "chunked"
        assert parsed["text"] == "hello there general kenobi from tatooine today"
        assert parsed["chunking"]["total_chunks"] == 2
        assert parsed["response"]["segments"][0]["speaker"] == "c0_speaker_a"
        assert parsed["response"]["segments"][1]["speaker"] == "c1_speaker_a"
        assert parsed["response"]["segments"][1]["start"] == pytest.approx(
            parsed["chunking"]["chunk_seconds"], abs=0.01
        )
        assert parsed["response"]["segments"][1]["end"] == pytest.approx(
            parsed["chunking"]["chunk_seconds"] + 2.0, abs=0.01
        )

    def test_audio_transcribe_off_keeps_oversize_rejection(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 512)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=64,
        )
        out = tools.audio_transcribe("clip.wav", chunking="off")
        assert "Audio file too large" in out

    def test_audio_transcribe_preserves_byte_budgeted_chunk_size(
        self, tmp_path: Path
    ) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 512)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=300_000,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)
            mp.setattr(tools, "_probe_media_duration", lambda _: 35.0)

            def fake_extract(
                source: Path,
                output: Path,
                *,
                start_sec: float,
                duration_sec: float,
            ) -> None:
                output.write_bytes(b"x" * int(duration_sec * 32_000))

            observed_sizes: list[int] = []

            def fake_request(*, resolved: Path, **_: object) -> dict[str, object]:
                observed_sizes.append(resolved.stat().st_size)
                if observed_sizes[-1] > tools.mistral_transcription_max_bytes:
                    raise ToolError(
                        f"Audio file too large: {observed_sizes[-1]:,} bytes "
                        f"(max {tools.mistral_transcription_max_bytes:,} bytes)"
                    )
                return {"text": f"chunk {len(observed_sizes)}"}

            mp.setattr(tools, "_extract_audio_chunk", fake_extract)
            mp.setattr(tools, "_mistral_transcription_request", fake_request)

            raw = tools.audio_transcribe(
                "clip.wav",
                chunking="force",
                chunk_max_seconds=30,
                chunk_overlap_seconds=0,
            )

        parsed = json.loads(raw)
        assert parsed["mode"] == "chunked"
        assert parsed["chunking"]["chunk_seconds"] < 30
        assert observed_sizes
        assert max(observed_sizes) <= tools.mistral_transcription_max_bytes

    def test_audio_transcribe_force_chunks_even_when_under_limit(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 32)
        tools = _make_tools(tmp_path)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)
            mp.setattr(tools, "_probe_media_duration", lambda _: 58.0)
            mp.setattr(
                tools,
                "_extract_audio_chunk",
                lambda *args, **kwargs: kwargs["output"].write_bytes(b"chunk"),
                raising=False,
            )
            responses = iter(
                [
                    {"text": "one two three four five"},
                    {"text": "three four five six"},
                ]
            )

            def fake_chunk(
                source: Path,
                output: Path,
                *,
                start_sec: float,
                duration_sec: float,
            ) -> None:
                output.write_bytes(b"chunk")

            mp.setattr(tools, "_extract_audio_chunk", fake_chunk)
            mp.setattr(
                tools,
                "_mistral_transcription_request",
                lambda **_: next(responses),
            )
            raw = tools.audio_transcribe(
                "clip.wav",
                chunking="force",
                chunk_max_seconds=30,
                chunk_overlap_seconds=2,
            )

        parsed = json.loads(raw)
        assert parsed["mode"] == "chunked"
        assert parsed["options"]["chunking"] == "force"

    def test_audio_transcribe_reports_missing_media_tools(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 512)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=64,
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tools,
                "_ensure_media_tools",
                lambda: (_ for _ in ()).throw(
                    ToolError(
                        "Long-form transcription requires ffmpeg, ffprobe. Install ffmpeg/ffprobe and retry."
                    )
                ),
            )
            out = tools.audio_transcribe("clip.wav")
        assert "ffmpeg" in out and "ffprobe" in out

    def test_audio_transcribe_extracts_video_before_upload(self, tmp_path: Path) -> None:
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"video")
        tools = _make_tools(tmp_path)
        extracted: dict[str, str] = {}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)

            def fake_extract(source: Path, output: Path) -> None:
                extracted["source"] = source.name
                output.write_bytes(b"wav")

            def fake_request(*, resolved: Path, **_: object) -> dict[str, object]:
                extracted["uploaded_suffix"] = resolved.suffix
                return {"text": "video transcript"}

            mp.setattr(tools, "_extract_audio_source", fake_extract)
            mp.setattr(tools, "_mistral_transcription_request", fake_request)
            raw = tools.audio_transcribe("clip.mp4", chunking="off")

        parsed = json.loads(raw)
        assert extracted["source"] == "clip.mp4"
        assert extracted["uploaded_suffix"] == ".wav"
        assert parsed["text"] == "video transcript"

    def test_audio_transcribe_fail_fast_on_chunk_error(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 1_200_000)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=1_100_000,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)
            mp.setattr(tools, "_probe_media_duration", lambda _: 50.0)

            def fake_extract(
                source: Path,
                output: Path,
                *,
                start_sec: float,
                duration_sec: float,
            ) -> None:
                output.write_bytes(b"chunk")

            calls = {"count": 0}

            def fake_request(**_: object) -> dict[str, object]:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise ToolError("boom")
                return {"text": "alpha beta gamma delta epsilon"}

            mp.setattr(tools, "_extract_audio_chunk", fake_extract)
            mp.setattr(tools, "_mistral_transcription_request", fake_request)
            out = tools.audio_transcribe(
                "clip.wav",
                chunk_max_seconds=30,
                chunk_overlap_seconds=2,
            )

        assert "audio_transcribe failed in chunk 1" in out

    def test_audio_transcribe_can_return_partial_chunked_output(self, tmp_path: Path) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio, payload=b"x" * 1_200_000)
        tools = _make_tools(
            tmp_path,
            mistral_transcription_max_bytes=1_100_000,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_ensure_media_tools", lambda: None)
            mp.setattr(tools, "_probe_media_duration", lambda _: 60.0)

            def fake_extract(
                source: Path,
                output: Path,
                *,
                start_sec: float,
                duration_sec: float,
            ) -> None:
                output.write_bytes(b"chunk")

            calls = {"count": 0}

            def fake_request(**_: object) -> dict[str, object]:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise ToolError("boom")
                return {"text": f"chunk {calls['count']} transcript words words words"}

            mp.setattr(tools, "_extract_audio_chunk", fake_extract)
            mp.setattr(tools, "_mistral_transcription_request", fake_request)
            raw = tools.audio_transcribe(
                "clip.wav",
                chunk_max_seconds=30,
                chunk_overlap_seconds=1,
                continue_on_chunk_error=True,
            )

        parsed = json.loads(raw)
        assert parsed["chunking"]["partial"] is True
        assert parsed["chunking"]["failed_chunks"] == 1
        assert parsed["warnings"][0].startswith("chunk 1 failed")

    def test_audio_transcribe_structured_truncation_keeps_valid_json(
        self,
        tmp_path: Path,
    ) -> None:
        audio = tmp_path / "clip.wav"
        _write_audio(audio)
        tools = _make_tools(
            tmp_path,
            max_file_chars=400,
            max_observation_chars=400,
        )
        mocked = {
            "text": "word " * 200,
            "segments": [
                {"text": "segment", "start": 0.0, "end": 1.0, "speaker": "speaker_a"}
                for _ in range(30)
            ],
            "words": [
                {"text": "word", "start": 0.0, "end": 0.1, "speaker": "speaker_a"}
                for _ in range(60)
            ],
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tools, "_mistral_transcription_request", lambda **_: mocked)
            raw = tools.audio_transcribe("clip.wav")

        parsed = json.loads(raw)
        assert parsed["truncation"]["applied"] is True
        assert "text_truncated_chars" in parsed["truncation"]


class TestAudioTranscribeToolDef:
    def test_audio_transcribe_in_tool_definitions(self) -> None:
        names = [d["name"] for d in TOOL_DEFINITIONS]
        assert "audio_transcribe" in names

    def test_audio_transcribe_definition_schema(self) -> None:
        defn = next(d for d in TOOL_DEFINITIONS if d["name"] == "audio_transcribe")
        assert defn["parameters"]["required"] == ["path"]
        props = defn["parameters"]["properties"]
        assert "context_bias" in props
        assert props["context_bias"]["type"] == "array"
        assert props["chunking"]["enum"] == ["auto", "off", "force"]
        assert props["chunk_max_seconds"]["type"] == "integer"
        assert props["continue_on_chunk_error"]["type"] == "boolean"
