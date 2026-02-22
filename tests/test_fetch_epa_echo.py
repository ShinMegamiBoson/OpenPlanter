#!/usr/bin/env python3
"""
Unit tests for EPA ECHO data acquisition script.

Tests the fetch_epa_echo.py script's ability to query the EPA ECHO API
and parse responses. Includes live API tests that are skipped if network
is unavailable.
"""

import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock
from io import StringIO

# Add scripts directory to path to import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fetch_epa_echo


class TestEpaEchoFetch(unittest.TestCase):
    """Test suite for EPA ECHO data acquisition."""

    def test_build_query_params_state(self):
        """Test building query parameters with state filter."""
        args = MagicMock()
        args.facility_name = None
        args.state = "ma"
        args.city = None
        args.zip_code = None
        args.radius = None
        args.latitude = None
        args.longitude = None
        args.compliance = None
        args.major_only = False
        args.program = None
        args.limit = 100

        params = fetch_epa_echo.build_query_params(args)

        self.assertEqual(params["p_st"], "MA")
        self.assertEqual(params["output"], "JSON")
        self.assertEqual(params["responseset"], "100")

    def test_build_query_params_radius(self):
        """Test building query parameters with radius search."""
        args = MagicMock()
        args.facility_name = None
        args.state = None
        args.city = None
        args.zip_code = None
        args.radius = 10.0
        args.latitude = 42.3601
        args.longitude = -71.0589
        args.compliance = None
        args.major_only = False
        args.program = None
        args.limit = 50

        params = fetch_epa_echo.build_query_params(args)

        self.assertEqual(params["p_lat"], "42.3601")
        self.assertEqual(params["p_long"], "-71.0589")
        self.assertEqual(params["p_radius"], "10.0")
        self.assertEqual(params["responseset"], "50")

    def test_build_query_params_compliance(self):
        """Test building query parameters with compliance filter."""
        args = MagicMock()
        args.facility_name = None
        args.state = "MA"
        args.city = None
        args.zip_code = None
        args.radius = None
        args.latitude = None
        args.longitude = None
        args.compliance = "SNC"
        args.major_only = True
        args.program = "NPDES"
        args.limit = 100

        params = fetch_epa_echo.build_query_params(args)

        self.assertEqual(params["p_cs"], "SNC")
        self.assertEqual(params["p_maj"], "Y")
        self.assertEqual(params["p_med"], "NPDES")

    def test_extract_facility_records_facilities_key(self):
        """Test extracting facility records from response with Facilities key."""
        response = {
            "Results": {
                "QueryID": "12345",
                "QueryRows": "2",
                "Facilities": [
                    {"RegistryID": "110000001234", "FacilityName": "Test Facility 1"},
                    {"RegistryID": "110000005678", "FacilityName": "Test Facility 2"}
                ]
            }
        }

        facilities = fetch_epa_echo.extract_facility_records(response)

        self.assertEqual(len(facilities), 2)
        self.assertEqual(facilities[0]["FacilityName"], "Test Facility 1")
        self.assertEqual(facilities[1]["FacilityName"], "Test Facility 2")

    def test_extract_facility_records_empty(self):
        """Test extracting facility records from empty response."""
        response = {"Results": {}}

        facilities = fetch_epa_echo.extract_facility_records(response)

        self.assertEqual(len(facilities), 0)

    def test_extract_facility_records_no_results(self):
        """Test extracting facility records from response with no Results key."""
        response = {"Error": "Invalid query"}

        facilities = fetch_epa_echo.extract_facility_records(response)

        self.assertEqual(len(facilities), 0)

    @unittest.skipUnless(
        os.environ.get('RUN_LIVE_TESTS') or True,  # Always run by default
        "Skipping live API test"
    )
    def test_live_api_state_query(self):
        """Live test: Query EPA ECHO API for facilities in Rhode Island (small state)."""
        args = MagicMock()
        args.facility_name = None
        args.state = "RI"  # Rhode Island - small state, should return quickly
        args.city = None
        args.zip_code = None
        args.radius = None
        args.latitude = None
        args.longitude = None
        args.compliance = None
        args.major_only = False
        args.program = None
        args.limit = 10  # Small limit for fast test

        params = fetch_epa_echo.build_query_params(args)

        try:
            response = fetch_epa_echo.fetch_facilities(params)

            # Verify response structure
            self.assertIn("Results", response)
            self.assertIsInstance(response["Results"], dict)

            # Extract facilities
            facilities = fetch_epa_echo.extract_facility_records(response)

            # Should have some facilities (RI has industrial facilities)
            self.assertGreaterEqual(len(facilities), 1)

            # Verify facility structure
            if facilities:
                facility = facilities[0]
                # Basic fields that should exist
                self.assertTrue(
                    any(k in facility for k in ["RegistryID", "FacilityName", "AIRIDs"]),
                    f"Facility missing expected fields. Keys: {facility.keys()}"
                )

            print(f"\nLive test: Retrieved {len(facilities)} facilities from Rhode Island")

        except Exception as e:
            # If network unavailable, skip test
            if "timed out" in str(e).lower() or "network" in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    @unittest.skipUnless(
        os.environ.get('RUN_LIVE_TESTS') or True,
        "Skipping live API test"
    )
    def test_live_api_zip_query(self):
        """Live test: Query EPA ECHO API by ZIP code."""
        args = MagicMock()
        args.facility_name = None
        args.state = None
        args.city = None
        args.zip_code = "02101"  # Boston, MA - should have facilities
        args.radius = None
        args.latitude = None
        args.longitude = None
        args.compliance = None
        args.major_only = False
        args.program = None
        args.limit = 5

        params = fetch_epa_echo.build_query_params(args)

        try:
            response = fetch_epa_echo.fetch_facilities(params)

            # Verify response structure
            self.assertIn("Results", response)

            # Extract facilities (may be 0 if ZIP has no regulated facilities)
            facilities = fetch_epa_echo.extract_facility_records(response)

            print(f"\nLive test: Retrieved {len(facilities)} facilities for ZIP 02101")

            # This test passes even with 0 results (some ZIPs have no facilities)
            self.assertIsInstance(facilities, list)

        except Exception as e:
            if "timed out" in str(e).lower() or "network" in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    def test_write_csv_creates_file(self):
        """Test CSV writing functionality."""
        import tempfile
        import csv

        facilities = [
            {"RegistryID": "123", "FacilityName": "Test 1", "State": "MA"},
            {"RegistryID": "456", "FacilityName": "Test 2", "State": "MA"}
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            temp_path = f.name

        try:
            fetch_epa_echo.write_csv(facilities, temp_path)

            # Verify file was created and contains data
            with open(temp_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["RegistryID"], "123")
            self.assertEqual(rows[1]["FacilityName"], "Test 2")

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_write_json_creates_file(self):
        """Test JSON writing functionality."""
        import tempfile

        facilities = [
            {"RegistryID": "123", "FacilityName": "Test 1"},
            {"RegistryID": "456", "FacilityName": "Test 2"}
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name

        try:
            fetch_epa_echo.write_json(facilities, temp_path)

            # Verify file was created and contains valid JSON
            with open(temp_path, 'r') as f:
                loaded = json.load(f)

            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["RegistryID"], "123")

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_print_summary(self):
        """Test summary printing functionality."""
        response = {
            "Results": {
                "QueryID": "TEST123",
                "QueryRows": "42",
                "Facilities": [{"test": "data"}] * 10
            }
        }

        # Capture stdout
        captured = StringIO()
        with patch('sys.stdout', captured):
            fetch_epa_echo.print_summary(response)

        output = captured.getvalue()
        self.assertIn("TEST123", output)
        self.assertIn("42", output)
        self.assertIn("10", output)


if __name__ == "__main__":
    unittest.main()
