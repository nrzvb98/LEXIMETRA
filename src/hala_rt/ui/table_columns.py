"""Presentation metadata and width math for the trial output table.

The CSV field order lives in ``trial_data.CSV_COLUMNS``; this module maps those
fields to their human labels, tooltips, and preferred widths, and fits them to
the available viewport.
"""

from PyQt6.QtGui import QFont, QFontMetrics

from hala_rt.data.trial_data import CSV_COLUMNS


COLUMN_LABELS = {
    "trial_index": "Trial",
    "trial_start_global": "Trial Start",
    "trial_end_global": "Trial End",
    "beep_timestamp_global": "Beep Start",
    "rt_first_speech_ms": "First Speech RT",
    "rt_main_response_ms": "Main Response RT",
    "prefiller_present": "Prefiller",
    "flag_anticipatory": "Anticipatory",
    "flag_timeout": "Timeout",
    "segments_count": "Segments",
}

COLUMN_HELP = {
    "trial_index": "CSV: trial_index. Sequential trial number.",
    "trial_start_global": "CSV: trial_start_global. Derived from the previous trial end.",
    "trial_end_global": "CSV: trial_end_global. End of the trial window, set from the global cursor.",
    "beep_timestamp_global": "CSV: beep_timestamp_global. Beep start timestamp in seconds.",
    "rt_first_speech_ms": "CSV: rt_first_speech_ms. Milliseconds from beep start to first speech sound.",
    "rt_main_response_ms": "CSV: rt_main_response_ms. Milliseconds from beep start to main response word.",
    "prefiller_present": "CSV: prefiller_present. Checked when a filler such as Umm is present.",
    "flag_anticipatory": "CSV: flag_anticipatory. Checked when response is too fast.",
    "flag_timeout": "CSV: flag_timeout. Checked when no response occurs in the trial window.",
    "segments_count": "CSV: segments_count. Number of distinct speech bursts.",
}

COLUMN_WIDTHS = {
    "trial_index": 72,
    "trial_start_global": 140,
    "trial_end_global": 140,
    "beep_timestamp_global": 140,
    "rt_first_speech_ms": 155,
    "rt_main_response_ms": 180,
    "prefiller_present": 105,
    "flag_anticipatory": 135,
    "flag_timeout": 105,
    "segments_count": 115,
}


def resize_table_columns(table):
    """Fit the columns to the viewport, never clipping a (bold) header label."""
    available_width = table.viewport().width()
    if available_width <= 0:
        available_width = table.width()
    if available_width <= 0:
        return

    base_widths = [COLUMN_WIDTHS[field] for field in CSV_COLUMNS]

    # Each column must be at least wide enough for its bold header label. The
    # font here matches the QHeaderView::section rule (Arial, 14px, bold).
    header_font = QFont("Arial")
    header_font.setBold(True)
    header_font.setPixelSize(14)
    metrics = QFontMetrics(header_font)
    header = table.horizontalHeader()
    header_padding = 16  # css padding (6+6) + borders + small safety margin
    # Take the larger of our own text measurement and Qt's style-aware section
    # size hint, so a header label is never clipped regardless of platform font.
    min_widths = [
        max(
            metrics.horizontalAdvance(COLUMN_LABELS[field]) + header_padding,
            header.sectionSizeHint(column) + 8,
        )
        for column, field in enumerate(CSV_COLUMNS)
    ]
    # The last section abuts the vertical scrollbar gutter, where Qt clips the
    # centered header text by a character; give it extra breathing room.
    min_widths[-1] += 24

    widths = list(min_widths)
    slack = available_width - sum(min_widths)
    if slack > 0:
        # Room to spare: hand out the extra space proportionally by base weight,
        # using cumulative rounding so the columns sum to exactly available_width.
        base_total = sum(base_widths)
        previous_edge = 0
        cumulative_base = 0
        for column, base_width in enumerate(base_widths):
            cumulative_base += base_width
            edge = round(slack * cumulative_base / base_total)
            widths[column] += edge - previous_edge
            previous_edge = edge
    # When slack <= 0 the viewport is too narrow to show every header at its
    # minimum width. Rather than scaling the columns down (which clips the header
    # labels), keep them at their minimums and let the table scroll horizontally.

    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
