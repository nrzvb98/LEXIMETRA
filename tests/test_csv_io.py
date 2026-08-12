import pytest

from hala_rt.data.csv_io import load_output_csv, write_output_csv
from hala_rt.data.trial_data import TrialData


def test_write_and_load_output_csv(tmp_path):
    path = tmp_path / "trial_hala_output.csv"
    trials = [
        TrialData(
            trial_index=1,
            trial_start_global=0.0,
            trial_end_global=1.25,
            beep_timestamp_global=0.2,
            rt_first_speech_ms=350.0,
            rt_main_response_ms=450.0,
            prefiller_present=True,
            segments_count=2,
        )
    ]

    write_output_csv(path, trials)
    loaded_trials = load_output_csv(path)

    assert loaded_trials == trials


def test_load_output_csv_requires_schema_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("trial_index,trial_start_global\n1,0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing CSV columns"):
        load_output_csv(path)

