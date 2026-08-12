from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPen

from hala_rt.ui import palette
from hala_rt.widgets.waveform_base import BaseWaveformWidget


class SimpleWaveformWidget(BaseWaveformWidget):
    """Global timeline waveform with committed trials, a draft range, and the
    playback position."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(200)

        self.audio_data = None
        self.sample_rate = 1
        self.duration = 1.0
        self.playback_position = 0.0
        self.is_playing = False
        self.trials = []
        self.draft_range = None
        self._selection_anchor = None
        self._dragging_cursor = False
        self.setToolTip("Click or drag the global timeline to place the next trial end cursor.")

    def _visible_window(self):
        return 0.0, self.duration

    def _reset_interaction_state(self):
        self._selection_anchor = None
        self._dragging_cursor = False

    def set_audio_data(self, audio_data, sample_rate):
        """Set audio data for visualization"""
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.duration = len(audio_data) / sample_rate if len(audio_data) > 0 else 1.0
        self.playback_position = min(max(self.playback_position, 0.0), self.duration)
        self.clear_selection(emit_signal=False)
        self._invalidate_background_cache()
        self.update()

    def set_trials(self, trials):
        self.trials = trials
        self._invalidate_background_cache()
        self.update()

    def set_draft_range(self, draft_range):
        self.draft_range = draft_range
        self._invalidate_background_cache()
        self.update()

    def set_playback_position(self, position):
        """Update playback position in seconds"""
        self.playback_position = min(max(float(position), 0.0), self.duration)
        self.update()

    def set_playing(self, is_playing):
        """Set playing state"""
        self.is_playing = is_playing
        self.update()

    def _set_cursor_from_x(self, x):
        selected_time = self._x_to_time(x)
        self.playback_position = selected_time
        self.cursor_changed.emit(selected_time)
        self.update()

    def _draw_time_range(self, painter, start, end, fill, outline, height, dashed=False):
        x1 = self._time_to_x(start)
        x2 = self._time_to_x(end)
        left = min(x1, x2)
        right = max(x1, x2)
        width = max(1, right - left)

        painter.fillRect(left, 0, width, height, fill)
        pen_style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
        painter.setPen(QPen(outline, 1, pen_style))
        painter.drawRect(left, 0, width, height - 1)

    def _cache_key(self, width, height):
        audio_length = len(self.audio_data) if self.audio_data is not None else 0
        trials_key = tuple(
            (trial.trial_start_global, trial.trial_end_global)
            for trial in self.trials
        )
        draft_key = tuple(self.draft_range) if self.draft_range else None
        return (
            width,
            height,
            id(self.audio_data),
            audio_length,
            self.sample_rate,
            self.duration,
            trials_key,
            draft_key,
        )

    def _draw_static_content(self, painter, width, height):
        painter.fillRect(0, 0, width, height, QColor(palette.BG))
        painter.setPen(QPen(QColor(palette.BORDER_STRONG), 1))
        painter.drawRect(0, 0, width - 1, height - 1)

        for trial in self.trials:
            self._draw_time_range(
                painter,
                trial.trial_start_global,
                trial.trial_end_global,
                QColor(*palette.TRIAL_FILL_RGBA),
                QColor(palette.TRIAL_OUTLINE),
                height,
            )

        if self.draft_range:
            start, end = self.draft_range
            self._draw_time_range(
                painter,
                start,
                end,
                QColor(*palette.DRAFT_FILL_RGBA),
                QColor(palette.BEEP),
                height,
                dashed=True,
            )

        if self.audio_data is None or len(self.audio_data) == 0:
            painter.setPen(QColor(palette.TEXT_MUTED))
            painter.setFont(QFont('Arial', 16))
            painter.drawText(width // 2 - 100, height // 2, "No audio loaded")
            return

        self._draw_waveform_columns(
            painter, self.audio_data, width, height,
            color=QColor(palette.PRIMARY), pen_width=2, amplitude=0.4,
        )

        # Center line
        painter.setPen(QPen(QColor(palette.BORDER_STRONG), 1))
        painter.drawLine(0, height // 2, width, height // 2)

    def _draw_dynamic_overlay(self, painter, width, height):
        if self.audio_data is None or len(self.audio_data) == 0:
            return

        if self.playback_position >= 0:
            pos_x = self._time_to_x(self.playback_position)
            painter.setPen(QPen(QColor(palette.PLAYHEAD), 3))
            painter.drawLine(pos_x, 0, pos_x, height)

            if not self.is_playing:
                painter.setPen(QColor(palette.PLAYHEAD))
                painter.setFont(QFont('Arial', 12, QFont.Weight.Bold))
                painter.drawText(pos_x + 5, 20, f"{self.playback_position:.2f}s")

    def mousePressEvent(self, event):
        if self.audio_data is None or len(self.audio_data) == 0:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.clear_selection(emit_signal=False)
            self._dragging_cursor = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_cursor_from_x(event.position().x())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_cursor:
            self._set_cursor_from_x(event.position().x())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_cursor and event.button() == Qt.MouseButton.LeftButton:
            self._dragging_cursor = False
            self.unsetCursor()
            self._set_cursor_from_x(event.position().x())
            event.accept()
            return

        super().mouseReleaseEvent(event)
