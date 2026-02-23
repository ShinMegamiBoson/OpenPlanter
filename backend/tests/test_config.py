"""Tests for redthread.config Settings."""

import os

import pytest

from redthread.config import Settings


class TestSettingsDefaults:
    """Default settings load without errors when no env vars set."""

    def test_default_settings_load(self):
        """Settings instantiates successfully with no env vars."""
        settings = Settings()
        assert settings is not None

    def test_default_database_dir(self):
        """DATABASE_DIR defaults to './data'."""
        settings = Settings()
        assert settings.DATABASE_DIR == "./data"

    def test_default_upload_dir(self):
        """UPLOAD_DIR defaults to './uploads'."""
        settings = Settings()
        assert settings.UPLOAD_DIR == "./uploads"

    def test_default_frontend_url(self):
        """FRONTEND_URL defaults to 'http://localhost:3000'."""
        settings = Settings()
        assert settings.FRONTEND_URL == "http://localhost:3000"


class TestSettingsEnvOverride:
    """Environment variable overrides are respected."""

    def test_database_dir_override(self, monkeypatch):
        """DATABASE_DIR override via env var is respected."""
        monkeypatch.setenv("DATABASE_DIR", "/custom/data/path")
        settings = Settings()
        assert settings.DATABASE_DIR == "/custom/data/path"

    def test_upload_dir_override(self, monkeypatch):
        """UPLOAD_DIR override via env var is respected."""
        monkeypatch.setenv("UPLOAD_DIR", "/custom/uploads")
        settings = Settings()
        assert settings.UPLOAD_DIR == "/custom/uploads"

    def test_frontend_url_override(self, monkeypatch):
        """FRONTEND_URL override via env var is respected."""
        monkeypatch.setenv("FRONTEND_URL", "https://myapp.example.com")
        settings = Settings()
        assert settings.FRONTEND_URL == "https://myapp.example.com"


class TestSettingsApiKeys:
    """API key fields handle missing values gracefully."""

    def test_missing_anthropic_api_key_loads_as_none(self, monkeypatch):
        """Missing ANTHROPIC_API_KEY loads as None (not a startup crash)."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        settings = Settings()
        assert settings.ANTHROPIC_API_KEY is None

    def test_anthropic_api_key_set_via_env(self, monkeypatch):
        """ANTHROPIC_API_KEY is populated when env var is set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-123")
        settings = Settings()
        assert settings.ANTHROPIC_API_KEY == "sk-test-key-123"

    def test_missing_exa_api_key_loads_as_none(self, monkeypatch):
        """Missing EXA_API_KEY loads as None."""
        monkeypatch.delenv("EXA_API_KEY", raising=False)
        settings = Settings()
        assert settings.EXA_API_KEY is None

    def test_exa_api_key_set_via_env(self, monkeypatch):
        """EXA_API_KEY is populated when env var is set."""
        monkeypatch.setenv("EXA_API_KEY", "exa-test-key-456")
        settings = Settings()
        assert settings.EXA_API_KEY == "exa-test-key-456"


class TestSettingsOfacPath:
    """OFAC_SDN_PATH field handles defaults and overrides."""

    def test_default_ofac_sdn_path_is_none(self, monkeypatch):
        """OFAC_SDN_PATH defaults to None when not set."""
        monkeypatch.delenv("OFAC_SDN_PATH", raising=False)
        settings = Settings()
        assert settings.OFAC_SDN_PATH is None

    def test_ofac_sdn_path_override(self, monkeypatch):
        """OFAC_SDN_PATH override via env var is respected."""
        monkeypatch.setenv("OFAC_SDN_PATH", "/path/to/sdn.xml")
        settings = Settings()
        assert settings.OFAC_SDN_PATH == "/path/to/sdn.xml"
