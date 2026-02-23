"""File ingestion agent tool.

Plain async function (NOT decorated with @tool) that ingests a data file
into an investigation. The SDK adapter will wrap it with the decorator
in section 8.

Takes dataset_repo as a parameter for dependency injection.
"""

from __future__ import annotations

import json
from pathlib import Path

from redthread.db.repositories import DatasetRepo
from redthread.ingestion.parsers import ParseResult, parse_file

# Mapping from file extensions to file_type strings
_EXTENSION_MAP = {
    ".csv": "csv",
    ".json": "json",
    ".xlsx": "xlsx",
}


def _detect_file_type(file_path: str) -> str | None:
    """Detect file type from the file extension.

    Returns the file_type string (csv/json/xlsx) or None if unsupported.
    """
    suffix = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(suffix)


async def ingest_file(
    dataset_repo: DatasetRepo,
    file_path: str,
    investigation_id: str,
    description: str = "",
) -> str:
    """Ingest a local data file (CSV, JSON, XLSX) into the investigation.

    Parses the file, stores records in the database, and returns a JSON
    summary including column names, row count, and any validation warnings.

    Parameters
    ----------
    dataset_repo : DatasetRepo
        Injected repository for dataset + record persistence.
    file_path : str
        Path to the file on disk.
    investigation_id : str
        ID of the investigation to associate with.
    description : str
        Optional description of the file contents.

    Returns
    -------
    str
        JSON string with ingestion summary or error details.
    """
    path = Path(file_path).resolve()

    # Detect file type from extension
    file_type = _detect_file_type(file_path)
    if file_type is None:
        return json.dumps({
            "status": "error",
            "message": (
                f"Unsupported file type: '{path.suffix}'. "
                f"Supported extensions: .csv, .json, .xlsx"
            ),
        })

    # Parse the file
    try:
        result: ParseResult = parse_file(path, file_type)
    except FileNotFoundError:
        return json.dumps({
            "status": "error",
            "message": f"File not found: {file_path}",
        })
    except ValueError as exc:
        return json.dumps({
            "status": "error",
            "message": str(exc),
        })

    # Create Dataset record in the database
    dataset = dataset_repo.create(
        investigation_id=investigation_id,
        filename=path.name,
        file_type=file_type,
        row_count=result.row_count,
        column_names=result.column_names,
        validation_warnings=result.warnings if result.warnings else None,
    )

    # Store all parsed rows as Record entries (batch insert)
    if result.rows:
        dataset_repo.store_records(dataset["id"], result.rows)

    # Return structured summary
    summary = {
        "status": "success",
        "dataset_id": dataset["id"],
        "filename": path.name,
        "file_type": file_type,
        "row_count": result.row_count,
        "column_names": result.column_names,
        "warnings": result.warnings,
    }

    if description:
        summary["description"] = description

    return json.dumps(summary, indent=2, ensure_ascii=True)
