"""Controller behaviour for :class:`HALAMainWindow`.

Covers the trial state machine (add / delete / renumber / derive starts), the
marker and RT maths, table-edit validation, dirty tracking, and the trial detail
view window -- the logic the CSV and path tests do not reach.
"""

import pytest

from hala_rt.data.csv_io import write_output_csv
from hala_rt.data.trial_data import CSV_COLUMNS, TrialData

from conftest import add_trial_ending_at, trial_bounds


def _column(field):
    return CSV_COLUMNS.index(field)


def _set_cell(window, row, field, text):
    """Type into a table cell the way a user would, firing itemChanged."""
    window.trial_table.item(row, _column(field)).setText(text)


# --- trial creation and numbering ------------------------------------------

def test_added_trials_are_contiguous_and_numbered_from_one(window):
    add_trial_ending_at(window, 5.0)
    add_trial_ending_at(window, 12.0)

    assert trial_bounds(window) == [(1, 0.0, 5.0), (2, 5.0, 12.0)]


def test_add_trial_rejects_a_cursor_at_or_before_the_trial_start(window, dialogs):
    add_trial_ending_at(window, 5.0)
    add_trial_ending_at(window, 5.0)  # no forward progress

    assert trial_bounds(window) == [(1, 0.0, 5.0)]
    assert any(kind == "warning" for kind, _, _ in dialogs)


def test_add_trial_button_tracks_whether_the_cursor_has_advanced(window):
    add_trial_ending_at(window, 5.0)

    window._set_playback_position(5.0)
    assert not window.add_trial_btn.isEnabled()

    window._set_playback_position(9.0)
    assert window.add_trial_btn.isEnabled()


def test_deleting_a_trial_renumbers_and_rederives_starts(window):
    for end in (4.0, 9.0, 15.0):
        add_trial_ending_at(window, end)

    window.load_trial(1)  # the middle trial
    window.delete_current_trial()

    # The survivors close the gap: starts always chain off the previous end.
    assert trial_bounds(window) == [(1, 0.0, 4.0), (2, 4.0, 15.0)]


def test_deleting_the_last_trial_returns_the_whole_recording_to_a_draft(window):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    window.delete_current_trial()

    assert window.session_data == []
    # Nothing is committed, so the entire recording is offered as the draft.
    assert window._current_trial_is_draft()
    assert window._draft_range() == pytest.approx((0.0, 20.0))
    assert not window.delete_trial_btn.isEnabled()


# --- markers and reaction times --------------------------------------------

def test_setting_rt_measures_milliseconds_from_the_beep(window):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)

    window._set_playback_position(1.0)
    window.set_beep_from_playhead()
    window._set_playback_position(1.5)
    window.set_rt_from_playhead("rt_first_speech_ms")

    trial = window.session_data[0]
    assert trial.beep_timestamp_global == pytest.approx(1.0)
    assert trial.rt_first_speech_ms == pytest.approx(500.0)
    assert trial.first_speech_global == pytest.approx(1.5)


def test_rt_before_the_beep_is_rejected(window, dialogs):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    window._set_playback_position(2.0)
    window.set_beep_from_playhead()

    window._set_playback_position(1.0)
    window.set_rt_from_playhead("rt_first_speech_ms")

    assert window.session_data[0].rt_first_speech_ms is None
    assert any(kind == "warning" for kind, _, _ in dialogs)


def test_set_first_and_main_writes_both_reaction_times(window):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    window._set_playback_position(1.0)
    window.set_beep_from_playhead()

    window._set_playback_position(2.25)
    window.set_first_and_main_response_from_playhead()

    trial = window.session_data[0]
    assert trial.rt_first_speech_ms == pytest.approx(1250.0)
    assert trial.rt_main_response_ms == pytest.approx(1250.0)


def test_beep_outside_the_trial_window_is_rejected(window, dialogs):
    add_trial_ending_at(window, 5.0)
    add_trial_ending_at(window, 10.0)
    window.load_trial(1)  # spans 5.0 - 10.0
    original = window.session_data[1].beep_timestamp_global

    window._set_playback_position(1.0)  # inside trial 1, not trial 2
    window.set_beep_from_playhead()

    assert window.session_data[1].beep_timestamp_global == original
    assert any(kind == "warning" for kind, _, _ in dialogs)


# --- table editing ----------------------------------------------------------

def test_table_edit_moves_the_trial_end_and_drags_the_next_start_with_it(window):
    add_trial_ending_at(window, 5.0)
    add_trial_ending_at(window, 12.0)

    _set_cell(window, 0, "trial_end_global", "3.0000")

    assert trial_bounds(window) == [(1, 0.0, 3.0), (2, 3.0, 12.0)]
    assert window.has_unsaved_changes


def test_table_edit_that_strands_the_next_trials_beep_is_rejected(window, dialogs):
    add_trial_ending_at(window, 5.0)
    add_trial_ending_at(window, 12.0)
    before = trial_bounds(window)

    # Trial 2's beep defaults to 5.0; pushing trial 1's end past it would leave
    # that beep in front of its own trial window.
    _set_cell(window, 0, "trial_end_global", "6.5000")

    assert trial_bounds(window) == before
    assert any(kind == "warning" for kind, _, _ in dialogs)


def test_table_edit_with_a_non_numeric_value_is_rejected(window, dialogs):
    add_trial_ending_at(window, 5.0)
    before = trial_bounds(window)

    _set_cell(window, 0, "trial_end_global", "not a number")

    assert trial_bounds(window) == before
    assert any(kind == "warning" for kind, _, _ in dialogs)


def test_table_edit_that_strands_the_beep_is_rejected(window, dialogs):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    window._set_playback_position(4.0)
    window.set_beep_from_playhead()

    # Pulling the end in front of the beep would leave it outside the window.
    _set_cell(window, 0, "trial_end_global", "2.0000")

    assert window.session_data[0].trial_end_global == pytest.approx(5.0)
    assert any(kind == "warning" for kind, _, _ in dialogs)


def test_toggling_a_boolean_cell_updates_the_trial(window):
    from PyQt6.QtCore import Qt

    add_trial_ending_at(window, 5.0)
    item = window.trial_table.item(0, _column("prefiller_present"))
    item.setCheckState(Qt.CheckState.Checked)

    assert window.session_data[0].prefiller_present is True


# --- dirty tracking and saving ----------------------------------------------

def test_save_buttons_follow_the_dirty_state(window):
    assert not window.save_btn.isEnabled()

    add_trial_ending_at(window, 5.0)
    assert window.has_unsaved_changes
    assert window.save_btn.isEnabled()
    assert window.save_as_btn.isEnabled()

    window.save_output_csv()
    assert not window.has_unsaved_changes
    assert not window.save_btn.isEnabled()
    assert window.save_as_btn.isEnabled()


def test_saving_round_trips_through_the_csv(window):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    window._set_playback_position(1.0)
    window.set_beep_from_playhead()
    window._set_playback_position(1.4)
    window.set_rt_from_playhead("rt_main_response_ms")
    window.save_output_csv()

    from hala_rt.data.csv_io import load_output_csv

    reloaded = load_output_csv(window.output_csv_path)
    assert reloaded == window.session_data


def test_loading_an_existing_csv_populates_the_session(window):
    trials = [
        TrialData(1, 0.0, 4.0, 0.5, rt_first_speech_ms=250.0),
        TrialData(2, 4.0, 9.0, 4.5, rt_main_response_ms=800.0),
    ]
    write_output_csv(window.output_csv_path, trials)

    status, tone = window._load_trials_for_audio()

    assert tone == "success"
    assert "2 trial(s)" in status
    assert trial_bounds(window) == [(1, 0.0, 4.0), (2, 4.0, 9.0)]


def test_loading_a_csv_with_a_gap_closes_it_to_stay_contiguous(window):
    # The schema requires each trial to start at the previous end; a hand-edited
    # gap is normalised on load rather than carried through.
    write_output_csv(
        window.output_csv_path,
        [TrialData(1, 0.0, 5.0, 1.0), TrialData(2, 7.0, 10.0, 7.5)],
    )

    window._load_trials_for_audio()
    window._sort_and_renumber_trials()

    assert trial_bounds(window) == [(1, 0.0, 5.0), (2, 5.0, 10.0)]


# --- trial detail view window ----------------------------------------------

def test_zoom_and_selection_survive_setting_a_marker(window):
    """Regression: placing one marker used to throw away the zoom for the next."""
    add_trial_ending_at(window, 10.0)
    window.load_trial(0)
    detail = window.trial_waveform

    detail.zoom_in()
    detail.zoom_in()
    zoomed = (detail.view_start, detail.view_end)
    detail._set_selection_from_times(0.5, 1.2)

    window._set_playback_position(1.5)
    window.set_rt_from_playhead("rt_first_speech_ms")

    assert (detail.view_start, detail.view_end) == zoomed
    assert window._trial_detail_selection_range == pytest.approx((0.5, 1.2))


def test_zoom_resets_when_navigating_to_another_trial(window):
    add_trial_ending_at(window, 10.0)
    add_trial_ending_at(window, 20.0)
    window.load_trial(0)
    detail = window.trial_waveform

    detail.zoom_in()
    window.next_trial()

    assert (detail.view_start, detail.view_end) == pytest.approx((10.0, 20.0))


def test_zoom_resets_when_the_trial_window_itself_changes(window):
    add_trial_ending_at(window, 10.0)
    window.load_trial(0)
    detail = window.trial_waveform
    detail.zoom_in()

    _set_cell(window, 0, "trial_end_global", "8.0000")

    assert (detail.view_start, detail.view_end) == pytest.approx((0.0, 8.0))


def test_cursor_nudge_stays_inside_the_trial(window):
    add_trial_ending_at(window, 5.0)
    window.load_trial(0)
    detail = window.trial_waveform

    for _ in range(200):
        detail.nudge_cursor(-1, multiplier=10)
    assert detail.play_position_global == pytest.approx(0.0)

    for _ in range(2000):
        detail.nudge_cursor(1, multiplier=10)
    assert detail.play_position_global == pytest.approx(5.0)


# --- draft trial ------------------------------------------------------------

def test_the_tail_of_the_recording_is_offered_as_a_draft_trial(window):
    add_trial_ending_at(window, 5.0)

    # One committed trial plus the un-cut remainder shown as a draft.
    assert window._display_trial_count() == 2
    assert window._draft_range() == pytest.approx((5.0, 20.0))

    window.load_trial(1)
    assert window._current_trial_is_draft()
    # A draft is not a real trial: it cannot be deleted or given markers.
    assert not window.delete_trial_btn.isEnabled()
    assert not window.set_beep_btn.isEnabled()


def test_no_draft_once_trials_reach_the_end_of_the_recording(window):
    add_trial_ending_at(window, 20.0)

    assert window._display_trial_count() == 1
    assert window._draft_range() is None
