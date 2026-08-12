from pathlib import Path


OUTPUT_SUFFIX = "_hala_output"
EDITED_SUFFIX = "_edited"
CSV_SUFFIX = ".csv"


def default_output_path(audio_file_path, output_dir=None):
    """Return the default CSV path for an audio file.

    By default, output stays next to the selected audio file so verified CSVs
    can travel with their source recording. ``output_dir`` exists for future
    workflows that want a central output folder.
    """
    audio_path = Path(audio_file_path)
    parent = Path(output_dir) if output_dir is not None else audio_path.parent
    return parent / f"{audio_path.stem}{OUTPUT_SUFFIX}{CSV_SUFFIX}"


def next_edited_output_path(base_output_path):
    """Return the first available edited-copy path for a CSV."""
    base_path = Path(base_output_path)
    suffix = base_path.suffix or CSV_SUFFIX
    candidate = base_path.with_name(f"{base_path.stem}{EDITED_SUFFIX}{suffix}")
    counter = 2

    while candidate.exists():
        candidate = base_path.with_name(
            f"{base_path.stem}{EDITED_SUFFIX}_{counter}{suffix}"
        )
        counter += 1

    return candidate

