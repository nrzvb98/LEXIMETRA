"""Shared rendering machinery for the global and trial waveform widgets.

Both views draw a cached static layer (waveform + markers) into a pixmap and
paint a cheap dynamic overlay (the moving playhead) on top each frame. They
differ only in the time window they show, so subclasses implement:

    _visible_window()                 -> (start_seconds, end_seconds)
    _cache_key(w, h)                  -> hashable identity of the static layer
    _draw_static_content(p, w, h)     -> waveform + markers (cached)
    _draw_dynamic_overlay(p, w, h)    -> playhead etc. (every frame; optional)
"""

import traceback

import numpy as np
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


class BaseWaveformWidget(QWidget):
    cursor_changed = pyqtSignal(float)
    selection_changed = pyqtSignal(float, float)

    # True when the selection is baked into the cached static layer, so clearing
    # it must invalidate the cache (the trial detail view); False when it is not.
    _selection_in_static_layer = False

    def __init__(self):
        super().__init__()
        self.selection_start = None
        self.selection_end = None
        self._background_cache = None
        self._background_cache_key = None

    # --- coordinate mapping -------------------------------------------------
    def _visible_window(self):
        raise NotImplementedError

    def _time_to_x(self, seconds):
        start, end = self._visible_window()
        duration = max(end - start, 1e-6)
        return int(((seconds - start) / duration) * self.width())

    def _x_to_time(self, x):
        start, end = self._visible_window()
        ratio = min(max(x / max(1, self.width()), 0.0), 1.0)
        return start + ratio * max(end - start, 1e-6)

    # --- selection ----------------------------------------------------------
    def get_selection_range(self):
        if self.selection_start is None or self.selection_end is None:
            return None
        return (
            min(self.selection_start, self.selection_end),
            max(self.selection_start, self.selection_end),
        )

    def clear_selection(self, emit_signal=True):
        self.selection_start = None
        self.selection_end = None
        self._reset_interaction_state()
        if self._selection_in_static_layer:
            self._invalidate_background_cache()
        if emit_signal:
            self.selection_changed.emit(-1.0, -1.0)
        self.update()

    def _reset_interaction_state(self):
        """Reset subclass-specific drag flags when the selection clears."""

    # --- background cache ---------------------------------------------------
    def _invalidate_background_cache(self):
        self._background_cache = None
        self._background_cache_key = None

    def _ensure_background_cache(self, w, h):
        cache_key = self._cache_key(w, h)
        if self._background_cache is not None and self._background_cache_key == cache_key:
            return

        cache = QPixmap(w, h)
        painter = QPainter(cache)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_static_content(painter, w, h)
        finally:
            if painter.isActive():
                painter.end()

        self._background_cache = cache
        self._background_cache_key = cache_key

    def _cache_key(self, w, h):
        raise NotImplementedError

    def _draw_static_content(self, painter, w, h):
        raise NotImplementedError

    def _draw_dynamic_overlay(self, painter, w, h):
        """Painted on top of the cached layer every frame (optional)."""

    # --- painting -----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            w, h = self.width(), self.height()
            if w <= 0 or h <= 0:
                return
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._ensure_background_cache(w, h)
            painter.drawPixmap(0, 0, self._background_cache)
            self._draw_dynamic_overlay(painter, w, h)
        except Exception:
            traceback.print_exc()
        finally:
            if painter.isActive():
                painter.end()

    def _draw_waveform_columns(self, painter, samples, w, h, color, pen_width, amplitude):
        """Draw one vertical min/max line per pixel column across the width."""
        if samples is None or len(samples) == 0:
            return

        painter.setPen(QPen(color, pen_width))
        samples_per_pixel = len(samples) / max(1, w)
        mid_y = h / 2

        for x in range(w):
            start_idx = int(x * samples_per_pixel)
            if start_idx >= len(samples):
                break
            end_idx = min(len(samples), max(start_idx + 1, int((x + 1) * samples_per_pixel)))
            segment = samples[start_idx:end_idx]
            if len(segment) == 0:
                continue
            y_min = int(mid_y - float(np.min(segment)) * h * amplitude)
            y_max = int(mid_y - float(np.max(segment)) * h * amplitude)
            painter.drawLine(x, y_min, x, y_max)
