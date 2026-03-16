from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.builder import _validate_model_provider, infer_provider_for_model
from agent.model import ModelError
from agent.settings import PersistentSettings, SettingsStore, normalize_reasoning_effort
from agent.tui import SLASH_COMMANDS, _compute_suggestions


class SettingsTests(unittest.TestCase):
    def test_settings_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SettingsStore(workspace=root, session_root_dir=".openplanter")
            settings = PersistentSettings(
                default_model="gpt-5.2",
                default_reasoning_effort="high",
            )
            store.save(settings)
            loaded = store.load()
            self.assertEqual(loaded.default_model, "gpt-5.2")
            self.assertEqual(loaded.default_reasoning_effort, "high")

    def test_normalize_reasoning_effort(self) -> None:
        self.assertEqual(normalize_reasoning_effort("LOW"), "low")
        self.assertEqual(normalize_reasoning_effort(" medium "), "medium")
        self.assertIsNone(normalize_reasoning_effort(""))
        with self.assertRaises(ValueError):
            normalize_reasoning_effort("extreme")

    def test_per_provider_model_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SettingsStore(workspace=root, session_root_dir=".openplanter")
            settings = PersistentSettings(
                default_model="global-model",
                default_model_openai="gpt-4.1-mini",
                default_model_anthropic="claude-opus-4-6",
                default_model_openrouter="anthropic/claude-sonnet-4-5",
            )
            store.save(settings)
            loaded = store.load()
            self.assertEqual(loaded.default_model, "global-model")
            self.assertEqual(loaded.default_model_openai, "gpt-4.1-mini")
            self.assertEqual(loaded.default_model_anthropic, "claude-opus-4-6")
            self.assertEqual(loaded.default_model_openrouter, "anthropic/claude-sonnet-4-5")

    def test_default_model_for_provider_specific(self) -> None:
        settings = PersistentSettings(
            default_model="global-model",
            default_model_openai="gpt-4.1-mini",
        )
        self.assertEqual(settings.default_model_for_provider("openai"), "gpt-4.1-mini")

    def test_default_model_for_provider_fallback(self) -> None:
        settings = PersistentSettings(default_model="global-model")
        self.assertEqual(settings.default_model_for_provider("openai"), "global-model")
        self.assertEqual(settings.default_model_for_provider("anthropic"), "global-model")

    def test_default_model_for_provider_none(self) -> None:
        settings = PersistentSettings()
        self.assertIsNone(settings.default_model_for_provider("openai"))
        self.assertIsNone(settings.default_model_for_provider("anthropic"))
        self.assertIsNone(settings.default_model_for_provider("openrouter"))
        self.assertIsNone(settings.default_model_for_provider("cerebras"))

    def test_per_provider_model_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SettingsStore(workspace=root, session_root_dir=".openplanter")
            settings = PersistentSettings(
                default_model_ollama="mistral",
            )
            store.save(settings)
            loaded = store.load()
            self.assertEqual(loaded.default_model_ollama, "mistral")

    def test_default_model_for_provider_ollama(self) -> None:
        settings = PersistentSettings(
            default_model="global-model",
            default_model_ollama="llama3.2",
        )
        self.assertEqual(settings.default_model_for_provider("ollama"), "llama3.2")

    def test_backward_compat_old_settings(self) -> None:
        """Old settings.json without per-provider keys still loads fine."""
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SettingsStore(workspace=root, session_root_dir=".openplanter")
            # Write old-format JSON (no provider keys).
            old_data = {"default_model": "old-model", "default_reasoning_effort": "high"}
            store.settings_path.write_text(json.dumps(old_data), encoding="utf-8")
            loaded = store.load()
            self.assertEqual(loaded.default_model, "old-model")
            self.assertEqual(loaded.default_reasoning_effort, "high")
            self.assertIsNone(loaded.default_model_openai)
            self.assertIsNone(loaded.default_model_anthropic)
            self.assertIsNone(loaded.default_model_openrouter)


class ComputeSuggestionsTests(unittest.TestCase):
    def test_slash_shows_all(self) -> None:
        matches, idx = _compute_suggestions("/")
        self.assertEqual(len(matches), len(SLASH_COMMANDS))
        self.assertEqual(idx, -1)

    def test_slash_e_filters(self) -> None:
        matches, idx = _compute_suggestions("/e")
        self.assertEqual(matches, ["/exit"])
        self.assertEqual(idx, -1)

    def test_slash_q_filters(self) -> None:
        matches, idx = _compute_suggestions("/q")
        self.assertEqual(matches, ["/quit"])

    def test_no_slash_no_suggestions(self) -> None:
        matches, _ = _compute_suggestions("hello")
        self.assertEqual(matches, [])

    def test_space_disables_suggestions(self) -> None:
        matches, _ = _compute_suggestions("/quit ")
        self.assertEqual(matches, [])

    def test_empty_string_no_suggestions(self) -> None:
        matches, _ = _compute_suggestions("")
        self.assertEqual(matches, [])

    def test_no_match(self) -> None:
        matches, _ = _compute_suggestions("/z")
        self.assertEqual(matches, [])

    def test_slash_cl_filters(self) -> None:
        matches, _ = _compute_suggestions("/cl")
        self.assertEqual(matches, ["/clear"])

    def test_exact_match(self) -> None:
        matches, _ = _compute_suggestions("/help")
        self.assertEqual(matches, ["/help"])

    def test_slash_m_matches_model(self) -> None:
        matches, _ = _compute_suggestions("/m")
        self.assertIn("/model", matches)

    def test_slash_r_matches_reasoning(self) -> None:
        matches, _ = _compute_suggestions("/r")
        self.assertIn("/reasoning", matches)


class InferProviderTests(unittest.TestCase):
    def test_claude_is_anthropic(self) -> None:
        self.assertEqual(infer_provider_for_model("claude-opus-4-6"), "anthropic")
        self.assertEqual(infer_provider_for_model("claude-sonnet-4-5-20250929"), "anthropic")
        self.assertEqual(infer_provider_for_model("Claude-3-Haiku"), "anthropic")

    def test_gpt_is_openai(self) -> None:
        self.assertEqual(infer_provider_for_model("gpt-5.2"), "openai")
        self.assertEqual(infer_provider_for_model("gpt-4.1-mini"), "openai")
        self.assertEqual(infer_provider_for_model("GPT-4o"), "openai")

    def test_o_series_is_openai(self) -> None:
        self.assertEqual(infer_provider_for_model("o1-mini"), "openai")
        self.assertEqual(infer_provider_for_model("o3-mini"), "openai")
        self.assertEqual(infer_provider_for_model("o4-mini"), "openai")
        self.assertEqual(infer_provider_for_model("o1"), "openai")

    def test_slash_is_openrouter(self) -> None:
        self.assertEqual(infer_provider_for_model("anthropic/claude-sonnet-4-5"), "openrouter")
        self.assertEqual(infer_provider_for_model("openai/gpt-5.2"), "openrouter")

    def test_cerebras_models(self) -> None:
        self.assertEqual(infer_provider_for_model("qwen-3-235b-a22b-instruct-2507"), "cerebras")
        self.assertEqual(infer_provider_for_model("gpt-oss-120b"), "cerebras")
        self.assertEqual(infer_provider_for_model("llama-4-scout-cerebras"), "cerebras")

    def test_ollama_models(self) -> None:
        self.assertEqual(infer_provider_for_model("llama3.2"), "ollama")
        self.assertEqual(infer_provider_for_model("llama-3.1"), "ollama")
        self.assertEqual(infer_provider_for_model("mistral"), "ollama")
        self.assertEqual(infer_provider_for_model("gemma2"), "ollama")
        self.assertEqual(infer_provider_for_model("phi3"), "ollama")
        self.assertEqual(infer_provider_for_model("codellama"), "ollama")
        self.assertEqual(infer_provider_for_model("deepseek-v2"), "ollama")
        self.assertEqual(infer_provider_for_model("qwen2.5"), "ollama")

    def test_cerebras_qwen3_not_ollama(self) -> None:
        """qwen-3 models go to Cerebras, not Ollama."""
        self.assertEqual(infer_provider_for_model("qwen-3-235b-a22b-instruct-2507"), "cerebras")

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(infer_provider_for_model("my-custom-model"))
        self.assertIsNone(infer_provider_for_model("some-random-model"))


class ValidateModelProviderTests(unittest.TestCase):
    def test_matching_provider_passes(self) -> None:
        _validate_model_provider("gpt-5.2", "openai")
        _validate_model_provider("claude-opus-4-6", "anthropic")
        _validate_model_provider("anthropic/claude-sonnet-4-5", "openrouter")

    def test_mismatch_raises(self) -> None:
        with self.assertRaises(ModelError):
            _validate_model_provider("claude-opus-4-6", "openai")
        with self.assertRaises(ModelError):
            _validate_model_provider("gpt-5.2", "anthropic")

    def test_openrouter_allows_anything(self) -> None:
        _validate_model_provider("claude-opus-4-6", "openrouter")
        _validate_model_provider("gpt-5.2", "openrouter")

    def test_unknown_model_passes(self) -> None:
        _validate_model_provider("my-custom-model", "openai")
        _validate_model_provider("some-random-model", "anthropic")


if __name__ == "__main__":
    unittest.main()
