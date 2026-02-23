"""Adapter layer for the Anthropic Agent SDK.

This module isolates all Agent SDK-specific imports behind a stable interface.
If the SDK's actual API surface differs from what's documented in the tech plan,
only this file needs to change.

Current state: The SDK package name (claude-agent-sdk or anthropic-agent-sdk)
is not yet verified on PyPI. This adapter provides a fallback implementation
using the standard anthropic Python SDK for basic chat functionality, with
the adapter interface ready to swap in the Agent SDK when available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol


# ---------------------------------------------------------------------------
# Stream event types
# ---------------------------------------------------------------------------

@dataclass
class StreamEvent:
    """A single event from the agent's response stream.

    Attributes
    ----------
    event_type : str
        One of: 'text_delta', 'tool_call', 'tool_result', 'message_complete', 'error'.
    content : str
        The text content (for text_delta and message_complete).
    tool_name : str
        Tool name (for tool_call and tool_result).
    tool_input : dict
        Tool input parameters (for tool_call).
    tool_output : str
        Tool output (for tool_result).
    """

    event_type: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    """A tool that can be called by the agent.

    Attributes
    ----------
    name : str
        The tool name as exposed to the agent.
    description : str
        Description of what the tool does.
    parameters : dict
        JSON Schema for the tool's parameters.
    handler : Callable
        The async function to call when the agent invokes this tool.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable


class ToolServer:
    """Registry of tools available to the agent.

    Wraps tool definitions into the format expected by the Anthropic API
    (or Agent SDK when available).
    """

    def __init__(self, name: str, tools: list[ToolDefinition] | None = None) -> None:
        self.name = name
        self._tools: dict[str, ToolDefinition] = {}
        if tools:
            for tool in tools:
                self._tools[tool.name] = tool

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Convert tools to the Anthropic API tool format.

        Returns a list of tool definitions compatible with the
        anthropic Python SDK's messages API.
        """
        tools = []
        for td in self._tools.values():
            tools.append({
                "name": td.name,
                "description": td.description,
                "input_schema": td.parameters,
            })
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a registered tool by name with the given arguments.

        Returns the tool's string output.
        """
        tool_def = self._tools.get(name)
        if tool_def is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            result = await tool_def.handler(**arguments)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": f"Tool error: {str(exc)}"})


# ---------------------------------------------------------------------------
# Agent client protocol
# ---------------------------------------------------------------------------

class AgentClientProtocol(Protocol):
    """Protocol for agent clients (SDK or fallback)."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: ToolServer,
    ) -> AsyncIterator[StreamEvent]:
        """Send messages and stream the response."""
        ...


# ---------------------------------------------------------------------------
# Fallback client using standard anthropic SDK
# ---------------------------------------------------------------------------

class AnthropicFallbackClient:
    """Agent client using the standard anthropic Python SDK.

    Provides chat with tool use via the Messages API. This is the fallback
    when the Agent SDK package is not available.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily initialize the anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "The 'anthropic' package is required. "
                    "Install it with: pip install anthropic"
                )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: ToolServer,
    ) -> AsyncIterator[StreamEvent]:
        """Send messages and yield StreamEvents.

        Handles the tool-use loop: when the model requests a tool call,
        executes it and continues the conversation until the model produces
        a final text response.
        """
        client = self._get_client()
        anthropic_tools = tools.to_anthropic_tools()
        conversation = list(messages)

        while True:
            # Make the API call
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=conversation,
                tools=anthropic_tools if anthropic_tools else None,
            )

            # Process content blocks
            tool_calls_in_response = []
            full_text = ""

            for block in response.content:
                if block.type == "text":
                    full_text += block.text
                    yield StreamEvent(
                        event_type="text_delta",
                        content=block.text,
                    )
                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input if isinstance(block.input, dict) else {}
                    tool_id = block.id

                    yield StreamEvent(
                        event_type="tool_call",
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )

                    # Execute the tool
                    result = await tools.call_tool(tool_name, tool_input)

                    yield StreamEvent(
                        event_type="tool_result",
                        tool_name=tool_name,
                        tool_output=result,
                    )

                    tool_calls_in_response.append({
                        "id": tool_id,
                        "name": tool_name,
                        "input": tool_input,
                        "result": result,
                    })

            # If no tool calls, we're done
            if not tool_calls_in_response:
                yield StreamEvent(
                    event_type="message_complete",
                    content=full_text,
                )
                return

            # If tool calls happened, continue the conversation
            # Add assistant message with tool_use blocks
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({
                        "type": "text",
                        "text": block.text,
                    })
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input if isinstance(block.input, dict) else {},
                    })

            conversation.append({"role": "assistant", "content": assistant_content})

            # Add tool results
            tool_results_content = []
            for tc in tool_calls_in_response:
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": tc["result"],
                })

            conversation.append({"role": "user", "content": tool_results_content})

            # If stop_reason is end_turn (not tool_use), we're done
            if response.stop_reason != "tool_use":
                yield StreamEvent(
                    event_type="message_complete",
                    content=full_text,
                )
                return
