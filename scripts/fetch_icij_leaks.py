#!/usr/bin/env python3
"""
ICIJ Offshore Leaks Database Bulk Download Script

Downloads the latest CSV export of the ICIJ Offshore Leaks Database
containing entities, officers, intermediaries, addresses, and relationships
from Panama Papers, Paradise Papers, Pandora Papers, and other leak investigations.

Usage:
    python fetch_icij_leaks.py --output data/icij_leaks/
    python fetch_icij_leaks.py --output /path/to/directory --no-extract
    python fetch_icij_leaks.py --help

Requirements:
    - Python 3.6+
    - Standard library only (urllib, zipfile, argparse)

License:
    Data is licensed under ODbL v1.0 (database) and CC BY-SA (contents).
    Attribution required: International Consortium of Investigative Journalists (ICIJ)
"""

import argparse
import os
import sys
import urllib.request
import urllib.error
import zipfile
from pathlib import Path


# ICIJ bulk download URL
DOWNLOAD_URL = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
DEFAULT_OUTPUT_DIR = "data/icij_leaks"
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for download progress


def download_file(url, output_path, show_progress=True):
    """
    Download a file from URL to output_path with optional progress display.

    Args:
        url: URL to download from
        output_path: Local file path to save to
        show_progress: Whether to display download progress

    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"Downloading from {url}...", file=sys.stderr)

        # Create parent directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Open URL and get file size
        with urllib.request.urlopen(url) as response:
            file_size = response.headers.get('Content-Length')
            if file_size:
                file_size = int(file_size)
                print(f"File size: {file_size / (1024*1024):.2f} MB", file=sys.stderr)

            # Download in chunks
            downloaded = 0
            with open(output_path, 'wb') as f:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if show_progress and file_size:
                        percent = (downloaded / file_size) * 100
                        print(f"\rProgress: {percent:.1f}% ({downloaded / (1024*1024):.2f} MB)",
                              end='', file=sys.stderr)

        if show_progress:
            print(file=sys.stderr)  # Newline after progress
        print(f"Download complete: {output_path}", file=sys.stderr)
        return True

    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return False


def extract_zip(zip_path, output_dir, show_progress=True):
    """
    Extract a ZIP file to output directory.

    Args:
        zip_path: Path to ZIP file
        output_dir: Directory to extract files to
        show_progress: Whether to display extraction progress

    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"Extracting {zip_path} to {output_dir}...", file=sys.stderr)
        output_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            members = zf.namelist()
            if show_progress:
                print(f"Found {len(members)} files in archive", file=sys.stderr)

            for i, member in enumerate(members, 1):
                zf.extract(member, output_dir)
                if show_progress:
                    print(f"\rExtracting: {i}/{len(members)} ({member})",
                          end='', file=sys.stderr)

        if show_progress:
            print(file=sys.stderr)  # Newline after progress
        print(f"Extraction complete: {output_dir}", file=sys.stderr)
        return True

    except zipfile.BadZipFile:
        print(f"Error: {zip_path} is not a valid ZIP file", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Download ICIJ Offshore Leaks Database CSV bulk export",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download and extract to default directory
  %(prog)s

  # Download to specific directory
  %(prog)s --output data/icij_leaks/

  # Download only, don't extract
  %(prog)s --no-extract

  # Keep ZIP file after extraction
  %(prog)s --keep-zip

Data License:
  Open Database License (ODbL) v1.0
  Attribution required: International Consortium of Investigative Journalists (ICIJ)

For more information: https://offshoreleaks.icij.org
        """
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f'Output directory (default: {DEFAULT_OUTPUT_DIR})'
    )

    parser.add_argument(
        '--url',
        type=str,
        default=DOWNLOAD_URL,
        help='Download URL (default: ICIJ bulk CSV export)'
    )

    parser.add_argument(
        '--no-extract',
        action='store_true',
        help='Download ZIP but do not extract'
    )

    parser.add_argument(
        '--keep-zip',
        action='store_true',
        help='Keep ZIP file after extraction'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output'
    )

    args = parser.parse_args()

    # Convert output path to Path object
    output_dir = Path(args.output).resolve()
    zip_filename = "full-oldb.LATEST.zip"
    zip_path = output_dir / zip_filename

    # Download the ZIP file
    print(f"ICIJ Offshore Leaks Database Bulk Download", file=sys.stderr)
    print(f"=" * 50, file=sys.stderr)

    success = download_file(args.url, zip_path, show_progress=not args.quiet)
    if not success:
        print("Download failed", file=sys.stderr)
        return 1

    # Extract if requested
    if not args.no_extract:
        success = extract_zip(zip_path, output_dir, show_progress=not args.quiet)
        if not success:
            print("Extraction failed", file=sys.stderr)
            return 1

        # Remove ZIP file unless --keep-zip specified
        if not args.keep_zip:
            try:
                zip_path.unlink()
                print(f"Removed ZIP file: {zip_path}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not remove ZIP file: {e}", file=sys.stderr)

    print(f"\nSuccess! Data available in: {output_dir}", file=sys.stderr)
    print(f"\nPlease cite: International Consortium of Investigative Journalists (ICIJ)",
          file=sys.stderr)
    print(f"License: ODbL v1.0 (database), CC BY-SA (contents)", file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
