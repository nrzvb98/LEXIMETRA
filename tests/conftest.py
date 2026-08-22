"""Shared fixtures for the GUI controller tests.

The Qt platform is forced to ``offscreen`` before PyQt6 is imported anywhere, so
these run headless in CI and without stealing focus locally.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from leximetra.data.output_paths import default_output_path  # noqa: E402
from leximetra.ui.main_window import HALAMainWindow  # noqa: E402


SAMPLE_RATE = 16000
DURATION_SECONDS = 20.0


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogs(monkeypatch):
    """Silence modal dialogs and record them so tests can assert on them.

    Every ``question`` is answered Yes, so delete confirmations and the unsaved
    changes prompt proceed rather than hanging the test run.
    """
    recorded = []

    def _record(kind):
        def handler(parent, title, text, *args, **kwargs):
            recorded.append((kind, title, text))
            return QMessageBox.StandardButton.Yes

        return handler

    for kind in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(_record(kind)))
    return recorded


@pytest.fixture
def window(qapp, dialogs, tmp_path):
    """A main window with synthetic silent audio already loaded.

    Bypasses the file dialog and the decoders: those are covered elsewhere, and
    the controller only needs a sample buffer, a rate, and a duration.
    """
    window = HALAMainWindow()
    samples = np.zeros(int(DURATION_SECONDS * SAMPLE_RATE), dtype=np.float32)

    audio = window.audio_manager
    audio.audio_data = samples
    audio.sample_rate = SAMPLE_RATE
    audio.duration = DURATION_SECONDS
    audio.num_channels = 1
    audio.file_path = str(tmp_path / "session.wav")
    audio.file_format = ".wav"

    window.output_csv_path = default_output_path(audio.file_path)
    window.global_waveform.set_audio_data(samples, SAMPLE_RATE)
    window.play_btn.setEnabled(True)
    window._refresh_trial_views(None)
    window._set_dirty(False)

    # The detail view needs a real width for the zoom/pan maths.
    window.trial_waveform.resize(800, 300)

    yield window
    window.close()


def add_trial_ending_at(window, seconds):
    """Drive the real 'Add Trial End' path with the cursor at ``seconds``."""
    window._set_playback_position(seconds)
    window.add_trial_from_end()


def trial_bounds(window):
    return [
        (t.trial_index, round(t.trial_start_global, 4), round(t.trial_end_global, 4))
        for t in window.session_data
    ]
