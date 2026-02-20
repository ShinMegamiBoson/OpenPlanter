"""German-specific name, legal form, and court normalization.

Handles umlauts, legal form extraction, title stripping, and court aliases
for entity resolution across German corporate/political datasets.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Umlaut normalization — bidirectional ä↔ae, ö↔oe, ü↔ue, ß↔ss
# ---------------------------------------------------------------------------

UMLAUT_TO_ASCII: dict[str, str] = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
}

ASCII_TO_UMLAUT: dict[str, str] = {
    "ae": "ä", "oe": "ö", "ue": "ü", "ss": "ß",
    "Ae": "Ä", "Oe": "Ö", "Ue": "Ü",
}

_UMLAUT_RE = re.compile(r"[äöüßÄÖÜ]")


def umlauts_to_ascii(text: str) -> str:
    """Replace umlauts with ASCII digraphs: ä→ae, ö→oe, ü→ue, ß→ss."""
    return _UMLAUT_RE.sub(lambda m: UMLAUT_TO_ASCII.get(m.group(), m.group()), text)


def normalize_unicode(text: str) -> str:
    """NFC-normalize and strip accents beyond standard umlauts."""
    return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------------------
# Legal forms — canonical mapping
# ---------------------------------------------------------------------------

# Map of variations → canonical form.  Order matters: longer patterns first.
LEGAL_FORMS: dict[str, str] = {
    "gmbh & co. kgaa": "GmbH & Co. KGaA",
    "gmbh & co. kg": "GmbH & Co. KG",
    "gmbh & co. ohg": "GmbH & Co. OHG",
    "gmbh & co.kg": "GmbH & Co. KG",
    "ug (haftungsbeschränkt)": "UG (haftungsbeschränkt)",
    "ug (haftungsbeschraenkt)": "UG (haftungsbeschränkt)",
    "ug haftungsbeschränkt": "UG (haftungsbeschränkt)",
    "kgaa": "KGaA",
    "gmbh": "GmbH",
    "ag": "AG",
    "kg": "KG",
    "ohg": "OHG",
    "gbr": "GbR",
    "e.v.": "e.V.",
    "ev": "e.V.",
    "eg": "eG",
    "e.g.": "eG",
    "se": "SE",
    "se & co. kgaa": "SE & Co. KGaA",
    "ug": "UG (haftungsbeschränkt)",
    "partg": "PartG",
    "partg mbb": "PartG mbB",
    "vvag": "VVaG",
    "ewiv": "EWIV",
    "stiftung": "Stiftung",
}

# Sorted by length descending so longer patterns match first.
_LEGAL_FORM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE), v)
    for k, v in sorted(LEGAL_FORMS.items(), key=lambda kv: -len(kv[0]))
]


def extract_legal_form(name: str) -> str | None:
    """Pull the legal form from a company name, or None if not recognized."""
    for pattern, canonical in _LEGAL_FORM_PATTERNS:
        if pattern.search(name):
            return canonical
    return None


def strip_legal_form(name: str) -> str:
    """Remove legal form suffix from company name."""
    for pattern, _ in _LEGAL_FORM_PATTERNS:
        name = pattern.sub("", name)
    return name.strip().rstrip(",").rstrip("&").strip()


# ---------------------------------------------------------------------------
# Title prefixes — common in German names
# ---------------------------------------------------------------------------

TITLE_PREFIXES: list[str] = [
    "Prof. Dr. Dr. h.c.",
    "Prof. Dr. Dr.",
    "Prof. Dr.",
    "Prof.",
    "Dr. Dr.",
    "Dr. h.c.",
    "Dr. med.",
    "Dr. jur.",
    "Dr. rer. nat.",
    "Dr. phil.",
    "Dr. ing.",
    "Dr.-Ing.",
    "Dr.",
    "Dipl.-Ing.",
    "Dipl.-Kfm.",
    "Dipl.-Vw.",
]

# Nobility particles kept lowercase in German convention.
NOBILITY_PARTICLES: set[str] = {
    "von", "zu", "von und zu", "vom", "zum", "zur",
    "freiherr", "freifrau", "freiin",
    "graf", "gräfin",
    "fürst", "fürstin",
    "prinz", "prinzessin",
    "baron", "baronin", "baroness",
    "ritter",
}

_TITLE_RE = re.compile(
    r"^(" + "|".join(re.escape(t) for t in TITLE_PREFIXES) + r")\s+",
    re.IGNORECASE,
)


def strip_titles(name: str) -> str:
    """Remove academic/professional title prefixes from a person name."""
    result = name.strip()
    while True:
        m = _TITLE_RE.match(result)
        if not m:
            break
        result = result[m.end():].strip()
    return result


def normalize_person_name(name: str) -> str:
    """Normalize a person name: strip titles, normalize umlauts, case-fold."""
    result = strip_titles(name.strip())
    result = umlauts_to_ascii(result)
    result = normalize_unicode(result)
    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()
    return result.lower()


# ---------------------------------------------------------------------------
# Court aliases
# ---------------------------------------------------------------------------

# Map of known court abbreviations/aliases → canonical name.
COURT_ALIASES: dict[str, str] = {
    "ag münchen": "Amtsgericht München",
    "amtsgericht münchen": "Amtsgericht München",
    "münchen": "Amtsgericht München",
    "muenchen": "Amtsgericht München",
    "ag berlin charlottenburg": "Amtsgericht Berlin-Charlottenburg",
    "amtsgericht berlin-charlottenburg": "Amtsgericht Berlin-Charlottenburg",
    "berlin charlottenburg": "Amtsgericht Berlin-Charlottenburg",
    "berlin-charlottenburg": "Amtsgericht Berlin-Charlottenburg",
    "ag hamburg": "Amtsgericht Hamburg",
    "amtsgericht hamburg": "Amtsgericht Hamburg",
    "hamburg": "Amtsgericht Hamburg",
    "ag frankfurt am main": "Amtsgericht Frankfurt am Main",
    "amtsgericht frankfurt am main": "Amtsgericht Frankfurt am Main",
    "frankfurt am main": "Amtsgericht Frankfurt am Main",
    "frankfurt": "Amtsgericht Frankfurt am Main",
    "ag köln": "Amtsgericht Köln",
    "amtsgericht köln": "Amtsgericht Köln",
    "ag koeln": "Amtsgericht Köln",
    "köln": "Amtsgericht Köln",
    "koeln": "Amtsgericht Köln",
    "ag düsseldorf": "Amtsgericht Düsseldorf",
    "amtsgericht düsseldorf": "Amtsgericht Düsseldorf",
    "duesseldorf": "Amtsgericht Düsseldorf",
    "düsseldorf": "Amtsgericht Düsseldorf",
    "ag stuttgart": "Amtsgericht Stuttgart",
    "amtsgericht stuttgart": "Amtsgericht Stuttgart",
    "stuttgart": "Amtsgericht Stuttgart",
    "ag nürnberg": "Amtsgericht Nürnberg",
    "amtsgericht nürnberg": "Amtsgericht Nürnberg",
    "nürnberg": "Amtsgericht Nürnberg",
    "nuernberg": "Amtsgericht Nürnberg",
    "ag hannover": "Amtsgericht Hannover",
    "amtsgericht hannover": "Amtsgericht Hannover",
    "hannover": "Amtsgericht Hannover",
    "ag bremen": "Amtsgericht Bremen",
    "amtsgericht bremen": "Amtsgericht Bremen",
    "bremen": "Amtsgericht Bremen",
    "ag leipzig": "Amtsgericht Leipzig",
    "amtsgericht leipzig": "Amtsgericht Leipzig",
    "leipzig": "Amtsgericht Leipzig",
    "ag dresden": "Amtsgericht Dresden",
    "amtsgericht dresden": "Amtsgericht Dresden",
    "dresden": "Amtsgericht Dresden",
}


def normalize_court(court: str) -> str:
    """Normalize a court name to its canonical form."""
    key = umlauts_to_ascii(court.strip()).lower()
    # Try exact match first, then umlaut-folded
    canonical = COURT_ALIASES.get(court.strip().lower())
    if canonical:
        return canonical
    canonical = COURT_ALIASES.get(key)
    if canonical:
        return canonical
    # Fallback: prepend "Amtsgericht" if not already present
    if not court.lower().startswith("ag ") and not court.lower().startswith("amtsgericht"):
        return court.strip()
    return court.strip()


# ---------------------------------------------------------------------------
# Company name normalization
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    """Normalize a company name for matching.

    Strips legal form, normalizes umlauts to ASCII, removes punctuation,
    collapses whitespace, and case-folds.
    """
    result = strip_legal_form(name.strip())
    result = umlauts_to_ascii(result)
    result = normalize_unicode(result)
    result = _PUNCT_RE.sub(" ", result)
    result = _MULTI_SPACE_RE.sub(" ", result).strip()
    return result.lower()
