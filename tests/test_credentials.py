from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.credentials import (
    CredentialBundle,
    CredentialStore,
    credential_bundle_from_key_file,
    discover_env_candidates,
    parse_api_key_file_spec,
    parse_env_file,
)


class CredentialTests(unittest.TestCase):
    def test_parse_env_file_extracts_supported_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENAI_API_KEY=oa-key",
                        "ANTHROPIC_API_KEY=an-key",
                        "OPENROUTER_API_KEY=or-key",
                        "EXA_API_KEY=exa-key",
                    ]
                ),
                encoding="utf-8",
            )
            creds = parse_env_file(env_path)
            self.assertEqual(creds.openai_api_key, "oa-key")
            self.assertEqual(creds.anthropic_api_key, "an-key")
            self.assertEqual(creds.openrouter_api_key, "or-key")
            self.assertEqual(creds.exa_api_key, "exa-key")

    def test_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = CredentialStore(workspace=root, session_root_dir=".openplanter")
            creds = CredentialBundle(
                openai_api_key="oa",
                anthropic_api_key="an",
                openrouter_api_key="or",
                exa_api_key="exa",
            )
            store.save(creds)
            loaded = store.load()
            self.assertEqual(loaded, creds)

    def test_discover_env_candidates_includes_workspace_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "RLMCode"
            workspace.mkdir(parents=True, exist_ok=True)
            candidates = discover_env_candidates(workspace)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0].resolve(), (workspace / ".env").resolve())

    def test_parse_api_key_file_spec_parses_provider_and_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            provider, path = parse_api_key_file_spec("openai=apikeys/openai.txt", cwd=cwd)
            self.assertEqual(provider, "openai")
            self.assertEqual(path, (cwd / "apikeys" / "openai.txt").resolve())

    def test_parse_api_key_file_spec_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError):
            parse_api_key_file_spec("bogus=/tmp/key.txt")

    def test_credential_bundle_from_key_file_loads_trimmed_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "openai.txt"
            path.write_text("  sk-test\n", encoding="utf-8")
            bundle = credential_bundle_from_key_file("openai", path)
            self.assertEqual(bundle.openai_api_key, "sk-test")

    def test_credential_bundle_from_key_file_rejects_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.txt"
            path.write_text("  \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                credential_bundle_from_key_file("openai", path)


if __name__ == "__main__":
    unittest.main()
