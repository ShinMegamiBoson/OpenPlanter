#!/usr/bin/env python3
"""
Unit tests for OFAC SDN acquisition script.

Tests verify that the OFAC SDN download endpoints are accessible and
the fetch script works correctly. Network tests are skipped if the
endpoint is unavailable.
"""

import sys
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path

# Add scripts directory to path to import the fetch module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

try:
    import fetch_ofac_sdn
except ImportError as e:
    raise ImportError(f"Could not import fetch_ofac_sdn: {e}")


class TestOfacSdnFetch(unittest.TestCase):
    """Test suite for OFAC SDN data acquisition."""

    BASE_URL = "https://www.treasury.gov/ofac/downloads/"
    SDN_URL = BASE_URL + "sdn.csv"

    @classmethod
    def setUpClass(cls):
        """Check if OFAC endpoint is accessible before running tests."""
        cls.endpoint_available = cls._check_endpoint()

    @classmethod
    def _check_endpoint(cls) -> bool:
        """
        Check if the OFAC SDN endpoint responds to HEAD request.

        Returns:
            True if endpoint is accessible, False otherwise
        """
        try:
            req = urllib.request.Request(
                cls.SDN_URL,
                method='HEAD',
                headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenPlanter test)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            return False

    def test_files_config(self):
        """Test that FILES constant is properly defined."""
        self.assertIn("sdn", fetch_ofac_sdn.FILES)
        self.assertIn("add", fetch_ofac_sdn.FILES)
        self.assertIn("alt", fetch_ofac_sdn.FILES)
        self.assertIn("comments", fetch_ofac_sdn.FILES)

        # Check SDN file structure
        sdn_config = fetch_ofac_sdn.FILES["sdn"]
        self.assertEqual(sdn_config["filename"], "sdn.csv")
        self.assertIn("expected_fields", sdn_config)
        self.assertGreater(len(sdn_config["expected_fields"]), 0)

        # Verify ent_num is in SDN fields
        self.assertIn("ent_num", [f.lower() for f in sdn_config["expected_fields"]])

    def test_base_url_format(self):
        """Test that BASE_URL is properly formatted."""
        self.assertTrue(fetch_ofac_sdn.BASE_URL.startswith("https://"))
        self.assertTrue(fetch_ofac_sdn.BASE_URL.endswith("/"))

    @unittest.skipUnless(
        sys.platform != "win32",
        "Skipping network test on Windows to avoid path issues"
    )
    def test_endpoint_accessibility(self):
        """Test that OFAC endpoint is accessible (network test)."""
        if not self.endpoint_available:
            self.skipTest("OFAC endpoint not accessible (network issue or server down)")

        # If we get here, endpoint was accessible in setUpClass
        self.assertTrue(self.endpoint_available)

    @unittest.skipUnless(
        sys.platform != "win32",
        "Skipping download test on Windows to avoid path issues"
    )
    def test_download_sdn_file(self):
        """Test downloading the primary SDN CSV file (network test)."""
        if not self.endpoint_available:
            self.skipTest("OFAC endpoint not accessible")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "sdn.csv"

            # Download the file
            success = fetch_ofac_sdn.download_file(
                self.SDN_URL,
                output_path,
                verbose=False
            )

            # Verify download succeeded
            self.assertTrue(success, "Download should succeed")
            self.assertTrue(output_path.exists(), "File should exist after download")
            self.assertGreater(output_path.stat().st_size, 0, "File should not be empty")

            # Basic content validation: file should contain numeric IDs and names
            # Note: SDN CSV files have NO headers, just data rows
            content = output_path.read_text(encoding='utf-8')
            lines = content.strip().split('\n')
            self.assertGreater(len(lines), 100, "Should have many SDN records")

            # First line should start with a number (ent_num) and contain a name
            first_line = lines[0]
            parts = first_line.split(',')
            self.assertGreater(len(parts), 3, "Should have multiple fields")
            # First field should be numeric (ent_num)
            self.assertTrue(parts[0].strip().isdigit(), "First field should be numeric ent_num")

    def test_validate_csv_schema(self):
        """Test CSV schema validation function (field count validation for no-header files)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV file (no header, just data)
            test_csv = Path(tmpdir) / "test.csv"
            test_csv.write_text("val1,val2,val3\nval4,val5,val6\n", encoding='utf-8')

            # Test exact field count match
            result = fetch_ofac_sdn.validate_csv_schema(
                test_csv,
                ["field1", "field2", "field3"],  # Names don't matter, only count
                verbose=False
            )
            self.assertTrue(result)

            # Test field count mismatch
            result = fetch_ofac_sdn.validate_csv_schema(
                test_csv,
                ["field1", "field2", "field3", "field4"],
                verbose=False
            )
            self.assertFalse(result)

            # Test empty expected fields (should pass)
            result = fetch_ofac_sdn.validate_csv_schema(
                test_csv,
                [],
                verbose=False
            )
            self.assertTrue(result)

    def test_count_csv_records(self):
        """Test CSV record counting function (no header, all rows counted)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV file with known record count (no header)
            test_csv = Path(tmpdir) / "test.csv"
            content = "row1val1,row1val2\n"
            content += "row2val1,row2val2\n"
            content += "row3val1,row3val2\n"
            test_csv.write_text(content, encoding='utf-8')

            # Count should be 3 (all rows, no header to exclude)
            count = fetch_ofac_sdn.count_csv_records(test_csv, verbose=False)
            self.assertEqual(count, 3)

    def test_fetch_ofac_sdn_creates_directory(self):
        """Test that fetch_ofac_sdn creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "ofac"

            # Directory shouldn't exist yet
            self.assertFalse(output_dir.exists())

            # Call fetch (will fail to download, but should create dir)
            # Use a non-existent base URL to avoid actual downloads in this test
            original_base = fetch_ofac_sdn.BASE_URL
            fetch_ofac_sdn.BASE_URL = "https://invalid.example.com/"

            try:
                fetch_ofac_sdn.fetch_ofac_sdn(
                    output_dir,
                    verbose=False,
                    validate=False
                )
            finally:
                fetch_ofac_sdn.BASE_URL = original_base

            # Directory should now exist
            self.assertTrue(output_dir.exists())
            self.assertTrue(output_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
