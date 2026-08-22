# LEXIMETRA

A desktop tool for **automatic trial analysis and reaction-time (RT) verification** of speech-response audio sessions. Load a session recording and it is analyzed on the spot — beeps detected, trials cut, speech onsets marked — leaving you to check and correct the results rather than produce them. Everything can still be done by hand when the analysis is wrong or unavailable.

Built with [PyQt6](https://pypi.org/project/PyQt6/).

---

## Features

- **Load a full session** as WAV, MP3, FLAC, or M4A and scrub it on a global timeline.
- **Automatic analysis on load** — beep detection, per-trial slicing, Silero VAD, and RT metrics, producing the output CSV without any manual cutting. A 2.5-minute session takes about 7 seconds. If a CSV already exists you are asked whether to keep it or analyze again; the previous file is backed up either way.
- **Cut trials manually** whenever you need to — drag the global cursor to a trial boundary and click *Add Trial End*. Each new trial starts where the previous one ended.
- **Per-trial detail view** with zoom, so you can check and move markers precisely:
  - **Beep Start** — the trial's onset cue.
  - **First Speech** — first sound after the beep (including fillers like *"umm"*).
  - **Main Response** — the main response word, skipping fillers.
- **Reaction times computed automatically** from the beep to each marker, in milliseconds.
- **Editable output table** — every column is hand-editable, with validation.
- **CSV export** following the [output schema](docs/output_schema.md), plus *Save As* for edited copies.
- Playback with selection looping, keyboard scrubbing, and waveform visualization.

Automatic analysis is optional. Without it the app behaves exactly as it always has — it reports the capability as unavailable at startup and every trial is cut by hand.

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
python -m pip install -e ".[processing]"
```

The `processing` extra adds automatic analysis (torch, torchaudio, pandas, scipy —
roughly 500 MB). Install without it for verification only:

```bash
python -m pip install -e .
```

The app degrades gracefully if optional audio backends are missing — it reports
which dependencies are absent on startup and continues with limited functionality.

> **Apple Silicon only for the analysis extra.** PyTorch no longer publishes
> macOS x86_64 wheels at the versions this pipeline pins, so on Intel Macs the
> app installs and runs but reports automatic analysis as unavailable.

## Build a macOS App

On macOS, install the packaging extra and run the build script:

```bash
python -m pip install -e ".[packaging,processing]"
packaging/macos/build_app.sh
```

The script creates `dist/LEXIMETRA.app` and the sendable archive
`dist/LEXIMETRA_0.2.0_macos_arm64.zip` (**212 MB**). The archive includes Python,
the Python dependencies, a bundled LGPL-oriented FFmpeg build for M4A/M4V
decoding, and the analysis pipeline with its Silero VAD model, so recipients need
neither Python, nor Homebrew FFmpeg, nor a network connection on first run.
Without Developer ID notarization, recipients may need to Control-click the app
and choose **Open** on first launch.

Analysis is bundled only if torch is installed in the build environment;
otherwise the script says so and builds a verification-only app (~53 MB). Before
signing, the build runs the packaged binary with `LEXIMETRA_SELF_TEST=1` and fails
unless it can import the pipeline, find the beep templates, and load the VAD
model — bundling breaks in ways the test suite cannot see, and this stops those
reaching a user.

The default build targets Apple Silicon (`arm64`). An Intel build needs an
x86_64 Python 3.11 virtualenv at `.venv-x86_64`:

```bash
TARGET_ARCH=x86_64 packaging/macos/build_app.sh
```

That produces `dist/LEXIMETRA_0.2.0_macos_x86_64.zip`, always without automatic
analysis — there are no macOS x86_64 torch wheels — so it is a verification-only
app. On Apple Silicon build machines the Intel build requires Rosetta and an
x86_64-capable Python environment; on Intel Macs it can be built natively.

## Build a Windows App

> **The Windows script has not been updated for automatic analysis.** Build it in
> an environment *without* the `processing` extra. torch has Windows wheels, but
> the script lacks the collection and pruning steps and the self-test the macOS
> one has, so a build made with torch installed would bundle it incompletely and
> fail when a user loads a recording. Installed as below, it produces the same
> verification-only app it always did.

On a Windows x64 machine, create a Python 3.11 virtualenv, install the packaging
extra, then run:

```powershell
python -m pip install -e ".[packaging]"
powershell -ExecutionPolicy Bypass -File packaging\windows\build_app.ps1
```

The script creates `dist\LEXIMETRA\LEXIMETRA.exe` and the sendable archive
`dist\LEXIMETRA_0.2.0_windows_x64.zip`. The Windows package bundles Python, the
Python dependencies, the LEXIMETRA icon, and `ffmpeg.exe` / `ffprobe.exe` under
`_internal\bin` so M4A/M4V decoding works without a user-installed FFmpeg.

By default, `packaging\windows\build_ffmpeg.ps1` builds FFmpeg from the official
source release using MSYS2. Install MSYS2 with the MINGW64 toolchain first, or
set `LEXIMETRA_FFMPEG_DIR` to a prepared LGPL-compatible FFmpeg directory
containing `ffmpeg.exe` and `ffprobe.exe`. For debugging only, set
`LEXIMETRA_BUNDLE_FFMPEG=0` to build the app without bundled FFmpeg.

In an MSYS2 MINGW64 shell, the expected build tools are:

```bash
pacman -S --needed mingw-w64-x86_64-gcc make diffutils tar xz
```

## App icon

Both builds read generated icon files, not the source artwork. After changing
`packaging/icons/leximetra-icon-source.png`, regenerate them:

```bash
python packaging/make_icons.py
```

That writes `packaging/macos/icons/leximetra-icon.icns` (the ten sizes macOS
asks for, on Apple's Big Sur grid) and `packaging/windows/icons/leximetra-icon.ico`
(seven sizes, edge to edge). The script cuts the artwork out against
transparency; source PNGs painted on an opaque background show black corners in
the Dock if used directly.

## Usage

```bash
python -m leximetra
```

1. Click **Load Audio File** and choose a WAV, MP3, FLAC, or M4A file.
2. The recording is analyzed automatically and the trials appear with their markers already placed. If an output CSV already exists you are asked whether to keep it or analyze again.
3. Step through the trials and check them in the **Trial Detail View**, moving the **Beep Start**, **First Speech**, and **Main Response** markers where the analysis got it wrong. Reaction times update as you go.
4. Edit any cell in the **Trial Output Editor** table directly if needed.
5. Click **Save Output CSV** (defaults to `<audiofile>_output.csv`) or **Save Output CSV As…** for an edited copy.

To cut trials by hand instead — when a recording has no beeps, or analysis is not
installed — place the trial-end cursor on the **Global Timeline** and click
**Add Trial End**, repeating to divide the session.

### Files written for `/sessions/p001.m4a`

| Path | Contents |
| --- | --- |
| `/sessions/p001_output.csv` | The output CSV the app loads and saves |
| `/sessions/p001_output/Slices/Trial_NNN.wav` | Per-trial audio from the analysis |
| `/sessions/p001_output/p001_Full_Analysis_Results.csv` | Absolute beep/speech/hesitation timings |
| `/sessions/p001_output/p001_Analysis_Results.csv` | RT and response-type summary |
| `/sessions/p001_output/p001_beep_pairing_report.csv` | Written only when a beep did not pair 1:1 — quiet-beep recoveries land here |

Re-analyzing renames the existing output CSV to `p001_output_backup.csv`
before writing a new one, so hand-verified work is never overwritten silently.

A recording whose CSV was written by an older release (`p001_hala_output.csv`)
still loads: the app prefers the new name but falls back to the legacy one, and
keeps using the legacy name for that recording so its files stay together.

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

The analysis pipeline is a *vendored copy* of a separate project and is treated
as a black box behind one service — see [Automatic analysis](#automatic-analysis).

> **A note on names.** Nothing this app writes carries `HALA` any more: the
> `<stem>_output.csv` CSV, the `<stem>_output/` sidecar, and inside it
> `Slices/` and the two `<stem>_*_Results.csv` files. The vendored pipeline
> produces those names itself — `tools/sync_processing.py` rewrites upstream's
> branding on the way in, so the pipeline sources are still generated rather
> than hand-edited, and still derive from a named upstream commit.
>
> Two `hala` names survive on purpose. A legacy `<stem>_hala_output.csv` is
> still read where one exists, so recordings verified under 0.2.x keep loading.
> And `Hala_Processing` is the upstream repo's actual name, which this repo
> only refers to. Study tooling that globs `*_hala_output.csv` will not see
> CSVs written under the new name.

```text
LEXIMETRA/
  README.md
  pyproject.toml
  .gitignore
  docs/
    output_schema.md
    integration_plan.md
  src/
    leximetra/
      app.py
      __main__.py
      audio/
      data/
      processing/     # vendored pipeline (generated -- do not edit)
      ui/
      widgets/
  tests/
    data/processing_baseline/
  tools/
    sync_processing.py
    vendor_silero.py
  examples/audio/
```

### Entry point & controller

- **`src/leximetra/app.py`** — Application entry point (`python -m leximetra` or `leximetra`).
  Prints a startup dependency report (pydub / soundfile / sounddevice, FFmpeg, and
  whether automatic analysis is available), creates the `QApplication`, and shows
  the main window. Degrades gracefully when optional backends are missing. Also
  holds `self_test()`, which the macOS build script runs against the packaged
  binary (`LEXIMETRA_SELF_TEST=1`) to prove a bundle can actually analyze.
- **`src/leximetra/ui/main_window.py`** — `LeximetraMainWindow`, the controller. Owns session
  state (the list of `TrialData`, the current trial index, unsaved-changes
  tracking, the output CSV path) and all behavior: playback timer and transport,
  global/trial cursor handling, trial add/delete, marker placement (beep / first
  speech / main response), the editable output table, keyboard shortcuts, and
  CSV load/save. The widgets it drives (`play_btn`, `trial_table`,
  `global_waveform`, `trial_waveform`, …) are assigned onto it by the UI module.

### UI construction & styling

- **`src/leximetra/ui/main_window_ui.py`** — `build_ui(window)` assembles the entire widget tree
  (header, status line, transport controls, global timeline, trial navigation,
  trial detail view with zoom, the output table, session info, and the shortcut
  hint) and attaches each widget onto the window the way a generated `setupUi`
  would. It builds layout only — the controller keeps the behavior.
- **`src/leximetra/ui/theme.py`** — Qt style sheets (QSS) composed from palette tokens via
  `string.Template`, plus per-button styling helpers (load / delete / marker
  buttons). Keeps style strings out of the widget tree.
- **`src/leximetra/ui/palette.py`** — Centralized design tokens (the slate neutral scale, the blue
  primary accent, the red playhead, and the beep / first-speech / main-response
  marker colors). Solid colors are hex strings that drop into both QSS and
  `QColor`; translucent fills are RGBA tuples.

### Waveform widgets

- **`src/leximetra/widgets/waveform_base.py`** — `BaseWaveformWidget`, shared rendering machinery for
  both timelines. Caches the static layer (waveform + markers) into a pixmap and
  paints a cheap dynamic overlay (the moving playhead) on top each frame; handles
  time↔pixel coordinate mapping and selection state. Subclasses supply the
  visible window, cache key, and draw routines.
- **`src/leximetra/widgets/simple_waveform.py`** — `SimpleWaveformWidget`, the **Global Timeline**. Shows
  the whole session with committed trial regions, the in-progress draft range,
  and the playback position; click or drag to place the next trial-end cursor.
- **`src/leximetra/widgets/trial_viz.py`** — `TrialWaveformWidget`, the **Trial Detail View**. Renders a
  single trial slice with the beep / first-speech / main-response markers, speech
  segments, and the playhead, with zoom (down to 50 ms) and auto-pan.

### Data model

- **`src/leximetra/data/trial_data.py`** — The `TrialData` dataclass and CSV row model: column order
  (`CSV_COLUMNS`), boolean/seconds/RT column groupings, formatting (seconds to 4
  decimals, RT to 0.1 ms), parsing helpers, row↔model conversion, and
  `validate()` (start ≥ 0, end after start, beep inside the window, no negatives).
- **`src/leximetra/data/csv_io.py`** — CSV file loading and writing, including schema checks.
- **`src/leximetra/data/output_paths.py`** — Default output path and edited-copy naming policy.
- **`src/leximetra/ui/table_columns.py`** — Presentation metadata for the output table: human
  labels, per-column tooltips (each naming its CSV field), and the width-fitting
  logic that distributes viewport space without ever clipping a header label.

## Automatic analysis

The pipeline that detects beeps and speech is developed and validated in a
separate repository, **Hala_Processing**, and vendored here so the app builds
and packages from one checkout.

- **`src/leximetra/processing/`** — the vendored pipeline. **Generated, not
  hand-edited.** Upstream's package is named `hala_rt`; `sync_processing.py`
  rewrites that to `leximetra.processing` on the way in, along with upstream's
  type names, its one environment variable, and the names it gives the files it
  writes. Because those rewrites are deterministic, the tool detects drift by
  re-running them and comparing.
- **`src/leximetra/data/processing_service.py`** — `run_processing()`, the only
  entry point the app uses. Returns a typed `ProcessingOutcome` and **never
  raises**: a missing dependency, a recording with no beeps, and a cancelled run
  are all statuses to report, because the manual workflow is always still there.
  Imports torch lazily, so launching the app costs nothing for anyone who only
  verifies existing CSVs.
- **`src/leximetra/ui/processing_worker.py`** — runs the service on a `QThread`
  so the window stays responsive, with a backstop that keeps any exception from
  escaping `run()` (PyQt6 turns those into a fatal abort of the process).

### Changing the pipeline

Edit it **upstream**, validate there with `regression_check.py` (which has the
full multi-recording reference set), commit, then re-vendor:

```bash
python tools/sync_processing.py --apply --upstream ../../Hala_Processing
```

`tools/sync_processing.py` with no arguments checks for drift and exits 1 with a
diff if the vendored copy no longer matches upstream, which is what makes "edit
upstream, not the copy" enforceable. `tools/vendor_silero.py` does the same job
for the bundled Silero VAD model.

Then confirm nothing moved:

```bash
python -m pytest tests/test_processing_regression.py
```

That compares against `tests/data/processing_baseline/`, frozen from upstream
*before* the copy was made, so it catches vendoring mistakes and not merely
later drift. See that directory's README for scope and re-baselining.

### Reference

- **`CHANGELOG.md`** — User-visible changes per release, with the vendored
  pipeline version each release shipped.
- **`docs/output_schema.md`** — The canonical CSV output schema (Phase 5).
- **`docs/integration_plan.md`** — How automatic analysis was integrated: the
  decisions taken, the corrections made along the way, and what is deliberately
  left undone (Windows and Intel builds, the ONNX size optimization).

## License

Released under the [MIT License](LICENSE).

The bundled Silero VAD model in `src/leximetra/processing/silero/` is MIT-licensed
by the Silero Team and carries its own `LICENSE` alongside it. The packaged macOS
and Windows apps additionally ship an LGPL-oriented FFmpeg build, whose license
notices are copied into the bundle under `Resources/licenses/ffmpeg/`.
