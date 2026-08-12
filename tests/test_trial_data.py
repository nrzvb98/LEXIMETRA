import pytest

from hala_rt.data.trial_data import TrialData, parse_bool, parse_optional_ms


def test_trial_data_derives_global_marker_times():
    trial = TrialData(
        trial_index=1,
        trial_start_global=5.0,
        trial_end_global=10.0,
        beep_timestamp_global=6.0,
        rt_first_speech_ms=250.0,
        rt_main_response_ms=500.0,
    )

    assert trial.first_speech_global == 6.25
    assert trial.main_response_global == 6.5


def test_trial_data_validation_rejects_beep_outside_trial():
    trial = TrialData(
        trial_index=1,
        trial_start_global=5.0,
        trial_end_global=10.0,
        beep_timestamp_global=11.0,
    )

    with pytest.raises(ValueError, match="beep_timestamp_global"):
        trial.validate()


def test_parsers_accept_expected_blank_and_boolean_values():
    assert parse_optional_ms("", "rt_first_speech_ms") is None
    assert parse_bool("yes") is True
    assert parse_bool("0") is False

