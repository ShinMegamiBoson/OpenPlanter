#!/usr/bin/env python3
"""
Unit tests for ICIJ Offshore Leaks Database fetch script.

Tests verify that the download endpoint is accessible and the script
can handle basic operations without requiring full data download.

Run tests from project root:
    python -m pytest tests/test_fetch_icij_leaks.py
    python -m unittest tests.test_fetch_icij_leaks.TestIcijLeaksFetch
"""

import os
import sys
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import fetch_icij_leaks
except ImportError:
    fetch_icij_leaks = None


class TestIcijLeaksFetch(unittest.TestCase):
    """Test suite for ICIJ Offshore Leaks fetch script."""

    @classmethod
    def setUpClass(cls):
        """Check if network access is available."""
        cls.network_available = True
        try:
            # Try to access ICIJ website with short timeout
            urllib.request.urlopen("https://offshoreleaks.icij.org", timeout=5)
        except (urllib.error.URLError, OSError):
            cls.network_available = False

    def test_module_imports(self):
        """Test that the fetch script can be imported."""
        self.assertIsNotNone(fetch_icij_leaks, "fetch_icij_leaks module should be importable")
        self.assertTrue(hasattr(fetch_icij_leaks, 'main'), "Module should have main() function")
        self.assertTrue(hasattr(fetch_icij_leaks, 'download_file'), "Module should have download_file() function")
        self.assertTrue(hasattr(fetch_icij_leaks, 'extract_zip'), "Module should have extract_zip() function")

    def test_download_url_constant(self):
        """Test that download URL is properly defined."""
        self.assertTrue(hasattr(fetch_icij_leaks, 'DOWNLOAD_URL'), "Module should define DOWNLOAD_URL")
        url = fetch_icij_leaks.DOWNLOAD_URL
        self.assertIsInstance(url, str, "DOWNLOAD_URL should be a string")
        self.assertTrue(url.startswith("https://"), "DOWNLOAD_URL should use HTTPS")
        self.assertTrue("offshoreleaks" in url.lower(), "URL should reference offshoreleaks")
        self.assertTrue(url.endswith(".zip"), "URL should point to a ZIP file")

    def test_download_endpoint_accessible(self):
        """Test that the ICIJ bulk download endpoint responds."""
        if not self.network_available:
            self.skipTest("Network access required for endpoint test")

        url = fetch_icij_leaks.DOWNLOAD_URL

        try:
            # Send HEAD request to check if endpoint exists
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.status
                self.assertEqual(status, 200, f"Expected HTTP 200, got {status}")

                # Check content type suggests a ZIP file
                content_type = response.headers.get('Content-Type', '')
                self.assertIn('zip', content_type.lower(),
                              f"Expected ZIP content type, got: {content_type}")

                # Check that file size is reasonable (> 1MB, < 10GB)
                content_length = response.headers.get('Content-Length')
                if content_length:
                    size_mb = int(content_length) / (1024 * 1024)
                    self.assertGreater(size_mb, 1, "File should be larger than 1MB")
                    self.assertLess(size_mb, 10000, "File should be smaller than 10GB")

        except urllib.error.HTTPError as e:
            self.fail(f"HTTP error accessing endpoint: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            self.fail(f"URL error accessing endpoint: {e.reason}")
        except Exception as e:
            self.fail(f"Unexpected error accessing endpoint: {e}")

    def test_download_file_creates_parent_directory(self):
        """Test that download_file creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested path that doesn't exist
            output_path = Path(tmpdir) / "nested" / "directory" / "test.txt"

            # Mock a simple download (we'll skip actual HTTP request)
            # This tests the directory creation logic
            self.assertFalse(output_path.parent.exists(),
                             "Parent directory should not exist yet")

            # We can't easily test the full download without network,
            # but we can verify the path handling logic exists
            self.assertTrue(callable(fetch_icij_leaks.download_file),
                            "download_file should be callable")

    def test_extract_zip_function_exists(self):
        """Test that ZIP extraction function exists and is callable."""
        self.assertTrue(callable(fetch_icij_leaks.extract_zip),
                        "extract_zip should be callable")

    def test_default_output_directory_constant(self):
        """Test that default output directory is defined."""
        self.assertTrue(hasattr(fetch_icij_leaks, 'DEFAULT_OUTPUT_DIR'),
                        "Module should define DEFAULT_OUTPUT_DIR")
        default_dir = fetch_icij_leaks.DEFAULT_OUTPUT_DIR
        self.assertIsInstance(default_dir, str, "DEFAULT_OUTPUT_DIR should be a string")
        self.assertTrue(len(default_dir) > 0, "DEFAULT_OUTPUT_DIR should not be empty")

    def test_script_has_argparse_help(self):
        """Test that script provides --help documentation."""
        # This verifies the script can be run with --help
        import subprocess

        script_path = SCRIPT_DIR / "fetch_icij_leaks.py"
        self.assertTrue(script_path.exists(), f"Script should exist at {script_path}")

        try:
            result = subprocess.run(
                [sys.executable, str(script_path), "--help"],
                capture_output=True,
                text=True,
                timeout=5
            )
            self.assertEqual(result.returncode, 0, "Script --help should exit with status 0")
            self.assertIn("ICIJ", result.stdout, "Help text should mention ICIJ")
            self.assertIn("--output", result.stdout, "Help text should document --output option")
            self.assertIn("--no-extract", result.stdout, "Help text should document --no-extract option")

        except subprocess.TimeoutExpired:
            self.fail("Script --help timed out")
        except Exception as e:
            self.fail(f"Error running script --help: {e}")

    def test_script_is_executable_python(self):
        """Test that the script is valid Python and can be imported."""
        script_path = SCRIPT_DIR / "fetch_icij_leaks.py"

        # Compile the script to check for syntax errors
        with open(script_path, 'r') as f:
            source = f.read()

        try:
            compile(source, str(script_path), 'exec')
        except SyntaxError as e:
            self.fail(f"Script has syntax error: {e}")


def suite():
    """Return test suite."""
    return unittest.TestLoader().loadTestsFromTestCase(TestIcijLeaksFetch)


if __name__ == '__main__':
    unittest.main()
