from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.credentials import (
    CredentialBundle,
    CredentialStore,
    parse_env_assignments,
    discover_env_candidates,
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
                        "OPENAI_OAUTH_TOKEN=oauth-token",
                        "ANTHROPIC_API_KEY=an-key",
                        "OPENROUTER_API_KEY=or-key",
                        "ZAI_API_KEY=zai-key",
                        "EXA_API_KEY=exa-key",
                        "FIRECRAWL_API_KEY=fc-key",
                        "BRAVE_API_KEY=brave-key",
                        "OPENPLANTER_TAVILY_API_KEY=tavily-key",
                        "MISTRAL_API_KEY=mistral-key",
                    ]
                ),
                encoding="utf-8",
            )
            creds = parse_env_file(env_path)
            self.assertEqual(creds.openai_api_key, "oa-key")
            self.assertEqual(creds.openai_oauth_token, "oauth-token")
            self.assertEqual(creds.anthropic_api_key, "an-key")
            self.assertEqual(creds.openrouter_api_key, "or-key")
            self.assertEqual(creds.zai_api_key, "zai-key")
            self.assertEqual(creds.exa_api_key, "exa-key")
            self.assertEqual(creds.firecrawl_api_key, "fc-key")
            self.assertEqual(creds.brave_api_key, "brave-key")
            self.assertEqual(creds.tavily_api_key, "tavily-key")
            self.assertEqual(creds.mistral_transcription_api_key, "mistral-key")

    def test_parse_env_assignments_preserves_generic_workspace_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENPLANTER_WORKSPACE=workspace",
                        "OPENAI_API_KEY=oa-key",
                    ]
                ),
                encoding="utf-8",
            )
            env_map = parse_env_assignments(env_path)
            self.assertEqual(env_map["OPENPLANTER_WORKSPACE"], "workspace")
            self.assertEqual(env_map["OPENAI_API_KEY"], "oa-key")

    def test_store_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = CredentialStore(workspace=root, session_root_dir=".openplanter")
            creds = CredentialBundle(
                openai_api_key="oa",
                openai_oauth_token="oauth",
                anthropic_api_key="an",
                openrouter_api_key="or",
                zai_api_key="zai",
                exa_api_key="exa",
                firecrawl_api_key="fc",
                brave_api_key="brave",
                tavily_api_key="tavily",
                mistral_transcription_api_key="mistral",
            )
            store.save(creds)
            loaded = store.load()
            self.assertEqual(loaded, creds)

    def test_discover_env_candidates_returns_nearest_ancestor_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            nested = repo / "workspace" / "deep"
            nested.mkdir(parents=True, exist_ok=True)
            (repo / ".env").write_text("OPENPLANTER_WORKSPACE=workspace\n", encoding="utf-8")
            candidates = discover_env_candidates(nested)
            self.assertEqual(candidates, [(repo / ".env").resolve()])

    def test_discover_env_candidates_returns_empty_when_no_env_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "RLMCode"
            workspace.mkdir(parents=True, exist_ok=True)
            self.assertEqual(discover_env_candidates(workspace), [])


if __name__ == "__main__":
    unittest.main()
