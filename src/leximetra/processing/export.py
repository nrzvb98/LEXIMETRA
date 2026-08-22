"""Software-format LEXIMETRA CSV export (absorbed from hala_output_export.py).

Trial windows tile the recording: each trial starts where the previous ended,
and ends `next_beep_margin_s` before the next beep (audio duration, probed via
ffprobe, closes the last trial).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pandas as pd

OUTPUT_COLUMNS = [
    "trial_index",
    "trial_start_global",
    "trial_end_global",
    "beep_timestamp_global",
    "rt_first_speech_ms",
    "rt_main_response_ms",
    "prefiller_present",
    "flag_anticipatory",
    "flag_timeout",
    "segments_count",
]


def _audio_duration_seconds(audio_path: str | Path) -> float | None:
    path = Path(audio_path)
    if not path.exists():
        return None

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _trial_index(trial_name: object, fallback: int) -> int:
    match = re.search(r"(\d+)$", str(trial_name))
    if match:
        return int(match.group(1))
    return fallback


def _format_seconds(value: object) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.4f}"


def _format_ms(value: object) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.1f}"


def _format_bool(value: object) -> str:
    return "true" if bool(value) else "false"


def _trial_windows(
    beep_timestamps: list[float],
    audio_duration_s: float | None,
    next_beep_margin_s: float,
) -> tuple[list[float], list[float]]:
    starts: list[float] = []
    ends: list[float] = []
    current_start = 0.0

    for index, beep_timestamp in enumerate(beep_timestamps):
        starts.append(current_start)

        if index < len(beep_timestamps) - 1:
            next_beep = beep_timestamps[index + 1]
            trial_end = next_beep - next_beep_margin_s
            if trial_end <= beep_timestamp:
                trial_end = beep_timestamp + ((next_beep - beep_timestamp) / 2)
        else:
            trial_end = audio_duration_s if audio_duration_s is not None else beep_timestamp + 3.0
            if trial_end <= beep_timestamp:
                trial_end = beep_timestamp + 0.001

        ends.append(trial_end)
        current_start = trial_end

    return starts, ends


def build_software_export(
    final_results: pd.DataFrame,
    audio_path: str | Path = "trial.m4a",
    anticipatory_threshold_ms: float = 150.0,
    timeout_threshold_ms: float = 3000.0,
    next_beep_margin_s: float = 0.05,
) -> pd.DataFrame:
    required_columns = {"trial_name", "beep_timestamp_global", "rt_first_speech_ms", "rt_main_response_ms"}
    missing = required_columns - set(final_results.columns)
    if missing:
        raise ValueError(f"Missing required columns for LEXIMETRA export: {sorted(missing)}")

    export = final_results.copy()
    export["trial_index"] = [
        _trial_index(trial_name, fallback)
        for fallback, trial_name in enumerate(export["trial_name"], start=1)
    ]
    export = export.sort_values("trial_index").reset_index(drop=True)
    export["beep_timestamp_global"] = pd.to_numeric(export["beep_timestamp_global"], errors="coerce")

    if export["beep_timestamp_global"].isna().any():
        bad_rows = export.loc[export["beep_timestamp_global"].isna(), "trial_name"].tolist()
        raise ValueError(f"Missing beep timestamps for trials: {bad_rows}")

    audio_duration_s = _audio_duration_seconds(audio_path)
    starts, ends = _trial_windows(
        export["beep_timestamp_global"].astype(float).tolist(),
        audio_duration_s,
        next_beep_margin_s,
    )

    rt_first = pd.to_numeric(export["rt_first_speech_ms"], errors="coerce")
    rt_main = pd.to_numeric(export["rt_main_response_ms"], errors="coerce")
    flag_anticipatory = rt_first <= anticipatory_threshold_ms
    flag_timeout = rt_first > timeout_threshold_ms

    # Propagate the upstream analysis instead of hardcoding. A prefiller ("Umm... Word")
    # is present whenever the pipeline flagged a hesitation pattern, or equivalently
    # whenever the main response lands measurably later than the first speech onset.
    if "prefiller_present" in export.columns:
        prefiller = export["prefiller_present"].astype(bool)
    elif "hesitation_pattern" in export.columns:
        prefiller = export["hesitation_pattern"].astype(bool)
    else:
        prefiller = (rt_main - rt_first) > 1.0

    if "segments_count" in export.columns:
        segments_count = pd.to_numeric(export["segments_count"], errors="coerce").fillna(0).astype(int)
    else:
        segments_count = pd.Series([0] * len(export), index=export.index)

    formatted = pd.DataFrame(
        {
            "trial_index": export["trial_index"].astype(int),
            "trial_start_global": [_format_seconds(value) for value in starts],
            "trial_end_global": [_format_seconds(value) for value in ends],
            "beep_timestamp_global": [
                _format_seconds(value) for value in export["beep_timestamp_global"]
            ],
            "rt_first_speech_ms": [_format_ms(value) for value in rt_first],
            "rt_main_response_ms": [_format_ms(value) for value in rt_main],
            "prefiller_present": [_format_bool(value) for value in prefiller],
            "flag_anticipatory": [_format_bool(value) for value in flag_anticipatory],
            "flag_timeout": [_format_bool(value) for value in flag_timeout],
            "segments_count": [int(value) for value in segments_count],
        }
    )

    return formatted[OUTPUT_COLUMNS]


def save_software_csv(
    final_results: pd.DataFrame,
    audio_path: str | Path = "trial.m4a",
    output_path: str | Path | None = None,
    **kwargs: object,
) -> Path:
    audio_path = Path(audio_path)
    if output_path is None:
        output_path = audio_path.with_name(f"{audio_path.stem}_output.csv")

    output_path = Path(output_path)
    export = build_software_export(final_results, audio_path=audio_path, **kwargs)
    export.to_csv(output_path, index=False)
    return output_path
