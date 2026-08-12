import csv
import os
import tempfile
from pathlib import Path

from .trial_data import CSV_COLUMNS, trial_from_csv_row


DEFAULT_OUTPUT_MODE = 0o644


def load_output_csv(path):
    """Load trial rows from a HALA output CSV."""
    output_path = Path(path)
    with output_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        missing = [column for column in CSV_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"Missing CSV columns: {', '.join(missing)}")

        return [
            trial_from_csv_row(row, fallback_index=index)
            for index, row in enumerate(reader, start=1)
        ]


def write_output_csv(path, trials):
    """Write trial rows to a HALA output CSV, atomically.

    The rows are hand-verified research data, so a failed write must not cost
    the previous CSV. Write a sibling temporary file, flush it to disk, then
    ``os.replace`` it onto the target -- atomic within a filesystem, so readers
    see either the old file or the complete new one, never a truncated one.
    """
    output_path = Path(path)
    # Preserve the existing file's permissions; a fresh temp file is 0600.
    mode = (
        output_path.stat().st_mode & 0o777
        if output_path.exists()
        else DEFAULT_OUTPUT_MODE
    )

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with temp_file:
            writer = csv.DictWriter(temp_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for trial in trials:
                writer.writerow(trial.to_csv_row())
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(temp_file.name, mode)
        os.replace(temp_file.name, output_path)
    except BaseException:
        Path(temp_file.name).unlink(missing_ok=True)
        raise

