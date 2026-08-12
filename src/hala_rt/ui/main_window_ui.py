"""Widget-tree construction for :class:`HALAMainWindow`.

``build_ui(window)`` assembles the layout and assigns the widgets the
controller drives (``window.play_btn``, ``window.trial_table``, ...) onto the
window, the way a generated ``setupUi`` would. All styling resolves through
``theme`` / ``palette``; the controller keeps the behavior.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from hala_rt.data.trial_data import CSV_COLUMNS
from hala_rt.ui import palette, theme
from hala_rt.ui.table_columns import COLUMN_HELP, COLUMN_LABELS, COLUMN_WIDTHS
from hala_rt.widgets.simple_waveform import SimpleWaveformWidget
from hala_rt.widgets.trial_viz import TrialWaveformWidget


def build_ui(window):
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    window.setCentralWidget(scroll_area)

    content_widget = QWidget()
    scroll_area.setWidget(content_widget)
    layout = QVBoxLayout(content_widget)

    _build_header(layout)
    _build_status(window, layout)
    _build_controls(window, layout)
    _build_global_timeline(window, layout)
    _build_navigation(window, layout)
    _build_trial_detail(window, layout)
    _build_trial_table(window, layout)
    _build_session_info(window, layout)
    _build_shortcuts(layout)

    window.setStyleSheet(theme.APP_STYLESHEET)


def _build_header(layout):
    header_layout = QVBoxLayout()
    header_layout.setSpacing(2)
    header_layout.setContentsMargins(0, 0, 0, 0)

    header = QLabel("HALA RT Verification Interface")
    header_font = QFont("Arial", 26, QFont.Weight.Bold)
    header_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.5)
    header.setFont(header_font)
    header.setStyleSheet(f"color: {palette.TEXT};")
    header_layout.addWidget(header)

    subtitle = QLabel("Manual trial-end cutting and CSV output editor")
    subtitle.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 15px; font-weight: normal;")
    subtitle.setContentsMargins(0, 0, 0, 0)
    header_layout.addWidget(subtitle)

    layout.addLayout(header_layout)


def _build_status(window, layout):
    window.status_label = QLabel("No audio loaded")
    window._set_status("No audio loaded", "info")
    layout.addWidget(window.status_label)


def _build_controls(window, layout):
    controls_layout = QHBoxLayout()

    load_btn = QPushButton("Load Audio File")
    load_btn.clicked.connect(window.load_audio)
    load_btn.setStyleSheet(theme.load_button_qss())
    controls_layout.addWidget(load_btn)

    window.play_btn = QPushButton("Play")
    window.play_btn.clicked.connect(window.toggle_playback)
    window.play_btn.setEnabled(False)
    window.play_btn.setStyleSheet("font-size: 16px;")
    # Fixed width so cycling the label between "Play"/"Play Selection"/"Pause"
    # doesn't resize the button and shift the surrounding controls.
    window.play_btn.setFixedWidth(150)
    controls_layout.addWidget(window.play_btn)

    window.add_trial_btn = QPushButton("Add Trial End")
    window.add_trial_btn.clicked.connect(window.add_trial_from_end)
    window.add_trial_btn.setEnabled(False)
    window.add_trial_btn.setStyleSheet("font-size: 16px;")
    controls_layout.addWidget(window.add_trial_btn)

    window.delete_trial_btn = QPushButton("Delete Trial")
    window.delete_trial_btn.clicked.connect(window.delete_current_trial)
    window.delete_trial_btn.setEnabled(False)
    window.delete_trial_btn.setToolTip("Delete the currently selected trial.")
    window.delete_trial_btn.setStyleSheet(theme.delete_button_qss())
    controls_layout.addWidget(window.delete_trial_btn)

    window.save_btn = QPushButton("Save Output CSV")
    window.save_btn.clicked.connect(window.save_output_csv)
    window.save_btn.setEnabled(False)
    window.save_btn.setStyleSheet("font-size: 16px;")
    controls_layout.addWidget(window.save_btn)

    window.save_as_btn = QPushButton("Save Output CSV As...")
    window.save_as_btn.clicked.connect(window.save_output_csv_as)
    window.save_as_btn.setEnabled(False)
    window.save_as_btn.setStyleSheet("font-size: 16px;")
    controls_layout.addWidget(window.save_as_btn)

    window.position_label = QLabel("Position: 0.00s / 0.00s")
    window.position_label.setStyleSheet(
        f"color: {palette.FIRST_SPEECH}; font-family: monospace; font-size: 15px;"
    )
    window.position_label.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    window._set_position_label_width()
    controls_layout.addWidget(window.position_label)

    controls_layout.addStretch()
    layout.addLayout(controls_layout)


def _build_global_timeline(window, layout):
    global_frame = QFrame()
    global_layout = QVBoxLayout(global_frame)
    global_layout.setContentsMargins(0, 0, 0, 0)

    global_label = QLabel("Global Timeline")
    global_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
    global_layout.addWidget(global_label)

    window.global_waveform = SimpleWaveformWidget()
    window.global_waveform.setFixedHeight(125)
    window.global_waveform.cursor_changed.connect(window.on_global_cursor_changed)
    global_layout.addWidget(window.global_waveform)

    layout.addWidget(global_frame)


def _build_navigation(window, layout):
    nav_layout = QHBoxLayout()

    window.prev_btn = QPushButton("Previous")
    window.prev_btn.clicked.connect(window.prev_trial)
    window.prev_btn.setEnabled(False)
    nav_layout.addWidget(window.prev_btn)

    window.trial_info_label = QLabel("Trial: -- / --")
    window.trial_info_label.setStyleSheet("font-weight: bold; font-size: 16px;")
    window.trial_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    nav_layout.addWidget(window.trial_info_label)

    window.next_btn = QPushButton("Next")
    window.next_btn.clicked.connect(window.next_trial)
    window.next_btn.setEnabled(False)
    nav_layout.addWidget(window.next_btn)

    layout.addLayout(nav_layout)


def _build_trial_detail(window, layout):
    trial_frame = QFrame()
    trial_layout = QVBoxLayout(trial_frame)

    window.trial_waveform = TrialWaveformWidget()
    window.trial_waveform.cursor_changed.connect(window.on_trial_cursor_changed)
    window.trial_waveform.selection_changed.connect(window.on_trial_detail_selection_changed)

    trial_header_layout = QHBoxLayout()

    trial_label = QLabel("Trial Detail View")
    trial_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    trial_header_layout.addWidget(trial_label)
    trial_header_layout.addStretch()

    window.zoom_in_btn = QPushButton("Zoom In")
    window.zoom_in_btn.clicked.connect(window.zoom_trial_detail_in)
    window.zoom_in_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.zoom_in_btn.setEnabled(False)
    window.zoom_in_btn.setToolTip("Zoom in around the red cursor.")
    trial_header_layout.addWidget(window.zoom_in_btn)

    window.zoom_out_btn = QPushButton("Zoom Out")
    window.zoom_out_btn.clicked.connect(window.zoom_trial_detail_out)
    window.zoom_out_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.zoom_out_btn.setEnabled(False)
    window.zoom_out_btn.setToolTip("Zoom out around the red cursor.")
    trial_header_layout.addWidget(window.zoom_out_btn)

    window.reset_zoom_btn = QPushButton("Reset Zoom")
    window.reset_zoom_btn.clicked.connect(window.reset_trial_detail_zoom)
    window.reset_zoom_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.reset_zoom_btn.setEnabled(False)
    window.reset_zoom_btn.setToolTip("Show the full selected trial window.")
    trial_header_layout.addWidget(window.reset_zoom_btn)

    trial_layout.addLayout(trial_header_layout)
    trial_layout.addWidget(window.trial_waveform)

    marker_controls = QHBoxLayout()
    marker_controls.setContentsMargins(0, 8, 0, 0)
    marker_controls.setSpacing(12)

    window.set_beep_btn = QPushButton("Set Beep Start")
    window.set_beep_btn.clicked.connect(window.set_beep_from_playhead)
    window.set_beep_btn.setEnabled(False)
    window.set_beep_btn.setToolTip("Set the beep marker to the red cursor position.")
    theme.style_marker_button(window.set_beep_btn, palette.BEEP, palette.BEEP_DARK)
    marker_controls.addWidget(window.set_beep_btn)

    window.set_first_speech_btn = QPushButton("Set First Speech")
    window.set_first_speech_btn.clicked.connect(lambda: window.set_rt_from_playhead("rt_first_speech_ms"))
    window.set_first_speech_btn.setEnabled(False)
    window.set_first_speech_btn.setToolTip("Set first speech RT from the red cursor position.")
    theme.style_marker_button(window.set_first_speech_btn, palette.FIRST_SPEECH, palette.FIRST_SPEECH_DARK)
    marker_controls.addWidget(window.set_first_speech_btn)

    window.set_main_response_btn = QPushButton("Set Main Response")
    window.set_main_response_btn.clicked.connect(lambda: window.set_rt_from_playhead("rt_main_response_ms"))
    window.set_main_response_btn.setEnabled(False)
    window.set_main_response_btn.setToolTip("Set main response RT from the red cursor position.")
    theme.style_marker_button(window.set_main_response_btn, palette.MAIN_RESPONSE, palette.MAIN_RESPONSE_DARK)
    marker_controls.addWidget(window.set_main_response_btn)

    window.set_both_response_btn = QPushButton("Set First + Main")
    window.set_both_response_btn.clicked.connect(window.set_first_and_main_response_from_playhead)
    window.set_both_response_btn.setEnabled(False)
    window.set_both_response_btn.setToolTip(
        "Set first speech and main response RT to the same red cursor position."
    )
    theme.style_marker_button(window.set_both_response_btn, palette.BOTH_RESPONSE, palette.BOTH_RESPONSE_DARK)
    marker_controls.addWidget(window.set_both_response_btn)
    marker_controls.addStretch()
    trial_layout.addLayout(marker_controls)

    layout.addWidget(trial_frame)


def _build_trial_table(window, layout):
    table_frame = QFrame()
    table_layout = QVBoxLayout(table_frame)
    table_layout.setContentsMargins(0, 0, 0, 0)

    table_title = QLabel("Trial Output Editor")
    table_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    table_layout.addWidget(table_title)

    window.trial_table = QTableWidget()
    window.trial_table.setColumnCount(len(CSV_COLUMNS))
    window.trial_table.setHorizontalHeaderLabels([COLUMN_LABELS[column] for column in CSV_COLUMNS])
    for column, field in enumerate(CSV_COLUMNS):
        header_item = window.trial_table.horizontalHeaderItem(column)
        if header_item:
            header_item.setToolTip(COLUMN_HELP[field])
        window.trial_table.setColumnWidth(column, COLUMN_WIDTHS[field])
    window.trial_table.setAlternatingRowColors(True)
    window.trial_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    window.trial_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    window.trial_table.setWordWrap(False)
    window.trial_table.setShowGrid(True)
    window.trial_table.horizontalHeader().setVisible(True)
    window.trial_table.horizontalHeader().setFixedHeight(44)
    window.trial_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    window.trial_table.horizontalHeader().setHighlightSections(False)
    window.trial_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    window.trial_table.horizontalHeader().setStretchLastSection(False)
    window.trial_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    window.trial_table.verticalHeader().setVisible(False)
    window.trial_table.verticalHeader().setDefaultSectionSize(36)
    window.trial_table.setMinimumHeight(240)
    window.trial_table.itemChanged.connect(window.on_table_item_changed)
    window.trial_table.currentCellChanged.connect(window.on_table_current_cell_changed)
    table_layout.addWidget(window.trial_table)

    layout.addWidget(table_frame)


def _build_session_info(window, layout):
    info_frame = QFrame()
    info_frame.setFrameStyle(QFrame.Shape.StyledPanel)
    info_layout = QVBoxLayout(info_frame)

    info_title = QLabel("Session Information")
    info_title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    info_layout.addWidget(info_title)

    window.info_text = QLabel("Load an audio file to see details")
    window.info_text.setStyleSheet(f"color: {palette.TEXT_BODY}; font-family: monospace;")
    window.info_text.setWordWrap(True)
    info_layout.addWidget(window.info_text)

    layout.addWidget(info_frame)


def _build_shortcuts(layout):
    shortcuts_label = QLabel(
        "Keyboard: [Space] Play/Pause. [Left]/[Right] move the trial cursor."
    )
    shortcuts_label.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 13px; padding: 4px;")
    layout.addWidget(shortcuts_label)
