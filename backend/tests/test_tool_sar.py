"""Tests for redthread.agent.tools.sar — SAR narrative generation.

TDD: These tests were written before the implementation.
Tools are plain async functions taking repos as dependency injection.
The SAR narrative tool assembles evidence chains into a structured template
(does NOT use an LLM). Must include DRAFT notice prominently.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from redthread.agent.tools.sar import generate_sar_narrative
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import EvidenceRepo, InvestigationRepo
from redthread.db.sqlite import SQLiteDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    return SQLiteDB(str(tmp_path / "test.db"))


@pytest.fixture
def graph_db(tmp_path: Path) -> NetworkXGraphDB:
    return NetworkXGraphDB(str(tmp_path / "test_graph.json"))


@pytest.fixture
def inv_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> InvestigationRepo:
    return InvestigationRepo(sqlite_db, graph_db)


@pytest.fixture
def evidence_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> EvidenceRepo:
    return EvidenceRepo(sqlite_db, graph_db)


@pytest.fixture
def investigation(inv_repo: InvestigationRepo) -> dict:
    """Create a test investigation."""
    return inv_repo.create(title="SAR Test Investigation")


@pytest.fixture
def investigation_with_evidence(
    inv_repo: InvestigationRepo,
    evidence_repo: EvidenceRepo,
    graph_db: NetworkXGraphDB,
) -> tuple[dict, list[dict]]:
    """Create an investigation with multiple evidence entries and graph entities.

    Returns (investigation, evidence_entries).
    """
    inv = inv_repo.create(title="Suspicious Wire Transfer Investigation")

    # Add entities to graph for subject info lookup
    graph_db.add_entity(
        entity_id="entity-john",
        entity_type="person",
        name="John Smith",
        properties={"investigation_id": inv["id"]},
    )
    graph_db.add_entity(
        entity_id="entity-acme",
        entity_type="organization",
        name="Acme Shell Corp LLC",
        properties={"investigation_id": inv["id"]},
    )

    entries = []

    # Confirmed evidence - should appear in suspicious activity summary
    e1 = evidence_repo.create(
        investigation_id=inv["id"],
        entity_id="entity-john",
        claim="John Smith made 5 wire transfers totaling $50,000 to Cayman Islands",
        supporting_evidence="Dataset transactions.csv records show transfers on "
        "2024-01-05, 2024-01-12, 2024-01-19, 2024-01-26, 2024-02-02",
        confidence="confirmed",
    )
    entries.append(e1)

    # Small sleep to ensure chronological ordering of created_at
    time.sleep(0.01)

    # Probable evidence
    e2 = evidence_repo.create(
        investigation_id=inv["id"],
        entity_id="entity-john",
        claim="John Smith uses alias 'J. Smithson' in related transactions",
        supporting_evidence="Name resolution matched John Smith to J. Smithson "
        "with 0.87 confidence score across two datasets",
        confidence="probable",
    )
    entries.append(e2)

    time.sleep(0.01)

    # Possible evidence for different entity
    e3 = evidence_repo.create(
        investigation_id=inv["id"],
        entity_id="entity-acme",
        claim="Acme Shell Corp has same registered address as 4 other entities",
        supporting_evidence="Address matching found 4 entities at "
        "123 Cayman Way, George Town, KY1-1234",
        confidence="possible",
    )
    entries.append(e3)

    time.sleep(0.01)

    # Unresolved evidence
    e4 = evidence_repo.create(
        investigation_id=inv["id"],
        entity_id="entity-acme",
        claim="Acme Shell Corp may be connected to known money laundering network",
        supporting_evidence="OFAC screening returned possible match score 0.62",
        confidence="unresolved",
    )
    entries.append(e4)

    return inv, entries


# ---------------------------------------------------------------------------
# generate_sar_narrative
# ---------------------------------------------------------------------------


class TestGenerateSARNarrative:
    """generate_sar_narrative tool — assembling evidence into SAR template."""

    async def test_generates_nonempty_output_with_evidence(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Generate narrative with evidence produces non-empty output."""
        inv, entries = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john,entity-acme",
        )

        assert len(result) > 100  # should be a substantial document

    async def test_output_includes_draft_notice(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Output includes DRAFT notice prominently."""
        inv, _ = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john",
        )

        # DRAFT should appear at least twice (header and footer)
        assert result.upper().count("DRAFT") >= 2

    async def test_output_references_evidence_chain_ids(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Output references evidence chain entry IDs."""
        inv, entries = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john,entity-acme",
        )

        # Each evidence entry ID should be referenced in the document
        for entry in entries:
            assert entry["id"] in result, (
                f"Evidence chain ID {entry['id']} not found in narrative"
            )

    async def test_output_includes_subject_entity_information(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Output includes subject entity information (names)."""
        inv, _ = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john,entity-acme",
        )

        assert "John Smith" in result
        assert "Acme Shell Corp LLC" in result

    async def test_no_evidence_returns_appropriate_message(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation: dict,
    ):
        """Generate narrative with no evidence returns appropriate message."""
        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=investigation["id"],
        )

        # Should indicate no evidence available
        lower = result.lower()
        assert "no evidence" in lower or "no findings" in lower or "no entries" in lower

    async def test_evidence_entries_in_chronological_order(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Evidence entries appear in chronological order in the appendix."""
        inv, entries = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john,entity-acme",
        )

        # Check that evidence IDs appear in chronological order (by created_at)
        # The entries fixture creates them in order, so entry IDs should appear
        # in that same order in the narrative.
        positions = []
        for entry in entries:
            pos = result.find(entry["id"])
            assert pos != -1, f"Entry {entry['id']} not found"
            positions.append(pos)

        # First occurrence of each ID should be in chronological order
        assert positions == sorted(positions), (
            "Evidence entries are not in chronological order"
        )

    async def test_narrative_includes_section_headers(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Narrative includes expected section structure."""
        inv, _ = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john",
        )

        result_upper = result.upper()
        # Must have key sections
        assert "SUBJECT" in result_upper
        assert "SUSPICIOUS ACTIVITY" in result_upper or "SUMMARY" in result_upper
        assert "NARRATIVE" in result_upper or "DETAILED" in result_upper
        assert "EVIDENCE" in result_upper or "APPENDIX" in result_upper

    async def test_summary_uses_confirmed_and_probable_evidence(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """Summary section draws from confirmed and probable evidence only."""
        inv, entries = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
            subject_entity_ids="entity-john,entity-acme",
        )

        # The confirmed and probable claims should appear in the summary section
        # The confirmed claim about wire transfers should be present
        assert "wire transfers" in result.lower() or entries[0]["claim"] in result

    async def test_no_subject_ids_uses_all_evidence(
        self,
        evidence_repo: EvidenceRepo,
        graph_db: NetworkXGraphDB,
        investigation_with_evidence: tuple[dict, list[dict]],
    ):
        """When no subject_entity_ids provided, uses all evidence."""
        inv, entries = investigation_with_evidence

        result = await generate_sar_narrative(
            evidence_repo=evidence_repo,
            graph_db=graph_db,
            investigation_id=inv["id"],
        )

        # Should still include all evidence entries
        for entry in entries:
            assert entry["id"] in result
