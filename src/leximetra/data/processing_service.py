"""Run the HALA pipeline on a recording and place its output for the app.

Sits between the controller and ``leximetra.processing``: the controller asks for
one recording to be processed and gets back a typed outcome, never an
exception. Automatic processing is a convenience — if it cannot run, the user
still has the manual trial-cutting workflow, so every failure here is a status
to report rather than an error to raise.

Import-light on purpose. The pipeline pulls in torch (~1.7 s), which sessions
that only verify an existing CSV should never pay, so it is imported lazily
inside :func:`run_processing`. Nothing at module scope imports it, and neither
does this module import Qt — threading lives in ``leximetra.ui``.

Artifact layout for ``/sessions/p001.m4a``::

    /sessions/p001_output.csv   the app's CSV (what the controller loads)
    /sessions/p001_output/      the pipeline's own artifacts
        Slices/Trial_NNN.wav
        p001_Full_Analysis_Results.csv
        p001_Analysis_Results.csv

The pipeline writes those three under upstream's ``HALA_`` names; this module
renames them after the run, so the layout above is what actually lands on disk.
"""

import importlib.util
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .output_paths import (
    CSV_SUFFIX,
    default_output_path,
    next_backup_output_path,
    processing_sidecar_dir,
)


REQUIRED_MODULES = ("torch", "torchaudio", "pandas", "scipy")

# The vendored pipeline names its export ``<stem>_hala_output.csv``; that name
# is upstream's, not this app's, and changes only via tools/sync_processing.py.
PIPELINE_EXPORT_SUFFIX = "_hala_output"

# The pipeline's remaining artifacts carry upstream's HALA_ prefix too. Dropping
# it at the source would mean editing Hala_Processing and re-vendoring, which
# would move the pipeline off the exact commit this app was measured against, so
# the app renames them in the sidecar once the run is over instead. Nothing reads
# these back -- they exist for the user to open.
PIPELINE_SLICE_DIR = "HALA_Slices"
SLICE_DIR = "Slices"
PIPELINE_RESULT_RENAMES = {
    "_HALA_Full_Analysis_Results": "_Full_Analysis_Results",
    "_HALA_Analysis_Results": "_Analysis_Results",
}


class ProcessingStatus(Enum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    NO_BEEPS = "no_beeps"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class ProcessingOutcome:
    """What happened, in terms the controller can act on and report."""

    status: ProcessingStatus
    message: str
    csv_path: Optional[Path] = None
    sidecar_dir: Optional[Path] = None
    backup_path: Optional[Path] = None
    trial_count: int = 0
    # Beeps too quiet for the detector's trigger, recovered by template match.
    # Worth reporting because they are trials the user would otherwise never
    # see: the pipeline's own explanation goes to a sidecar CSV nobody opens.
    rescued_beep_count: int = 0

    @property
    def succeeded(self):
        return self.status is ProcessingStatus.SUCCESS


class _Cancelled(Exception):
    """Raised out of the progress callback to unwind the pipeline."""


def processing_available():
    """Whether the optional ``processing`` extra is installed.

    Checks for the modules without importing them: this runs during the startup
    dependency report, and importing torch there would add seconds to launch for
    every user, including those who never process anything.
    """
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def _load_process_audio():
    """Import the pipeline entry point. Seam for tests, which fake it."""
    from leximetra.processing import process_audio

    return process_audio


def _describe_failure(error):
    """Map a pipeline exception onto a status and a message worth showing.

    The pipeline signals "this recording has nothing to work with" with a plain
    ``RuntimeError``, which is worth separating from a genuine fault: it is the
    expected outcome for a recording with no beeps, and the user's next step is
    to cut trials by hand rather than to report a bug.
    """
    text = str(error)
    if isinstance(error, RuntimeError) and "no beeps detected" in text.lower():
        return ProcessingStatus.NO_BEEPS, "No beeps were detected in this recording."
    if isinstance(error, FileNotFoundError):
        return ProcessingStatus.ERROR, f"Audio file could not be read: {text}"
    return ProcessingStatus.ERROR, text or error.__class__.__name__


def _drop_hala_prefix(sidecar, stem):
    """Rename the pipeline's HALA_-prefixed artifacts inside the sidecar.

    Best-effort on purpose. These are files the user opens, never files the app
    reads back, so a rename that fails should cost a cosmetic name rather than a
    finished analysis -- upstream's names simply stay in that case.
    """
    try:
        produced_slices = sidecar / PIPELINE_SLICE_DIR
        if produced_slices.is_dir():
            # The pipeline clears a stale HALA_Slices before each run, but it
            # knows nothing about the renamed one, so an earlier run's Slices/
            # is still sitting here -- and replace() will not overwrite a
            # directory that has anything in it.
            shutil.rmtree(sidecar / SLICE_DIR, ignore_errors=True)
            produced_slices.replace(sidecar / SLICE_DIR)

        for produced_suffix, renamed_suffix in PIPELINE_RESULT_RENAMES.items():
            produced = sidecar / f"{stem}{produced_suffix}{CSV_SUFFIX}"
            if produced.is_file():
                produced.replace(sidecar / f"{stem}{renamed_suffix}{CSV_SUFFIX}")
    except OSError:
        # Same filesystem, in a directory this run just wrote, so this is close
        # to impossible -- but not worth losing the run over.
        pass


def run_processing(
    audio_path,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    output_csv_path=None,
):
    """Process one recording; return a :class:`ProcessingOutcome`, never raise.

    ``on_progress(stage, done, total)`` is forwarded from the pipeline.
    ``should_cancel()`` is polled on each of those callbacks — the pipeline has
    no cancel token, so cancellation can only take effect where it reports
    progress. It is called per trial during VAD, but beep detection runs as one
    uninterruptible block, so a cancel there applies once slicing finishes.

    An existing output CSV is renamed to a ``_backup`` sibling rather than
    overwritten; it may hold hand-verified work. That happens only after
    processing has succeeded, so a failed run leaves the previous CSV in place.
    """
    audio_path = Path(audio_path)
    target_csv = Path(output_csv_path) if output_csv_path else default_output_path(audio_path)
    sidecar = processing_sidecar_dir(audio_path)

    if not processing_available():
        return ProcessingOutcome(
            status=ProcessingStatus.UNAVAILABLE,
            message=(
                "Automatic processing is not installed "
                '(pip install -e ".[processing]").'
            ),
        )

    try:
        process_audio = _load_process_audio()
    except Exception as error:  # noqa: BLE001 - see below
        # Deliberately broader than ImportError. A damaged or incompletely
        # packaged torch fails at import with its own exception types (a build
        # that pruned torch/bin raised RuntimeError from torch/__init__.py),
        # and none of those should reach the caller as an exception.
        return ProcessingOutcome(
            status=ProcessingStatus.UNAVAILABLE,
            message=f"Automatic analysis could not be loaded: {error}",
        )

    def progress(stage, done, total):
        if should_cancel is not None and should_cancel():
            raise _Cancelled
        if on_progress is not None:
            on_progress(stage, done, total)

    # Only clean up a sidecar this run created; an existing one may hold
    # artifacts from an earlier successful run.
    sidecar_existed = sidecar.exists()

    try:
        result = process_audio(audio_path, output_dir=sidecar, on_progress=progress)
    except _Cancelled:
        if not sidecar_existed:
            shutil.rmtree(sidecar, ignore_errors=True)
        return ProcessingOutcome(
            status=ProcessingStatus.CANCELLED,
            message="Processing cancelled.",
        )
    except Exception as error:  # noqa: BLE001 - every failure is a reportable status
        if not sidecar_existed:
            shutil.rmtree(sidecar, ignore_errors=True)
        status, message = _describe_failure(error)
        return ProcessingOutcome(status=status, message=message, sidecar_dir=sidecar)

    _drop_hala_prefix(sidecar, audio_path.stem)

    # The pipeline names its export after the recording, which is not
    # necessarily what the caller wants the CSV called.
    produced_csv = sidecar / f"{audio_path.stem}{PIPELINE_EXPORT_SUFFIX}{CSV_SUFFIX}"
    if not produced_csv.is_file():
        return ProcessingOutcome(
            status=ProcessingStatus.ERROR,
            message=f"The pipeline did not produce {produced_csv.name}.",
            sidecar_dir=sidecar,
        )

    backup_path = None
    if target_csv.exists():
        backup_path = next_backup_output_path(target_csv)
        target_csv.replace(backup_path)

    # Same filesystem (the sidecar is a subdirectory of the CSV's parent), so
    # this is an atomic rename. Moved rather than copied: two copies of the same
    # export, one of which the user can edit, invites reading the stale one.
    produced_csv.replace(target_csv)

    trial_count = len(result.df_output) if result.df_output is not None else 0

    # The pipeline reports several kinds of beep anomaly; only `rescued_beep`
    # means a trial exists that the detector alone would not have produced.
    rescued_beep_count = sum(
        1 for anomaly in result.beep_anomalies if anomaly.get("kind") == "rescued_beep"
    )
    message = f"Processed {trial_count} trial(s)."
    if rescued_beep_count:
        message += f" {rescued_beep_count} quiet beep(s) recovered."

    return ProcessingOutcome(
        status=ProcessingStatus.SUCCESS,
        message=message,
        csv_path=target_csv,
        sidecar_dir=sidecar,
        backup_path=backup_path,
        trial_count=trial_count,
        rescued_beep_count=rescued_beep_count,
    )
