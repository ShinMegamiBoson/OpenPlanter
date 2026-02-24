from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.__main__ import _load_credentials, build_parser
from agent.config import AgentConfig
from agent.credentials import CredentialBundle


class MainCliCredentialTests(unittest.TestCase):
    def test_build_parser_accepts_repeatable_api_key_file(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "--api-key-file", "openai=oa.txt",
            "--api-key-file", "anthropic=an.txt",
        ])
        self.assertEqual(args.api_key_file, ["openai=oa.txt", "anthropic=an.txt"])

    def test_load_credentials_api_key_file_overrides_env_but_not_direct_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            key_file = ws / "openai-key.txt"
            key_file.write_text("from-file\n", encoding="utf-8")
            cfg = AgentConfig(workspace=ws)
            parser = build_parser()
            args = parser.parse_args(["--api-key-file", f"openai={key_file}"])

            with (
                patch("agent.__main__.UserCredentialStore") as MockUserStore,
                patch("agent.__main__.CredentialStore") as MockStore,
                patch("agent.__main__.credentials_from_env", return_value=CredentialBundle(openai_api_key="from-env")),
                patch("agent.__main__.discover_env_candidates", return_value=[]),
                patch("agent.__main__.prompt_for_credentials", return_value=(CredentialBundle(), False)),
            ):
                MockUserStore.return_value.load.return_value = CredentialBundle()
                MockStore.return_value.load.return_value = CredentialBundle()
                creds = _load_credentials(cfg, args, allow_prompt=False)
            self.assertEqual(creds.openai_api_key, "from-file")

            args2 = parser.parse_args([
                "--api-key-file", f"openai={key_file}",
                "--openai-api-key", "from-cli",
            ])
            with (
                patch("agent.__main__.UserCredentialStore") as MockUserStore,
                patch("agent.__main__.CredentialStore") as MockStore,
                patch("agent.__main__.credentials_from_env", return_value=CredentialBundle(openai_api_key="from-env")),
                patch("agent.__main__.discover_env_candidates", return_value=[]),
                patch("agent.__main__.prompt_for_credentials", return_value=(CredentialBundle(), False)),
            ):
                MockUserStore.return_value.load.return_value = CredentialBundle()
                MockStore.return_value.load.return_value = CredentialBundle()
                creds2 = _load_credentials(cfg, args2, allow_prompt=False)
            self.assertEqual(creds2.openai_api_key, "from-cli")


if __name__ == "__main__":
    unittest.main()
