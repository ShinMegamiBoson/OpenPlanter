"""Tests for functions that had zero test coverage.

Covers: _strip_quotes, merge_missing, credentials_from_env, AgentConfig.from_env,
_summarize_args, _summarize_observation, _resolve_model_name, build_engine paths,
ExternalContext boundary conditions, and normalize_reasoning_effort edge cases.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.builder import _resolve_model_name, build_engine
from agent.config import AgentConfig
from agent.credentials import (
    CredentialBundle,
    _strip_quotes,
    credentials_from_env,
)
from agent.engine import ExternalContext, _summarize_args, _summarize_observation
from agent.model import (
    AnthropicModel,
    EchoFallbackModel,
    ModelError,
    OpenAICompatibleModel,
)
from agent.settings import normalize_reasoning_effort


# ---------------------------------------------------------------------------
# _strip_quotes
# ---------------------------------------------------------------------------


class StripQuotesTests(unittest.TestCase):
    def test_double_quotes_stripped(self) -> None:
        self.assertEqual(_strip_quotes('"hello"'), "hello")

    def test_single_quotes_stripped(self) -> None:
        self.assertEqual(_strip_quotes("'hello'"), "hello")

    def test_mismatched_quotes_not_stripped(self) -> None:
        self.assertEqual(_strip_quotes("'hello\""), "'hello\"")

    def test_no_quotes(self) -> None:
        self.assertEqual(_strip_quotes("hello"), "hello")

    def test_empty_string(self) -> None:
        self.assertEqual(_strip_quotes(""), "")

    def test_single_char(self) -> None:
        self.assertEqual(_strip_quotes("x"), "x")

    def test_whitespace_trimmed_then_stripped(self) -> None:
        self.assertEqual(_strip_quotes('  "val"  '), "val")

    def test_inner_quotes_preserved(self) -> None:
        self.assertEqual(_strip_quotes('"he said \\"hi\\""'), 'he said \\"hi\\"')


# ---------------------------------------------------------------------------
# CredentialBundle.merge_missing
# ---------------------------------------------------------------------------


class MergeMissingTests(unittest.TestCase):
    def test_fills_missing_keys(self) -> None:
        a = CredentialBundle(openai_api_key="oa")
        b = CredentialBundle(anthropic_api_key="an", exa_api_key="exa")
        a.merge_missing(b)
        self.assertEqual(a.openai_api_key, "oa")
        self.assertEqual(a.anthropic_api_key, "an")
        self.assertEqual(a.exa_api_key, "exa")

    def test_does_not_overwrite_existing(self) -> None:
        a = CredentialBundle(openai_api_key="mine")
        b = CredentialBundle(openai_api_key="theirs")
        a.merge_missing(b)
        self.assertEqual(a.openai_api_key, "mine")

    def test_merge_all_none(self) -> None:
        a = CredentialBundle()
        b = CredentialBundle()
        a.merge_missing(b)
        self.assertFalse(a.has_any())

    def test_merge_all_fields(self) -> None:
        a = CredentialBundle()
        b = CredentialBundle(
            openai_api_key="oa",
            anthropic_api_key="an",
            openrouter_api_key="or",
            cerebras_api_key="cb",
            exa_api_key="exa",
        )
        a.merge_missing(b)
        self.assertEqual(a.openai_api_key, "oa")
        self.assertEqual(a.anthropic_api_key, "an")
        self.assertEqual(a.openrouter_api_key, "or")
        self.assertEqual(a.cerebras_api_key, "cb")
        self.assertEqual(a.exa_api_key, "exa")


# ---------------------------------------------------------------------------
# credentials_from_env
# ---------------------------------------------------------------------------


class CredentialsFromEnvTests(unittest.TestCase):
    def test_reads_standard_env_vars(self) -> None:
        env = {
            "OPENAI_API_KEY": "oa-key",
            "ANTHROPIC_API_KEY": "an-key",
            "OPENROUTER_API_KEY": "or-key",
            "EXA_API_KEY": "exa-key",
        }
        with patch.dict(os.environ, env, clear=True):
            creds = credentials_from_env()
        self.assertEqual(creds.openai_api_key, "oa-key")
        self.assertEqual(creds.anthropic_api_key, "an-key")
        self.assertEqual(creds.openrouter_api_key, "or-key")
        self.assertEqual(creds.exa_api_key, "exa-key")

    def test_rlm_prefix_takes_priority(self) -> None:
        env = {
            "OPENPLANTER_OPENAI_API_KEY": "rlm-key",
            "OPENAI_API_KEY": "standard-key",
        }
        with patch.dict(os.environ, env, clear=True):
            creds = credentials_from_env()
        self.assertEqual(creds.openai_api_key, "rlm-key")

    def test_empty_env_returns_none_fields(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            creds = credentials_from_env()
        self.assertIsNone(creds.openai_api_key)
        self.assertIsNone(creds.anthropic_api_key)

    def test_whitespace_only_treated_as_none(self) -> None:
        env = {"OPENAI_API_KEY": "   "}
        with patch.dict(os.environ, env, clear=True):
            creds = credentials_from_env()
        self.assertIsNone(creds.openai_api_key)

    def test_openplanter_openai_key_from_env(self) -> None:
        env = {"OPENPLANTER_OPENAI_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=True):
            creds = credentials_from_env()
        self.assertEqual(creds.openai_api_key, "test-key")


# ---------------------------------------------------------------------------
# AgentConfig.from_env
# ---------------------------------------------------------------------------


class AgentConfigFromEnvTests(unittest.TestCase):
    def test_defaults_from_clean_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = AgentConfig.from_env("/tmp/test-ws")
        self.assertEqual(cfg.provider, "auto")
        self.assertEqual(cfg.model, "claude-opus-4-6")
        self.assertEqual(cfg.reasoning_effort, "high")
        self.assertEqual(cfg.max_depth, 4)
        self.assertEqual(cfg.max_steps_per_call, 100)
        self.assertEqual(cfg.shell, "/bin/sh")

    def test_custom_env_overrides(self) -> None:
        env = {
            "OPENPLANTER_PROVIDER": "anthropic",
            "OPENPLANTER_MODEL": "claude-opus-4-6",
            "OPENPLANTER_REASONING_EFFORT": "low",
            "OPENPLANTER_MAX_DEPTH": "5",
            "OPENPLANTER_MAX_STEPS": "20",
            "OPENPLANTER_SHELL": "/bin/bash",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = AgentConfig.from_env("/tmp/test-ws")
        self.assertEqual(cfg.provider, "anthropic")
        self.assertEqual(cfg.model, "claude-opus-4-6")
        self.assertEqual(cfg.reasoning_effort, "low")
        self.assertEqual(cfg.max_depth, 5)
        self.assertEqual(cfg.max_steps_per_call, 20)
        self.assertEqual(cfg.shell, "/bin/bash")

    def test_api_keys_from_env(self) -> None:
        env = {
            "OPENAI_API_KEY": "oa",
            "ANTHROPIC_API_KEY": "an",
            "OPENROUTER_API_KEY": "or",
            "EXA_API_KEY": "exa",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = AgentConfig.from_env("/tmp/test-ws")
        self.assertEqual(cfg.openai_api_key, "oa")
        self.assertEqual(cfg.anthropic_api_key, "an")
        self.assertEqual(cfg.openrouter_api_key, "or")
        self.assertEqual(cfg.exa_api_key, "exa")

    def test_workspace_resolved(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cfg = AgentConfig.from_env("/tmp/test-ws")
        self.assertTrue(cfg.workspace.is_absolute())


# ---------------------------------------------------------------------------
# _summarize_args
# ---------------------------------------------------------------------------


class SummarizeArgsTests(unittest.TestCase):
    def test_empty_args(self) -> None:
        self.assertEqual(_summarize_args({}), "")

    def test_short_args(self) -> None:
        result = _summarize_args({"path": "hello.txt"})
        self.assertIn("path=hello.txt", result)

    def test_long_value_truncated(self) -> None:
        result = _summarize_args({"content": "x" * 100})
        self.assertIn("...", result)
        self.assertLessEqual(len("content=" + "x" * 57 + "..."), 70)

    def test_total_length_truncated(self) -> None:
        args = {f"key{i}": f"value{i}" for i in range(20)}
        result = _summarize_args(args, max_len=50)
        self.assertLessEqual(len(result), 50)
        self.assertTrue(result.endswith("..."))

    def test_multiple_args(self) -> None:
        result = _summarize_args({"a": "1", "b": "2"})
        self.assertIn("a=1", result)
        self.assertIn("b=2", result)


# ---------------------------------------------------------------------------
# _summarize_observation
# ---------------------------------------------------------------------------


class SummarizeObservationTests(unittest.TestCase):
    def test_single_line(self) -> None:
        result = _summarize_observation("Hello world")
        self.assertEqual(result, "Hello world")

    def test_multiline_shows_stats(self) -> None:
        result = _summarize_observation("line1\nline2\nline3")
        self.assertIn("line1", result)
        self.assertIn("3 lines", result)

    def test_long_first_line_truncated(self) -> None:
        text = "x" * 300
        result = _summarize_observation(text, max_len=100)
        self.assertLessEqual(len(result), 110)  # some overhead for stats
        self.assertIn("...", result)

    def test_empty_string(self) -> None:
        result = _summarize_observation("")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _resolve_model_name
# ---------------------------------------------------------------------------


class ResolveModelNameTests(unittest.TestCase):
    def test_explicit_model_returned(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"), provider="openai", model="gpt-4o")
        self.assertEqual(_resolve_model_name(cfg), "gpt-4o")

    def test_empty_model_uses_provider_default(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"), provider="openai", model="")
        self.assertEqual(_resolve_model_name(cfg), "gpt-5.2")

    def test_empty_model_anthropic_default(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"), provider="anthropic", model="")
        self.assertEqual(_resolve_model_name(cfg), "claude-opus-4-6")

    def test_unknown_provider_fallback(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"), provider="custom", model="")
        result = _resolve_model_name(cfg)
        self.assertEqual(result, "claude-opus-4-6")

    def test_newest_without_key_raises(self) -> None:
        cfg = AgentConfig(workspace=Path("/tmp"), provider="openai", model="newest")
        with self.assertRaises(ModelError):
            _resolve_model_name(cfg)


# ---------------------------------------------------------------------------
# build_engine paths
# ---------------------------------------------------------------------------


class BuildEngineTests(unittest.TestCase):
    def test_openai_provider_with_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                workspace=Path(tmpdir),
                provider="openai",
                model="gpt-5.2",
                openai_api_key="test-key",
            )
            engine = build_engine(cfg)
            self.assertIsInstance(engine.model, OpenAICompatibleModel)

    def test_anthropic_provider_with_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                workspace=Path(tmpdir),
                provider="anthropic",
                model="claude-opus-4-6",
                anthropic_api_key="test-key",
            )
            engine = build_engine(cfg)
            self.assertIsInstance(engine.model, AnthropicModel)

    def test_no_key_fallback_to_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                workspace=Path(tmpdir),
                provider="openai",
                model="gpt-5.2",
            )
            engine = build_engine(cfg)
            self.assertIsInstance(engine.model, EchoFallbackModel)

    def test_openrouter_provider_with_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                workspace=Path(tmpdir),
                provider="openrouter",
                model="anthropic/claude-sonnet-4-5",
                openrouter_api_key="test-key",
            )
            engine = build_engine(cfg)
            self.assertIsInstance(engine.model, OpenAICompatibleModel)

    def test_model_provider_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AgentConfig(
                workspace=Path(tmpdir),
                provider="openai",
                model="claude-opus-4-6",
                openai_api_key="test-key",
            )
            with self.assertRaises(ModelError):
                build_engine(cfg)


# ---------------------------------------------------------------------------
# ExternalContext boundary conditions
# ---------------------------------------------------------------------------


class ExternalContextBoundaryTests(unittest.TestCase):
    def test_summary_empty(self) -> None:
        ctx = ExternalContext()
        self.assertEqual(ctx.summary(), "(empty)")

    def test_summary_max_items_zero(self) -> None:
        ctx = ExternalContext()
        ctx.add("item1")
        ctx.add("item2")
        self.assertEqual(ctx.summary(max_items=0), "(empty)")

    def test_summary_max_items_negative(self) -> None:
        ctx = ExternalContext()
        ctx.add("item1")
        self.assertEqual(ctx.summary(max_items=-1), "(empty)")

    def test_summary_max_items_one(self) -> None:
        ctx = ExternalContext()
        ctx.add("first")
        ctx.add("second")
        result = ctx.summary(max_items=1)
        self.assertNotIn("first", result)
        self.assertIn("second", result)

    def test_summary_truncation(self) -> None:
        ctx = ExternalContext()
        ctx.add("x" * 5000)
        ctx.add("y" * 5000)
        result = ctx.summary(max_chars=100)
        self.assertIn("truncated", result)
        self.assertLessEqual(len(result), 200)  # some overhead

    def test_add_and_count(self) -> None:
        ctx = ExternalContext()
        for i in range(5):
            ctx.add(f"obs {i}")
        self.assertEqual(len(ctx.observations), 5)


# ---------------------------------------------------------------------------
# normalize_reasoning_effort edge cases
# ---------------------------------------------------------------------------


class NormalizeReasoningEffortEdgeCasesTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(normalize_reasoning_effort(None))

    def test_whitespace_only_returns_none(self) -> None:
        self.assertIsNone(normalize_reasoning_effort("   "))

    def test_valid_values_case_insensitive(self) -> None:
        self.assertEqual(normalize_reasoning_effort("HIGH"), "high")
        self.assertEqual(normalize_reasoning_effort("Medium"), "medium")
        self.assertEqual(normalize_reasoning_effort("low"), "low")

    def test_invalid_raises_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            normalize_reasoning_effort("extreme")
        with self.assertRaises(ValueError):
            normalize_reasoning_effort("max")
        with self.assertRaises(ValueError):
            normalize_reasoning_effort("off")

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(normalize_reasoning_effort(""))


# ---------------------------------------------------------------------------
# CredentialBundle edge cases
# ---------------------------------------------------------------------------


class CredentialBundleEdgeCasesTests(unittest.TestCase):
    def test_has_any_with_whitespace_only_key(self) -> None:
        bundle = CredentialBundle(openai_api_key="   ")
        self.assertFalse(bundle.has_any())

    def test_has_any_with_real_key(self) -> None:
        bundle = CredentialBundle(exa_api_key="real")
        self.assertTrue(bundle.has_any())

    def test_has_any_with_cerebras_key(self) -> None:
        bundle = CredentialBundle(cerebras_api_key="csk-test")
        self.assertTrue(bundle.has_any())

    def test_to_json_skips_none(self) -> None:
        bundle = CredentialBundle(openai_api_key="oa")
        j = bundle.to_json()
        self.assertIn("openai_api_key", j)
        self.assertNotIn("anthropic_api_key", j)
        self.assertNotIn("cerebras_api_key", j)

    def test_to_json_includes_cerebras(self) -> None:
        bundle = CredentialBundle(cerebras_api_key="csk-test")
        j = bundle.to_json()
        self.assertIn("cerebras_api_key", j)
        self.assertEqual(j["cerebras_api_key"], "csk-test")

    def test_from_json_cerebras(self) -> None:
        bundle = CredentialBundle.from_json({"cerebras_api_key": "csk-test"})
        self.assertEqual(bundle.cerebras_api_key, "csk-test")

    def test_from_json_none_payload(self) -> None:
        bundle = CredentialBundle.from_json(None)
        self.assertFalse(bundle.has_any())

    def test_from_json_non_dict(self) -> None:
        bundle = CredentialBundle.from_json("not a dict")  # type: ignore
        self.assertFalse(bundle.has_any())

    def test_from_json_whitespace_values(self) -> None:
        bundle = CredentialBundle.from_json({"openai_api_key": "   "})
        self.assertIsNone(bundle.openai_api_key)


if __name__ == "__main__":
    unittest.main()
