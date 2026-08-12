import csv
from pathlib import Path

from .trial_data import CSV_COLUMNS, trial_from_csv_row


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
    """Write trial rows to a HALA output CSV."""
    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for trial in trials:
            writer.writerow(trial.to_csv_row())

