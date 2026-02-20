# Gemini Provider

**Date:** 2026-02-20
**PR:** #8

---

## Problem

OpenPlanter supported four providers (OpenAI, Anthropic, OpenRouter, Cerebras). Gemini models are widely used and have no support.

---

## Solution

Google exposes an OpenAI-compatible REST endpoint:

```
https://generativelanguage.googleapis.com/v1beta/openai
```

`OpenAICompatibleModel` can be pointed at this URL with no new model class. The only Gemini-specific requirement is `strict_tools=False`: Google's compatibility layer does not enforce `additionalProperties: false` / strict-mode schemas.

---

## Files Changed

### `agent/credentials.py`

`gemini_api_key` added to `CredentialBundle` (7 locations: dataclass field, `from_env`, `from_keyring`, `to_keyring`, `clear_keyring`, `has_any`, prompt label).

Env var priority chain:

```
OPENPLANTER_GEMINI_API_KEY → GEMINI_API_KEY → GOOGLE_API_KEY
```

`GOOGLE_API_KEY` is the third fallback so users with a pre-existing Google AI environment variable get automatic pickup.

Prompt label is `"Gemini"` (not `"Google Gemini"`).

### `agent/config.py`

Two new fields on `AgentConfig`:

```python
gemini_api_key: str | None = None
gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
```

`"gemini"` added to `PROVIDER_DEFAULT_MODELS` with default model `gemini-2.5-flash`.

### `agent/builder.py`

**Model inference:**

```python
_GEMINI_RE = re.compile(r"^gemini-", re.IGNORECASE)

def infer_provider_for_model(model: str) -> str:
    ...
    if _GEMINI_RE.match(model):
        return "gemini"
    ...
```

**`build_model_factory`** — Gemini branch:

```python
if provider == "gemini":
    return lambda model_name: OpenAICompatibleModel(
        model=model_name,
        api_key=cfg.gemini_api_key or creds.gemini_api_key or "",
        base_url=cfg.gemini_base_url,
        strict_tools=False,
    )
```

**`build_engine`** — Gemini branch mirrors the factory, also with `strict_tools=False`.

**Factory guard clause** updated to include `cfg.gemini_api_key` alongside the other provider keys.

### `agent/engine.py`

**`_model_tier`** — keyword matching, version-agnostic:

```python
def _model_tier(model: str) -> int:
    if "pro" in model:
        return 1
    if "lite" in model:
        return 3
    return 2
```

`"pro"→1`, `"lite"→3`, else→2. `"gemini-3-pro"` and `"gemini-2.5-pro"` both map to tier 1 without a code change.

**`_lowest_tier_model`** — Gemini branch returns `"gemini-2.0-flash-lite"`.

**`_MODEL_CONTEXT_WINDOWS`** — 5 Gemini entries, all `1_000_000`:

```python
"gemini-2.5-pro":        1_000_000,
"gemini-2.5-flash":      1_000_000,
"gemini-2.0-pro":        1_000_000,
"gemini-2.0-flash":      1_000_000,
"gemini-2.0-flash-lite": 1_000_000,
```

### `agent/model.py`

`EchoFallbackModel.note` updated to mention Gemini alongside other providers.

### `tests/test_gemini.py`

28 tests, no live API calls:

- Env var priority chain (`OPENPLANTER_GEMINI_API_KEY` wins over `GEMINI_API_KEY` wins over `GOOGLE_API_KEY`)
- `infer_provider_for_model` matches various `gemini-*` strings and non-Gemini strings
- `build_model_factory` produces `OpenAICompatibleModel` with correct URL and `strict_tools=False`
- `_model_tier` keyword mapping (`pro`, `lite`, unrecognised)
- `_lowest_tier_model` Gemini branch
- Context window lookups for all 5 Gemini entries
- Guard clause rejects missing key

---

## Usage

```bash
export GEMINI_API_KEY=AIzaSy-...

# By provider
openplanter --provider gemini

# By model name (provider inferred)
openplanter --model gemini-2.5-pro
```

---

## Opus Review Findings (all addressed pre-implementation)

| Finding | Resolution |
|---------|-----------|
| `strict_tools=False` must appear in both `build_engine` and `build_model_factory` | Both branches set it explicitly |
| `cfg.gemini_api_key` must be in the factory guard clause | Added alongside existing provider keys |
| Model tiers should match by keyword, not version number | `_model_tier` checks `"pro"`/`"lite"` substrings |
| Support `GOOGLE_API_KEY` as third env var fallback | Added as final fallback in `from_env` |
| Prompt label should be `"Gemini"`, not `"Google Gemini"` | Label is `"Gemini"` |
| Add Gemini to `_MODEL_CONTEXT_WINDOWS` | 5 entries, all 1 M |

---

## Alternatives Considered

### New `GeminiModel` class

Add a dedicated model class the way Anthropic has `AnthropicModel`.

**Why rejected:** Google's OpenAI-compatible endpoint makes this unnecessary. A new class would duplicate streaming, retry, and token-counting logic already in `OpenAICompatibleModel` just to set a URL and a flag.

### Per-version tier constants

Map specific version numbers (`2.0`, `2.5`) to tiers rather than keywords.

**Why rejected:** Keyword matching on `"pro"`/`"lite"` is version-agnostic. When `gemini-3-pro` ships, the mapping is correct with no code change. Version-based constants would need updating on every new release.
