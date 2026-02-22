#!/usr/bin/env python3
"""
Unit tests for scripts/fetch_osha.py

Tests the OSHA inspection data fetcher script with stdlib-only implementation.
Live tests require DOL_API_KEY environment variable and network connectivity.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fetch_osha


class TestOshaFetch(unittest.TestCase):
    """Tests for OSHA data fetcher."""

    def test_build_filter_state(self):
        """Test filter builder with state parameter."""
        filter_json = fetch_osha.build_filter(state="MA")
        filters = json.loads(filter_json)

        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["field"], "site_state")
        self.assertEqual(filters[0]["operator"], "eq")
        self.assertEqual(filters[0]["value"], "MA")

    def test_build_filter_year(self):
        """Test filter builder with year parameter."""
        filter_json = fetch_osha.build_filter(year=2024)
        filters = json.loads(filter_json)

        self.assertEqual(len(filters), 2)
        # Should create gt and lt filters for year boundaries
        date_filters = [f for f in filters if f["field"] == "open_date"]
        self.assertEqual(len(date_filters), 2)

        operators = {f["operator"] for f in date_filters}
        self.assertEqual(operators, {"gt", "lt"})

    def test_build_filter_establishment(self):
        """Test filter builder with establishment name."""
        filter_json = fetch_osha.build_filter(establishment="ABC Corp")
        filters = json.loads(filter_json)

        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["field"], "estab_name")
        self.assertEqual(filters[0]["operator"], "like")
        self.assertEqual(filters[0]["value"], "ABC Corp")

    def test_build_filter_combined(self):
        """Test filter builder with multiple parameters."""
        filter_json = fetch_osha.build_filter(
            state="CA",
            year=2023,
            establishment="Test Inc"
        )
        filters = json.loads(filter_json)

        # Should have state + 2 date filters + establishment = 4 filters
        self.assertEqual(len(filters), 4)

        fields = {f["field"] for f in filters}
        self.assertIn("site_state", fields)
        self.assertIn("open_date", fields)
        self.assertIn("estab_name", fields)

    def test_build_filter_none(self):
        """Test filter builder with no parameters returns None."""
        filter_json = fetch_osha.build_filter()
        self.assertIsNone(filter_json)

    def test_format_as_csv_empty(self):
        """Test CSV formatter with empty records."""
        csv = fetch_osha.format_as_csv([])
        self.assertEqual(csv, "")

    def test_format_as_csv_single_record(self):
        """Test CSV formatter with single record."""
        records = [
            {
                "activity_nr": "12345",
                "estab_name": "Test Corp",
                "site_state": "MA",
                "open_date": "2024-01-15"
            }
        ]

        csv = fetch_osha.format_as_csv(records)
        lines = csv.strip().split("\n")

        self.assertEqual(len(lines), 2)  # Header + 1 data row
        self.assertIn("activity_nr", lines[0])
        self.assertIn("12345", lines[1])
        self.assertIn("Test Corp", lines[1])

    def test_format_as_csv_with_commas(self):
        """Test CSV formatter handles commas in values."""
        records = [
            {
                "name": "Smith, John",
                "city": "Boston, MA"
            }
        ]

        csv = fetch_osha.format_as_csv(records)
        lines = csv.strip().split("\n")

        # Values with commas should be quoted
        self.assertIn('"Smith, John"', lines[1])
        self.assertIn('"Boston, MA"', lines[1])

    def test_format_as_csv_with_quotes(self):
        """Test CSV formatter handles quotes in values."""
        records = [
            {
                "name": 'ABC "The Best" Corp'
            }
        ]

        csv = fetch_osha.format_as_csv(records)
        lines = csv.strip().split("\n")

        # Quotes should be escaped
        self.assertIn('""', lines[1])

    @unittest.skipIf(
        not os.environ.get("DOL_API_KEY"),
        "DOL_API_KEY not set; skipping live API test"
    )
    def test_fetch_inspections_live(self):
        """
        Live test: fetch a small number of real OSHA inspections.

        Requires DOL_API_KEY environment variable.
        Makes a real API call to data.dol.gov.
        """
        api_key = os.environ.get("DOL_API_KEY")

        try:
            result = fetch_osha.fetch_inspections(
                api_key=api_key,
                top=5,  # Small request
                skip=0,
                sort_by="open_date",
                sort_order="desc"
            )

            # Verify response structure
            self.assertIsInstance(result, (list, dict))

            # Extract records (handle different response formats)
            if isinstance(result, list):
                records = result
            elif isinstance(result, dict):
                records = (
                    result.get("results") or
                    result.get("data") or
                    result.get("inspection") or
                    []
                )
            else:
                records = []

            # Should get at least 1 record (OSHA has tons of data)
            self.assertGreater(len(records), 0, "Expected at least 1 inspection record")

            # Check first record has expected fields
            if records:
                first_record = records[0]
                # Common fields that should be present
                expected_fields = ["activity_nr", "estab_name"]
                for field in expected_fields:
                    self.assertIn(
                        field,
                        first_record,
                        f"Expected field '{field}' in inspection record"
                    )

        except Exception as e:
            self.fail(f"Live API test failed: {e}")

    @unittest.skipIf(
        not os.environ.get("DOL_API_KEY"),
        "DOL_API_KEY not set; skipping live filter test"
    )
    def test_fetch_with_state_filter_live(self):
        """
        Live test: fetch inspections with state filter.

        Verifies filter syntax works correctly with DOL API.
        """
        api_key = os.environ.get("DOL_API_KEY")
        filter_json = fetch_osha.build_filter(state="MA")

        try:
            result = fetch_osha.fetch_inspections(
                api_key=api_key,
                top=3,
                filter_json=filter_json
            )

            # Extract records
            if isinstance(result, list):
                records = result
            elif isinstance(result, dict):
                records = (
                    result.get("results") or
                    result.get("data") or
                    result.get("inspection") or
                    []
                )
            else:
                records = []

            # Verify all returned records are from MA
            for record in records:
                if "site_state" in record:
                    self.assertEqual(
                        record["site_state"],
                        "MA",
                        "Filter failed: non-MA record returned"
                    )

        except Exception as e:
            self.fail(f"Live filter test failed: {e}")

    def test_main_missing_api_key(self):
        """Test main() exits with error when API key missing."""
        with patch.object(sys, "argv", ["fetch_osha.py"]):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as cm:
                    fetch_osha.main()

                self.assertEqual(cm.exception.code, 1)


class TestOshaFetchIntegration(unittest.TestCase):
    """Integration tests for fetch_osha script."""

    @unittest.skipIf(
        not os.environ.get("DOL_API_KEY"),
        "DOL_API_KEY not set; skipping integration test"
    )
    def test_full_workflow(self):
        """
        Integration test: fetch and format data end-to-end.

        Tests the complete workflow from API fetch to CSV formatting.
        """
        api_key = os.environ.get("DOL_API_KEY")

        # Fetch small dataset
        result = fetch_osha.fetch_inspections(
            api_key=api_key,
            top=5
        )

        # Extract records
        if isinstance(result, list):
            records = result
        elif isinstance(result, dict):
            records = (
                result.get("results") or
                result.get("data") or
                result.get("inspection") or
                []
            )
        else:
            records = []

        self.assertGreater(len(records), 0, "No records fetched")

        # Test JSON formatting
        json_output = json.dumps(records, indent=2, default=str)
        self.assertIsInstance(json_output, str)
        self.assertGreater(len(json_output), 0)

        # Test CSV formatting
        csv_output = fetch_osha.format_as_csv(records)
        self.assertIsInstance(csv_output, str)
        self.assertGreater(len(csv_output), 0)

        # CSV should have at least header + 1 data row
        csv_lines = csv_output.strip().split("\n")
        self.assertGreaterEqual(len(csv_lines), 2)


if __name__ == "__main__":
    unittest.main()
