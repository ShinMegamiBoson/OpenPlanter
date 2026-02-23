"""Tests for redthread.agent.tools.evidence — evidence chain recording/querying.

TDD: These tests were written before the implementation.
Tools are plain async functions taking repos as dependency injection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redthread.agent.tools.evidence import query_evidence, record_evidence
from redthread.db.graph import NetworkXGraphDB
from redthread.db.repositories import DatasetRepo, EvidenceRepo, InvestigationRepo
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
def dataset_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> DatasetRepo:
    return DatasetRepo(sqlite_db, graph_db)


@pytest.fixture
def evidence_repo(sqlite_db: SQLiteDB, graph_db: NetworkXGraphDB) -> EvidenceRepo:
    return EvidenceRepo(sqlite_db, graph_db)


@pytest.fixture
def investigation(inv_repo: InvestigationRepo) -> dict:
    """Create a test investigation."""
    return inv_repo.create(title="Evidence Tool Test Investigation")


@pytest.fixture
def dataset_with_records(
    dataset_repo: DatasetRepo, investigation: dict,
) -> tuple[dict, list[dict]]:
    """Create a dataset with sample records and return (dataset, records)."""
    ds = dataset_repo.create(
        investigation_id=investigation["id"],
        filename="transactions.csv",
        file_type="csv",
        row_count=2,
        column_names=["date", "amount", "description"],
    )
    rows = [
        {"date": "2024-01-01", "amount": 1000, "desc": "Wire transfer"},
        {"date": "2024-01-02", "amount": 2500, "desc": "Check deposit"},
    ]
    dataset_repo.store_records(ds["id"], rows)
    records = dataset_repo.get_records(ds["id"])
    return ds, records


# ---------------------------------------------------------------------------
# record_evidence
# ---------------------------------------------------------------------------


class TestRecordEvidence:
    """record_evidence tool — recording structured evidence chain entries."""

    async def test_record_with_all_fields(
        self,
        evidence_repo: EvidenceRepo,
        investigation: dict,
        dataset_with_records: tuple[dict, list[dict]],
    ):
        """Record evidence with all fields creates entry in DB."""
        ds, records = dataset_with_records
        result = await record_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            claim="Multiple wire transfers to offshore accounts",
            supporting_evidence="Records show 5 transfers totaling $50,000 to Cayman Islands",
            source_record_id=records[0]["id"],
            source_dataset_id=ds["id"],
            confidence="confirmed",
            entity_id="entity-1",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"
        assert "id" in parsed
        assert parsed["claim"] == "Multiple wire transfers to offshore accounts"
        assert parsed["confidence"] == "confirmed"

        # Verify actually persisted in DB
        entries = evidence_repo.query(investigation_id=investigation["id"])
        assert len(entries) == 1
        assert entries[0]["claim"] == "Multiple wire transfers to offshore accounts"

    async def test_record_without_entity_id(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Record evidence without entity_id succeeds (entity optional).

        Also tests web-sourced evidence with no source record/dataset IDs.
        """
        result = await record_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            claim="Suspicious pattern found",
            supporting_evidence="Transaction frequency analysis indicates structuring",
            source_record_id="",
            source_dataset_id="",
            confidence="probable",
        )

        parsed = json.loads(result)
        assert parsed["status"] == "recorded"
        assert parsed["confidence"] == "probable"

    async def test_record_invalid_confidence_returns_error(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Record evidence with invalid confidence returns error message."""
        result = await record_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            claim="Some claim",
            supporting_evidence="Some evidence",
            source_record_id="",
            source_dataset_id="",
            confidence="definitely",
        )

        assert "error" in result.lower() or "invalid" in result.lower()

        # Verify nothing was persisted
        entries = evidence_repo.query(investigation_id=investigation["id"])
        assert len(entries) == 0

    async def test_record_empty_claim_returns_error(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Record evidence with empty claim returns error message."""
        result = await record_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            claim="",
            supporting_evidence="Some evidence",
            source_record_id="",
            source_dataset_id="",
            confidence="confirmed",
        )

        assert "error" in result.lower() or "claim" in result.lower()

        entries = evidence_repo.query(investigation_id=investigation["id"])
        assert len(entries) == 0

    async def test_record_empty_supporting_evidence_returns_error(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Record evidence with empty supporting_evidence returns error."""
        result = await record_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            claim="Valid claim",
            supporting_evidence="",
            source_record_id="",
            source_dataset_id="",
            confidence="confirmed",
        )

        assert "error" in result.lower() or "supporting_evidence" in result.lower()

        entries = evidence_repo.query(investigation_id=investigation["id"])
        assert len(entries) == 0

    async def test_record_all_valid_confidence_levels(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """All four confidence levels are accepted: confirmed, probable, possible, unresolved."""
        for confidence in ("confirmed", "probable", "possible", "unresolved"):
            result = await record_evidence(
                evidence_repo=evidence_repo,
                investigation_id=investigation["id"],
                claim=f"Claim at {confidence}",
                supporting_evidence=f"Evidence at {confidence}",
                source_record_id="",
                source_dataset_id="",
                confidence=confidence,
            )
            parsed = json.loads(result)
            assert parsed["status"] == "recorded"
            assert parsed["confidence"] == confidence


# ---------------------------------------------------------------------------
# query_evidence
# ---------------------------------------------------------------------------


class TestQueryEvidence:
    """query_evidence tool — querying accumulated evidence chains."""

    async def _seed_evidence(
        self, evidence_repo: EvidenceRepo, investigation_id: str,
    ) -> None:
        """Insert sample evidence entries for query tests.

        Uses None for source_record_id/source_dataset_id to avoid FK issues.
        """
        evidence_repo.create(
            investigation_id=investigation_id,
            entity_id="entity-A",
            claim="Entity A suspicious transfers",
            supporting_evidence="5 transfers totaling $50k",
            confidence="confirmed",
        )
        evidence_repo.create(
            investigation_id=investigation_id,
            entity_id="entity-A",
            claim="Entity A known alias usage",
            supporting_evidence="Uses 3 different names across datasets",
            confidence="probable",
        )
        evidence_repo.create(
            investigation_id=investigation_id,
            entity_id="entity-B",
            claim="Entity B shell company links",
            supporting_evidence="Registered at same address as 4 other entities",
            confidence="possible",
        )

    async def test_query_by_entity_id(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Query evidence by entity_id returns only matching entries."""
        await self._seed_evidence(evidence_repo, investigation["id"])

        result = await query_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            entity_id="entity-A",
        )

        parsed = json.loads(result)
        assert len(parsed["evidence"]) == 2
        for entry in parsed["evidence"]:
            assert entry["entity_id"] == "entity-A"

    async def test_query_by_confidence(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Query evidence by confidence returns only matching entries."""
        await self._seed_evidence(evidence_repo, investigation["id"])

        result = await query_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            confidence="confirmed",
        )

        parsed = json.loads(result)
        assert len(parsed["evidence"]) == 1
        assert parsed["evidence"][0]["confidence"] == "confirmed"

    async def test_query_all_for_investigation(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Query all evidence for investigation returns complete list."""
        await self._seed_evidence(evidence_repo, investigation["id"])

        result = await query_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
        )

        parsed = json.loads(result)
        assert len(parsed["evidence"]) == 3

    async def test_query_no_evidence_returns_empty_list(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Query for investigation with no evidence returns empty list."""
        result = await query_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
        )

        parsed = json.loads(result)
        assert len(parsed["evidence"]) == 0

    async def test_query_by_entity_and_confidence(
        self, evidence_repo: EvidenceRepo, investigation: dict,
    ):
        """Query with both entity_id and confidence filters correctly."""
        await self._seed_evidence(evidence_repo, investigation["id"])

        result = await query_evidence(
            evidence_repo=evidence_repo,
            investigation_id=investigation["id"],
            entity_id="entity-A",
            confidence="confirmed",
        )

        parsed = json.loads(result)
        assert len(parsed["evidence"]) == 1
        assert parsed["evidence"][0]["entity_id"] == "entity-A"
        assert parsed["evidence"][0]["confidence"] == "confirmed"
