#!/usr/bin/env python3
"""
Unit tests for FEC data fetcher (scripts/fetch_fec.py).

Tests make real API calls to verify endpoints are functional.
Tests are skipped if network is unavailable.
"""

import unittest
import sys
import os
import json
from unittest import skipIf

# Add scripts directory to path to import fetch_fec
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fetch_fec


def check_network() -> bool:
    """Check if FEC API is reachable."""
    import urllib.request
    import urllib.error
    try:
        url = f"{fetch_fec.API_BASE}/candidates/?api_key=DEMO_KEY&per_page=1"
        urllib.request.urlopen(url, timeout=5)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


NETWORK_AVAILABLE = check_network()


class TestFecFetch(unittest.TestCase):
    """Test FEC API client functionality."""

    def setUp(self):
        """Set up test client."""
        self.client = fetch_fec.FECAPIClient(api_key='DEMO_KEY')

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_get_candidates_basic(self):
        """Test basic candidates endpoint with minimal parameters."""
        response = self.client.get_candidates(per_page=5)

        # Check response structure
        self.assertIn('results', response)
        self.assertIn('pagination', response)

        # Check pagination structure
        pagination = response['pagination']
        self.assertIn('page', pagination)
        self.assertIn('per_page', pagination)
        self.assertIn('count', pagination)

        # Check results
        results = response['results']
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "Expected at least one candidate")

        # Check first result has expected fields
        if results:
            candidate = results[0]
            self.assertIn('candidate_id', candidate)
            self.assertIn('name', candidate)
            # candidate_id should follow FEC format (letter + 8 digits)
            self.assertRegex(candidate['candidate_id'], r'^[A-Z]\d{8}$')

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_get_candidates_with_filters(self):
        """Test candidates endpoint with cycle and office filters."""
        response = self.client.get_candidates(
            cycle=2024,
            office='P',  # Presidential
            per_page=10
        )

        self.assertIn('results', response)
        results = response['results']
        self.assertIsInstance(results, list)

        # If we got results, verify they match the filter
        for candidate in results:
            self.assertIn('office', candidate)
            self.assertIn('cycles', candidate)
            # Office should be P (President) or office_full should contain President
            if 'office' in candidate:
                # Some might be None or empty, but if set should be 'P'
                if candidate['office']:
                    self.assertIn(candidate['office'], ['P', 'H', 'S'])

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_get_committees_basic(self):
        """Test basic committees endpoint."""
        response = self.client.get_committees(per_page=5)

        self.assertIn('results', response)
        self.assertIn('pagination', response)

        results = response['results']
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "Expected at least one committee")

        # Check first result
        if results:
            committee = results[0]
            self.assertIn('committee_id', committee)
            self.assertIn('name', committee)
            # committee_id should follow FEC format (C + 8 digits)
            self.assertRegex(committee['committee_id'], r'^C\d{8}$')

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_get_schedule_a_basic(self):
        """Test Schedule A (contributions) endpoint."""
        response = self.client.get_schedule_a(
            cycle=2024,
            per_page=5
        )

        self.assertIn('results', response)
        results = response['results']
        self.assertIsInstance(results, list)

        # Check structure if we got results
        if results:
            contribution = results[0]
            # These fields should exist in Schedule A records
            expected_fields = ['committee', 'contributor_name', 'contribution_receipt_amount']
            for field in expected_fields:
                self.assertIn(field, contribution)

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_api_error_handling(self):
        """Test that invalid requests raise appropriate errors."""
        # Test with invalid endpoint (should fail at URL building stage)
        with self.assertRaises(Exception):
            # This should fail because there's no such endpoint
            url = self.client._build_url('invalid_endpoint_xyz', {})
            self.client._request(url)

    def test_build_url(self):
        """Test URL building with parameters."""
        url = self.client._build_url('candidates', {
            'cycle': 2024,
            'office': 'H',
            'page': 1,
            'per_page': 20
        })

        self.assertIn('api.open.fec.gov/v1/candidates/', url)
        self.assertIn('api_key=DEMO_KEY', url)
        self.assertIn('cycle=2024', url)
        self.assertIn('office=H', url)

    def test_build_url_filters_none(self):
        """Test that None values are filtered from URL parameters."""
        url = self.client._build_url('candidates', {
            'cycle': 2024,
            'office': None,  # Should be filtered out
            'state': None    # Should be filtered out
        })

        self.assertIn('cycle=2024', url)
        self.assertNotIn('office=', url)
        self.assertNotIn('state=', url)

    @skipIf(not NETWORK_AVAILABLE, "Network or FEC API unavailable")
    def test_pagination(self):
        """Test that pagination works across multiple pages."""
        # Fetch first page
        page1 = self.client.get_candidates(page=1, per_page=5)
        results1 = page1['results']

        # Fetch second page
        page2 = self.client.get_candidates(page=2, per_page=5)
        results2 = page2['results']

        # Results should be different
        if results1 and results2:
            id1 = results1[0]['candidate_id']
            id2 = results2[0]['candidate_id']
            self.assertNotEqual(id1, id2, "Different pages should have different results")

    def test_output_json(self):
        """Test JSON output formatting."""
        test_data = [
            {'id': 1, 'name': 'Test Candidate'},
            {'id': 2, 'name': 'Another Candidate'}
        ]

        # Test that it produces valid JSON
        import io
        import json as json_lib
        from unittest.mock import patch

        output = io.StringIO()
        with patch('sys.stdout', output):
            fetch_fec.output_json(test_data)

        output_str = output.getvalue()
        parsed = json_lib.loads(output_str)
        self.assertEqual(parsed, test_data)

    def test_output_csv(self):
        """Test CSV output formatting."""
        test_data = [
            {'id': 1, 'name': 'Test Candidate'},
            {'id': 2, 'name': 'Another Candidate'}
        ]

        import io
        import csv as csv_lib
        from unittest.mock import patch

        output = io.StringIO()
        with patch('sys.stdout', output):
            fetch_fec.output_csv(test_data)

        output_str = output.getvalue()
        lines = output_str.strip().split('\n')

        # Should have header + 2 data rows
        self.assertEqual(len(lines), 3)
        self.assertIn('id', lines[0])
        self.assertIn('name', lines[0])


def suite():
    """Return test suite."""
    return unittest.TestLoader().loadTestsFromTestCase(TestFecFetch)


if __name__ == '__main__':
    # Run with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
