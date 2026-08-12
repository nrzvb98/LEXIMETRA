from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen, QFont

from hala_rt.data.trial_data import format_seconds
from hala_rt.ui import palette
from hala_rt.widgets.waveform_base import BaseWaveformWidget


MIN_ZOOM_WINDOW_SECONDS = 0.05
AUTO_PAN_MARGIN_RATIO = 0.12


class TrialWaveformWidget(BaseWaveformWidget):
    """
    Visualizes a single trial slice with RT markers and segments.
    """

    # The selection box is baked into the cached static layer.
    _selection_in_static_layer = True

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(250)
        self.trial_data = None
        self.full_audio = None
        self.sample_rate = 1
        self.play_position_global = 0.0
        self.view_start = 0.0
        self.view_end = 1.0
        self.show_playhead_label = True

        self._dragging_cursor = False
        self._dragging_selection = False
        self._drag_anchor_global = None
        self._drag_start_x = None
        self._selection_drag_threshold_px = 5
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Click to move the red cursor. Drag to select a trial detail playback range.")

    def _visible_window(self):
        return self.view_start, self.view_end

    def _reset_interaction_state(self):
        self._drag_anchor_global = None
        self._drag_start_x = None
        self._dragging_selection = False

    def _view_duration(self):
        return max(1e-6, self.view_end - self.view_start)

    def _trial_duration(self):
        if not self.trial_data:
            return self._view_duration()
        return max(
            1e-6,
            self.trial_data.trial_end_global - self.trial_data.trial_start_global,
        )

    def _minimum_zoom_window(self):
        return min(MIN_ZOOM_WINDOW_SECONDS, self._trial_duration())

    def _cursor_nudge_seconds(self):
        visible_pixel_step = self._view_duration() / max(1, self.width())
        sample_step = 1.0 / self.sample_rate if self.sample_rate > 0 else 0.0
        return max(visible_pixel_step, sample_step)

    def _is_zoomed_in(self):
        return bool(self.trial_data) and self._view_duration() < self._trial_duration() - 1e-6

    def _clamp_to_trial(self, global_seconds):
        if not self.trial_data:
            return global_seconds
        return max(
            self.trial_data.trial_start_global,
            min(global_seconds, self.trial_data.trial_end_global),
        )

    def _set_view_window(self, center_global, duration):
        if not self.trial_data:
            return

        trial_start = self.trial_data.trial_start_global
        trial_end = self.trial_data.trial_end_global
        trial_duration = self._trial_duration()
        view_duration = min(
            trial_duration,
            max(float(duration), self._minimum_zoom_window()),
        )

        center = self._clamp_to_trial(center_global)
        start = center - view_duration / 2.0
        end = center + view_duration / 2.0

        if start < trial_start:
            start = trial_start
            end = trial_start + view_duration
        if end > trial_end:
            end = trial_end
            start = trial_end - view_duration

        self.view_start = max(trial_start, start)
        self.view_end = min(trial_end, end)
        self._invalidate_background_cache()
        self.update()

    def _set_view_start(self, start_global, duration):
        if not self.trial_data:
            return

        trial_start = self.trial_data.trial_start_global
        trial_end = self.trial_data.trial_end_global
        trial_duration = self._trial_duration()
        view_duration = min(
            trial_duration,
            max(float(duration), self._minimum_zoom_window()),
        )
        max_start = max(trial_start, trial_end - view_duration)
        start = min(max(start_global, trial_start), max_start)

        new_end = min(trial_end, start + view_duration)
        if abs(start - self.view_start) > 1e-9 or abs(new_end - self.view_end) > 1e-9:
            self.view_start = start
            self.view_end = new_end
            self._invalidate_background_cache()

    def _pan_to_keep_time_visible(self, global_seconds):
        if not self._is_zoomed_in():
            return

        global_seconds = self._clamp_to_trial(global_seconds)
        view_duration = self._view_duration()
        margin = min(view_duration * AUTO_PAN_MARGIN_RATIO, view_duration / 2.0)
        new_start = None

        if global_seconds < self.view_start + margin:
            new_start = global_seconds - margin
        elif global_seconds > self.view_end - margin:
            new_start = global_seconds - view_duration + margin

        if new_start is not None:
            self._set_view_start(new_start, view_duration)

    def _page_view_for_edge_nudge(self, cursor_time, direction):
        if not self._is_zoomed_in():
            return

        trial_start = self.trial_data.trial_start_global
        trial_end = self.trial_data.trial_end_global
        view_duration = self._view_duration()
        overlap = view_duration * AUTO_PAN_MARGIN_RATIO

        moving_past_right_edge = (
            direction > 0
            and cursor_time >= self.view_end - 1e-9
            and self.view_end < trial_end - 1e-9
        )
        moving_past_left_edge = (
            direction < 0
            and cursor_time <= self.view_start + 1e-9
            and self.view_start > trial_start + 1e-9
        )

        if moving_past_right_edge:
            self._set_view_start(self.view_end - overlap, view_duration)
        elif moving_past_left_edge:
            self._set_view_start(self.view_start - view_duration + overlap, view_duration)

    def zoom_in(self):
        if not self.trial_data:
            return
        self._set_view_window(self.play_position_global, self._view_duration() / 2.0)

    def zoom_out(self):
        if not self.trial_data:
            return
        self._set_view_window(self.play_position_global, self._view_duration() * 2.0)

    def reset_zoom(self):
        if not self.trial_data:
            return
        self.view_start = self.trial_data.trial_start_global
        self.view_end = self.trial_data.trial_end_global
        self._invalidate_background_cache()
        self.update()

    def nudge_cursor(self, direction, multiplier=1):
        if not self.trial_data:
            return None

        if self.get_selection_range():
            self.clear_selection()

        direction = 1 if direction >= 0 else -1
        step = self._cursor_nudge_seconds() * max(1, int(multiplier))
        cursor_time = self._clamp_to_trial(
            self.play_position_global + direction * step
        )
        self.play_position_global = cursor_time
        self.show_playhead_label = True
        self._page_view_for_edge_nudge(cursor_time, direction)
        self._pan_to_keep_time_visible(cursor_time)
        self.cursor_changed.emit(cursor_time)
        self.update()
        return cursor_time

    def set_trial(self, trial, full_audio, sr):
        self.trial_data = trial
        self.full_audio = full_audio
        self.sample_rate = sr

        self.view_start = trial.trial_start_global
        self.view_end = trial.trial_end_global
        self.play_position_global = trial.beep_timestamp_global
        self.show_playhead_label = True
        self._invalidate_background_cache()
        self.clear_selection()
        self.update()

    def clear_trial(self):
        self.trial_data = None
        self.full_audio = None
        self._invalidate_background_cache()
        self.clear_selection()
        self.update()

    def set_playback_position(self, global_seconds, auto_pan=True, show_label=True):
        """Update the red playhead line"""
        self.play_position_global = global_seconds
        self.show_playhead_label = show_label
        if auto_pan:
            self._pan_to_keep_time_visible(global_seconds)
        self.update()

    def _set_cursor_from_x(self, x):
        cursor_time = self._clamp_to_trial(self._x_to_time(x))
        self.play_position_global = cursor_time
        self.show_playhead_label = True
        self._pan_to_keep_time_visible(cursor_time)
        self.cursor_changed.emit(cursor_time)
        self.update()

    def _set_selection_from_times(self, start_global, end_global, emit_signal=True):
        start = self._clamp_to_trial(start_global)
        end = self._clamp_to_trial(end_global)
        self.selection_start = start
        self.selection_end = end
        selection_start, selection_end = self.get_selection_range()
        self.play_position_global = selection_start
        self.show_playhead_label = True
        self._invalidate_background_cache()
        if emit_signal:
            self.selection_changed.emit(selection_start, selection_end)
        self.update()

    def _draw_selection(self, painter, width, height):
        selection = self.get_selection_range()
        if not selection:
            return

        start, end = selection
        x1 = self._time_to_x(start)
        x2 = self._time_to_x(end)
        left = max(0, min(x1, x2))
        right = min(width - 1, max(x1, x2))
        rect_width = max(1, right - left)

        painter.fillRect(left, 0, rect_width, height, QColor(*palette.SELECTION_FILL_RGBA))
        painter.setPen(QPen(QColor(palette.PRIMARY), 1, Qt.PenStyle.DashLine))
        painter.drawRect(left, 0, rect_width, height - 1)
        painter.setPen(QColor(palette.PRIMARY_DARK))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._draw_marker_label(
            painter,
            left,
            height - 12,
            f"Selection {format_seconds(start)}s - {format_seconds(end)}s",
            QColor(palette.PRIMARY_DARK),
            width,
        )

    def _draw_beep_marker(self, painter, beep_x, height):
        painter.setPen(QPen(QColor(palette.BEEP_DARK), 2, Qt.PenStyle.DashLine))
        painter.drawLine(beep_x, 0, beep_x, height)
        painter.fillRect(beep_x - 5, 0, 10, 7, QColor(palette.BEEP))
        painter.fillRect(beep_x - 5, max(0, height - 7), 10, 7, QColor(palette.BEEP))

    def _draw_marker_label(self, painter, marker_x, baseline_y, text, color, width):
        metrics = painter.fontMetrics()
        label_width = metrics.horizontalAdvance(text) + 10
        label_height = metrics.height() + 4
        label_x = min(max(marker_x + 6, 6), max(6, width - label_width - 6))
        label_y = max(4, baseline_y - metrics.ascent() - 3)

        painter.fillRect(label_x, label_y, label_width, label_height, QColor(*palette.LABEL_BG_RGBA))
        painter.setPen(QPen(QColor(palette.BORDER), 1))
        painter.drawRect(label_x, label_y, label_width, label_height)
        painter.setPen(color)
        painter.drawText(label_x + 5, baseline_y, text)

    def _cache_key(self, width, height):
        audio_length = len(self.full_audio) if self.full_audio is not None else 0
        selection = self.get_selection_range()
        selection_key = tuple(selection) if selection else None
        if not self.trial_data:
            trial_key = None
        else:
            trial_key = (
                self.trial_data.trial_index,
                self.trial_data.trial_start_global,
                self.trial_data.trial_end_global,
                self.trial_data.beep_timestamp_global,
                self.trial_data.first_speech_global,
                self.trial_data.main_response_global,
            )

        return (
            width,
            height,
            id(self.full_audio),
            audio_length,
            self.sample_rate,
            self.view_start,
            self.view_end,
            trial_key,
            selection_key,
        )

    def _draw_static_content(self, painter, w, h):
        # 1. Background
        painter.fillRect(0, 0, w, h, QColor(palette.SURFACE))
        painter.setPen(QPen(QColor(palette.BORDER), 1))
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.setPen(QPen(QColor(palette.GRID), 1))
        for x in range(0, w, max(1, w // 8)):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, max(1, h // 4)):
            painter.drawLine(0, y, w, y)

        if not self.trial_data or self.full_audio is None:
            painter.setPen(QColor(palette.TEXT_MUTED))
            painter.drawText(w//2 - 50, h//2, "No Trial Loaded")
            return

        # 2. Coordinate Mapping Setup
        t_start = self.view_start
        t_end = self.view_end

        # 3. Draw trial boundary range
        painter.setPen(QColor(palette.TEXT_SLATE))
        painter.setFont(QFont("Arial", 12))
        painter.drawText(
            8,
            h - 10,
            f"{format_seconds(t_start)}s - {format_seconds(self.trial_data.trial_end_global)}s",
        )

        # 4. Draw Waveform (Sliced) — zoom Y slightly via the amplitude factor.
        start_sample = max(0, int(t_start * self.sample_rate))
        end_sample = min(len(self.full_audio), int(t_end * self.sample_rate))
        chunk = self.full_audio[start_sample:end_sample]
        self._draw_waveform_columns(
            painter, chunk, w, h,
            color=QColor(palette.TEXT_SLATE), pen_width=1, amplitude=0.8,
        )

        self._draw_selection(painter, w, h)

        # 5. Draw Markers (Lines)
        # First speech RT (Green)
        first_speech = self.trial_data.first_speech_global
        if first_speech is not None:
            x_phys = self._time_to_x(first_speech)
            painter.setPen(QPen(QColor(palette.FIRST_SPEECH), 2, Qt.PenStyle.DashLine))
            painter.drawLine(x_phys, 0, x_phys, h)
            painter.setPen(QColor(palette.FIRST_SPEECH))
            painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            self._draw_marker_label(painter, x_phys, 42, "First speech", QColor(palette.FIRST_SPEECH), w)

        # Main response RT (Purple)
        main_response = self.trial_data.main_response_global
        if main_response is not None:
            x_sem = self._time_to_x(main_response)
            painter.setPen(QPen(QColor(palette.MAIN_RESPONSE), 2, Qt.PenStyle.DashLine))
            painter.drawLine(x_sem, 0, x_sem, h)
            painter.setPen(QColor(palette.MAIN_RESPONSE))
            painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            self._draw_marker_label(painter, x_sem, 62, "Main response", QColor(palette.MAIN_RESPONSE), w)

        # 6. Draw committed beep marker
        beep_x = self._time_to_x(self.trial_data.beep_timestamp_global)
        self._draw_beep_marker(painter, beep_x, h)
        painter.setPen(QColor(palette.BEEP_DARK))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._draw_marker_label(painter, beep_x, 22, "Beep start", QColor(palette.BEEP_DARK), w)

    def _draw_dynamic_overlay(self, painter, w, h):
        if not self.trial_data:
            return

        if self.view_start <= self.play_position_global <= self.view_end:
            x_play = self._time_to_x(self.play_position_global)
            painter.setPen(QPen(QColor(palette.PLAYHEAD), 2))
            painter.drawLine(x_play, 0, x_play, h)

            if self.show_playhead_label:
                painter.setPen(QColor(palette.PLAYHEAD))
                painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
                cursor_label = f"Cursor {format_seconds(self.play_position_global)}s"
                self._draw_marker_label(painter, x_play, 82, cursor_label, QColor(palette.PLAYHEAD), w)

    def mousePressEvent(self, event):
        if self.trial_data and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.clear_selection()
            self._dragging_cursor = True
            self._dragging_selection = False
            self._drag_start_x = event.position().x()
            self._drag_anchor_global = self._clamp_to_trial(self._x_to_time(self._drag_start_x))
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_cursor_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.trial_data:
            super().mouseMoveEvent(event)
            return

        if self._dragging_cursor:
            current_x = event.position().x()
            if (
                self._drag_start_x is not None
                and abs(current_x - self._drag_start_x) >= self._selection_drag_threshold_px
            ):
                self._dragging_selection = True

            if self._dragging_selection and self._drag_anchor_global is not None:
                self._set_selection_from_times(self._drag_anchor_global, self._x_to_time(current_x))
            else:
                self._set_cursor_from_x(current_x)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_cursor and event.button() == Qt.MouseButton.LeftButton:
            if self._dragging_selection and self._drag_anchor_global is not None:
                self._set_selection_from_times(
                    self._drag_anchor_global,
                    self._x_to_time(event.position().x()),
                )
            self._dragging_cursor = False
            self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._dragging_cursor:
            self.unsetCursor()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if self.trial_data and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            direction = -1 if event.key() == Qt.Key.Key_Left else 1
            multiplier = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.nudge_cursor(direction, multiplier)
            event.accept()
            return
        super().keyPressEvent(event)
