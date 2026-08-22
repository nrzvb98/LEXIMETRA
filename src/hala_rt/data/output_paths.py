from pathlib import Path


OUTPUT_SUFFIX = "_output"
EDITED_SUFFIX = "_edited"
BACKUP_SUFFIX = "_backup"
SIDECAR_SUFFIX = "_output"
CSV_SUFFIX = ".csv"

# Name used through 0.2.x; recordings verified with those releases have their
# CSV under this suffix, and that work must keep loading.
LEGACY_OUTPUT_SUFFIX = "_hala_output"


def default_output_path(audio_file_path, output_dir=None):
    """Return the default CSV path for an audio file.

    By default, output stays next to the selected audio file so verified CSVs
    can travel with their source recording. ``output_dir`` exists for future
    workflows that want a central output folder.
    """
    audio_path = Path(audio_file_path)
    parent = Path(output_dir) if output_dir is not None else audio_path.parent
    return parent / f"{audio_path.stem}{OUTPUT_SUFFIX}{CSV_SUFFIX}"


def resolve_output_path(audio_file_path):
    """Return the CSV path the app should use for an audio file.

    Prefers the current naming, but a recording whose CSV was written by a
    0.2.x release only has a ``_hala_output.csv`` — that file may hold
    hand-verified trials, so it wins over creating a fresh one under the new
    name. Sticking with the legacy name for that recording (saves, backups,
    edited copies included) keeps one recording's files under one name.
    """
    audio_path = Path(audio_file_path)
    preferred = default_output_path(audio_path)
    if preferred.exists():
        return preferred
    legacy = audio_path.parent / f"{audio_path.stem}{LEGACY_OUTPUT_SUFFIX}{CSV_SUFFIX}"
    if legacy.exists():
        return legacy
    return preferred


def processing_sidecar_dir(audio_file_path):
    """Return the folder holding the pipeline's own artifacts for a recording.

    The pipeline writes per-trial slices and two analysis CSVs alongside the
    output CSV the app reads. Those belong together in one folder rather than
    loose in the user's recordings directory, where a session can add ~50 WAVs.
    """
    audio_path = Path(audio_file_path)
    return audio_path.parent / f"{audio_path.stem}{SIDECAR_SUFFIX}"


def _next_available_path(base_output_path, marker):
    base_path = Path(base_output_path)
    suffix = base_path.suffix or CSV_SUFFIX
    candidate = base_path.with_name(f"{base_path.stem}{marker}{suffix}")
    counter = 2

    while candidate.exists():
        candidate = base_path.with_name(f"{base_path.stem}{marker}_{counter}{suffix}")
        counter += 1

    return candidate


def next_edited_output_path(base_output_path):
    """Return the first available edited-copy path for a CSV."""
    return _next_available_path(base_output_path, EDITED_SUFFIX)


def next_backup_output_path(base_output_path):
    """Return the first available backup path for a CSV about to be replaced.

    Deliberately distinct from the edited-copy naming: ``_edited`` means a copy
    the user chose to save, while ``_backup`` is one the app set aside on their
    behalf before re-processing overwrote it. Conflating the two would make it
    guesswork which file holds hand-verified work.
    """
    return _next_available_path(base_output_path, BACKUP_SUFFIX)

