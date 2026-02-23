"""Tests for the SDK adapter layer."""

from __future__ import annotations

import json

import pytest

from redthread.agent.sdk_adapter import (
    StreamEvent,
    ToolDefinition,
    ToolServer,
)


# -- StreamEvent tests -------------------------------------------------------

def test_stream_event_text_delta():
    event = StreamEvent(event_type="text_delta", content="hello")
    assert event.event_type == "text_delta"
    assert event.content == "hello"
    assert event.tool_name == ""


def test_stream_event_tool_call():
    event = StreamEvent(
        event_type="tool_call",
        tool_name="web_search",
        tool_input={"query": "test"},
    )
    assert event.event_type == "tool_call"
    assert event.tool_name == "web_search"
    assert event.tool_input == {"query": "test"}


def test_stream_event_defaults():
    event = StreamEvent(event_type="message_complete")
    assert event.content == ""
    assert event.tool_name == ""
    assert event.tool_input == {}
    assert event.tool_output == ""


# -- ToolDefinition tests ----------------------------------------------------

def test_tool_definition_creation():
    async def handler(x: str) -> str:
        return x

    td = ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        handler=handler,
    )
    assert td.name == "test_tool"
    assert td.description == "A test tool"
    assert callable(td.handler)


# -- ToolServer tests --------------------------------------------------------

def test_tool_server_register_and_list():
    server = ToolServer("test")

    async def handler(x: str) -> str:
        return x

    td = ToolDefinition(
        name="my_tool",
        description="My tool",
        parameters={"type": "object"},
        handler=handler,
    )
    server.register(td)
    assert "my_tool" in server.list_tools()


def test_tool_server_get_tool():
    server = ToolServer("test")

    async def handler() -> str:
        return "ok"

    td = ToolDefinition(name="t1", description="t1", parameters={}, handler=handler)
    server.register(td)
    assert server.get_tool("t1") is td
    assert server.get_tool("nonexistent") is None


def test_tool_server_init_with_tools():
    async def handler() -> str:
        return "ok"

    tools = [
        ToolDefinition(name="a", description="a", parameters={}, handler=handler),
        ToolDefinition(name="b", description="b", parameters={}, handler=handler),
    ]
    server = ToolServer("test", tools=tools)
    assert sorted(server.list_tools()) == ["a", "b"]


def test_tool_server_to_anthropic_tools():
    async def handler(query: str) -> str:
        return query

    td = ToolDefinition(
        name="search",
        description="Search",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=handler,
    )
    server = ToolServer("test", [td])
    anthropic_tools = server.to_anthropic_tools()

    assert len(anthropic_tools) == 1
    assert anthropic_tools[0]["name"] == "search"
    assert anthropic_tools[0]["description"] == "Search"
    assert anthropic_tools[0]["input_schema"]["type"] == "object"


@pytest.mark.asyncio
async def test_tool_server_call_tool_success():
    async def greet(name: str) -> str:
        return f"Hello, {name}!"

    td = ToolDefinition(
        name="greet",
        description="Greet",
        parameters={},
        handler=greet,
    )
    server = ToolServer("test", [td])
    result = await server.call_tool("greet", {"name": "World"})
    assert result == "Hello, World!"


@pytest.mark.asyncio
async def test_tool_server_call_tool_unknown():
    server = ToolServer("test")
    result = await server.call_tool("nonexistent", {})
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Unknown tool" in parsed["error"]


@pytest.mark.asyncio
async def test_tool_server_call_tool_error():
    async def failing_tool() -> str:
        raise ValueError("Something went wrong")

    td = ToolDefinition(
        name="fail",
        description="Fails",
        parameters={},
        handler=failing_tool,
    )
    server = ToolServer("test", [td])
    result = await server.call_tool("fail", {})
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Something went wrong" in parsed["error"]


@pytest.mark.asyncio
async def test_tool_server_call_tool_returns_dict():
    """Tool handler returns a dict, server should JSON-encode it."""

    async def dict_tool() -> dict:
        return {"status": "ok"}

    td = ToolDefinition(
        name="dict_tool",
        description="Returns dict",
        parameters={},
        handler=dict_tool,
    )
    server = ToolServer("test", [td])
    result = await server.call_tool("dict_tool", {})
    parsed = json.loads(result)
    assert parsed == {"status": "ok"}
