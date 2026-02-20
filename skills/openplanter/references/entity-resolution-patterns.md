# Entity Resolution Patterns

Comprehensive normalization rules, suffix tables, and matching patterns for cross-dataset entity resolution.

## Name Normalization Pipeline

Apply these steps in order to every entity name before comparison:

```
1. Unicode NFKD decomposition → strip diacritics (category 'Mn')
2. NFKC normalization (handles ligatures, fullwidth chars)
3. Lowercase
4. Expand/normalize ampersand: & → and
5. Extract and canonicalize legal suffix (separate from base name)
6. Strip noise words (The, A, An — for organization names only)
7. Remove punctuation except hyphens in hyphenated names
8. Collapse whitespace
9. Strip leading/trailing whitespace
```

## Corporate Suffix Canonical Mapping

The single most critical normalization step. All variants must map to a single canonical form.

| Raw Input Variants | Canonical Form |
|---|---|
| `LLC`, `L.L.C.`, `Limited Liability Company`, `limited liability co` | `LLC` |
| `Inc`, `Inc.`, `Incorporated`, `Incorp.` | `INC` |
| `Corp`, `Corp.`, `Corporation` | `CORP` |
| `Ltd`, `Ltd.`, `Limited`, `Limted` (common typo) | `LTD` |
| `Co`, `Co.`, `Company`, `Compny` | `CO` |
| `LP`, `L.P.`, `Limited Partnership` | `LP` |
| `LLP`, `L.L.P.`, `Limited Liability Partnership` | `LLP` |
| `PLC`, `P.L.C.`, `Public Limited Company` | `PLC` |
| `GmbH`, `Gesellschaft mit beschraenkter Haftung` | `GMBH` |
| `SA`, `S.A.`, `Societe Anonyme`, `Sociedad Anonima` | `SA` |
| `AG`, `Aktiengesellschaft` | `AG` |
| `BV`, `B.V.`, `Besloten Vennootschap` | `BV` |
| `SRL`, `S.R.L.`, `Sociedad de Responsabilidad Limitada` | `SRL` |
| `Pty`, `Pty Ltd`, `Proprietary Limited` | `PTY` |
| `PC`, `P.C.`, `Professional Corporation` | `PC` |
| `PA`, `P.A.`, `Professional Association` | `PA` |
| `NV`, `N.V.`, `Naamloze Vennootschap` | `NV` |
| `SARL`, `S.A.R.L.` | `SARL` |

**Regex patterns for extraction:**

```python
SUFFIX_PATTERNS = [
    (r'\blimited\s+liability\s+company\b', 'LLC'),
    (r'\bl\.?l\.?c\.?\b', 'LLC'),
    (r'\bincorporated\b', 'INC'),
    (r'\binc\.?\b', 'INC'),
    (r'\bcorporation\b', 'CORP'),
    (r'\bcorp\.?\b', 'CORP'),
    (r'\blimited\s+liability\s+partnership\b', 'LLP'),
    (r'\bl\.?l\.?p\.?\b', 'LLP'),
    (r'\blimited\s+partnership\b', 'LP'),
    (r'\bl\.?p\.?\b', 'LP'),
    (r'\blimited\b', 'LTD'),
    (r'\bltd\.?\b', 'LTD'),
    (r'\bcompany\b', 'CO'),
    (r'\bco\.?\b', 'CO'),
    (r'\bpublic\s+limited\s+company\b', 'PLC'),
    (r'\bp\.?l\.?c\.?\b', 'PLC'),
    (r'\bprofessional\s+corporation\b', 'PC'),
    (r'\bp\.?c\.?\b', 'PC'),
    (r'\bprofessional\s+association\b', 'PA'),
    (r'\bp\.?a\.?\b', 'PA'),
]
```

**Important**: Match longest pattern first (e.g., "Limited Liability Company" before "Limited" and "Company").

## Person Name Normalization

### Nickname Expansion Table

| Nickname | Canonical |
|---|---|
| Bill, Billy, Willy | William |
| Bob, Bobby, Rob, Robbie | Robert |
| Jim, Jimmy, Jamie | James |
| Mike, Mikey | Michael |
| Tom, Tommy | Thomas |
| Dick, Rick, Rich | Richard |
| Jack, Jackie | John |
| Ted, Teddy, Ed, Eddie, Ned | Edward |
| Joe, Joey | Joseph |
| Dan, Danny | Daniel |
| Dave, Davy | David |
| Pat, Patty | Patrick / Patricia |
| Liz, Beth, Betty, Betsy, Eliza | Elizabeth |
| Kate, Katie, Kathy, Cathy | Katherine / Catherine |
| Maggie, Meg, Peggy | Margaret |
| Sue, Suzy | Susan |
| Jenny, Jen | Jennifer |
| Chris | Christopher / Christine |
| Alex | Alexander / Alexandra |
| Sam | Samuel / Samantha |
| Tony | Anthony |
| Chuck | Charles |
| Larry | Lawrence |
| Jerry | Gerald / Jerome |
| Harry | Harold / Henry |
| Hank | Henry |
| Steve | Stephen / Steven |
| Andy | Andrew |
| Tim | Timothy |
| Jeff | Jeffrey |
| Ron | Ronald |

### Person Name Rules

| Issue | Rule |
|---|---|
| Middle name/initial | Match on `first + last` only as fallback; middle initial mismatch = warning not failure |
| Name order | Try `First Last` and `Last, First` both |
| Titles/honorifics | Strip: Dr., Mr., Mrs., Ms., Prof., Jr., Sr., II, III, IV, Esq. |
| Suffixes | Separate: Jr., Sr., II, III, IV, Esq., MD, PhD, CPA |
| Hyphenated names | Treat as single unit; also try each component separately |
| Transliteration variants | Arabic: Mohamed/Muhammad/Mohammed; Chinese: Wei/Wai; Russian: Sergey/Sergei |

## Address Normalization

### USPS Canonical Abbreviations

| Full Form | Canonical | Full Form | Canonical |
|---|---|---|---|
| Street | ST | Suite | STE |
| Avenue | AVE | Apartment | APT |
| Boulevard | BLVD | Unit | UNIT |
| Drive | DR | Building | BLDG |
| Road | RD | Floor | FL |
| Lane | LN | Room | RM |
| Court | CT | Department | DEPT |
| Place | PL | Highway | HWY |
| Circle | CIR | Parkway | PKWY |
| Way | WAY | Expressway | EXPY |
| Terrace | TER | Turnpike | TPKE |
| Trail | TRL | Crossing | XING |

### Directional Abbreviations

| Full | Canonical |
|---|---|
| North | N |
| South | S |
| East | E |
| West | W |
| Northeast | NE |
| Northwest | NW |
| Southeast | SE |
| Southwest | SW |

### State Abbreviations

Always normalize to 2-letter USPS code. Example: `New York` → `NY`, `California` → `CA`.

### Address Normalization Pipeline

```
1. Uppercase entire address
2. Replace directional words with abbreviations
3. Replace street type words with abbreviations
4. Replace unit type words with abbreviations
5. Remove periods and commas
6. Normalize spacing (collapse multiple spaces)
7. Remove # symbol before unit numbers
```

## Common Abbreviation Expansions

| Abbreviation | Full Form |
|---|---|
| Intl, Int'l | International |
| Mgmt | Management |
| Svcs, Svc | Services, Service |
| Assoc, Assocs | Associates |
| Bros | Brothers |
| Natl, Nat'l | National |
| Dept | Department |
| Grp | Group |
| Hldgs | Holdings |
| Fin, Finl | Financial |
| Tech | Technology / Technologies |
| Sys | Systems |
| Dev | Development |
| Mfg | Manufacturing |
| Dist | Distribution / Distributing |
| Prop, Props | Properties |
| Invt, Inv | Investment(s) |
| Ins | Insurance |
| Rlty | Realty |
| Pharm | Pharmaceutical(s) |
| Engr, Eng | Engineering |
| Consult | Consulting |
| Comm, Comms | Communications |
| Ent, Entmt | Entertainment |
| Advsr, Adv | Advisor(s) / Advisory |

## Fuzzy Matching Thresholds

### Recommended Thresholds (difflib.SequenceMatcher)

| Score Range | Classification | Action |
|---|---|---|
| >= 0.95 | Near-certain (exact after normalization) | Auto-merge |
| 0.85–0.94 | High confidence | Auto-merge with audit log |
| 0.70–0.84 | Probable match | Queue for review |
| 0.55–0.69 | Possible match | Surface as candidate, do not auto-merge |
| < 0.55 | No match | Discard |

### Signal Weights for Composite Scoring

| Signal | Weight | Notes |
|---|---|---|
| TIN/EIN exact match | 1.0 | Near-deterministic; hard signal |
| Phone E.164 exact match | 0.8 | Hard signal |
| Email exact match | 0.8 | Hard signal |
| Name token set ratio | 0.5 | Primary soft signal |
| Name Jaro-Winkler | 0.3 | Supplementary |
| Name phonetic match | 0.2 | Supplementary |
| Address exact match | 0.4 | Moderate signal |
| Address fuzzy match | 0.2 | Weak signal |
| State/jurisdiction match | 0.1 | Weak signal |
| Suffix mismatch | -0.1 | Penalty |
| Country mismatch | -0.5 | Strong disqualifier |

## Edge Cases

### Known Registered Agent Addresses (Do NOT use for positive matching)

These addresses host 10,000+ entities and should be flagged:

- `1209 Orange Street, Wilmington, DE 19801` — The Corporation Trust Company (~250K entities)
- `2711 Centerville Road, Suite 400, Wilmington, DE 19808` — Corporation Service Company
- `850 New Burton Road, Suite 201, Dover, DE 19904` — Registered Agents Inc
- `1013 Centre Road, Suite 403-B, Wilmington, DE 19805` — The Company Corporation
- `311 S State Street, Dover, DE 19901` — Legalinc Corporate Services
- `1100 H Street NW, Suite 840, Washington, DC 20005` — CT Corporation System (DC)

When either entity address is a known RA address, exclude address from positive matching signals.

### DBA (Doing Business As) Handling

A single legal entity may file under multiple trade names:
- `McDonald's Corporation` operates as `McDonald's`
- `Alphabet Inc` operates as `Google`
- `Meta Platforms Inc` operates as `Facebook`, `Instagram`, `WhatsApp`

Strategy: maintain a `legal_name ↔ dba_name` mapping. When matching, try both. If DBA match scores >= 0.85, link to parent legal entity.

### Shell Company Detection Signals

- Generic name pattern: `[Word] Holdings LLC`, `[Word] Ventures LLC`, `[Word] Capital Partners LLC`
- Known RA address (see above)
- No officers listed, no phone, no web presence
- Recently formed (within 90 days of investigated transaction)
- Same formation date as multiple other entities with same RA

**Rule**: Require >= 2 independent signals for shell-company entities. Do not trust name or address alone.

### Regex Patterns for Entity Extraction

```python
# EIN / TIN (XX-XXXXXXX)
EIN_PAT = r'\b(\d{2}-\d{7})\b'

# US Phone (flexible)
PHONE_PAT = r'(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}'

# Email
EMAIL_PAT = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

# Dollar amounts
DOLLAR_PAT = r'\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\b'

# Dates (ISO, US, written)
DATE_ISO = r'\b\d{4}[-/]\d{2}[-/]\d{2}\b'
DATE_US = r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'
DATE_WRITTEN = r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b'
```
