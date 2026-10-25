"""Anticipatory and timeout flags are measured from picture onset, not the beep."""

import math

import pandas as pd
import pytest

pytest.importorskip("leximetra.processing", reason="the 'processing' extra is not installed")
from leximetra.processing.export import build_software_export


def _export(rt_first_values, **kwargs):
    n = len(rt_first_values)
    df = pd.DataFrame(
        {
            "trial_name": [f"trial_{i + 1}" for i in range(n)],
            "beep_timestamp_global": [10.0 * (i + 1) for i in range(n)],
            "rt_first_speech_ms": rt_first_values,
            "rt_main_response_ms": rt_first_values,
        }
    )
    return build_software_export(df, audio_path="does_not_exist.m4a", **kwargs)


def test_flags_are_relative_to_picture_onset():
    # RTs are from beep onset; the picture appears 500 ms later.
    out = _export([100.0, 600.0, 700.0, 3400.0, 3600.0, math.nan])
    assert out["flag_anticipatory"].tolist() == ["true", "true", "false", "false", "false", "false"]
    assert out["flag_timeout"].tolist() == ["false", "false", "false", "false", "true", "true"]


def test_stimulus_onset_is_configurable():
    out = _export([250.0, 3300.0], stimulus_onset_after_beep_ms=0.0)
    assert out["flag_anticipatory"].tolist() == ["false", "false"]
    assert out["flag_timeout"].tolist() == ["false", "true"]
