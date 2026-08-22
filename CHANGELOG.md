# Changelog

User-visible changes to LEXIMETRA, newest first. Each release also names the
vendored processing pipeline it ships (pipeline version and upstream commit;
the live values are in `src/leximetra/processing/VERSION`), because most
behaviour changes arrive through pipeline syncs rather than app code.

Add to **Unreleased** in the same commit as the change it describes; a
`release:` commit moves that section under a version heading with the date.
Versions follow `pyproject.toml`.

## Unreleased

Vendored pipeline: 1.2.0 (upstream `8970af9`).

### Added

- LEXIMETRA name and application icon (previously "HALA RT").
- Beeps too quiet for the detector's trigger are recovered: candidates are
  found by matched filter and confirmed exactly against the beep template
  before acceptance. The status bar reports how many quiet beeps were
  recovered so the extra trials don't appear unexplained.

### Changed

- Nothing the app writes carries `HALA` any more. For a recording `p001.m4a`:
  the CSV is `p001_output.csv` (was `p001_hala_output.csv`), the artifacts
  folder is `p001_output/` (was `p001_hala/`), and inside it are `Slices/`
  (was `HALA_Slices/`) and `p001_Full_Analysis_Results.csv` /
  `p001_Analysis_Results.csv` (both previously `_HALA_` infixed). Backups and
  Save-As copies follow the CSV.
- Recordings analysed by an earlier release keep working: with no
  `p001_output.csv` but a `p001_hala_output.csv` present, the app loads the
  legacy file and keeps using that name for that recording — backups and
  edited copies included — so one recording's files never split across two
  naming schemes. Nothing needs renaming by hand.
- The import package is `leximetra`, not `hala_rt`. The distribution and the
  `leximetra` command were already named that; only the import path lagged.
- Environment variables are `LEXIMETRA_*`, not `HALA_*` — including
  `LEXIMETRA_FFMPEG_DIR` and `LEXIMETRA_BUNDLE_FFMPEG`, which the Windows
  build documents.
- The `hala-rt` console script is gone. `leximetra` is the only entry point,
  so shells and notes that still call `hala-rt` will need updating.

### Fixed

- Exported beep timestamps are paired to their trial slices rather than by row
  order, so a missed or spurious detection no longer shifts every later beep
  against the wrong trial's speech.
- A near-silent window late in a long recording could score as a beep, because
  the rescue's match profile derived window energy from a difference of
  cumulative sums that float64 cannot resolve at those magnitudes. Candidates
  are now re-scored exactly before acceptance. Measured over the 95-recording
  research corpus this removes one phantom beep and adds none.

### Note for external tooling

Tooling that globs `*_hala_output.csv` will not see CSVs written under the new
name, and anything reading `<recording>_hala/HALA_Slices/` should read
`<recording>_output/Slices/` instead.

## 0.2.0 — 2026-08-12

Vendored pipeline: 1.0.0 (upstream `84c0355`).

### Added

- Automatic analysis on load: the vendored processing pipeline (beep
  detection, trial slicing, Silero VAD, RT metrics) produces the output CSV
  the moment a recording loads. An existing CSV is backed up, never
  overwritten, and any failure degrades to the manual workflow.
- macOS Apple Silicon app bundle with the analysis dependencies included.

### Fixed

- Output CSV is written atomically.
- Trial detail zoom and selection survive re-showing the same trial.
- Trial starts silently adjusted when loading a non-contiguous CSV are now
  reported.

## 0.1.0 — 2026-08-12

Initial version: the manual verification interface. Load a session recording,
cut trials by hand, place beep / first-speech / main-response markers, compute
reaction times, and edit and export the output CSV.
