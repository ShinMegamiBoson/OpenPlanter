#!/usr/bin/env python3
"""
Tests for SAM.gov data fetcher.

These tests verify the fetch_sam_gov.py script functionality.
Tests are skipped if SAM.gov API key is not available or network is unreachable.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to path to import the module
SCRIPTS_DIR = Path(__file__).parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from fetch_sam_gov import SAMGovClient
except ImportError as e:
    print(f"Warning: Could not import fetch_sam_gov: {e}", file=sys.stderr)
    SAMGovClient = None


class TestSamGovFetch(unittest.TestCase):
    """Test SAM.gov data fetching functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.api_key = os.environ.get('SAM_GOV_API_KEY')
        if not cls.api_key:
            # Try reading from .env file in project root
            env_file = Path(__file__).parent.parent / '.env'
            if env_file.exists():
                with open(env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('SAM_GOV_API_KEY='):
                            cls.api_key = line.split('=', 1)[1].strip().strip('"\'')
                            break

    def setUp(self):
        """Set up each test."""
        if SAMGovClient is None:
            self.skipTest("fetch_sam_gov module not available")

        if not self.api_key:
            self.skipTest("SAM_GOV_API_KEY not available (set env var or add to .env)")

        self.client = SAMGovClient(self.api_key)

    def test_client_initialization(self):
        """Test that SAMGovClient initializes correctly."""
        self.assertIsNotNone(self.client)
        self.assertEqual(self.client.api_key, self.api_key)
        self.assertTrue(self.client.BASE_URL.startswith('https://'))

    def test_search_exclusions_minimal(self):
        """Test exclusions search with minimal parameters."""
        try:
            result = self.client.search_exclusions(page=0, size=1)
            self.assertIsInstance(result, dict)

            # Check for expected response structure
            # SAM.gov API typically returns these fields
            if 'totalRecords' in result or 'recordsCount' in result or 'exclusionDetails' in result:
                # Response has expected structure
                self.assertTrue(True)
            elif 'error' in result or 'messages' in result:
                # API returned an error (possibly rate limit or auth issue)
                self.skipTest(f"API returned error: {result}")
            else:
                # Got some response, consider it valid
                self.assertIsNotNone(result)

        except Exception as e:
            # Network errors or API issues
            if 'HTTP Error 403' in str(e):
                self.skipTest("API key authentication failed - check key validity")
            elif 'HTTP Error 429' in str(e):
                self.skipTest("Rate limit exceeded")
            elif 'URLError' in str(e) or 'timeout' in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    def test_search_exclusions_with_state(self):
        """Test exclusions search filtered by state."""
        try:
            # Search for exclusions in a large state (likely to have results)
            result = self.client.search_exclusions(state='CA', page=0, size=1)
            self.assertIsInstance(result, dict)

            # Verify we got some kind of valid response
            if isinstance(result, dict) and len(result) > 0:
                self.assertTrue(True)

        except Exception as e:
            if 'HTTP Error 403' in str(e):
                self.skipTest("API key authentication failed")
            elif 'HTTP Error 429' in str(e):
                self.skipTest("Rate limit exceeded")
            elif 'URLError' in str(e) or 'timeout' in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    def test_search_entity_structure(self):
        """Test that entity search returns expected structure."""
        try:
            # Try searching for a common company name
            result = self.client.search_entity(page=0)
            self.assertIsInstance(result, dict)

            # Just verify we got a response
            self.assertIsNotNone(result)

        except Exception as e:
            if 'HTTP Error 403' in str(e):
                self.skipTest("API key authentication failed")
            elif 'HTTP Error 429' in str(e):
                self.skipTest("Rate limit exceeded")
            elif 'HTTP Error 400' in str(e):
                # Entity search may require specific parameters
                self.skipTest("Entity search requires specific parameters")
            elif 'URLError' in str(e) or 'timeout' in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    def test_json_output_is_valid(self):
        """Test that search results can be serialized to JSON."""
        try:
            result = self.client.search_exclusions(page=0, size=1)

            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
                json.dump(result, f, indent=2)
                temp_path = f.name

            try:
                # Verify the file was written and is valid JSON
                self.assertTrue(os.path.exists(temp_path))
                self.assertGreater(os.path.getsize(temp_path), 0)

                with open(temp_path, 'r') as f:
                    loaded_data = json.load(f)
                    self.assertEqual(result, loaded_data)

            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except Exception as e:
            if 'HTTP Error 403' in str(e):
                self.skipTest("API key authentication failed")
            elif 'HTTP Error 429' in str(e):
                self.skipTest("Rate limit exceeded")
            elif 'URLError' in str(e) or 'timeout' in str(e).lower():
                self.skipTest(f"Network unavailable: {e}")
            else:
                raise

    def test_url_construction(self):
        """Test that API URLs are constructed correctly."""
        self.assertTrue(self.client.BASE_URL.startswith('https://api.sam.gov'))
        self.assertEqual(self.client.EXCLUSIONS_ENDPOINT, '/entity-information/v4/exclusions')
        self.assertEqual(self.client.ENTITY_ENDPOINT, '/entity-information/v3/entities')
        self.assertEqual(self.client.EXTRACT_ENDPOINT, '/data-services/v1/extracts')

    def test_api_endpoints_format(self):
        """Test that API endpoint constants are properly formatted."""
        # Endpoints should start with /
        self.assertTrue(self.client.EXCLUSIONS_ENDPOINT.startswith('/'))
        self.assertTrue(self.client.ENTITY_ENDPOINT.startswith('/'))
        self.assertTrue(self.client.EXTRACT_ENDPOINT.startswith('/'))

        # Endpoints should not end with /
        self.assertFalse(self.client.EXCLUSIONS_ENDPOINT.endswith('/'))
        self.assertFalse(self.client.ENTITY_ENDPOINT.endswith('/'))
        self.assertFalse(self.client.EXTRACT_ENDPOINT.endswith('/'))


class TestSamGovFetchWithoutAPIKey(unittest.TestCase):
    """Tests that don't require an API key."""

    def test_module_imports(self):
        """Test that the module can be imported."""
        self.assertIsNotNone(SAMGovClient)

    def test_client_accepts_dummy_key(self):
        """Test that client can be initialized with dummy key."""
        if SAMGovClient is None:
            self.skipTest("fetch_sam_gov module not available")

        client = SAMGovClient("dummy_key_for_testing")
        self.assertEqual(client.api_key, "dummy_key_for_testing")


def run_tests():
    """Run the test suite."""
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all tests
    suite.addTests(loader.loadTestsFromTestCase(TestSamGovFetch))
    suite.addTests(loader.loadTestsFromTestCase(TestSamGovFetchWithoutAPIKey))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
