"""The global waveform's cached static layer.

Rendering the layer rescans the whole recording (a min/max pass per pixel
column), so it must be rebuilt when -- and only when -- something it draws
actually changed. A rebuild produces a pixel-identical pixmap when the content
is unchanged, so these tests count ``_draw_static_content`` calls rather than
comparing images: the call *is* the cost being guarded.
"""

import numpy as np
import pytest

from hala_rt.data.trial_data import TrialData
from hala_rt.widgets.simple_waveform import SimpleWaveformWidget


WIDTH, HEIGHT = 600, 125
SAMPLE_RATE = 44100


@pytest.fixture
def waveform(qapp):
    widget = SimpleWaveformWidget()
    widget.resize(WIDTH, HEIGHT)
    tone = np.sin(np.linspace(0, 500, SAMPLE_RATE * 10)).astype(np.float32)
    widget.set_audio_data(tone, SAMPLE_RATE)
    widget.set_trials([TrialData(1, 0.0, 5.0, 1.0)])
    return widget


@pytest.fixture
def redraws(waveform, monkeypatch):
    """Count full static-layer renders of ``waveform``."""
    counter = {"count": 0}
    original = waveform._draw_static_content

    def counted(painter, width, height):
        counter["count"] += 1
        return original(painter, width, height)

    monkeypatch.setattr(waveform, "_draw_static_content", counted)
    waveform._ensure_background_cache(WIDTH, HEIGHT)  # prime the cache
    counter["count"] = 0
    return counter


def _repaint(waveform):
    waveform._ensure_background_cache(WIDTH, HEIGHT)


def test_moving_a_marker_does_not_redraw_the_global_waveform(waveform, redraws):
    """The controller re-pushes the trial list after every marker edit.

    The global view draws neither beeps nor RTs, so an unchanged set of trial
    ranges must reuse the cached pixmap instead of rescanning the recording.
    """
    trials = waveform.trials
    trials[0].beep_timestamp_global = 2.0
    trials[0].rt_first_speech_ms = 400.0
    waveform.set_trials(trials)
    waveform.set_draft_range(waveform.draft_range)
    _repaint(waveform)

    assert redraws["count"] == 0


def test_adding_a_trial_redraws_the_global_waveform(waveform, redraws):
    waveform.set_trials([TrialData(1, 0.0, 5.0, 1.0), TrialData(2, 5.0, 9.0, 5.5)])
    _repaint(waveform)

    assert redraws["count"] == 1


def test_changing_the_draft_range_redraws_the_global_waveform(waveform, redraws):
    waveform.set_draft_range((5.0, 10.0))
    _repaint(waveform)

    assert redraws["count"] == 1


def test_repainting_without_changes_never_redraws(waveform, redraws):
    for _ in range(5):
        _repaint(waveform)

    assert redraws["count"] == 0


def test_loading_new_audio_drops_the_cache(waveform):
    """Guards the ``id(audio_data)`` term in the cache key.

    A replacement array can land at the address the old one just freed; if its
    length and sample rate also match, every term in the key matches and the
    stale waveform would survive. set_audio_data drops the cache outright.
    """
    waveform._ensure_background_cache(WIDTH, HEIGHT)
    assert waveform._background_cache is not None

    waveform.set_audio_data(np.zeros(SAMPLE_RATE * 10, dtype=np.float32), SAMPLE_RATE)

    assert waveform._background_cache is None


def test_resizing_redraws_at_the_new_width(waveform, redraws):
    waveform._ensure_background_cache(WIDTH * 2, HEIGHT)

    assert redraws["count"] == 1
