"""Tests for the read_image tool and image propagation through the model layer."""
from __future__ import annotations

import base64
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agent.model import (
    AnthropicModel,
    Conversation,
    ImageData,
    OpenAICompatibleModel,
    ToolResult,
)
from agent.tools import WorkspaceTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_png(width: int = 1, height: int = 1) -> bytes:
    """Create a minimal valid PNG (1x1 red pixel)."""
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    # Single row: filter byte 0 + RGB
    raw_row = b"\x00\xff\x00\x00"
    idat = _chunk(b"IDAT", zlib.compress(raw_row))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


# ---------------------------------------------------------------------------
# WorkspaceTools.read_image tests
# ---------------------------------------------------------------------------


class TestReadImage:
    def test_read_image_returns_base64(self, tmp_path: Path) -> None:
        png_data = _make_minimal_png()
        img_path = tmp_path / "test.png"
        img_path.write_bytes(png_data)

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("test.png")

        assert b64 is not None
        assert media_type == "image/png"
        assert base64.b64decode(b64) == png_data
        assert "test.png" in text
        assert "image/png" in text

    def test_read_image_jpeg(self, tmp_path: Path) -> None:
        # Just need a file with .jpg extension; content doesn't need to be valid JPEG.
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0dummy-jpeg")

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("photo.jpg")

        assert b64 is not None
        assert media_type == "image/jpeg"

    def test_read_image_jpeg_extension(self, tmp_path: Path) -> None:
        img_path = tmp_path / "photo.jpeg"
        img_path.write_bytes(b"\xff\xd8\xff\xe0dummy-jpeg")

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("photo.jpeg")

        assert b64 is not None
        assert media_type == "image/jpeg"

    def test_read_image_gif(self, tmp_path: Path) -> None:
        img_path = tmp_path / "anim.gif"
        img_path.write_bytes(b"GIF89a-dummy")

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("anim.gif")

        assert b64 is not None
        assert media_type == "image/gif"

    def test_read_image_webp(self, tmp_path: Path) -> None:
        img_path = tmp_path / "pic.webp"
        img_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("pic.webp")

        assert b64 is not None
        assert media_type == "image/webp"

    def test_read_image_invalid_extension(self, tmp_path: Path) -> None:
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("hello")

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("notes.txt")

        assert b64 is None
        assert media_type is None
        assert "Unsupported image format" in text

    def test_read_image_not_found(self, tmp_path: Path) -> None:
        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("missing.png")

        assert b64 is None
        assert media_type is None
        assert "not found" in text.lower()

    def test_read_image_directory(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("subdir")

        assert b64 is None
        assert "directory" in text.lower()

    def test_read_image_too_large(self, tmp_path: Path) -> None:
        img_path = tmp_path / "huge.png"
        # Write a file just over the limit
        img_path.write_bytes(b"\x00" * (20 * 1024 * 1024 + 1))

        tools = WorkspaceTools(root=tmp_path)
        text, b64, media_type = tools.read_image("huge.png")

        assert b64 is None
        assert media_type is None
        assert "too large" in text.lower()

    def test_read_image_path_escape_blocked(self, tmp_path: Path) -> None:
        from agent.tools import ToolError

        tools = WorkspaceTools(root=tmp_path)
        with pytest.raises(ToolError, match="escapes workspace"):
            tools.read_image("../../etc/passwd.png")


# ---------------------------------------------------------------------------
# Model layer: Anthropic tool result formatting with image
# ---------------------------------------------------------------------------


class TestAnthropicToolResultWithImage:
    def test_image_tool_result_uses_content_array(self) -> None:
        model = AnthropicModel(model="test", api_key="test")
        conv = Conversation(
            _provider_messages=[{"role": "user", "content": "hello"}],
            system_prompt="sys",
        )
        result = ToolResult(
            tool_call_id="tc1",
            name="read_image",
            content="Image test.png (100 bytes, image/png)",
            image=ImageData(base64_data="AAAA", media_type="image/png"),
        )
        model.append_tool_results(conv, [result])

        # The last message should be a user message with tool_result blocks
        last_msg = conv._provider_messages[-1]
        assert last_msg["role"] == "user"
        blocks = last_msg["content"]
        assert isinstance(blocks, list)
        assert len(blocks) == 1

        tr_block = blocks[0]
        assert tr_block["type"] == "tool_result"
        assert tr_block["tool_use_id"] == "tc1"

        # Content should be an array with image + text blocks
        content = tr_block["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[0]["source"]["data"] == "AAAA"
        assert content[1]["type"] == "text"
        assert "test.png" in content[1]["text"]

    def test_no_image_uses_string_content(self) -> None:
        model = AnthropicModel(model="test", api_key="test")
        conv = Conversation(
            _provider_messages=[{"role": "user", "content": "hello"}],
            system_prompt="sys",
        )
        result = ToolResult(
            tool_call_id="tc1",
            name="read_file",
            content="file contents here",
        )
        model.append_tool_results(conv, [result])

        last_msg = conv._provider_messages[-1]
        tr_block = last_msg["content"][0]
        # Content should be a plain string
        assert tr_block["content"] == "file contents here"


# ---------------------------------------------------------------------------
# Model layer: OpenAI tool result formatting with image
# ---------------------------------------------------------------------------


class TestOpenAIToolResultWithImage:
    def test_image_injects_user_message(self) -> None:
        model = OpenAICompatibleModel(
            model="test", api_key="test", strict_tools=False,
        )
        conv = Conversation(
            _provider_messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
            ],
            system_prompt="sys",
        )
        result = ToolResult(
            tool_call_id="tc1",
            name="read_image",
            content="Image test.png (100 bytes, image/png)",
            image=ImageData(base64_data="AAAA", media_type="image/png"),
        )
        model.append_tool_results(conv, [result])

        msgs = conv._provider_messages
        # Should have: system, user, tool, user(image)
        assert len(msgs) == 4

        # Tool result message
        tool_msg = msgs[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "tc1"

        # Injected user message with image
        user_msg = msgs[3]
        assert user_msg["role"] == "user"
        content = user_msg["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "text"
        assert "[Image from read_image:" in content[1]["text"]

    def test_no_image_no_extra_message(self) -> None:
        model = OpenAICompatibleModel(
            model="test", api_key="test", strict_tools=False,
        )
        conv = Conversation(
            _provider_messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hello"},
            ],
            system_prompt="sys",
        )
        result = ToolResult(
            tool_call_id="tc1",
            name="read_file",
            content="file contents",
        )
        model.append_tool_results(conv, [result])

        msgs = conv._provider_messages
        # Should have: system, user, tool (no extra user message)
        assert len(msgs) == 3
        assert msgs[2]["role"] == "tool"


# ---------------------------------------------------------------------------
# Engine integration: read_image populates image data on ToolResult
# ---------------------------------------------------------------------------


class TestEngineReadImage:
    def test_engine_read_image_populates_image_data(self, tmp_path: Path) -> None:
        """End-to-end: engine._run_one_tool for read_image produces ToolResult with image."""
        from agent.config import AgentConfig
        from agent.engine import RLMEngine
        from agent.model import ScriptedModel, ToolCall

        png_data = _make_minimal_png()
        img = tmp_path / "chart.png"
        img.write_bytes(png_data)

        cfg = AgentConfig(workspace=tmp_path)
        model = ScriptedModel()
        tools = WorkspaceTools(root=tmp_path)
        engine = RLMEngine(model=model, tools=tools, config=cfg)

        tc = ToolCall(id="call_1", name="read_image", arguments={"path": "chart.png"})

        result, is_final = engine._run_one_tool(
            tc=tc, depth=0, step=1, objective="test",
            context=None or __import__("agent.engine", fromlist=["ExternalContext"]).ExternalContext(),
            on_event=None, on_step=None, deadline=0,
            current_model=model, replay_logger=None,
        )

        assert not is_final
        assert result.image is not None
        assert result.image.media_type == "image/png"
        assert base64.b64decode(result.image.base64_data) == png_data
        assert "chart.png" in result.content

    def test_engine_read_image_error_no_image_data(self, tmp_path: Path) -> None:
        """Engine read_image on a missing file: ToolResult.image should be None."""
        from agent.config import AgentConfig
        from agent.engine import ExternalContext, RLMEngine
        from agent.model import ScriptedModel, ToolCall

        cfg = AgentConfig(workspace=tmp_path)
        model = ScriptedModel()
        tools = WorkspaceTools(root=tmp_path)
        engine = RLMEngine(model=model, tools=tools, config=cfg)

        tc = ToolCall(id="call_1", name="read_image", arguments={"path": "missing.png"})

        result, is_final = engine._run_one_tool(
            tc=tc, depth=0, step=1, objective="test",
            context=ExternalContext(),
            on_event=None, on_step=None, deadline=0,
            current_model=model, replay_logger=None,
        )

        assert not is_final
        assert result.image is None
        assert "not found" in result.content.lower()

    def test_engine_read_image_empty_path(self, tmp_path: Path) -> None:
        """Engine read_image with empty path returns an error."""
        from agent.config import AgentConfig
        from agent.engine import ExternalContext, RLMEngine
        from agent.model import ScriptedModel, ToolCall

        cfg = AgentConfig(workspace=tmp_path)
        model = ScriptedModel()
        tools = WorkspaceTools(root=tmp_path)
        engine = RLMEngine(model=model, tools=tools, config=cfg)

        tc = ToolCall(id="call_1", name="read_image", arguments={"path": ""})

        result, is_final = engine._run_one_tool(
            tc=tc, depth=0, step=1, objective="test",
            context=ExternalContext(),
            on_event=None, on_step=None, deadline=0,
            current_model=model, replay_logger=None,
        )

        assert not is_final
        assert result.image is None
        assert "requires path" in result.content.lower()


# ---------------------------------------------------------------------------
# Tool definition exists
# ---------------------------------------------------------------------------


class TestReadImageToolDef:
    def test_read_image_in_tool_definitions(self) -> None:
        from agent.tool_defs import TOOL_DEFINITIONS

        names = [d["name"] for d in TOOL_DEFINITIONS]
        assert "read_image" in names

    def test_read_image_definition_schema(self) -> None:
        from agent.tool_defs import TOOL_DEFINITIONS

        defn = next(d for d in TOOL_DEFINITIONS if d["name"] == "read_image")
        assert defn["parameters"]["required"] == ["path"]
        assert "path" in defn["parameters"]["properties"]
