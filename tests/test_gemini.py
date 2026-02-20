"""Tests for the Gemini provider integration (no live API calls)."""
from __future__ import annotations

from agent.builder import build_engine, build_model_factory, infer_provider_for_model
from agent.config import PROVIDER_DEFAULT_MODELS, AgentConfig
from agent.credentials import CredentialBundle, credentials_from_env, parse_env_file
from agent.engine import _lowest_tier_model, _model_tier
from agent.model import OpenAICompatibleModel

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

class TestGeminiCredentials:
    def test_bundle_field_exists(self):
        cb = CredentialBundle(gemini_api_key="AIzaSy-x")
        assert cb.gemini_api_key == "AIzaSy-x"

    def test_has_any_with_gemini_only(self):
        assert CredentialBundle(gemini_api_key="key").has_any()

    def test_merge_missing(self):
        a = CredentialBundle()
        b = CredentialBundle(gemini_api_key="key-b")
        a.merge_missing(b)
        assert a.gemini_api_key == "key-b"

    def test_merge_does_not_overwrite(self):
        a = CredentialBundle(gemini_api_key="key-a")
        b = CredentialBundle(gemini_api_key="key-b")
        a.merge_missing(b)
        assert a.gemini_api_key == "key-a"

    def test_to_from_json_roundtrip(self):
        cb = CredentialBundle(gemini_api_key="AIzaSy-x")
        j = cb.to_json()
        assert j["gemini_api_key"] == "AIzaSy-x"
        cb2 = CredentialBundle.from_json(j)
        assert cb2.gemini_api_key == "AIzaSy-x"

    def test_from_json_missing_key_is_none(self):
        cb = CredentialBundle.from_json({})
        assert cb.gemini_api_key is None

    def test_parse_env_file_gemini_api_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("GEMINI_API_KEY=AIzaSy-file\n")
        cb = parse_env_file(env)
        assert cb.gemini_api_key == "AIzaSy-file"

    def test_parse_env_file_openplanter_prefix(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OPENPLANTER_GEMINI_API_KEY=AIzaSy-prefixed\n")
        cb = parse_env_file(env)
        assert cb.gemini_api_key == "AIzaSy-prefixed"

    def test_parse_env_file_google_api_key_fallback(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("GOOGLE_API_KEY=AIzaSy-google\n")
        cb = parse_env_file(env)
        assert cb.gemini_api_key == "AIzaSy-google"

    def test_credentials_from_env_gemini(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-env")
        cb = credentials_from_env()
        assert cb.gemini_api_key == "AIzaSy-env"

    def test_credentials_from_env_google_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENPLANTER_GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSy-google")
        cb = credentials_from_env()
        assert cb.gemini_api_key == "AIzaSy-google"

    def test_credentials_from_env_openplanter_prefix_wins(self, monkeypatch):
        monkeypatch.setenv("OPENPLANTER_GEMINI_API_KEY", "AIzaSy-prefixed")
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-plain")
        cb = credentials_from_env()
        assert cb.gemini_api_key == "AIzaSy-prefixed"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestGeminiConfig:
    def test_default_model_in_provider_defaults(self):
        assert "gemini" in PROVIDER_DEFAULT_MODELS
        assert PROVIDER_DEFAULT_MODELS["gemini"].startswith("gemini-")

    def test_config_has_gemini_fields(self, tmp_path):
        cfg = AgentConfig(workspace=tmp_path, gemini_api_key="key")
        assert cfg.gemini_api_key == "key"
        assert "generativelanguage.googleapis.com" in cfg.gemini_base_url

    def test_from_env_reads_gemini_api_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-env")
        cfg = AgentConfig.from_env(tmp_path)
        assert cfg.gemini_api_key == "AIzaSy-env"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class TestGeminiBuilder:
    def test_infer_provider_flash(self):
        assert infer_provider_for_model("gemini-2.5-flash") == "gemini"

    def test_infer_provider_pro(self):
        assert infer_provider_for_model("gemini-3-pro") == "gemini"

    def test_infer_provider_lite(self):
        assert infer_provider_for_model("gemini-2.0-flash-lite") == "gemini"

    def test_infer_provider_openrouter_gemini_not_matched(self):
        # google/gemini-* should go to openrouter, not gemini
        assert infer_provider_for_model("google/gemini-2.5-flash") == "openrouter"

    def test_build_engine_returns_openai_compatible_model(self, tmp_path):
        cfg = AgentConfig(
            workspace=tmp_path,
            provider="gemini",
            model="gemini-2.5-flash",
            gemini_api_key="AIzaSy-test",
        )
        engine = build_engine(cfg)
        assert isinstance(engine.model, OpenAICompatibleModel)

    def test_build_engine_strict_tools_false(self, tmp_path):
        cfg = AgentConfig(
            workspace=tmp_path,
            provider="gemini",
            model="gemini-2.5-flash",
            gemini_api_key="AIzaSy-test",
        )
        engine = build_engine(cfg)
        assert engine.model.strict_tools is False

    def test_build_engine_correct_base_url(self, tmp_path):
        cfg = AgentConfig(
            workspace=tmp_path,
            provider="gemini",
            model="gemini-2.5-flash",
            gemini_api_key="AIzaSy-test",
        )
        engine = build_engine(cfg)
        assert "generativelanguage.googleapis.com" in engine.model.base_url

    def test_model_factory_creates_gemini_model(self, tmp_path):
        cfg = AgentConfig(workspace=tmp_path, gemini_api_key="AIzaSy-test")
        factory = build_model_factory(cfg)
        assert factory is not None
        m = factory("gemini-2.5-flash")
        assert isinstance(m, OpenAICompatibleModel)
        assert m.strict_tools is False


# ---------------------------------------------------------------------------
# Model tier
# ---------------------------------------------------------------------------

class TestGeminiModelTier:
    def test_pro_is_tier_1(self):
        assert _model_tier("gemini-2.5-pro") == 1
        assert _model_tier("gemini-3-pro-preview") == 1

    def test_flash_is_tier_2(self):
        assert _model_tier("gemini-2.5-flash") == 2
        assert _model_tier("gemini-3-flash") == 2

    def test_lite_is_tier_3(self):
        assert _model_tier("gemini-2.0-flash-lite") == 3

    def test_lowest_tier_is_flash_lite(self):
        name, effort = _lowest_tier_model("gemini-2.5-pro")
        assert name == "gemini-2.0-flash-lite"
        assert effort is None

    def test_lowest_tier_flash_model_also_gives_lite(self):
        name, _ = _lowest_tier_model("gemini-2.5-flash")
        assert name == "gemini-2.0-flash-lite"
