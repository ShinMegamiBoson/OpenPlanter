"""Tier 1 pairwise entity resolution.

Compares two entity names using a pipeline of normalization, fuzzy matching,
and phonetic comparison to produce a composite match score.

Pipeline:
1. Normalize: strip whitespace, lowercase, remove punctuation
2. Business suffix strip: cleanco.basename() for organizations
3. Human name decomposition: nameparser.HumanName for persons
4. Fuzzy score: rapidfuzz.fuzz.token_sort_ratio (handles word reordering)
5. Phonetic check: jellyfish.soundex comparison as secondary signal
6. Composite score: fuzzy(0.7) + phonetic_bonus(0.15) + exact_bonus(0.15)

Thresholds:
- >= 0.95 = confirmed
- >= 0.80 = probable
- >= 0.60 = possible
- <  0.60 = unresolved
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

import jellyfish
from cleanco import basename as cleanco_basename
from nameparser import HumanName
from rapidfuzz import fuzz


@dataclass
class MatchResult:
    """Result of comparing two entity names.

    Attributes
    ----------
    score : float
        Composite score between 0.0 and 1.0.
    name_similarity : float
        Raw fuzzy similarity from rapidfuzz (0.0–1.0).
    phonetic_match : bool
        Whether the soundex codes of the two names match.
    normalized_a : str
        Normalized version of the first name.
    normalized_b : str
        Normalized version of the second name.
    match_type : str
        Classification: 'exact', 'fuzzy', 'phonetic', or 'weak'.
    """

    score: float
    name_similarity: float
    phonetic_match: bool
    normalized_a: str
    normalized_b: str
    match_type: str


# -- Thresholds ---------------------------------------------------------------

THRESHOLD_CONFIRMED = 0.95
THRESHOLD_PROBABLE = 0.80
THRESHOLD_POSSIBLE = 0.60

# -- Weights ------------------------------------------------------------------

WEIGHT_FUZZY = 0.70
WEIGHT_PHONETIC_BONUS = 0.15
WEIGHT_EXACT_BONUS = 0.15


def _normalize(name: str) -> str:
    """Strip whitespace, lowercase, collapse internal whitespace."""
    name = name.strip().lower()
    # Replace & with 'and' before removing punctuation
    name = name.replace("&", "and")
    # Remove punctuation (apostrophes, commas, periods, etc.)
    name = name.translate(str.maketrans("", "", string.punctuation))
    # Collapse multiple spaces into one
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _strip_business_suffix(name: str) -> str:
    """Remove business suffixes (LLC, Inc, Corp, Ltd, AG, etc.) using cleanco."""
    stripped = cleanco_basename(name)
    # cleanco may return empty string for names that are entirely a suffix
    return stripped.strip() if stripped.strip() else name


def _decompose_human_name(name: str) -> str:
    """Decompose a human name into normalized 'first last' order.

    Handles 'Smith, John' -> 'john smith' and strips suffixes like Jr/Sr.
    """
    parsed = HumanName(name)
    parts = []
    if parsed.first:
        parts.append(parsed.first.lower())
    if parsed.middle:
        parts.append(parsed.middle.lower())
    if parsed.last:
        parts.append(parsed.last.lower())
    return " ".join(parts) if parts else name.lower()


def _fuzzy_score(name_a: str, name_b: str) -> float:
    """Compute fuzzy similarity using token_sort_ratio.

    rapidfuzz returns 0-100, we normalize to 0.0-1.0.
    """
    return fuzz.token_sort_ratio(name_a, name_b) / 100.0


def _phonetic_match(name_a: str, name_b: str) -> bool:
    """Check if two names have matching soundex codes.

    For multi-word names, compare soundex of each word pairwise (sorted).
    """
    if not name_a or not name_b:
        return False

    words_a = sorted(name_a.split())
    words_b = sorted(name_b.split())

    # If different number of words, compare soundex of the full strings
    if len(words_a) != len(words_b):
        try:
            return jellyfish.soundex(name_a) == jellyfish.soundex(name_b)
        except Exception:
            return False

    # Compare soundex of each sorted word pair
    try:
        return all(
            jellyfish.soundex(wa) == jellyfish.soundex(wb)
            for wa, wb in zip(words_a, words_b)
        )
    except Exception:
        return False


def _classify_match(score: float, exact_after_norm: bool, phonetic: bool) -> str:
    """Classify the match type based on score and signals."""
    if exact_after_norm:
        return "exact"
    if score >= THRESHOLD_CONFIRMED:
        return "fuzzy"
    if phonetic and score >= THRESHOLD_POSSIBLE:
        return "phonetic"
    return "weak"


def compare_entities(
    name_a: str,
    name_b: str,
    entity_type: str = "unknown",
) -> MatchResult:
    """Compare two entity names and return a MatchResult.

    Parameters
    ----------
    name_a : str
        First entity name.
    name_b : str
        Second entity name.
    entity_type : str
        Type of entity: 'person', 'organization', or 'unknown'.

    Returns
    -------
    MatchResult
        Composite comparison result with score, classification, and details.
    """
    # Handle empty inputs
    if not name_a or not name_a.strip() or not name_b or not name_b.strip():
        return MatchResult(
            score=0.0,
            name_similarity=0.0,
            phonetic_match=False,
            normalized_a=name_a.strip().lower() if name_a else "",
            normalized_b=name_b.strip().lower() if name_b else "",
            match_type="weak",
        )

    # Step 1: Human name decomposition BEFORE punctuation removal (for persons).
    # nameparser uses commas to detect "Last, First" format, so we must run it
    # on the raw input before stripping punctuation.
    if entity_type == "person":
        norm_a = _normalize(_decompose_human_name(name_a))
        norm_b = _normalize(_decompose_human_name(name_b))
    else:
        # Step 1: Normalize
        norm_a = _normalize(name_a)
        norm_b = _normalize(name_b)

    # Step 2: Business suffix stripping (for organizations)
    if entity_type in ("organization", "unknown"):
        norm_a = _normalize(_strip_business_suffix(norm_a))
        norm_b = _normalize(_strip_business_suffix(norm_b))

    # Step 4: Fuzzy score
    fuzzy = _fuzzy_score(norm_a, norm_b)

    # Step 5: Phonetic check
    phonetic = _phonetic_match(norm_a, norm_b)

    # Step 6: Composite score
    exact_after_norm = (norm_a == norm_b) and bool(norm_a)
    exact_bonus = WEIGHT_EXACT_BONUS if exact_after_norm else 0.0
    phonetic_bonus = WEIGHT_PHONETIC_BONUS if phonetic else 0.0
    composite = (fuzzy * WEIGHT_FUZZY) + phonetic_bonus + exact_bonus

    # Clamp to [0.0, 1.0]
    composite = max(0.0, min(1.0, composite))

    # Classify
    match_type = _classify_match(composite, exact_after_norm, phonetic)

    return MatchResult(
        score=composite,
        name_similarity=fuzzy,
        phonetic_match=phonetic,
        normalized_a=norm_a,
        normalized_b=norm_b,
        match_type=match_type,
    )


def score_to_confidence(score: float) -> str:
    """Convert a numeric score to a confidence tier string.

    Returns
    -------
    str
        One of: 'confirmed', 'probable', 'possible', 'unresolved'.
    """
    if score >= THRESHOLD_CONFIRMED:
        return "confirmed"
    if score >= THRESHOLD_PROBABLE:
        return "probable"
    if score >= THRESHOLD_POSSIBLE:
        return "possible"
    return "unresolved"
