"""Tests for redthread.ofac.downloader — SDN list download, parse, and load.

All tests are self-contained with inline XML fixtures (no live network calls).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redthread.db.sqlite import SQLiteDB
from redthread.ofac.downloader import (
    SDNEntry,
    create_sdn_table,
    load_sdn_to_sqlite,
    parse_sdn_xml,
    parse_sdn_xml_string,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal SDN XML that exercises all supported fields.
SAMPLE_SDN_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <publshInformation>
    <Publish_Date>02/18/2026</Publish_Date>
    <Record_Count>3</Record_Count>
  </publshInformation>

  <sdnEntry>
    <uid>1234</uid>
    <firstName>John</firstName>
    <lastName>DOE</lastName>
    <sdnType>Individual</sdnType>
    <programList>
      <program>SDGT</program>
      <program>SDNTK</program>
    </programList>
    <akaList>
      <aka>
        <uid>100</uid>
        <type>a.k.a.</type>
        <category>strong</category>
        <lastName>DOE</lastName>
        <firstName>Johnny</firstName>
      </aka>
      <aka>
        <uid>101</uid>
        <type>a.k.a.</type>
        <category>weak</category>
        <lastName>SMITH</lastName>
        <firstName>John</firstName>
      </aka>
    </akaList>
    <addressList>
      <address>
        <uid>200</uid>
        <city>Havana</city>
        <country>Cuba</country>
      </address>
    </addressList>
    <idList>
      <id>
        <uid>300</uid>
        <idType>Passport</idType>
        <idNumber>A12345678</idNumber>
        <idCountry>Cuba</idCountry>
      </id>
    </idList>
    <remarks>Subject is known to operate in multiple jurisdictions.</remarks>
  </sdnEntry>

  <sdnEntry>
    <uid>5678</uid>
    <lastName>ACME TRADING CO</lastName>
    <sdnType>Entity</sdnType>
    <programList>
      <program>IRAN</program>
    </programList>
    <akaList>
      <aka>
        <uid>102</uid>
        <type>a.k.a.</type>
        <category>strong</category>
        <lastName>ACME IMPORTS LLC</lastName>
      </aka>
    </akaList>
  </sdnEntry>

  <sdnEntry>
    <uid>9999</uid>
    <lastName>VESSEL SEABIRD</lastName>
    <sdnType>Vessel</sdnType>
    <programList>
      <program>CUBA</program>
    </programList>
  </sdnEntry>
</sdnList>
"""

# Malformed XML — one entry has no uid, another has no name.
MALFORMED_SDN_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry>
    <lastName>GOOD ENTRY</lastName>
    <uid>1111</uid>
    <sdnType>Entity</sdnType>
    <programList><program>TEST</program></programList>
  </sdnEntry>

  <sdnEntry>
    <uid></uid>
    <lastName>NO UID ENTRY</lastName>
    <sdnType>Entity</sdnType>
  </sdnEntry>

  <sdnEntry>
    <uid>2222</uid>
    <sdnType>Entity</sdnType>
  </sdnEntry>
</sdnList>
"""

INVALID_XML = """<this is not valid xml at all!!!>"""


@pytest.fixture
def sqlite_db(tmp_path: Path) -> SQLiteDB:
    return SQLiteDB(str(tmp_path / "test_ofac.db"))


@pytest.fixture
def xml_file(tmp_path: Path) -> Path:
    """Write sample SDN XML to a temporary file and return the path."""
    p = tmp_path / "sdn.xml"
    p.write_text(SAMPLE_SDN_XML, encoding="utf-8")
    return p


@pytest.fixture
def malformed_xml_file(tmp_path: Path) -> Path:
    p = tmp_path / "sdn_bad.xml"
    p.write_text(MALFORMED_SDN_XML, encoding="utf-8")
    return p


@pytest.fixture
def invalid_xml_file(tmp_path: Path) -> Path:
    p = tmp_path / "sdn_invalid.xml"
    p.write_text(INVALID_XML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# parse_sdn_xml — correct extraction
# ---------------------------------------------------------------------------


class TestParseSdnXml:
    """Parsing a well-formed SDN XML file extracts entries correctly."""

    def test_extracts_correct_number_of_entries(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        assert len(entries) == 3

    def test_individual_entry_has_full_name(self, xml_file: Path):
        """Individual entries combine firstName + lastName."""
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert individual.name == "John DOE"

    def test_entity_entry_has_lastname_only(self, xml_file: Path):
        """Entity entries use lastName as the full name."""
        entries = parse_sdn_xml(xml_file)
        entity = [e for e in entries if e.uid == 5678][0]
        assert entity.name == "ACME TRADING CO"

    def test_entry_type_populated(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        types = {e.uid: e.entry_type for e in entries}
        assert types[1234] == "Individual"
        assert types[5678] == "Entity"
        assert types[9999] == "Vessel"

    def test_aliases_populated(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert len(individual.aliases) == 2
        assert "Johnny DOE" in individual.aliases
        assert "John SMITH" in individual.aliases

    def test_entity_aliases(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        entity = [e for e in entries if e.uid == 5678][0]
        assert "ACME IMPORTS LLC" in entity.aliases

    def test_programs_extracted(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert "SDGT" in individual.program
        assert "SDNTK" in individual.program

    def test_addresses_extracted(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert len(individual.addresses) == 1
        assert "Havana" in individual.addresses[0]
        assert "Cuba" in individual.addresses[0]

    def test_id_numbers_extracted(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert len(individual.id_numbers) == 1
        assert "Passport" in individual.id_numbers[0]
        assert "A12345678" in individual.id_numbers[0]

    def test_remarks_extracted(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        individual = [e for e in entries if e.uid == 1234][0]
        assert "multiple jurisdictions" in individual.remarks

    def test_entry_without_aliases_has_empty_list(self, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        vessel = [e for e in entries if e.uid == 9999][0]
        assert vessel.aliases == []


# ---------------------------------------------------------------------------
# parse_sdn_xml — malformed / invalid XML
# ---------------------------------------------------------------------------


class TestParseSdnXmlMalformed:
    """Malformed XML is handled gracefully — bad entries are skipped."""

    def test_skips_entries_without_uid(self, malformed_xml_file: Path):
        """Entries with empty/missing uid are skipped."""
        entries = parse_sdn_xml(malformed_xml_file)
        uids = [e.uid for e in entries]
        assert 1111 in uids
        # Entry with empty uid is skipped
        assert len([e for e in entries if e.name == "NO UID ENTRY"]) == 0

    def test_skips_entries_without_name(self, malformed_xml_file: Path):
        """Entries with no firstName/lastName are skipped."""
        entries = parse_sdn_xml(malformed_xml_file)
        uids = [e.uid for e in entries]
        assert 2222 not in uids

    def test_good_entries_still_extracted(self, malformed_xml_file: Path):
        """Valid entries alongside bad ones are still parsed."""
        entries = parse_sdn_xml(malformed_xml_file)
        assert len(entries) == 1
        assert entries[0].uid == 1111
        assert entries[0].name == "GOOD ENTRY"

    def test_completely_invalid_xml_returns_empty(self, invalid_xml_file: Path):
        """Completely invalid XML returns empty list without raising."""
        entries = parse_sdn_xml(invalid_xml_file)
        assert entries == []


# ---------------------------------------------------------------------------
# load_sdn_to_sqlite
# ---------------------------------------------------------------------------


class TestLoadSdnToSqlite:
    """Loading parsed entries into SQLite and retrieving them."""

    def test_load_returns_entry_count(self, sqlite_db: SQLiteDB, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        count = load_sdn_to_sqlite(entries, sqlite_db)
        assert count == 3

    def test_entries_retrievable_by_uid(self, sqlite_db: SQLiteDB, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        load_sdn_to_sqlite(entries, sqlite_db)

        row = sqlite_db.fetchone("SELECT * FROM sdn_entries WHERE uid = ?", (1234,))
        assert row is not None
        assert row["name"] == "John DOE"
        assert row["entry_type"] == "Individual"

    def test_all_entries_retrievable(self, sqlite_db: SQLiteDB, xml_file: Path):
        entries = parse_sdn_xml(xml_file)
        load_sdn_to_sqlite(entries, sqlite_db)

        rows = sqlite_db.fetchall("SELECT * FROM sdn_entries")
        assert len(rows) == 3

    def test_aliases_stored_as_json(self, sqlite_db: SQLiteDB, xml_file: Path):
        """Aliases are stored as a JSON array string."""
        entries = parse_sdn_xml(xml_file)
        load_sdn_to_sqlite(entries, sqlite_db)

        row = sqlite_db.fetchone("SELECT aliases FROM sdn_entries WHERE uid = ?", (1234,))
        assert row is not None
        import json
        aliases = json.loads(row["aliases"])
        assert isinstance(aliases, list)
        assert "Johnny DOE" in aliases

    def test_name_index_exists(self, sqlite_db: SQLiteDB, xml_file: Path):
        """The idx_sdn_entries_name index exists after loading."""
        entries = parse_sdn_xml(xml_file)
        load_sdn_to_sqlite(entries, sqlite_db)

        indexes = sqlite_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sdn_entries'"
        )
        index_names = [idx["name"] for idx in indexes]
        assert "idx_sdn_entries_name" in index_names

    def test_load_empty_list(self, sqlite_db: SQLiteDB):
        """Loading an empty list creates the table but inserts nothing."""
        count = load_sdn_to_sqlite([], sqlite_db)
        assert count == 0

        rows = sqlite_db.fetchall("SELECT * FROM sdn_entries")
        assert len(rows) == 0

    def test_load_replaces_on_duplicate_uid(self, sqlite_db: SQLiteDB):
        """Loading entries with duplicate UIDs replaces existing rows."""
        entries_v1 = [SDNEntry(uid=1, entry_type="Entity", name="OLD NAME")]
        entries_v2 = [SDNEntry(uid=1, entry_type="Entity", name="NEW NAME")]

        load_sdn_to_sqlite(entries_v1, sqlite_db)
        load_sdn_to_sqlite(entries_v2, sqlite_db)

        row = sqlite_db.fetchone("SELECT * FROM sdn_entries WHERE uid = ?", (1,))
        assert row is not None
        assert row["name"] == "NEW NAME"


# ---------------------------------------------------------------------------
# parse_sdn_xml_string — string-based parsing
# ---------------------------------------------------------------------------


class TestParseSdnXmlString:
    """parse_sdn_xml_string works on in-memory XML strings."""

    def test_parses_from_string(self):
        entries = parse_sdn_xml_string(SAMPLE_SDN_XML)
        assert len(entries) == 3

    def test_invalid_string_returns_empty(self):
        entries = parse_sdn_xml_string(INVALID_XML)
        assert entries == []
