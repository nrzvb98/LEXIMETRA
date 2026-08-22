"""Auto-processing as the controller drives it, on the real load-audio path.

``_run_auto_processing`` is stubbed: the worker and the pipeline are covered by
their own tests, and what matters here is the decision around them — when
analysis runs, when the user is asked first, and that a failure still leaves a
usable window.
"""

import csv

import numpy as np
import pytest
from PyQt6.QtWidgets import QMessageBox

from hala_rt.audio.manager import AudioManager
from hala_rt.data.processing_service import ProcessingOutcome, ProcessingStatus
from hala_rt.data.trial_data import CSV_COLUMNS
from hala_rt.ui.main_window import HALAMainWindow


SAMPLE_RATE = 16000
DURATION_SECONDS = 20.0


def write_csv(path, trial_count):
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


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "session.wav"
    path.write_bytes(b"not really audio")
    return path


@pytest.fixture
def fake_decoder(monkeypatch):
    """Make AudioManager.load_audio succeed without touching a real decoder."""

    def load_audio(self, file_path, progress_callback=None):
        self.audio_data = np.zeros(int(DURATION_SECONDS * SAMPLE_RATE), dtype=np.float32)
        self.sample_rate = SAMPLE_RATE
        self.duration = DURATION_SECONDS
        self.num_channels = 1
        self.file_path = str(file_path)
        self.file_format = ".wav"
        return True

    monkeypatch.setattr(AudioManager, "load_audio", load_audio)


@pytest.fixture
def loaded_window(qapp, dialogs, fake_decoder):
    """A window on which ``_load_audio_file`` can be driven for real."""
    window = HALAMainWindow()
    window.trial_waveform.resize(800, 300)
    yield window
    window.close()


@pytest.fixture
def processing(monkeypatch):
    """Stub the analysis run; record whether it was invoked."""
    calls = []

    def install(outcome, writes=None):
        def run(self, file_path):
            calls.append(file_path)
            if writes is not None:
                write_csv(self.output_csv_path, writes)
            return outcome

        monkeypatch.setattr(HALAMainWindow, "_run_auto_processing", run)
        monkeypatch.setattr(
            "hala_rt.ui.main_window.processing_available", lambda: True
        )
        return calls

    return install


def success(trial_count, backup_path=None, rescued_beep_count=0):
    return ProcessingOutcome(
        status=ProcessingStatus.SUCCESS,
        message=f"Processed {trial_count} trial(s).",
        trial_count=trial_count,
        backup_path=backup_path,
        rescued_beep_count=rescued_beep_count,
    )


# --- when analysis runs -----------------------------------------------------

def test_missing_csv_is_analyzed_automatically(loaded_window, audio_file, processing):
    calls = processing(success(3), writes=3)

    loaded_window._load_audio_file(audio_file)

    assert calls == [str(audio_file)]
    assert len(loaded_window.session_data) == 3
    assert "Analyzed 3 trial(s)" in loaded_window.status_label.text()


def test_recovered_beeps_are_mentioned_in_the_status(
    loaded_window, audio_file, processing
):
    """Otherwise the extra trials appear with no explanation anywhere visible."""
    processing(success(5, rescued_beep_count=2), writes=5)

    loaded_window._load_audio_file(audio_file)

    status = loaded_window.status_label.text()
    assert "Analyzed 5 trial(s)" in status
    assert "2 quiet beep(s) recovered" in status


def test_a_clean_recording_mentions_no_beeps(loaded_window, audio_file, processing):
    processing(success(5), writes=5)

    loaded_window._load_audio_file(audio_file)

    assert "recovered" not in loaded_window.status_label.text()


def test_existing_csv_is_kept_when_the_user_declines(
    loaded_window, audio_file, processing, monkeypatch
):
    write_csv(audio_file.parent / "session_output.csv", 2)
    calls = processing(success(9), writes=9)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    loaded_window._load_audio_file(audio_file)

    assert calls == []
    assert len(loaded_window.session_data) == 2  # the CSV already on disk


def test_existing_csv_is_reanalyzed_when_the_user_agrees(
    loaded_window, audio_file, processing
):
    write_csv(audio_file.parent / "session_output.csv", 2)
    # The shared ``dialogs`` fixture answers every question Yes.
    calls = processing(success(9), writes=9)

    loaded_window._load_audio_file(audio_file)

    assert calls == [str(audio_file)]
    assert len(loaded_window.session_data) == 9


def test_analysis_is_skipped_when_unavailable(
    loaded_window, audio_file, monkeypatch
):
    write_csv(audio_file.parent / "session_output.csv", 2)
    monkeypatch.setattr("hala_rt.ui.main_window.processing_available", lambda: False)
    called = []
    monkeypatch.setattr(
        HALAMainWindow,
        "_run_auto_processing",
        lambda self, path: called.append(path),
    )

    loaded_window._load_audio_file(audio_file)

    assert called == []
    assert len(loaded_window.session_data) == 2


def test_a_legacy_named_csv_still_loads(
    loaded_window, audio_file, processing, monkeypatch
):
    """CSVs verified before the ``_output`` rename must not be re-analyzed away."""
    legacy = audio_file.parent / "session_hala_output.csv"
    write_csv(legacy, 2)
    calls = processing(success(9), writes=9)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    loaded_window._load_audio_file(audio_file)

    assert calls == []
    assert loaded_window.output_csv_path == legacy
    assert len(loaded_window.session_data) == 2


def test_a_backup_is_named_in_the_status(loaded_window, audio_file, processing):
    write_csv(audio_file.parent / "session_output.csv", 2)
    backup = audio_file.parent / "session_output_backup.csv"
    processing(success(4, backup_path=backup), writes=4)

    loaded_window._load_audio_file(audio_file)

    assert "session_output_backup.csv" in loaded_window.status_label.text()


# --- failures leave a usable window -----------------------------------------

@pytest.mark.parametrize(
    "status, expected",
    [
        (ProcessingStatus.NO_BEEPS, "No beeps detected"),
        (ProcessingStatus.CANCELLED, "Analysis cancelled"),
        (ProcessingStatus.ERROR, "Automatic analysis failed"),
    ],
)
def test_failure_falls_back_to_manual_mode(
    loaded_window, audio_file, processing, status, expected
):
    processing(ProcessingOutcome(status=status, message="something went wrong"))

    assert loaded_window._load_audio_file(audio_file) is True
    assert expected in loaded_window.status_label.text()
    assert loaded_window.session_data == []
    # The audio is still loaded, so trials can be cut by hand.
    assert loaded_window.audio_manager.duration == DURATION_SECONDS
    assert loaded_window.play_btn.isEnabled()


def test_an_unreadable_csv_outranks_the_analysis_status(
    loaded_window, audio_file, monkeypatch, dialogs
):
    """A CSV that will not load is the more urgent thing to report."""

    def run(self, file_path):
        self.output_csv_path.write_text("not,a,valid,schema\n1,2,3,4\n", encoding="utf-8")
        return success(3)

    monkeypatch.setattr("hala_rt.ui.main_window.processing_available", lambda: True)
    monkeypatch.setattr(HALAMainWindow, "_run_auto_processing", run)

    loaded_window._load_audio_file(audio_file)

    assert "could not be loaded" in loaded_window.status_label.text()
    assert loaded_window.session_data == []


# --- progress mapping -------------------------------------------------------

@pytest.mark.parametrize(
    "stage, done, total, expected_value, expected_text",
    [
        ("load", 0, 1, 5, "Loading audio…"),
        ("slices", 12, 12, 20, "Detected 12 trial(s). Slicing…"),
        ("vad", 0, 12, 20, "Analyzing trial 0 of 12…"),
        ("vad", 6, 12, 57, "Analyzing trial 6 of 12…"),
        ("vad", 12, 12, 95, "Analyzing trial 12 of 12…"),
        ("export", 1, 1, 95, "Writing results…"),
    ],
)
def test_progress_mapping(stage, done, total, expected_value, expected_text):
    value, text = HALAMainWindow._processing_progress(stage, done, total)

    assert (value, text) == (expected_value, expected_text)


def test_progress_mapping_survives_a_zero_total():
    value, text = HALAMainWindow._processing_progress("vad", 0, 0)

    assert value == 20
    assert "0 of 0" in text
