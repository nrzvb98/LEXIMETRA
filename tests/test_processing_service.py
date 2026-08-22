"""Service-layer behavior, with the pipeline faked.

The real pipeline is covered by ``test_processing_regression.py``. What matters
here is everything around it: where artifacts land, that an existing CSV is
never destroyed, and that failures come back as statuses rather than
exceptions. Faking the pipeline keeps these tests fast and runnable without the
``processing`` extra installed.
"""

import csv

import pytest

from leximetra.data import processing_service
from leximetra.data.processing_service import (
    ProcessingStatus,
    processing_available,
    run_processing,
)
from leximetra.data.trial_data import CSV_COLUMNS


def write_output_csv(path, trial_count):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for index in range(1, trial_count + 1):
            writer.writerow(
                {
                    "trial_index": index,
                    "trial_start_global": f"{index - 1}.0000",
                    "trial_end_global": f"{index}.0000",
                    "beep_timestamp_global": f"{index - 1}.5000",
                    "rt_first_speech_ms": "500.0",
                    "rt_main_response_ms": "500.0",
                    "prefiller_present": "false",
                    "flag_anticipatory": "false",
                    "flag_timeout": "false",
                    "segments_count": "1",
                }
            )


class FakeResult:
    def __init__(self, trial_count, beep_anomalies=None):
        self.df_output = list(range(trial_count))
        # Mirrors LeximetraResult, which defaults this to an empty list.
        self.beep_anomalies = beep_anomalies or []


def fake_pipeline(
    trial_count=3,
    stages=(("load", 1, 1), ("vad", 1, 1)),
    raises=None,
    beep_anomalies=None,
):
    """Build a stand-in for ``process_audio`` with the same call signature."""

    def process_audio(audio_path, output_dir=None, on_progress=None, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        for stage in stages:
            if on_progress is not None:
                on_progress(*stage)
        if raises is not None:
            raise raises
        slices = output_dir / "HALA_Slices"
        slices.mkdir(exist_ok=True)
        (slices / "Trial_001.wav").write_bytes(b"fake audio")
        (output_dir / f"{audio_path.stem}_HALA_Analysis_Results.csv").write_text("analysis")
        write_output_csv(output_dir / f"{audio_path.stem}_hala_output.csv", trial_count)
        return FakeResult(trial_count, beep_anomalies)

    return process_audio


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "session.m4a"
    path.write_bytes(b"not really audio")
    return path


@pytest.fixture
def pipeline(monkeypatch):
    """Install a fake pipeline and report it as available."""

    def install(process_audio):
        monkeypatch.setattr(processing_service, "_load_process_audio", lambda: process_audio)
        monkeypatch.setattr(processing_service, "processing_available", lambda: True)

    return install


def test_availability_probe_does_not_import_torch(monkeypatch):
    """The startup report calls this; importing torch there would cost seconds."""
    import sys

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    processing_available()

    assert "torch" not in sys.modules


def test_missing_dependency_reports_unavailable(monkeypatch):
    monkeypatch.setattr(processing_service, "processing_available", lambda: False)

    outcome = run_processing("/sessions/p001.m4a")

    assert outcome.status is ProcessingStatus.UNAVAILABLE
    assert not outcome.succeeded
    assert "processing" in outcome.message


@pytest.mark.parametrize(
    "error",
    [
        ImportError("No module named 'torch'"),
        # A packaged build that pruned torch/bin raised exactly this.
        RuntimeError("Unable to find torch_shm_manager at .../torch/bin/..."),
        OSError("dlopen failed: libtorch_cpu.dylib"),
    ],
)
def test_a_broken_install_is_reported_not_raised(audio, monkeypatch, error):
    """Any import failure degrades to manual mode, whatever its type."""
    def explode():
        raise error

    monkeypatch.setattr(processing_service, "processing_available", lambda: True)
    monkeypatch.setattr(processing_service, "_load_process_audio", explode)

    outcome = run_processing(audio)

    assert outcome.status is ProcessingStatus.UNAVAILABLE
    assert str(error) in outcome.message


def test_success_puts_the_csv_beside_the_audio(audio, pipeline):
    pipeline(fake_pipeline(trial_count=4))

    outcome = run_processing(audio)

    assert outcome.succeeded
    assert outcome.trial_count == 4
    assert outcome.csv_path == audio.parent / "session_output.csv"
    assert outcome.csv_path.is_file()


def test_recovered_beeps_are_counted_and_reported(audio, pipeline):
    """A quiet recording gains trials the detector never saw; say so.

    Without this the only trace is a sidecar CSV the user has no reason to
    open, so extra trials would appear with no explanation at all.
    """
    pipeline(fake_pipeline(trial_count=4, beep_anomalies=[
        {"kind": "rescued_beep", "trial_name": "Trial_002", "tone_match": 0.97},
        {"kind": "rescued_beep", "trial_name": "Trial_007", "tone_match": 0.91},
    ]))

    outcome = run_processing(audio)

    assert outcome.succeeded
    assert outcome.rescued_beep_count == 2
    assert "2 quiet beep(s) recovered" in outcome.message


def test_only_rescued_beeps_count_as_recovered(audio, pipeline):
    """The other anomaly kinds are pairing bookkeeping, not recovered trials."""
    pipeline(fake_pipeline(trial_count=3, beep_anomalies=[
        {"kind": "filled_from_template", "trial_name": "Trial_001"},
        {"kind": "dropped_legacy_beep", "trial_name": "Trial_003"},
    ]))

    outcome = run_processing(audio)

    assert outcome.rescued_beep_count == 0
    assert "recovered" not in outcome.message


def test_a_clean_recording_says_nothing_about_beeps(audio, pipeline):
    pipeline(fake_pipeline(trial_count=3))

    outcome = run_processing(audio)

    assert outcome.rescued_beep_count == 0
    assert outcome.message == "Processed 3 trial(s)."


def test_pipeline_artifacts_stay_in_the_sidecar(audio, pipeline):
    pipeline(fake_pipeline())

    outcome = run_processing(audio)

    sidecar = audio.parent / "session_output"
    assert outcome.sidecar_dir == sidecar
    assert (sidecar / "Slices" / "Trial_001.wav").is_file()
    assert (sidecar / "session_Analysis_Results.csv").is_file()
    # Moved, not copied: one editable copy of the export, not two. The export
    # keeps the pipeline's own name until the move renames it.
    assert not (sidecar / "session_hala_output.csv").exists()
    assert sorted(p.name for p in audio.parent.iterdir()) == [
        "session.m4a",
        "session_output",
        "session_output.csv",
    ]


def test_upstream_artifact_names_do_not_survive(audio, pipeline):
    pipeline(fake_pipeline())

    run_processing(audio)

    sidecar = audio.parent / "session_output"
    assert not (sidecar / "HALA_Slices").exists()
    assert not (sidecar / "session_HALA_Analysis_Results.csv").exists()


def test_reprocessing_replaces_the_previous_slices(audio, pipeline):
    pipeline(fake_pipeline())
    run_processing(audio)

    # The pipeline clears its own HALA_Slices before each run but knows nothing
    # about the renamed one, so without help the first run's trials would sit
    # alongside the second run's -- and the rename onto a non-empty directory
    # would fail outright.
    stale = audio.parent / "session_output" / "Slices" / "Trial_999.wav"
    stale.write_bytes(b"from the earlier run")

    run_processing(audio)

    assert not stale.exists()
    assert (audio.parent / "session_output" / "Slices" / "Trial_001.wav").is_file()


def test_existing_csv_is_backed_up_not_overwritten(audio, pipeline):
    existing = audio.parent / "session_output.csv"
    existing.write_text("hand,verified,work\n", encoding="utf-8")
    pipeline(fake_pipeline(trial_count=2))

    outcome = run_processing(audio)

    assert outcome.backup_path == audio.parent / "session_output_backup.csv"
    assert outcome.backup_path.read_text(encoding="utf-8") == "hand,verified,work\n"
    assert outcome.csv_path.read_text(encoding="utf-8") != "hand,verified,work\n"


def test_repeated_processing_keeps_every_backup(audio, pipeline):
    (audio.parent / "session_output.csv").write_text("first\n", encoding="utf-8")
    pipeline(fake_pipeline())

    run_processing(audio)
    second = run_processing(audio)

    assert second.backup_path == audio.parent / "session_output_backup_2.csv"
    assert (audio.parent / "session_output_backup.csv").read_text(encoding="utf-8") == "first\n"


def test_recording_without_beeps_is_reported_distinctly(audio, pipeline):
    pipeline(fake_pipeline(raises=RuntimeError("No beeps detected in session.m4a")))

    outcome = run_processing(audio)

    assert outcome.status is ProcessingStatus.NO_BEEPS
    assert "no beeps" in outcome.message.lower()


def test_failure_leaves_the_existing_csv_untouched(audio, pipeline):
    existing = audio.parent / "session_output.csv"
    existing.write_text("hand,verified,work\n", encoding="utf-8")
    pipeline(fake_pipeline(raises=RuntimeError("boom")))

    outcome = run_processing(audio)

    assert outcome.status is ProcessingStatus.ERROR
    assert outcome.message == "boom"
    assert existing.read_text(encoding="utf-8") == "hand,verified,work\n"
    assert outcome.backup_path is None


def test_failure_cleans_up_a_sidecar_it_created(audio, pipeline):
    pipeline(fake_pipeline(raises=RuntimeError("boom")))

    run_processing(audio)

    assert not (audio.parent / "session_output").exists()


def test_failure_keeps_a_sidecar_from_an_earlier_run(audio, pipeline):
    sidecar = audio.parent / "session_output"
    sidecar.mkdir()
    (sidecar / "earlier.csv").write_text("keep me", encoding="utf-8")
    pipeline(fake_pipeline(raises=RuntimeError("boom")))

    run_processing(audio)

    assert (sidecar / "earlier.csv").read_text(encoding="utf-8") == "keep me"


def test_cancellation_stops_the_run(audio, pipeline):
    pipeline(fake_pipeline(stages=(("load", 1, 1), ("vad", 1, 5), ("vad", 2, 5))))
    seen = []

    outcome = run_processing(
        audio,
        on_progress=lambda stage, done, total: seen.append((stage, done, total)),
        should_cancel=lambda: len(seen) >= 2,
    )

    assert outcome.status is ProcessingStatus.CANCELLED
    assert not (audio.parent / "session_output.csv").exists()
    assert seen == [("load", 1, 1), ("vad", 1, 5)]


def test_progress_is_forwarded(audio, pipeline):
    pipeline(fake_pipeline(stages=(("load", 0, 1), ("slices", 3, 3), ("vad", 1, 3))))
    seen = []

    run_processing(audio, on_progress=lambda *args: seen.append(args))

    assert seen == [("load", 0, 1), ("slices", 3, 3), ("vad", 1, 3)]


def test_missing_export_is_an_error_not_a_crash(audio, pipeline):
    def process_audio(audio_path, output_dir=None, on_progress=None, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        return FakeResult(0)

    pipeline(process_audio)

    outcome = run_processing(audio)

    assert outcome.status is ProcessingStatus.ERROR
    assert "session_hala_output.csv" in outcome.message


def test_output_path_can_be_overridden(audio, pipeline, tmp_path):
    pipeline(fake_pipeline())
    target = tmp_path / "elsewhere.csv"

    outcome = run_processing(audio, output_csv_path=target)

    assert outcome.csv_path == target
    assert target.is_file()
