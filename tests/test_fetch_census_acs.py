#!/usr/bin/env python3
"""
Unit tests for fetch_census_acs.py script.

Includes live API tests that are skipped if network is unavailable.
Tests use small queries that don't require an API key.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

# Add scripts directory to path to import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fetch_census_acs


class TestCensusAcsFetch(unittest.TestCase):
    """Test suite for Census ACS data fetching."""

    def test_build_api_url_with_variables(self):
        """Test URL construction with variable list."""
        url = fetch_census_acs.build_api_url(
            year=2023,
            dataset="acs5",
            variables=["B19013_001E", "B19013_001M"],
            geography="state:*"
        )
        self.assertIn("https://api.census.gov/data/2023/acs/acs5", url)
        self.assertIn("get=NAME%2CB19013_001E%2CB19013_001M", url)
        self.assertIn("for=state%3A%2A", url)

    def test_build_api_url_with_group(self):
        """Test URL construction with table group."""
        url = fetch_census_acs.build_api_url(
            year=2023,
            dataset="acs5",
            group="B01001",
            geography="state:*"
        )
        self.assertIn("https://api.census.gov/data/2023/acs/acs5", url)
        self.assertIn("group%28B01001%29", url)
        self.assertIn("for=state%3A%2A", url)

    def test_build_api_url_with_geographic_filters(self):
        """Test URL construction with state and county filters."""
        url = fetch_census_acs.build_api_url(
            year=2023,
            dataset="acs5",
            variables=["B01003_001E"],
            geography="tract:*",
            state="25",
            county="025"
        )
        self.assertIn("in=state%3A25%2Bcounty%3A025", url)

    def test_build_api_url_with_api_key(self):
        """Test URL construction with API key."""
        url = fetch_census_acs.build_api_url(
            year=2023,
            dataset="acs5",
            variables=["B01003_001E"],
            geography="state:*",
            api_key="test_key_12345"
        )
        self.assertIn("key=test_key_12345", url)

    def test_build_api_url_requires_variables_or_group(self):
        """Test that either variables or group must be specified."""
        with self.assertRaises(ValueError):
            fetch_census_acs.build_api_url(
                year=2023,
                dataset="acs5",
                geography="state:*"
            )

    def test_write_csv(self):
        """Test CSV output writing."""
        test_data = [
            ["NAME", "B01003_001E", "state"],
            ["Alabama", "5074296", "01"],
            ["Alaska", "733391", "02"]
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            temp_path = f.name

        try:
            fetch_census_acs.write_csv(test_data, temp_path)

            with open(temp_path, 'r') as f:
                content = f.read()
                self.assertIn("Alabama", content)
                self.assertIn("5074296", content)
                lines = content.strip().split('\n')
                self.assertEqual(len(lines), 3)
        finally:
            os.unlink(temp_path)

    def test_write_json(self):
        """Test JSON output writing."""
        test_data = [
            ["NAME", "B01003_001E", "state"],
            ["Alabama", "5074296", "01"],
            ["Alaska", "733391", "02"]
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name

        try:
            fetch_census_acs.write_json(test_data, temp_path)

            with open(temp_path, 'r') as f:
                records = json.load(f)
                self.assertEqual(len(records), 2)
                self.assertEqual(records[0]["NAME"], "Alabama")
                self.assertEqual(records[0]["B01003_001E"], "5074296")
                self.assertEqual(records[1]["NAME"], "Alaska")
        finally:
            os.unlink(temp_path)

    @unittest.skipIf(
        os.getenv("SKIP_LIVE_TESTS") == "1",
        "Skipping live API test (set SKIP_LIVE_TESTS=0 to run)"
    )
    def test_fetch_census_data_live(self):
        """
        Live test: Fetch real data from Census API.

        This test makes an actual API call to census.gov.
        It's skipped if SKIP_LIVE_TESTS=1 environment variable is set.
        Uses a small query that doesn't require an API key.
        """
        try:
            # Build URL for a small query: total population for all states
            url = fetch_census_acs.build_api_url(
                year=2022,  # Use 2022 to ensure data availability
                dataset="acs5",
                variables=["B01003_001E"],  # Total population
                geography="state:*"
            )

            # Fetch data
            data = fetch_census_acs.fetch_census_data(url)

            # Verify response structure
            self.assertIsInstance(data, list)
            self.assertGreater(len(data), 1, "Should have header + at least one state")

            # Check header
            header = data[0]
            self.assertIn("NAME", header)
            self.assertIn("B01003_001E", header)
            self.assertIn("state", header)

            # Check that we have data for multiple states
            self.assertGreaterEqual(len(data), 50, "Should have ~50 states + territories")

            # Verify a data row has expected structure
            first_row = data[1]
            self.assertEqual(len(first_row), len(header))
            self.assertTrue(first_row[header.index("B01003_001E")].isdigit(),
                            "Population should be numeric")

            print(f"\nLive test: Successfully fetched {len(data) - 1} states from Census API")

        except urllib.error.URLError as e:
            self.skipTest(f"Network unavailable: {e}")
        except Exception as e:
            self.fail(f"Live API test failed: {e}")

    @unittest.skipIf(
        os.getenv("SKIP_LIVE_TESTS") == "1",
        "Skipping live API test (set SKIP_LIVE_TESTS=0 to run)"
    )
    def test_fetch_median_income_live(self):
        """
        Live test: Fetch median household income for Massachusetts counties.

        Tests a more complex query with geographic filtering.
        """
        try:
            url = fetch_census_acs.build_api_url(
                year=2022,
                dataset="acs5",
                variables=["B19013_001E"],  # Median household income
                geography="county:*",
                state="25"  # Massachusetts
            )

            data = fetch_census_acs.fetch_census_data(url)

            # Verify response
            self.assertGreater(len(data), 1)

            header = data[0]
            self.assertIn("B19013_001E", header)
            self.assertIn("county", header)

            # Massachusetts has 14 counties
            self.assertGreaterEqual(len(data) - 1, 14)

            print(f"\nLive test: Successfully fetched income data for {len(data) - 1} MA counties")

        except urllib.error.URLError as e:
            self.skipTest(f"Network unavailable: {e}")
        except Exception as e:
            self.fail(f"Live API test failed: {e}")

    def test_fetch_census_data_handles_http_error(self):
        """Test error handling for HTTP errors."""
        # Build URL with intentionally invalid parameters
        url = "https://api.census.gov/data/9999/acs/acs5?get=INVALID&for=state:*"

        with self.assertRaises(urllib.error.HTTPError):
            fetch_census_acs.fetch_census_data(url)

    @unittest.skipIf(
        os.getenv("SKIP_LIVE_TESTS") == "1",
        "Skipping live integration test"
    )
    def test_end_to_end_csv_output(self):
        """
        End-to-end test: Fetch data and write to CSV.

        Tests the complete workflow from API call to file output.
        """
        try:
            # Build URL
            url = fetch_census_acs.build_api_url(
                year=2022,
                dataset="acs5",
                variables=["B01003_001E", "B19013_001E"],
                geography="state:06"  # California only
            )

            # Fetch data
            data = fetch_census_acs.fetch_census_data(url)

            # Write to temporary CSV
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
                temp_path = f.name

            try:
                fetch_census_acs.write_csv(data, temp_path)

                # Read back and verify
                with open(temp_path, 'r') as f:
                    content = f.read()
                    self.assertIn("California", content)
                    self.assertIn("B01003_001E", content)
                    self.assertIn("B19013_001E", content)

                print(f"\nEnd-to-end test: Successfully wrote CSV to {temp_path}")

            finally:
                os.unlink(temp_path)

        except urllib.error.URLError as e:
            self.skipTest(f"Network unavailable: {e}")
        except Exception as e:
            self.fail(f"End-to-end test failed: {e}")


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)
