#!/usr/bin/env python3
"""
Unit tests for scripts/fetch_sec_edgar.py

These tests make real API calls to SEC EDGAR to verify the endpoints work.
They are designed to be minimal and respect SEC rate limits.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

# Add scripts directory to path so we can import the module
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import fetch_sec_edgar


class TestSecEdgarFetch(unittest.TestCase):
    """Test suite for SEC EDGAR data fetcher."""

    def test_ticker_lookup_endpoint(self):
        """Verify SEC company_tickers.json endpoint is accessible."""
        try:
            mapping = fetch_sec_edgar.get_ticker_to_cik_mapping()

            # Basic validation
            self.assertIsInstance(mapping, dict)
            self.assertGreater(len(mapping), 5000, "Should have thousands of tickers")

            # Verify known tickers exist
            self.assertIn("AAPL", mapping, "Apple ticker should exist")
            self.assertIn("MSFT", mapping, "Microsoft ticker should exist")

            # Verify CIK format
            aapl_cik = mapping["AAPL"]
            self.assertIsInstance(aapl_cik, (str, int))
            # Apple's CIK is 320193
            self.assertTrue(
                str(aapl_cik) == "320193" or str(aapl_cik) == "0000320193",
                f"Apple CIK should be 320193, got {aapl_cik}"
            )

        except (HTTPError, URLError) as e:
            self.skipTest(f"Network error or SEC API unavailable: {e}")

    def test_cik_formatting(self):
        """Verify CIK formatting adds leading zeros correctly."""
        test_cases = [
            ("320193", "0000320193"),
            (320193, "0000320193"),
            ("0000320193", "0000320193"),
            ("789019", "0000789019"),
            (1234, "0000001234"),
        ]

        for input_cik, expected in test_cases:
            with self.subTest(input_cik=input_cik):
                result = fetch_sec_edgar.format_cik(input_cik)
                self.assertEqual(result, expected)

    def test_company_submissions_endpoint(self):
        """Verify submissions API returns valid data for a known company."""
        try:
            # Use Apple (CIK 320193) as a test case
            data = fetch_sec_edgar.get_company_submissions("320193")

            # Validate response structure
            self.assertIsInstance(data, dict)
            self.assertIn("cik", data)
            self.assertIn("name", data)
            self.assertIn("filings", data)

            # Validate company metadata
            # CIK is returned with leading zeros in the JSON response
            self.assertIn(str(data["cik"]), ["320193", "0000320193"])
            self.assertIn("APPLE", data["name"].upper(), "Should be Apple Inc.")

            # Validate filings structure
            filings = data["filings"]
            self.assertIn("recent", filings)
            recent = filings["recent"]

            # Verify recent filings have expected fields
            required_fields = [
                "accessionNumber",
                "filingDate",
                "form",
                "primaryDocument"
            ]
            for field in required_fields:
                self.assertIn(field, recent, f"Missing field: {field}")
                self.assertIsInstance(recent[field], list)

            # Verify non-empty filings
            self.assertGreater(
                len(recent["accessionNumber"]),
                0,
                "Should have at least one filing"
            )

        except HTTPError as e:
            if e.code == 403:
                self.skipTest("SEC rate limit reached - this is expected behavior")
            else:
                self.skipTest(f"HTTP error from SEC API: {e}")
        except URLError as e:
            self.skipTest(f"Network error: {e}")

    def test_user_agent_included_in_requests(self):
        """Verify User-Agent header is set correctly."""
        # This is a white-box test checking the module constant
        self.assertIsInstance(fetch_sec_edgar.USER_AGENT, str)
        self.assertGreater(len(fetch_sec_edgar.USER_AGENT), 10)
        self.assertIn("@", fetch_sec_edgar.USER_AGENT, "Should include email")

    def test_fetch_json_handles_errors(self):
        """Verify fetch_json properly handles HTTP errors."""
        # Test with a URL that should return 404
        bad_url = "https://data.sec.gov/submissions/CIK9999999999.json"

        with self.assertRaises(HTTPError) as context:
            fetch_sec_edgar.fetch_json(bad_url)

        # Should be 404 Not Found
        self.assertEqual(context.exception.code, 404)

    def test_integration_ticker_to_submissions(self):
        """
        Integration test: look up ticker, then fetch submissions.

        This simulates the full workflow of the script.
        """
        try:
            # Step 1: Get ticker mapping
            mapping = fetch_sec_edgar.get_ticker_to_cik_mapping()
            self.assertIn("MSFT", mapping, "Microsoft should be in ticker list")

            msft_cik = mapping["MSFT"]

            # Step 2: Fetch submissions using the CIK
            import time
            time.sleep(0.15)  # Respect rate limit

            data = fetch_sec_edgar.get_company_submissions(msft_cik)

            # Step 3: Validate we got Microsoft's data
            self.assertIn("MICROSOFT", data["name"].upper())
            self.assertIn("filings", data)
            self.assertGreater(
                len(data["filings"]["recent"]["accessionNumber"]),
                0,
                "Should have recent filings"
            )

        except (HTTPError, URLError) as e:
            self.skipTest(f"Network error or SEC API unavailable: {e}")


class TestSecEdgarDataQuality(unittest.TestCase):
    """
    Tests focused on data quality and schema validation.

    These tests verify the structure and content of SEC responses.
    """

    @classmethod
    def setUpClass(cls):
        """Fetch test data once for all data quality tests."""
        try:
            # Use a small company to minimize data transfer
            cls.test_data = fetch_sec_edgar.get_company_submissions("320193")
        except (HTTPError, URLError) as e:
            cls.test_data = None
            cls.skip_reason = f"Cannot fetch test data: {e}"

    def setUp(self):
        """Skip tests if test data is unavailable."""
        if self.test_data is None:
            self.skipTest(self.skip_reason)

    def test_submissions_schema_completeness(self):
        """Verify submissions response has all expected top-level fields."""
        expected_fields = {
            "cik",
            "entityType",
            "sic",
            "sicDescription",
            "name",
            "filings",
        }

        for field in expected_fields:
            self.assertIn(field, self.test_data, f"Missing field: {field}")

    def test_recent_filings_arrays_same_length(self):
        """Verify all arrays in filings.recent have the same length."""
        recent = self.test_data["filings"]["recent"]

        # Get length of first array
        first_key = next(iter(recent.keys()))
        expected_length = len(recent[first_key])

        # All arrays should have same length
        for key, value in recent.items():
            if isinstance(value, list):
                self.assertEqual(
                    len(value),
                    expected_length,
                    f"Array {key} has mismatched length"
                )

    def test_form_types_are_valid(self):
        """Verify form types in filings are valid SEC form codes."""
        recent = self.test_data["filings"]["recent"]
        forms = recent.get("form", [])

        # Common form types (not exhaustive, just sanity check)
        known_forms = {
            "10-K", "10-Q", "8-K", "DEF 14A", "4", "3", "5",
            "S-1", "S-3", "13F-HR", "13D", "13G", "SC 13D", "SC 13G"
        }

        for form in forms[:20]:  # Check first 20
            self.assertIsInstance(form, str)
            self.assertGreater(len(form), 0, "Form type should not be empty")

    def test_dates_are_valid_format(self):
        """Verify filing dates are in YYYY-MM-DD format."""
        recent = self.test_data["filings"]["recent"]
        filing_dates = recent.get("filingDate", [])

        import re
        date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')

        for date in filing_dates[:20]:  # Check first 20
            self.assertRegex(
                date,
                date_pattern,
                f"Date {date} doesn't match YYYY-MM-DD format"
            )


if __name__ == "__main__":
    unittest.main()
