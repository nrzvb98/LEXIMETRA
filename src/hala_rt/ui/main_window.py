from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QTableWidgetItem,
)

from hala_rt.audio.manager import AudioManager
from hala_rt.data.csv_io import load_output_csv, write_output_csv
from hala_rt.data.output_paths import default_output_path, next_edited_output_path
from hala_rt.data.trial_data import (
    BOOLEAN_COLUMNS,
    CSV_COLUMNS,
    MS_DECIMALS,
    RT_COLUMNS,
    SECONDS_COLUMNS,
    SECONDS_DECIMALS,
    TrialData,
    format_optional_ms,
    format_seconds,
    parse_float,
    parse_nonnegative_int,
    parse_optional_ms,
)
from hala_rt.ui import theme
from hala_rt.ui.main_window_ui import build_ui
from hala_rt.ui.table_columns import COLUMN_LABELS, resize_table_columns


MIN_TRIAL_DURATION_SECONDS = 0.01
EPSILON_SECONDS = 1e-6


class HALAMainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HALA RT Verification Interface")
        self.setGeometry(100, 100, 1180, 820)

        self.audio_manager = AudioManager()

        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self.update_playback)
        self.playback_timer.setInterval(33)

        self.session_data = []
        self.current_trial_index = -1
        self.has_unsaved_changes = False
        self.output_csv_path = None
        self._trial_detail_selection_range = None
        self._updating_table = False

        build_ui(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_playback()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.current_trial_index >= 0:
            direction = -1 if event.key() == Qt.Key.Key_Left else 1
            multiplier = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.trial_waveform.nudge_cursor(direction, multiplier)
            event.accept()
            return
        super().keyPressEvent(event)

    def _focus_trial_waveform(self):
        self.trial_waveform.setFocus(Qt.FocusReason.OtherFocusReason)

    def zoom_trial_detail_in(self):
        self.trial_waveform.zoom_in()
        self._focus_trial_waveform()

    def zoom_trial_detail_out(self):
        self.trial_waveform.zoom_out()
        self._focus_trial_waveform()

    def reset_trial_detail_zoom(self):
        self.trial_waveform.reset_zoom()
        self._focus_trial_waveform()

    def closeEvent(self, event):
        if self._confirm_discard_changes():
            event.accept()
        else:
            event.ignore()

    def _set_status(self, text, tone):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(theme.status_label_qss(tone))

    def _set_position_label_width(self):
        max_seconds = max(self.audio_manager.duration, 999.99)
        sample = (
            f"Position: {max_seconds:.{SECONDS_DECIMALS}f}s / "
            f"{max_seconds:.{SECONDS_DECIMALS}f}s"
        )
        width = QFontMetrics(self.position_label.font()).horizontalAdvance(sample) + 16
        self.position_label.setFixedWidth(width)

    def _confirm_discard_changes(self):
        if not self.has_unsaved_changes:
            return True

        response = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved CSV edits. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _set_playback_position(self, position):
        self.global_waveform.set_playback_position(position)
        self.trial_waveform.set_playback_position(
            position,
            auto_pan=not self.audio_manager.is_playing,
            show_label=not self.audio_manager.is_playing,
        )
        self._update_position_label(position)
        self._update_add_trial_button()

    def _update_position_label(self, position):
        self.position_label.setText(
            f"Position: {position:.{SECONDS_DECIMALS}f}s / {self.audio_manager.duration:.{SECONDS_DECIMALS}f}s"
        )

    def _current_cursor_position(self):
        if self.trial_waveform.trial_data is not None:
            return self.trial_waveform.play_position_global
        return self.global_waveform.playback_position

    def _detail_selection_range(self):
        trial = self._display_trial_for_index(self.current_trial_index)
        if trial is None:
            return None

        selection = self._trial_detail_selection_range
        if not selection:
            return None

        start, end = selection
        start = max(trial.trial_start_global, min(start, trial.trial_end_global))
        end = max(trial.trial_start_global, min(end, trial.trial_end_global))
        start, end = min(start, end), max(start, end)
        if end - start <= EPSILON_SECONDS:
            return None
        return start, end

    def _refresh_play_button_text(self):
        if not self.audio_manager.is_playing:
            text = "Play Selection" if self._detail_selection_range() else "Play"
            self.play_btn.setText(text)

    def _set_dirty(self, dirty):
        self.has_unsaved_changes = dirty
        has_saveable_trials = bool(self.output_csv_path) and bool(self.session_data)
        self.save_btn.setEnabled(has_saveable_trials and dirty)
        self.save_as_btn.setEnabled(has_saveable_trials)

    def _format_audio_info(self, file_name):
        output_path = str(self.output_csv_path) if self.output_csv_path else "--"
        return f"""File: {file_name}
Format: {self.audio_manager.file_format}
Sample Rate: {self.audio_manager.sample_rate:,} Hz
Duration: {self.audio_manager.duration:.2f} seconds
Samples: {len(self.audio_manager.audio_data):,}
Channels: {self.audio_manager.num_channels}
Output CSV: {output_path}"""

    def _refresh_audio_info(self):
        if self.audio_manager.file_path:
            self.info_text.setText(self._format_audio_info(Path(self.audio_manager.file_path).name))

    @staticmethod
    def _ranges_overlap(start_a, end_a, start_b, end_b):
        return start_a < end_b - EPSILON_SECONDS and end_a > start_b + EPSILON_SECONDS

    def _find_overlap(self, start, end, exclude_index=None):
        for index, trial in enumerate(self.session_data):
            if exclude_index is not None and index == exclude_index:
                continue
            if self._ranges_overlap(
                start,
                end,
                trial.trial_start_global,
                trial.trial_end_global,
            ):
                return trial
        return None

    def _validate_no_overlaps(self, trials):
        ordered = sorted(trials, key=lambda trial: trial.trial_start_global)
        for trial in ordered:
            trial.validate()
        for previous, current in zip(ordered, ordered[1:]):
            if self._ranges_overlap(
                previous.trial_start_global,
                previous.trial_end_global,
                current.trial_start_global,
                current.trial_end_global,
            ):
                raise ValueError(
                    f"Trial {previous.trial_index} overlaps trial {current.trial_index}"
                )

    @staticmethod
    def _apply_derived_trial_starts(trials):
        next_start = 0.0
        for trial in trials:
            trial.trial_start_global = next_start
            next_start = trial.trial_end_global

    def _sort_and_renumber_trial_list(self, trials):
        trials.sort(key=lambda trial: (trial.trial_start_global, trial.trial_end_global))
        self._apply_derived_trial_starts(trials)
        for index, trial in enumerate(trials, start=1):
            trial.trial_index = index

    def _sort_and_renumber_trials(self):
        self._sort_and_renumber_trial_list(self.session_data)

    def _next_trial_start(self):
        if not self.session_data:
            return 0.0
        return self.session_data[-1].trial_end_global

    def _draft_trial(self):
        if self.audio_manager.audio_data is None:
            return None

        start = self._next_trial_start()
        end = self.audio_manager.duration
        if end - start <= MIN_TRIAL_DURATION_SECONDS:
            return None

        return TrialData(
            trial_index=len(self.session_data) + 1,
            trial_start_global=start,
            trial_end_global=end,
            beep_timestamp_global=start,
        )

    def _has_draft_trial(self):
        return self._draft_trial() is not None

    def _display_trial_count(self):
        return len(self.session_data) + (1 if self._has_draft_trial() else 0)

    def _is_draft_index(self, index):
        return index == len(self.session_data) and self._has_draft_trial()

    def _display_trial_for_index(self, index):
        if 0 <= index < len(self.session_data):
            return self.session_data[index]
        if self._is_draft_index(index):
            return self._draft_trial()
        return None

    def _current_trial_is_committed(self):
        return 0 <= self.current_trial_index < len(self.session_data)

    def _current_trial_is_draft(self):
        return self._is_draft_index(self.current_trial_index)

    def _draft_range(self):
        draft = self._draft_trial()
        if draft is None:
            return None
        return draft.trial_start_global, draft.trial_end_global

    def _refresh_global_waveform_ranges(self):
        self.global_waveform.set_trials(self.session_data)
        self.global_waveform.set_draft_range(self._draft_range())

    def _update_add_trial_button(self):
        if not hasattr(self, "add_trial_btn"):
            return

        draft = self._draft_trial()
        cursor_position = self._current_cursor_position()
        self.add_trial_btn.setEnabled(
            draft is not None
            and cursor_position - draft.trial_start_global > MIN_TRIAL_DURATION_SECONDS
        )

    def _trial_index_by_identity(self, target):
        for index, trial in enumerate(self.session_data):
            if trial is target:
                return index
        return -1

    def _field_text(self, trial, field):
        if field in SECONDS_COLUMNS:
            return format_seconds(getattr(trial, field))
        if field in RT_COLUMNS:
            return format_optional_ms(getattr(trial, field))
        return str(getattr(trial, field))

    def _populate_trial_table(self, select_index=None):
        self._updating_table = True
        self.trial_table.setRowCount(len(self.session_data))
        resize_table_columns(self.trial_table)

        for row, trial in enumerate(self.session_data):
            for column, field in enumerate(CSV_COLUMNS):
                item = QTableWidgetItem()

                if field in BOOLEAN_COLUMNS:
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setCheckState(
                        Qt.CheckState.Checked if getattr(trial, field) else Qt.CheckState.Unchecked
                    )
                else:
                    item.setText(self._field_text(trial, field))
                    if field in {"trial_index", "trial_start_global"}:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.trial_table.setItem(row, column, item)

        if select_index is not None and 0 <= select_index < len(self.session_data):
            self.trial_table.setCurrentCell(select_index, 0)
        else:
            self.trial_table.clearSelection()

        self._updating_table = False

    def _set_current_trial_actions(self, has_display_trial, is_committed_trial):
        self.zoom_in_btn.setEnabled(has_display_trial)
        self.zoom_out_btn.setEnabled(has_display_trial)
        self.reset_zoom_btn.setEnabled(has_display_trial)
        self.set_beep_btn.setEnabled(is_committed_trial)
        self.set_first_speech_btn.setEnabled(is_committed_trial)
        self.set_main_response_btn.setEnabled(is_committed_trial)
        self.set_both_response_btn.setEnabled(is_committed_trial)
        self.delete_trial_btn.setEnabled(is_committed_trial)

    def _update_navigation_buttons(self):
        display_count = self._display_trial_count()
        has_display_trial = 0 <= self.current_trial_index < display_count
        is_committed_trial = self._current_trial_is_committed()
        self.prev_btn.setEnabled(has_display_trial and self.current_trial_index > 0)
        self.next_btn.setEnabled(
            has_display_trial and self.current_trial_index < display_count - 1
        )
        self._set_current_trial_actions(has_display_trial, is_committed_trial)

    def _clear_current_trial(self):
        self.current_trial_index = -1
        self._trial_detail_selection_range = None
        self.trial_waveform.clear_trial()
        self.trial_info_label.setText("Trial: -- / --")
        self._refresh_play_button_text()
        self._update_navigation_buttons()
        self._update_add_trial_button()

    def _load_trials_for_audio(self):
        self.session_data = []
        self.current_trial_index = -1

        if not self.output_csv_path:
            return "No output CSV path available.", "warning"

        if not self.output_csv_path.exists():
            return "No output CSV found. Create trials manually.", "warning"

        try:
            self.session_data = load_output_csv(self.output_csv_path)
            self._sort_and_renumber_trials()
            self._validate_no_overlaps(self.session_data)
        except Exception as error:
            self.session_data = []
            QMessageBox.critical(
                self,
                "CSV Load Failed",
                f"Could not load output CSV:\n{self.output_csv_path}\n\n{error}",
            )
            return "Output CSV exists but could not be loaded.", "error"

        if not self.session_data:
            return "Output CSV is empty. Create trials manually.", "warning"
        return f"Loaded {len(self.session_data)} trial(s) from output CSV.", "success"

    def _refresh_trial_views(self, select_index=None):
        self._sort_and_renumber_trials()
        self._refresh_global_waveform_ranges()
        self._populate_trial_table(select_index)

        display_count = self._display_trial_count()
        if display_count:
            target_index = select_index if select_index is not None else 0
            target_index = min(max(target_index, 0), display_count - 1)
            self.load_trial(target_index)
        else:
            self._clear_current_trial()

    def _load_audio_file(self, file_path, confirm_discard=True):
        file_path = str(file_path)
        if confirm_discard and not self._confirm_discard_changes():
            return False

        progress = QProgressDialog("Loading audio file...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def update_progress(value, message):
            progress.setValue(value)
            progress.setLabelText(message)
            QApplication.processEvents()

        success = self.audio_manager.load_audio(file_path, update_progress)
        progress.setValue(100)

        if not success:
            self._set_status("Failed to load audio", "error")
            QMessageBox.critical(self, "Error", "Failed to load audio file.\n\nCheck console for details.")
            return False

        self.output_csv_path = default_output_path(file_path)
        self.global_waveform.set_audio_data(
            self.audio_manager.audio_data,
            self.audio_manager.sample_rate,
        )
        self.global_waveform.set_trials([])
        self.global_waveform.set_draft_range(None)
        self.global_waveform.clear_selection()
        self.current_trial_index = -1
        self._trial_detail_selection_range = None
        self.trial_waveform.clear_trial()
        self.play_btn.setEnabled(True)
        self._set_position_label_width()
        self._refresh_play_button_text()
        self._update_add_trial_button()

        file_name = Path(file_path).name
        self.info_text.setText(self._format_audio_info(file_name))
        status_text, status_tone = self._load_trials_for_audio()
        self._refresh_trial_views(0 if self.session_data else None)

        self._set_dirty(False)
        self._set_status(status_text, status_tone)
        return True

    def load_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Audio File",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.m4a *.m4v);;All Files (*.*)",
        )

        if not file_path:
            return
        self._load_audio_file(file_path)

    def on_global_cursor_changed(self, position):
        if self.audio_manager.is_playing:
            self.stop_playback()
        self._set_playback_position(position)

    def on_trial_detail_selection_changed(self, start, end):
        if start < 0 or end < 0:
            self._trial_detail_selection_range = None
            self._refresh_play_button_text()
            return

        start, end = min(start, end), max(start, end)
        if end - start <= EPSILON_SECONDS:
            self._trial_detail_selection_range = None
        else:
            self._trial_detail_selection_range = (start, end)
            if self.audio_manager.is_playing:
                self.stop_playback()
            self._set_playback_position(start)

        self._refresh_play_button_text()

    def add_trial_from_end(self):
        if self.audio_manager.audio_data is None:
            QMessageBox.information(self, "No Audio", "Load an audio file before adding trials.")
            return

        draft = self._draft_trial()
        if draft is None:
            QMessageBox.information(self, "No Remaining Audio", "There is no remaining audio to add as a trial.")
            return

        start = draft.trial_start_global
        end = self._current_cursor_position()
        end = min(max(end, 0.0), self.audio_manager.duration)

        if end - start <= MIN_TRIAL_DURATION_SECONDS:
            QMessageBox.warning(
                self,
                "Invalid Trial End",
                f"Move the global cursor after {format_seconds(start)}s before adding the next trial end.",
            )
            return

        trial = TrialData(
            trial_index=len(self.session_data) + 1,
            trial_start_global=start,
            trial_end_global=end,
            beep_timestamp_global=start,
        )
        trial.validate()

        self.session_data.append(trial)
        self._sort_and_renumber_trials()
        new_index = self._trial_index_by_identity(trial)
        next_index = len(self.session_data) if self._has_draft_trial() else new_index
        self._refresh_trial_views(next_index)
        self.global_waveform.clear_selection()
        self._set_dirty(True)
        self._set_status(
            f"Added trial {trial.trial_index} ending at {format_seconds(end)}s.",
            "success",
        )

    def delete_current_trial(self):
        if not self._current_trial_is_committed():
            return

        removed_index = self.current_trial_index
        trial = self.session_data[removed_index]
        confirm = QMessageBox.question(
            self,
            "Delete Trial",
            f"Delete trial {trial.trial_index} "
            f"({format_seconds(trial.trial_start_global)}s - "
            f"{format_seconds(trial.trial_end_global)}s)?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        del self.session_data[removed_index]
        if self.session_data:
            next_index = min(removed_index, len(self.session_data) - 1)
        else:
            next_index = None
        self._refresh_trial_views(next_index)
        self.global_waveform.clear_selection()
        self._set_dirty(True)
        self._set_status(f"Deleted trial {trial.trial_index}.", "success")

    def _candidate_trials_from_table_edit(self, row, field, item):
        candidate_trials = [replace(trial) for trial in self.session_data]
        candidate = candidate_trials[row]

        if field in {"trial_index", "trial_start_global"}:
            return None, None
        if field in BOOLEAN_COLUMNS:
            setattr(candidate, field, item.checkState() == Qt.CheckState.Checked)
        elif field in SECONDS_COLUMNS:
            setattr(candidate, field, parse_float(item.text(), field))
        elif field in RT_COLUMNS:
            setattr(candidate, field, parse_optional_ms(item.text(), field))
        elif field == "segments_count":
            setattr(candidate, field, parse_nonnegative_int(item.text(), field))
        else:
            raise ValueError(f"Unsupported field: {field}")

        self._sort_and_renumber_trial_list(candidate_trials)
        self._validate_no_overlaps(candidate_trials)
        return candidate_trials, candidate

    def on_table_item_changed(self, item):
        if self._updating_table:
            return

        row = item.row()
        column = item.column()
        if row < 0 or row >= len(self.session_data):
            return

        field = CSV_COLUMNS[column]
        try:
            candidate_trials, target_trial = self._candidate_trials_from_table_edit(row, field, item)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Value", str(error))
            self._populate_trial_table(self.current_trial_index)
            return

        if candidate_trials is None:
            return

        self.session_data = candidate_trials
        new_index = self._trial_index_by_identity(target_trial)
        self._refresh_trial_views(new_index)
        self._set_dirty(True)

    def on_table_current_cell_changed(self, current_row, current_column, previous_row, previous_column):
        if self._updating_table:
            return
        if 0 <= current_row < len(self.session_data):
            self.load_trial(current_row, update_table_selection=False)

    def _apply_beep_timestamp(self, new_beep_timestamp):
        if not self._current_trial_is_committed():
            return False

        trial = self.session_data[self.current_trial_index]

        if abs(new_beep_timestamp - trial.beep_timestamp_global) < EPSILON_SECONDS:
            return False

        trial.beep_timestamp_global = new_beep_timestamp
        trial.validate()

        self._set_playback_position(new_beep_timestamp)
        self._refresh_trial_views(self.current_trial_index)
        self._set_dirty(True)
        return True

    def on_trial_cursor_changed(self, new_cursor_timestamp):
        trial = self._display_trial_for_index(self.current_trial_index)
        if trial is None:
            return

        clamped_timestamp = max(
            trial.trial_start_global,
            min(new_cursor_timestamp, trial.trial_end_global),
        )
        if self.audio_manager.is_playing:
            self.stop_playback()
        self._set_playback_position(clamped_timestamp)
        self._refresh_play_button_text()

    def set_beep_from_playhead(self):
        if not self._current_trial_is_committed():
            return

        trial = self.session_data[self.current_trial_index]
        position = self._current_cursor_position()
        if position < trial.trial_start_global or position > trial.trial_end_global:
            QMessageBox.warning(
                self,
                "Invalid Beep Start",
                "Move the cursor inside the selected trial window before setting beep start.",
            )
            return

        if self._apply_beep_timestamp(position):
            self._set_status(
                f"Set beep start for trial {trial.trial_index} at {format_seconds(position)}s. Press Next to continue.",
                "success",
            )
        else:
            self._set_status(
                f"Beep start for trial {trial.trial_index} is already at {format_seconds(position)}s.",
                "info",
            )

    def _cursor_rt_ms(self):
        if not self._current_trial_is_committed():
            return None

        trial = self.session_data[self.current_trial_index]
        position = self._current_cursor_position()
        if position <= trial.beep_timestamp_global + EPSILON_SECONDS:
            QMessageBox.warning(self, "Invalid RT", "Move the cursor after the beep marker before setting RT.")
            return None
        if position > trial.trial_end_global + EPSILON_SECONDS:
            QMessageBox.warning(self, "Invalid RT", "Move the cursor inside the selected trial window.")
            return None

        return trial, position, round((position - trial.beep_timestamp_global) * 1000.0, MS_DECIMALS)

    def set_rt_from_playhead(self, field):
        rt_data = self._cursor_rt_ms()
        if rt_data is None:
            return

        trial, position, rt_ms = rt_data
        setattr(trial, field, rt_ms)
        trial.validate()
        self._refresh_trial_views(self.current_trial_index)
        self._set_playback_position(position)
        self._set_dirty(True)
        self._set_status(
            f"Set {COLUMN_LABELS[field].lower()} for trial {trial.trial_index} at {format_seconds(position)}s.",
            "success",
        )

    def set_first_and_main_response_from_playhead(self):
        rt_data = self._cursor_rt_ms()
        if rt_data is None:
            return

        trial, position, rt_ms = rt_data
        trial.rt_first_speech_ms = rt_ms
        trial.rt_main_response_ms = rt_ms
        trial.validate()
        self._refresh_trial_views(self.current_trial_index)
        self._set_playback_position(position)
        self._set_dirty(True)
        self._set_status(
            f"Set first speech and main response RTs for trial {trial.trial_index} at {format_seconds(position)}s.",
            "success",
        )

    def _save_output_csv_to_path(self, output_path, update_output_path=False):
        if not self.output_csv_path:
            QMessageBox.information(self, "No Output Path", "Load an audio file before saving.")
            return False
        if not self.session_data:
            QMessageBox.information(self, "No Trials", "Create at least one trial before saving output CSV.")
            return False

        try:
            self._validate_no_overlaps(self.session_data)
            self._sort_and_renumber_trials()
            write_output_csv(output_path, self.session_data)
        except Exception as error:
            QMessageBox.critical(self, "Save Failed", f"Could not save output CSV:\n{error}")
            return False

        if update_output_path:
            self.output_csv_path = output_path
            self._refresh_audio_info()

        self._populate_trial_table(self.current_trial_index)
        self._refresh_global_waveform_ranges()
        self._set_dirty(False)
        self._set_status(f"Saved output CSV: {output_path}", "success")
        QMessageBox.information(self, "Saved", f"Output CSV saved:\n{output_path}")
        return True

    def save_output_csv(self):
        self._save_output_csv_to_path(self.output_csv_path)

    def save_output_csv_as(self):
        if not self.output_csv_path:
            QMessageBox.information(self, "No Output Path", "Load an audio file before saving.")
            return
        default_path = next_edited_output_path(self.output_csv_path)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output CSV As",
            str(default_path),
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not file_path:
            return

        output_path = Path(file_path)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".csv")

        if output_path.exists():
            QMessageBox.warning(
                self,
                "File Exists",
                "Choose a new file name so the existing CSV is not overwritten.",
            )
            return

        self._save_output_csv_to_path(output_path, update_output_path=True)

    def toggle_playback(self):
        if self.audio_manager.is_playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self):
        start_t = self.global_waveform.playback_position
        end_t = None
        detail_selection = self._detail_selection_range()
        trial = self._display_trial_for_index(self.current_trial_index)

        if detail_selection:
            start_t, end_t = detail_selection
        elif trial is not None:
            end_t = trial.trial_end_global
            if start_t < trial.trial_start_global or start_t >= trial.trial_end_global:
                start_t = trial.trial_start_global

        if self.audio_manager.play(start_time=start_t, end_time=end_t):
            self.play_btn.setText("Pause")
            self.global_waveform.set_playing(True)
            self.playback_timer.start()

    def stop_playback(self):
        self.audio_manager.pause()
        self._refresh_play_button_text()
        self.global_waveform.set_playing(False)
        self.trial_waveform.set_playback_position(
            self.trial_waveform.play_position_global,
            auto_pan=False,
            show_label=True,
        )
        self.playback_timer.stop()

    def update_playback(self):
        position = self.audio_manager.get_playback_position()
        playback_end = self.audio_manager.get_playback_end_time()

        if playback_end is not None and position >= playback_end - EPSILON_SECONDS:
            self._set_playback_position(playback_end)
            self.stop_playback()
            return

        if not self.audio_manager.is_playback_active():
            self._set_playback_position(position)
            self.stop_playback()
            return

        self._set_playback_position(position)

        current_trial = self._display_trial_for_index(self.current_trial_index)
        if current_trial is not None:
            if playback_end is None and position > current_trial.trial_end_global:
                self.stop_playback()

    def load_trial(self, index, update_table_selection=True):
        display_count = self._display_trial_count()
        if index < 0 or index >= display_count:
            return

        self.current_trial_index = index
        trial = self._display_trial_for_index(index)
        if trial is None:
            self._clear_current_trial()
            return

        self.trial_waveform.set_trial(
            trial,
            self.audio_manager.audio_data,
            self.audio_manager.sample_rate,
        )
        self._set_playback_position(trial.beep_timestamp_global)
        self._refresh_play_button_text()

        if self._is_draft_index(index):
            self.trial_info_label.setText(f"Draft Trial {index + 1} / {display_count} (not saved)")
        else:
            self.trial_info_label.setText(f"Trial: {index + 1} / {display_count}")

        if update_table_selection:
            self._updating_table = True
            if self._is_draft_index(index):
                self.trial_table.clearSelection()
            else:
                self.trial_table.setCurrentCell(index, 0)
            self._updating_table = False

        self._update_navigation_buttons()

    def _navigate_trial(self, step):
        next_index = self.current_trial_index + step
        if 0 <= next_index < self._display_trial_count():
            self.load_trial(next_index)
            self.start_playback()

    def next_trial(self):
        self._navigate_trial(1)

    def prev_trial(self):
        self._navigate_trial(-1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "trial_table"):
            resize_table_columns(self.trial_table)
