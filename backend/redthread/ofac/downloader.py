"""SDN list downloader, XML parser, and SQLite loader.

Downloads the OFAC Specially Designated Nationals (SDN) list from the
U.S. Treasury, parses it from XML into structured entries, and loads
those entries into a local SQLite table for offline screening.

SDN XML source:
    https://www.treasury.gov/ofac/downloads/sdn.xml
Alternative CSV:
    https://www.treasury.gov/ofac/downloads/sdn.csv
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from redthread.db.sqlite import SQLiteDB

logger = logging.getLogger(__name__)

# OFAC SDN XML namespace (tempuri.org/sdnList.xsd as per Treasury schema).
_SDN_NS = "http://tempuri.org/sdnList.xsd"

# Primary download URL.
SDN_XML_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"

# Schema for the sdn_entries table — separate from the main Redthread schema
# since OFAC screening is a standalone concern.
_SDN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sdn_entries (
    uid INTEGER PRIMARY KEY,
    entry_type TEXT,
    name TEXT NOT NULL,
    program TEXT,
    aliases TEXT,
    addresses TEXT,
    id_numbers TEXT,
    remarks TEXT
);

CREATE INDEX IF NOT EXISTS idx_sdn_entries_name ON sdn_entries(name);
"""


@dataclass
class SDNEntry:
    """A single entry from the OFAC SDN list."""

    uid: int
    entry_type: str  # Individual | Entity | Vessel | Aircraft
    name: str
    program: str = ""
    aliases: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    id_numbers: list[str] = field(default_factory=list)
    remarks: str = ""


@dataclass
class DownloadResult:
    """Outcome of an SDN list download attempt."""

    success: bool
    path: Path | None = None
    error: str = ""
    bytes_downloaded: int = 0


def _ns(tag: str) -> str:
    """Return a namespace-qualified tag name for the SDN XML."""
    return f"{{{_SDN_NS}}}{tag}"


def _text(element: ET.Element | None) -> str:
    """Safely extract text from an XML element."""
    if element is None:
        return ""
    return (element.text or "").strip()


def _build_name(entry_el: ET.Element) -> str:
    """Build the display name from firstName + lastName elements."""
    first = _text(entry_el.find(_ns("firstName")))
    last = _text(entry_el.find(_ns("lastName")))
    if first and last:
        return f"{first} {last}"
    return last or first


def _extract_programs(entry_el: ET.Element) -> str:
    """Extract semicolon-delimited program list."""
    prog_list = entry_el.find(_ns("programList"))
    if prog_list is None:
        return ""
    programs = [
        _text(p) for p in prog_list.findall(_ns("program")) if _text(p)
    ]
    return "; ".join(programs)


def _extract_aliases(entry_el: ET.Element) -> list[str]:
    """Extract all alternate names (a.k.a.) from the akaList."""
    aka_list = entry_el.find(_ns("akaList"))
    if aka_list is None:
        return []
    aliases: list[str] = []
    for aka in aka_list.findall(_ns("aka")):
        first = _text(aka.find(_ns("firstName")))
        last = _text(aka.find(_ns("lastName")))
        if first and last:
            alias = f"{first} {last}"
        else:
            alias = last or first
        if alias:
            aliases.append(alias)
    return aliases


def _extract_addresses(entry_el: ET.Element) -> list[str]:
    """Extract address strings from the addressList."""
    addr_list = entry_el.find(_ns("addressList"))
    if addr_list is None:
        return []
    addresses: list[str] = []
    for addr in addr_list.findall(_ns("address")):
        parts = []
        for tag in ("address1", "address2", "address3", "city",
                     "stateOrProvince", "postalCode", "country"):
            val = _text(addr.find(_ns(tag)))
            if val:
                parts.append(val)
        if parts:
            addresses.append(", ".join(parts))
    return addresses


def _extract_ids(entry_el: ET.Element) -> list[str]:
    """Extract ID numbers from the idList."""
    id_list = entry_el.find(_ns("idList"))
    if id_list is None:
        return []
    ids: list[str] = []
    for id_el in id_list.findall(_ns("id")):
        id_type = _text(id_el.find(_ns("idType")))
        id_number = _text(id_el.find(_ns("idNumber")))
        id_country = _text(id_el.find(_ns("idCountry")))
        parts = [p for p in (id_type, id_number, id_country) if p]
        if parts:
            ids.append(" ".join(parts))
    return ids


async def download_sdn_list(target_path: Path) -> DownloadResult:
    """Download the OFAC SDN XML file to *target_path*.

    Uses httpx async client with redirect following.  Returns a
    :class:`DownloadResult` indicating success or failure.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            resp = await client.get(SDN_XML_URL)
            resp.raise_for_status()

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(resp.content)

        return DownloadResult(
            success=True,
            path=target_path,
            bytes_downloaded=len(resp.content),
        )
    except Exception as exc:
        logger.error("SDN download failed: %s", exc)
        return DownloadResult(success=False, error=str(exc))


def parse_sdn_xml(xml_path: Path) -> list[SDNEntry]:
    """Parse an SDN XML file into a list of :class:`SDNEntry` objects.

    Malformed entries (missing uid or name) are logged and skipped so
    that a single bad record does not prevent the rest from loading.

    Also supports XML provided as a string when *xml_path* points to
    a file on disk.
    """
    entries: list[SDNEntry] = []

    try:
        tree = ET.parse(xml_path)  # noqa: S314
        root = tree.getroot()
    except ET.ParseError as exc:
        logger.warning("Failed to parse SDN XML at %s: %s", xml_path, exc)
        return entries

    for entry_el in root.findall(_ns("sdnEntry")):
        try:
            uid_text = _text(entry_el.find(_ns("uid")))
            if not uid_text:
                logger.warning("Skipping SDN entry with missing uid")
                continue

            name = _build_name(entry_el)
            if not name:
                logger.warning("Skipping SDN entry uid=%s with empty name", uid_text)
                continue

            entry = SDNEntry(
                uid=int(uid_text),
                entry_type=_text(entry_el.find(_ns("sdnType"))) or "Unknown",
                name=name,
                program=_extract_programs(entry_el),
                aliases=_extract_aliases(entry_el),
                addresses=_extract_addresses(entry_el),
                id_numbers=_extract_ids(entry_el),
                remarks=_text(entry_el.find(_ns("remarks"))),
            )
            entries.append(entry)
        except (ValueError, TypeError) as exc:
            logger.warning("Skipping malformed SDN entry: %s", exc)
            continue

    return entries


def parse_sdn_xml_string(xml_string: str) -> list[SDNEntry]:
    """Parse SDN XML from a string (convenience for testing)."""
    entries: list[SDNEntry] = []

    try:
        root = ET.fromstring(xml_string)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("Failed to parse SDN XML string: %s", exc)
        return entries

    for entry_el in root.findall(_ns("sdnEntry")):
        try:
            uid_text = _text(entry_el.find(_ns("uid")))
            if not uid_text:
                logger.warning("Skipping SDN entry with missing uid")
                continue

            name = _build_name(entry_el)
            if not name:
                logger.warning("Skipping SDN entry uid=%s with empty name", uid_text)
                continue

            entry = SDNEntry(
                uid=int(uid_text),
                entry_type=_text(entry_el.find(_ns("sdnType"))) or "Unknown",
                name=name,
                program=_extract_programs(entry_el),
                aliases=_extract_aliases(entry_el),
                addresses=_extract_addresses(entry_el),
                id_numbers=_extract_ids(entry_el),
                remarks=_text(entry_el.find(_ns("remarks"))),
            )
            entries.append(entry)
        except (ValueError, TypeError) as exc:
            logger.warning("Skipping malformed SDN entry: %s", exc)
            continue

    return entries


def create_sdn_table(db: SQLiteDB) -> None:
    """Create the sdn_entries table and name index.

    This is a standalone function (not part of the main schema) because
    OFAC screening is a separate concern from core investigation data.
    """
    db.execute(
        """CREATE TABLE IF NOT EXISTS sdn_entries (
            uid INTEGER PRIMARY KEY,
            entry_type TEXT,
            name TEXT NOT NULL,
            program TEXT,
            aliases TEXT,
            addresses TEXT,
            id_numbers TEXT,
            remarks TEXT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdn_entries_name ON sdn_entries(name)"
    )


def load_sdn_to_sqlite(entries: list[SDNEntry], db: SQLiteDB) -> int:
    """Load parsed SDN entries into the ``sdn_entries`` SQLite table.

    Creates the table if it does not exist, then inserts/replaces all
    entries.  Returns the number of entries loaded.
    """
    create_sdn_table(db)

    params_seq = [
        (
            entry.uid,
            entry.entry_type,
            entry.name,
            entry.program,
            json.dumps(entry.aliases),
            json.dumps(entry.addresses),
            json.dumps(entry.id_numbers),
            entry.remarks,
        )
        for entry in entries
    ]

    if params_seq:
        db.executemany(
            """INSERT OR REPLACE INTO sdn_entries
               (uid, entry_type, name, program, aliases, addresses, id_numbers, remarks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            params_seq,
        )

    return len(params_seq)
