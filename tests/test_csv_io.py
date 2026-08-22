import pytest

from leximetra.data.csv_io import load_output_csv, write_output_csv
from leximetra.data.trial_data import TrialData


class _ExplodingTrial(TrialData):
    """A trial that fails partway through serialization."""

    def to_csv_row(self):
        raise RuntimeError("disk full")


def test_write_and_load_output_csv(tmp_path):
    path = tmp_path / "trial_output.csv"
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


def test_failed_write_leaves_the_previous_csv_intact(tmp_path):
    path = tmp_path / "trial_output.csv"
    first = TrialData(
        trial_index=1,
        trial_start_global=0.0,
        trial_end_global=1.0,
        beep_timestamp_global=0.1,
    )
    second = TrialData(
        trial_index=2,
        trial_start_global=1.0,
        trial_end_global=2.0,
        beep_timestamp_global=1.1,
    )
    write_output_csv(path, [first, second])
    original = path.read_text(encoding="utf-8")

    # Fail on the *first* row, so a non-atomic write would leave a file holding
    # only the header -- strictly less than the two rows already on disk.
    doomed = _ExplodingTrial(
        trial_index=1,
        trial_start_global=0.0,
        trial_end_global=1.0,
        beep_timestamp_global=0.1,
    )
    with pytest.raises(RuntimeError, match="disk full"):
        write_output_csv(path, [doomed, second])

    assert path.read_text(encoding="utf-8") == original
    assert load_output_csv(path) == [first, second]
    # the temporary file must not be left behind next to the output
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_write_preserves_existing_file_permissions(tmp_path):
    path = tmp_path / "trial_output.csv"
    trial = TrialData(
        trial_index=1,
        trial_start_global=0.0,
        trial_end_global=1.0,
        beep_timestamp_global=0.1,
    )
    write_output_csv(path, [trial])
    assert path.stat().st_mode & 0o777 == 0o644

    path.chmod(0o640)
    write_output_csv(path, [trial])
    assert path.stat().st_mode & 0o777 == 0o640


def test_load_output_csv_requires_schema_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("trial_index,trial_start_global\n1,0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing CSV columns"):
        load_output_csv(path)

