"""Centralized design tokens for the HALA RT interface.

Solid colors are plain hex strings so they drop straight into both Qt style
sheets (`f"color: {palette.TEXT}"`) and painters (`QColor(palette.TEXT)`).
Translucent fills are exposed as RGBA tuples; expand them at the call site
with `QColor(*palette.TRIAL_FILL_RGBA)`.
"""

# --- Neutrals (slate scale) ------------------------------------------------
BG = "#f8fafc"             # app / canvas background
SURFACE = "#ffffff"        # cards, waveform detail background
SURFACE_MUTED = "#f1f5f9"  # header sections, button hover
BORDER = "#dbe3ef"         # default panel / table border
BORDER_STRONG = "#cbd5e1"  # global waveform frame, center line
BORDER_MUTED = "#e2e8f0"   # gridlines, disabled borders
GRID = "#eef2f7"           # trial detail gridlines

TEXT = "#0f172a"           # primary text
TEXT_BODY = "#334155"      # body copy
TEXT_SLATE = "#475569"     # trial-detail waveform + boundary labels
TEXT_MUTED = "#64748b"     # subtitles, placeholders
TEXT_DISABLED = "#94a3b8"  # disabled controls

# --- Primary accent (blue) -------------------------------------------------
PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
SELECTION_BG = "#dbeafe"   # table row selection

# --- Playhead --------------------------------------------------------------
PLAYHEAD = "#dc2626"

# --- Trial markers ---------------------------------------------------------
BEEP = "#d97706"
BEEP_DARK = "#b45309"
TRIAL_OUTLINE = "#7dd3fc"
FIRST_SPEECH = "#047857"
FIRST_SPEECH_DARK = "#065f46"
MAIN_RESPONSE = "#4f46e5"
MAIN_RESPONSE_DARK = "#4338ca"
BOTH_RESPONSE = "#0f766e"
BOTH_RESPONSE_DARK = "#0f5f59"

# --- Danger (delete control) ----------------------------------------------
DANGER = "#b91c1c"
DANGER_BG = "#fef2f2"
DANGER_BORDER = "#fca5a5"
DANGER_BORDER_HOVER = "#f87171"

# --- Translucent fills (RGBA) ---------------------------------------------
TRIAL_FILL_RGBA = (14, 165, 233, 22)
DRAFT_FILL_RGBA = (217, 119, 6, 26)
SELECTION_FILL_RGBA = (37, 99, 235, 38)
LABEL_BG_RGBA = (255, 255, 255, 235)

# --- Status banner tones: (foreground, background, border) ----------------
STATUS_TONES = {
    "info": (PRIMARY_DARK, "#eff6ff", "#bfdbfe"),
    "success": (FIRST_SPEECH, "#ecfdf5", "#a7f3d0"),
    "warning": ("#92400e", "#fffbeb", "#fde68a"),
    "error": (DANGER, DANGER_BG, "#fecaca"),
}
