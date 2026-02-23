"""Redthread agent client — wires together tools, prompts, and the SDK adapter.

The RedthreadAgent is the central orchestrator for investigation conversations.
It manages the tool server, conversation history, and streaming responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from redthread.agent.prompts import SYSTEM_PROMPT, SUB_INVESTIGATOR_PROMPT_TEMPLATE
from redthread.agent.sdk_adapter import (
    AnthropicFallbackClient,
    StreamEvent,
    ToolServer,
)
from redthread.agent.tools import create_tool_server
from redthread.config import Settings
from redthread.db.graph import GraphDB
from redthread.db.repositories import (
    DatasetRepo,
    EvidenceRepo,
    MessageRepo,
    TimelineEventRepo,
)
from redthread.db.sqlite import SQLiteDB
from redthread.search.exa import ExaClient


@dataclass
class Repositories:
    """Container for all repository instances used by the agent."""

    dataset_repo: DatasetRepo
    evidence_repo: EvidenceRepo
    timeline_repo: TimelineEventRepo
    message_repo: MessageRepo


class RedthreadAgent:
    """Central agent client for investigation conversations.

    Assembles all tools, manages the Anthropic client, and provides
    chat() and create_sub_investigation() methods for the API layer.

    Parameters
    ----------
    settings : Settings
        Application settings (API keys, paths).
    db : SQLiteDB
        SQLite database instance.
    graph_db : GraphDB
        Entity graph database.
    repos : Repositories
        All repository instances.
    """

    def __init__(
        self,
        settings: Settings,
        db: SQLiteDB,
        graph_db: GraphDB,
        repos: Repositories,
    ) -> None:
        self._settings = settings
        self._db = db
        self._graph_db = graph_db
        self._repos = repos

        # Create Exa client if API key is configured
        exa_client: ExaClient | None = None
        if settings.EXA_API_KEY:
            exa_client = ExaClient(api_key=settings.EXA_API_KEY)

        # Create tool server with all investigation tools
        self._tool_server: ToolServer = create_tool_server(
            db=db,
            graph_db=graph_db,
            dataset_repo=repos.dataset_repo,
            evidence_repo=repos.evidence_repo,
            timeline_repo=repos.timeline_repo,
            message_repo=repos.message_repo,
            exa_client=exa_client,
        )

        # Create the Anthropic client (fallback mode)
        if not settings.ANTHROPIC_API_KEY:
            self._client = None
        else:
            self._client = AnthropicFallbackClient(
                api_key=settings.ANTHROPIC_API_KEY,
                model="claude-sonnet-4-6",
            )

    @property
    def tool_server(self) -> ToolServer:
        """Access the tool server (for testing and introspection)."""
        return self._tool_server

    def _build_messages(
        self, investigation_id: str, user_message: str,
    ) -> list[dict[str, Any]]:
        """Build the messages list from conversation history + new message.

        Loads prior messages from the database and appends the new user message.
        """
        history = self._repos.message_repo.get_history(investigation_id)
        messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in history
        ]
        messages.append({"role": "user", "content": user_message})
        return messages

    async def chat(
        self,
        investigation_id: str,
        user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        """Send a message and stream the response.

        1. Loads conversation history from MessageRepo
        2. Appends user message
        3. Calls the Anthropic client with streaming
        4. Yields StreamEvent objects
        5. After completion, saves both user and assistant messages

        Parameters
        ----------
        investigation_id : str
            The investigation this conversation belongs to.
        user_message : str
            The analyst's message.

        Yields
        ------
        StreamEvent
            Events from the agent's response (text deltas, tool calls, etc.).
        """
        if self._client is None:
            yield StreamEvent(
                event_type="error",
                content="ANTHROPIC_API_KEY is not configured. Cannot start agent.",
            )
            return

        # Save user message
        self._repos.message_repo.append(investigation_id, "user", user_message)

        # Build conversation messages
        messages = self._build_messages(investigation_id, user_message)

        # Stream the response
        full_response = ""
        async for event in self._client.chat(
            messages=messages,
            system=SYSTEM_PROMPT,
            tools=self._tool_server,
        ):
            if event.event_type == "text_delta":
                full_response += event.content
            elif event.event_type == "message_complete":
                full_response = event.content if event.content else full_response

            yield event

        # Save assistant response
        if full_response:
            self._repos.message_repo.append(
                investigation_id, "assistant", full_response,
            )

    async def create_sub_investigation(
        self,
        investigation_id: str,
        question: str,
    ) -> str:
        """Launch a focused sub-investigation on a specific question.

        The sub-agent inherits the same tool server but gets a narrower
        system prompt focused on the specific question.

        Parameters
        ----------
        investigation_id : str
            The parent investigation ID.
        question : str
            The specific question to investigate.

        Returns
        -------
        str
            The sub-agent's findings as a string.
        """
        if self._client is None:
            return "ANTHROPIC_API_KEY is not configured. Cannot run sub-investigation."

        # Build context summary from current investigation state
        evidence = self._repos.evidence_repo.query(investigation_id=investigation_id)
        entities = self._graph_db.get_all_entities(investigation_id)

        context_parts = []
        if entities:
            entity_names = [e.get("name", "unknown") for e in entities[:20]]
            context_parts.append(f"Known entities: {', '.join(entity_names)}")
        if evidence:
            context_parts.append(f"Evidence entries recorded: {len(evidence)}")
            confirmed = [e for e in evidence if e.get("confidence") == "confirmed"]
            if confirmed:
                context_parts.append(
                    f"Confirmed findings: {len(confirmed)}"
                )

        context = "\n".join(context_parts) if context_parts else "No prior findings."

        # Build the sub-agent's system prompt
        sub_system = SUB_INVESTIGATOR_PROMPT_TEMPLATE.format(
            question=question,
            context=context,
        )

        # Send a single message to the sub-agent
        messages = [{"role": "user", "content": question}]

        full_response = ""
        async for event in self._client.chat(
            messages=messages,
            system=sub_system,
            tools=self._tool_server,
        ):
            if event.event_type == "text_delta":
                full_response += event.content
            elif event.event_type == "message_complete":
                full_response = event.content if event.content else full_response

        return full_response
