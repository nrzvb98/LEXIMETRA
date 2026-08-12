# HALA RT Verification Interface

A desktop tool for **manual trial-end cutting, playback, and reaction-time (RT) verification** of speech-response audio sessions. Load a single session recording, mark trial boundaries and beep/speech events by ear and by eye, and export a clean per-trial CSV — or load an existing output CSV and correct it by hand.

Built with [PyQt6](https://pypi.org/project/PyQt6/).

---

## Features

- **Load a full session** as WAV, MP3, FLAC, or M4A and scrub it on a global timeline.
- **Cut trials manually** — drag the global cursor to a trial boundary and click *Add Trial End*. Each new trial starts where the previous one ended.
- **Per-trial detail view** with zoom, so you can place markers precisely:
  - **Beep Start** — the trial's onset cue.
  - **First Speech** — first sound after the beep (including fillers like *"umm"*).
  - **Main Response** — the main response word, skipping fillers.
- **Reaction times computed automatically** from the beep to each marker, in milliseconds.
- **Editable output table** — every column is hand-editable, with validation.
- **CSV export** following the [output schema](docs/output_schema.md), plus *Save As* for edited copies.
- Playback with selection looping, keyboard scrubbing, and waveform visualization.

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/download.html) on your `PATH` (required for **M4A** support in source/dev mode)

Install FFmpeg:

| Platform | Command |
| --- | --- |
| macOS | `brew install ffmpeg` |
| Linux | `sudo apt-get install ffmpeg` |
| Windows | [Download from ffmpeg.org](https://ffmpeg.org/download.html) |

## Installation

```bash
python -m pip install -e .
```

The app degrades gracefully if optional audio backends are missing — it reports
which dependencies are absent on startup and continues with limited functionality.

## Build a macOS App

On macOS, install the packaging extra and run the build script:

```bash
python -m pip install -e ".[packaging]"
packaging/macos/build_app.sh
```

The script creates `dist/HALA RT.app` and the sendable archive
`dist/HALA_RT_0.1.0_macos_arm64.zip`. The archive includes Python, the Python
dependencies, and a bundled LGPL-oriented FFmpeg build for M4A/M4V decoding, so
recipients do not need to install Python or Homebrew FFmpeg. Without Developer
ID notarization, recipients may need to Control-click the app and choose **Open**
on first launch.

The default build targets Apple Silicon (`arm64`). To build an Intel Mac archive,
create an x86_64 Python 3.11 virtualenv at `.venv-x86_64`, install the same
packaging extra in that environment, then run:

```bash
TARGET_ARCH=x86_64 packaging/macos/build_app.sh
```

That produces `dist/HALA_RT_0.1.0_macos_x86_64.zip`. On Apple Silicon build
machines, the Intel build requires Rosetta and an x86_64-capable Python
environment; on Intel Macs it can be built natively.

## Build a Windows App

On a Windows x64 machine, create a Python 3.11 virtualenv, install the packaging
extra, then run:

```powershell
python -m pip install -e ".[packaging]"
powershell -ExecutionPolicy Bypass -File packaging\windows\build_app.ps1
```

The script creates `dist\HALA RT\HALA RT.exe` and the sendable archive
`dist\HALA_RT_0.1.0_windows_x64.zip`. The Windows package bundles Python, the
Python dependencies, the HALA RT icon, and `ffmpeg.exe` / `ffprobe.exe` under
`_internal\bin` so M4A/M4V decoding works without a user-installed FFmpeg.

By default, `packaging\windows\build_ffmpeg.ps1` builds FFmpeg from the official
source release using MSYS2. Install MSYS2 with the MINGW64 toolchain first, or
set `HALA_FFMPEG_DIR` to a prepared LGPL-compatible FFmpeg directory containing
`ffmpeg.exe` and `ffprobe.exe`. For debugging only, set `HALA_BUNDLE_FFMPEG=0`
to build the app without bundled FFmpeg.

In an MSYS2 MINGW64 shell, the expected build tools are:

```bash
pacman -S --needed mingw-w64-x86_64-gcc make diffutils tar xz
```

## Usage

```bash
python -m hala_rt
```

1. Click **Load Audio File** and choose a WAV, MP3, FLAC, or M4A file.
2. On the **Global Timeline**, click or drag to place the trial-end cursor, then click **Add Trial End**. Repeat to cut the session into trials.
3. Select a trial and use the **Trial Detail View** to place the **Beep Start**, **First Speech**, and **Main Response** markers. Reaction times are filled in automatically.
4. Edit any cell in the **Trial Output Editor** table directly if needed.
5. Click **Save Output CSV** (defaults to `<audiofile>_hala_output.csv`) or **Save Output CSV As…** for an edited copy.

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Space` | Play / Pause |
| `←` / `→` | Nudge the trial cursor |
| `Shift` + `←` / `→` | Nudge the trial cursor ×10 |

## Output

One CSV row per trial. Timestamps are in seconds (4 decimals); reaction times are in
milliseconds (0.1 ms precision). See [output_schema.md](docs/output_schema.md) for the full
column reference.

| Column | Description |
| --- | --- |
| `trial_index` | Sequential trial ID, starting at 1. |
| `trial_start_global` | Trial start (seconds); trial 1 at `0.0000`, later trials at the previous trial's end. |
| `trial_end_global` | Manually placed trial-end boundary (seconds). |
| `beep_timestamp_global` | Beep start in the session file (seconds). |
| `rt_first_speech_ms` | Beep → first sound, including fillers (ms). |
| `rt_main_response_ms` | Beep → main word, skipping fillers (ms). |
| `prefiller_present` | Whether an `Umm… Word` pattern was detected. |
| `flag_anticipatory` | Response was physiologically too fast. |
| `flag_timeout` | No response detected in the trial window. |
| `segments_count` | Number of distinct speech bursts in the trial. |

## Project structure

The app follows a deliberate separation: one controller owns behavior and state,
the UI module builds *structure* (no logic), styling resolves through
`theme` / `palette` tokens, and output path/CSV logic lives in the data layer.
Audio and the data model are independent, GUI-agnostic layers.

```text
HALA_RT_v1/
  README.md
  pyproject.toml
  .gitignore
  docs/
    output_schema.md
  src/
    hala_rt/
      app.py
      __main__.py
      audio/
      data/
      ui/
      widgets/
  tests/
  examples/
  outputs/
```

### Entry point & controller

- **`src/hala_rt/app.py`** — Application entry point (`python -m hala_rt` or `hala-rt`).
  Prints a startup dependency report (pydub / soundfile / sounddevice and FFmpeg
  availability), creates the `QApplication`, and shows the main window. Degrades
  gracefully when optional backends are missing.
- **`src/hala_rt/ui/main_window.py`** — `HALAMainWindow`, the controller. Owns session
  state (the list of `TrialData`, the current trial index, unsaved-changes
  tracking, the output CSV path) and all behavior: playback timer and transport,
  global/trial cursor handling, trial add/delete, marker placement (beep / first
  speech / main response), the editable output table, keyboard shortcuts, and
  CSV load/save. The widgets it drives (`play_btn`, `trial_table`,
  `global_waveform`, `trial_waveform`, …) are assigned onto it by the UI module.

### UI construction & styling

- **`src/hala_rt/ui/main_window_ui.py`** — `build_ui(window)` assembles the entire widget tree
  (header, status line, transport controls, global timeline, trial navigation,
  trial detail view with zoom, the output table, session info, and the shortcut
  hint) and attaches each widget onto the window the way a generated `setupUi`
  would. It builds layout only — the controller keeps the behavior.
- **`src/hala_rt/ui/theme.py`** — Qt style sheets (QSS) composed from palette tokens via
  `string.Template`, plus per-button styling helpers (load / delete / marker
  buttons). Keeps style strings out of the widget tree.
- **`src/hala_rt/ui/palette.py`** — Centralized design tokens (the slate neutral scale, the blue
  primary accent, the red playhead, and the beep / first-speech / main-response
  marker colors). Solid colors are hex strings that drop into both QSS and
  `QColor`; translucent fills are RGBA tuples.

### Waveform widgets

- **`src/hala_rt/widgets/waveform_base.py`** — `BaseWaveformWidget`, shared rendering machinery for
  both timelines. Caches the static layer (waveform + markers) into a pixmap and
  paints a cheap dynamic overlay (the moving playhead) on top each frame; handles
  time↔pixel coordinate mapping and selection state. Subclasses supply the
  visible window, cache key, and draw routines.
- **`src/hala_rt/widgets/simple_waveform.py`** — `SimpleWaveformWidget`, the **Global Timeline**. Shows
  the whole session with committed trial regions, the in-progress draft range,
  and the playback position; click or drag to place the next trial-end cursor.
- **`src/hala_rt/widgets/trial_viz.py`** — `TrialWaveformWidget`, the **Trial Detail View**. Renders a
  single trial slice with the beep / first-speech / main-response markers, speech
  segments, and the playhead, with zoom (down to 50 ms) and auto-pan.

### Data model

- **`src/hala_rt/data/trial_data.py`** — The `TrialData` dataclass and CSV row model: column order
  (`CSV_COLUMNS`), boolean/seconds/RT column groupings, formatting (seconds to 4
  decimals, RT to 0.1 ms), parsing helpers, row↔model conversion, and
  `validate()` (start ≥ 0, end after start, beep inside the window, no negatives).
- **`src/hala_rt/data/csv_io.py`** — CSV file loading and writing, including schema checks.
- **`src/hala_rt/data/output_paths.py`** — Default output path and edited-copy naming policy.
- **`src/hala_rt/ui/table_columns.py`** — Presentation metadata for the output table: human
  labels, per-column tooltips (each naming its CSV field), and the width-fitting
  logic that distributes viewport space without ever clipping a header label.

### Reference

- **`docs/output_schema.md`** — The canonical CSV output schema (Phase 5).
