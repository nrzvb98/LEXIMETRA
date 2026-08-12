"""Qt style sheets for the HALA RT interface, composed from palette tokens.

Keeping the QSS here (rather than inline in the widget tree) means the main
window builds structure, not strings, and every color resolves to one token in
``palette``.
"""

from string import Template

from hala_rt.ui import palette


APP_STYLESHEET = Template("""
    QMainWindow, QWidget {
        background-color: $bg;
        color: $text;
        font-family: Arial;
        font-size: 15px;
    }
    QScrollArea {
        border: none;
        background-color: $bg;
    }
    QFrame {
        background-color: $surface;
        border: 1px solid $border;
        border-radius: 6px;
        padding: 12px;
    }
    QPushButton {
        background-color: $surface;
        color: $text;
        border: 1px solid $border_strong;
        padding: 10px 20px;
        border-radius: 4px;
        font-size: 15px;
    }
    QPushButton:hover {
        background-color: $surface_muted;
        border-color: $disabled;
    }
    QPushButton:disabled {
        color: $disabled;
        background-color: $bg;
        border-color: $border_muted;
    }
    QLabel {
        background-color: transparent;
        border: none;
    }
    QTableWidget {
        background-color: $surface;
        alternate-background-color: $bg;
        border: 1px solid $border;
        gridline-color: $border_muted;
        selection-background-color: $selection_bg;
        selection-color: $text;
    }
    QHeaderView::section {
        background-color: $surface_muted;
        color: $text_body;
        border: 1px solid $border;
        padding: 0px 6px;
        font-weight: bold;
        font-size: 14px;
        min-height: 0px;
        height: 40px;
    }
""").substitute(
    bg=palette.BG,
    text=palette.TEXT,
    surface=palette.SURFACE,
    surface_muted=palette.SURFACE_MUTED,
    border=palette.BORDER,
    border_strong=palette.BORDER_STRONG,
    border_muted=palette.BORDER_MUTED,
    disabled=palette.TEXT_DISABLED,
    selection_bg=palette.SELECTION_BG,
    text_body=palette.TEXT_BODY,
)


def load_button_qss():
    return (
        f"background-color: {palette.PRIMARY}; color: white; "
        f"border-color: {palette.PRIMARY}; font-size: 16px;"
    )


def delete_button_qss():
    return (
        f"QPushButton {{ background-color: {palette.SURFACE}; color: {palette.DANGER};"
        f" border: 1px solid {palette.DANGER_BORDER}; padding: 10px 20px; border-radius: 4px;"
        f" font-size: 16px; }}"
        f"QPushButton:hover {{ background-color: {palette.DANGER_BG};"
        f" border-color: {palette.DANGER_BORDER_HOVER}; }}"
        f"QPushButton:disabled {{ color: {palette.TEXT_DISABLED};"
        f" background-color: {palette.BG}; border-color: {palette.BORDER_MUTED}; }}"
    )


def status_label_qss(tone):
    color, background, border = palette.STATUS_TONES.get(tone, palette.STATUS_TONES["info"])
    return (
        f"color: {color}; font-size: 15px; padding: 8px; "
        f"background-color: {background}; border: 1px solid {border}; border-radius: 4px;"
    )


def style_marker_button(button, color, hover_color):
    """Apply the colored, fixed-size styling shared by the four RT marker buttons."""
    button.setMinimumWidth(178)
    button.setFixedHeight(46)
    button.setStyleSheet(f"""
        QPushButton {{
            background-color: {color};
            color: white;
            border: 1px solid {color};
            border-radius: 4px;
            font-size: 16px;
            font-weight: 600;
            padding: 10px 16px;
        }}
        QPushButton:hover {{
            background-color: {hover_color};
            border-color: {hover_color};
        }}
        QPushButton:disabled {{
            color: {palette.TEXT_DISABLED};
            background-color: {palette.BG};
            border-color: {palette.BORDER_MUTED};
        }}
    """)
