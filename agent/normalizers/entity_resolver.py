"""Composite entity matching for German corporate entities.

Provides multi-signal matching using register numbers, normalized names,
officer overlap, and address similarity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .german import (
    extract_legal_form,
    normalize_company_name,
    normalize_court,
    normalize_person_name,
)


@dataclass(slots=True)
class MatchResult:
    """Result of a company match attempt."""
    confidence: float  # 0.0–1.0
    match_type: str    # "exact_register", "name_form_city", "officer_address", "none"
    details: dict[str, Any]


def _normalize_register(register: str | None) -> str:
    """Normalize a register number for comparison (strip whitespace, uppercase)."""
    if not register:
        return ""
    return register.strip().upper().replace(" ", "")


def _officer_overlap(officers_a: list[str], officers_b: list[str]) -> float:
    """Return fraction of overlapping officers (by normalized name)."""
    if not officers_a or not officers_b:
        return 0.0
    set_a = {normalize_person_name(o) for o in officers_a}
    set_b = {normalize_person_name(o) for o in officers_b}
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def match_company(a: dict[str, Any], b: dict[str, Any]) -> MatchResult:
    """Composite matching of two company records.

    Expected record fields (all optional):
        name: str — company name
        legal_form: str — legal form (GmbH, AG, etc.)
        court: str — register court
        register_type: str — HRA or HRB
        register_number: str — the register number
        city: str — registered office city
        officers: list[str] — officer/director names
        address: str — full address

    Match tiers:
        1. Exact: court + register_type + register_number → confidence=1.0
        2. High: normalized name + legal form + city → confidence=0.85
        3. Medium: overlapping officers + similar city → confidence=0.6
        4. None: no match signals → confidence=0.0
    """
    details: dict[str, Any] = {}

    # --- Tier 1: Exact register match ---
    reg_a = _normalize_register(a.get("register_number"))
    reg_b = _normalize_register(b.get("register_number"))
    if reg_a and reg_b and reg_a == reg_b:
        court_a = normalize_court(a.get("court", ""))
        court_b = normalize_court(b.get("court", ""))
        type_a = (a.get("register_type") or "").upper().strip()
        type_b = (b.get("register_type") or "").upper().strip()
        if court_a == court_b and type_a == type_b:
            details["court"] = court_a
            details["register_type"] = type_a
            details["register_number"] = reg_a
            return MatchResult(confidence=1.0, match_type="exact_register", details=details)

    # --- Tier 2: Normalized name + legal form + city ---
    name_a = normalize_company_name(a.get("name", ""))
    name_b = normalize_company_name(b.get("name", ""))

    if name_a and name_b and name_a == name_b:
        form_a = extract_legal_form(a.get("name", "")) or a.get("legal_form", "")
        form_b = extract_legal_form(b.get("name", "")) or b.get("legal_form", "")
        city_a = (a.get("city") or "").strip().lower()
        city_b = (b.get("city") or "").strip().lower()

        form_match = (form_a or "").lower() == (form_b or "").lower() if (form_a and form_b) else True
        city_match = city_a == city_b if (city_a and city_b) else True

        if form_match and city_match and (form_a or city_a):
            details["normalized_name"] = name_a
            details["legal_form_match"] = form_match
            details["city_match"] = city_match
            return MatchResult(confidence=0.85, match_type="name_form_city", details=details)

    # --- Tier 3: Officer overlap + city ---
    officers_a = a.get("officers", [])
    officers_b = b.get("officers", [])
    overlap = _officer_overlap(officers_a, officers_b)

    city_a = (a.get("city") or "").strip().lower()
    city_b = (b.get("city") or "").strip().lower()
    city_match = city_a == city_b if (city_a and city_b) else False

    if overlap >= 0.3 and city_match:
        details["officer_overlap"] = round(overlap, 3)
        details["city"] = city_a
        return MatchResult(confidence=0.6, match_type="officer_address", details=details)

    if overlap >= 0.5:
        details["officer_overlap"] = round(overlap, 3)
        return MatchResult(confidence=0.5, match_type="officer_overlap_only", details=details)

    # --- No match ---
    return MatchResult(confidence=0.0, match_type="none", details={})
