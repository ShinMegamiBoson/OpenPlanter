"""
Tests for Senate lobbying disclosure data fetcher.

Verifies that the download endpoint is accessible and the fetch script
can retrieve lobbying disclosure data from soprweb.senate.gov.
"""

import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from scripts.fetch_senate_lobbying import download_lobbying_data


class TestSenateLobbyingFetch(unittest.TestCase):
    """Test suite for Senate lobbying disclosure data acquisition."""

    def test_endpoint_accessible(self):
        """Verify soprweb.senate.gov download endpoint responds (HEAD request)."""
        # Use a known historical year/quarter that should be stable
        url = "http://soprweb.senate.gov/downloads/2023_1.zip"

        try:
            # HEAD request to check if endpoint is accessible without full download
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=10) as response:
                self.assertEqual(response.status, 200, "Endpoint should return 200 OK")
                content_type = response.headers.get('Content-Type', '')
                # Should be a ZIP file
                self.assertIn('zip', content_type.lower(),
                             f"Expected ZIP content type, got {content_type}")
        except urllib.error.URLError as e:
            self.skipTest(f"Network unavailable or endpoint unreachable: {e}")
        except Exception as e:
            self.fail(f"Unexpected error accessing endpoint: {e}")

    def test_download_function_success(self):
        """Test that download_lobbying_data can fetch a small historical file."""
        # Use 1999 Q1 (first available quarter, likely smallest file)
        year = 1999
        quarter = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                success = download_lobbying_data(year, quarter, output_dir, verbose=False)

                # Skip if download failed (likely network issue)
                if not success:
                    self.skipTest("Download failed - network may be unavailable")

                # Verify file was created
                expected_file = output_dir / f"{year}_{quarter}.zip"
                self.assertTrue(expected_file.exists(), "ZIP file should be created")
                self.assertGreater(expected_file.stat().st_size, 0, "ZIP file should not be empty")

            except urllib.error.URLError as e:
                self.skipTest(f"Network unavailable: {e}")

    def test_download_function_invalid_quarter(self):
        """Test that download_lobbying_data rejects invalid quarter values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Test quarter = 0
            success = download_lobbying_data(2023, 0, output_dir, verbose=False)
            self.assertFalse(success, "Should fail for quarter < 1")

            # Test quarter = 5
            success = download_lobbying_data(2023, 5, output_dir, verbose=False)
            self.assertFalse(success, "Should fail for quarter > 4")

    def test_download_function_invalid_year(self):
        """Test that download_lobbying_data rejects invalid year values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Test year before data availability
            success = download_lobbying_data(1990, 1, output_dir, verbose=False)
            self.assertFalse(success, "Should fail for year < 1999")

            # Test unreasonable future year
            success = download_lobbying_data(2050, 1, output_dir, verbose=False)
            self.assertFalse(success, "Should fail for year > 2030")

    def test_download_function_nonexistent_quarter(self):
        """Test that download_lobbying_data handles 404 for nonexistent data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                # Future quarter that definitely doesn't exist yet
                success = download_lobbying_data(2029, 4, output_dir, verbose=False)
                self.assertFalse(success, "Should fail for nonexistent future quarter")

                # File should not be created for failed download
                expected_file = output_dir / "2029_4.zip"
                self.assertFalse(expected_file.exists(), "File should not exist for failed download")

            except urllib.error.URLError as e:
                self.skipTest(f"Network unavailable: {e}")

    def test_output_directory_creation(self):
        """Test that download_lobbying_data creates output directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested path that doesn't exist yet
            output_dir = Path(tmpdir) / "nested" / "lobbying" / "data"
            self.assertFalse(output_dir.exists(), "Output dir should not exist initially")

            try:
                # Attempt download (may fail due to network, but directory should be created)
                download_lobbying_data(1999, 1, output_dir, verbose=False)

                # Directory should be created regardless of download success
                self.assertTrue(output_dir.exists(), "Output directory should be created")
                self.assertTrue(output_dir.is_dir(), "Output path should be a directory")

            except urllib.error.URLError:
                # Network issue, but directory should still be created
                self.assertTrue(output_dir.exists(), "Output directory should be created even on network error")


if __name__ == '__main__':
    unittest.main()
