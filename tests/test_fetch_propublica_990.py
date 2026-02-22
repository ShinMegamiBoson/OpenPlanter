"""
Tests for the ProPublica 990 acquisition script.

These tests make real API calls to verify the script works correctly.
Tests are skipped if network is unavailable.
"""

import json
import sys
import unittest
from pathlib import Path

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

try:
    import fetch_propublica_990
except ImportError:
    fetch_propublica_990 = None


class TestPropublica990Fetch(unittest.TestCase):
    """Test ProPublica Nonprofit Explorer API fetching."""

    @classmethod
    def setUpClass(cls):
        """Check if API is reachable before running tests."""
        if fetch_propublica_990 is None:
            raise unittest.SkipTest("fetch_propublica_990 module not available")

        import urllib.request
        import urllib.error

        try:
            # Quick connectivity check
            req = urllib.request.Request(
                f"{fetch_propublica_990.API_BASE}/search.json?q=test",
                headers={"User-Agent": "OpenPlanter-Test/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except (urllib.error.URLError, OSError):
            raise unittest.SkipTest("ProPublica API not reachable")

    def test_search_by_keyword(self):
        """Test organization search by keyword."""
        results = fetch_propublica_990.search_organizations(query="Red Cross")

        self.assertIn("organizations", results)
        self.assertIn("total_results", results)
        self.assertIsInstance(results["organizations"], list)
        self.assertGreater(results["total_results"], 0)

        # Verify first result has expected fields
        if results["organizations"]:
            org = results["organizations"][0]
            self.assertIn("ein", org)
            self.assertIn("name", org)
            self.assertIn("state", org)

    def test_search_by_state(self):
        """Test organization search by state filter."""
        results = fetch_propublica_990.search_organizations(state="MA")

        self.assertIn("organizations", results)
        self.assertGreater(results["total_results"], 0)

        # Verify results are from Massachusetts
        for org in results["organizations"][:5]:
            self.assertEqual(org.get("state"), "MA")

    def test_search_by_ntee_code(self):
        """Test organization search by NTEE code."""
        # NTEE code 3 = Human Services
        results = fetch_propublica_990.search_organizations(ntee="3")

        self.assertIn("organizations", results)
        self.assertGreater(results["total_results"], 0)

    def test_search_by_subsection_code(self):
        """Test organization search by IRS subsection code."""
        # c_code 3 = 501(c)(3) public charities
        results = fetch_propublica_990.search_organizations(c_code="3")

        self.assertIn("organizations", results)
        self.assertGreater(results["total_results"], 0)

    def test_search_pagination(self):
        """Test search pagination works correctly."""
        page0 = fetch_propublica_990.search_organizations(query="foundation", page=0)
        page1 = fetch_propublica_990.search_organizations(query="foundation", page=1)

        # Verify both pages return results
        self.assertIn("organizations", page0)
        self.assertIn("organizations", page1)
        self.assertGreater(len(page0["organizations"]), 0)
        self.assertGreater(len(page1["organizations"]), 0)

        # Verify different results on different pages
        ein0 = page0["organizations"][0]["ein"]
        ein1 = page1["organizations"][0]["ein"]
        self.assertNotEqual(ein0, ein1)

    def test_get_organization_by_ein(self):
        """Test fetching a single organization by EIN."""
        # Harvard University EIN: 04-2103580 (known to have filings)
        ein = "042103580"
        result = fetch_propublica_990.get_organization(ein)

        self.assertIn("organization", result)
        org = result["organization"]

        self.assertEqual(org["ein"], 42103580)
        self.assertIn("name", org)

        # Check for filings_with_data array
        self.assertIn("filings_with_data", result)
        self.assertIsInstance(result["filings_with_data"], list)

        # Verify filing structure if filings exist
        if result["filings_with_data"]:
            filing = result["filings_with_data"][0]
            self.assertIn("tax_prd", filing)
            self.assertIn("formtype", filing)
            self.assertIn("pdf_url", filing)

    def test_get_organization_ein_formats(self):
        """Test EIN parsing with different formats."""
        # Test with hyphen
        result1 = fetch_propublica_990.get_organization("53-0196605")
        # Test without hyphen
        result2 = fetch_propublica_990.get_organization("530196605")

        org1 = result1["organization"]
        org2 = result2["organization"]

        self.assertEqual(org1["ein"], org2["ein"])
        self.assertEqual(org1["name"], org2["name"])

    def test_invalid_ein_raises_error(self):
        """Test that invalid EIN format raises ValueError."""
        with self.assertRaises(ValueError):
            fetch_propublica_990.get_organization("12345")  # Too short

        with self.assertRaises(ValueError):
            fetch_propublica_990.get_organization("abcdefghi")  # Non-numeric

    def test_organization_not_found(self):
        """Test handling of non-existent EIN returns stub organization."""
        # ProPublica API returns a stub "Unknown Organization" instead of 404
        result = fetch_propublica_990.get_organization("999999999")

        self.assertIn("organization", result)
        org = result["organization"]
        self.assertEqual(org["ein"], 999999999)
        # Unknown orgs have "Unknown Organization" as name
        self.assertIn("Unknown", org.get("name", ""))

    def test_search_combined_filters(self):
        """Test search with multiple filters combined."""
        results = fetch_propublica_990.search_organizations(
            query="hospital",
            state="MA",
            c_code="3",
        )

        self.assertIn("organizations", results)
        # Should return results or empty list, not error
        self.assertIsInstance(results["organizations"], list)

    def test_fetch_json_returns_dict(self):
        """Test that fetch_json helper returns parsed dict."""
        url = f"{fetch_propublica_990.API_BASE}/search.json?q=test"
        result = fetch_propublica_990.fetch_json(url)

        self.assertIsInstance(result, dict)
        self.assertIn("organizations", result)

    def test_search_empty_query_allowed_with_filters(self):
        """Test that search works without query if other filters provided."""
        # Should work with just state filter
        results = fetch_propublica_990.search_organizations(state="RI")

        self.assertIn("organizations", results)
        self.assertIsInstance(results["organizations"], list)


if __name__ == "__main__":
    unittest.main()
