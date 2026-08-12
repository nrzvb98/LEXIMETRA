from dataclasses import dataclass
from typing import Optional


CSV_COLUMNS = [
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

BOOLEAN_COLUMNS = {
    "prefiller_present",
    "flag_anticipatory",
    "flag_timeout",
}

SECONDS_COLUMNS = {
    "trial_start_global",
    "trial_end_global",
    "beep_timestamp_global",
}

RT_COLUMNS = {
    "rt_first_speech_ms",
    "rt_main_response_ms",
}

SECONDS_DECIMALS = 4
MS_DECIMALS = 1


def format_seconds(value):
    return f"{value:.{SECONDS_DECIMALS}f}"


def format_optional_ms(value):
    if value is None or value <= 0:
        return ""
    return f"{value:.{MS_DECIMALS}f}"


def parse_bool(value):
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"Expected boolean value, got {value!r}")


def parse_float(value, column):
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{column} must be a number") from exc


def parse_optional_ms(value, column):
    text = str(value or "").strip()
    if text == "":
        return None
    parsed = parse_float(text, column)
    if parsed < 0:
        raise ValueError(f"{column} cannot be negative")
    if parsed == 0:
        return None
    return parsed


def parse_nonnegative_int(value, column):
    text = str(value or "").strip()
    if text == "":
        return 0
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"{column} must be a whole number") from exc
    if parsed < 0:
        raise ValueError(f"{column} cannot be negative")
    return parsed


@dataclass
class TrialData:
    trial_index: int
    trial_start_global: float
    trial_end_global: float
    beep_timestamp_global: float
    rt_first_speech_ms: Optional[float] = None
    rt_main_response_ms: Optional[float] = None
    prefiller_present: bool = False
    flag_anticipatory: bool = False
    flag_timeout: bool = False
    segments_count: int = 0

    def validate(self):
        if self.trial_start_global < 0:
            raise ValueError("trial_start_global cannot be negative")
        if self.trial_end_global <= self.trial_start_global:
            raise ValueError("trial_end_global must be after trial_start_global")
        if not self.trial_start_global <= self.beep_timestamp_global <= self.trial_end_global:
            raise ValueError("beep_timestamp_global must be inside the trial window")
        if self.segments_count < 0:
            raise ValueError("segments_count cannot be negative")
        if self.rt_first_speech_ms is not None and self.rt_first_speech_ms < 0:
            raise ValueError("rt_first_speech_ms cannot be negative")
        if self.rt_main_response_ms is not None and self.rt_main_response_ms < 0:
            raise ValueError("rt_main_response_ms cannot be negative")

    @property
    def first_speech_global(self):
        if self.rt_first_speech_ms is None or self.rt_first_speech_ms <= 0:
            return None
        return self.beep_timestamp_global + self.rt_first_speech_ms / 1000.0

    @property
    def main_response_global(self):
        if self.rt_main_response_ms is None or self.rt_main_response_ms <= 0:
            return None
        return self.beep_timestamp_global + self.rt_main_response_ms / 1000.0

    def to_csv_row(self):
        return {
            "trial_index": str(self.trial_index),
            "trial_start_global": format_seconds(self.trial_start_global),
            "trial_end_global": format_seconds(self.trial_end_global),
            "beep_timestamp_global": format_seconds(self.beep_timestamp_global),
            "rt_first_speech_ms": format_optional_ms(self.rt_first_speech_ms),
            "rt_main_response_ms": format_optional_ms(self.rt_main_response_ms),
            "prefiller_present": str(self.prefiller_present).lower(),
            "flag_anticipatory": str(self.flag_anticipatory).lower(),
            "flag_timeout": str(self.flag_timeout).lower(),
            "segments_count": str(self.segments_count),
        }


def trial_from_csv_row(row, fallback_index):
    trial = TrialData(
        trial_index=parse_nonnegative_int(row.get("trial_index") or fallback_index, "trial_index"),
        trial_start_global=parse_float(row.get("trial_start_global"), "trial_start_global"),
        trial_end_global=parse_float(row.get("trial_end_global"), "trial_end_global"),
        beep_timestamp_global=parse_float(row.get("beep_timestamp_global"), "beep_timestamp_global"),
        rt_first_speech_ms=parse_optional_ms(row.get("rt_first_speech_ms"), "rt_first_speech_ms"),
        rt_main_response_ms=parse_optional_ms(row.get("rt_main_response_ms"), "rt_main_response_ms"),
        prefiller_present=parse_bool(row.get("prefiller_present")),
        flag_anticipatory=parse_bool(row.get("flag_anticipatory")),
        flag_timeout=parse_bool(row.get("flag_timeout")),
        segments_count=parse_nonnegative_int(row.get("segments_count"), "segments_count"),
    )
    trial.validate()
    return trial
