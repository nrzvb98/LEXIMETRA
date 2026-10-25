# Changelog

User-visible changes to LEXIMETRA, newest first. Releases up to 0.2.x also name
the processing pipeline version they shipped, from when that pipeline was
vendored from a separate repository; `src/leximetra/processing/VERSION` records
where it came from. It is maintained in this repository now, so later entries
describe pipeline changes like any other change.

Add to **Unreleased** in the same commit as the change it describes; a
`release:` commit moves that section under a version heading with the date.
Versions follow `pyproject.toml`.

## Unreleased

Pipeline: 1.2.0.

### Added

- LEXIMETRA name and application icon.
- `CITATION.cff` and a README *Citing LEXIMETRA* section, so published work
  can name the exact version that produced its reaction times.
- Beeps too quiet for the detector's trigger are recovered: candidates are
  found by matched filter and confirmed exactly against the beep template
  before acceptance. The status bar reports how many quiet beeps were
  recovered so the extra trials don't appear unexplained.

### Fixed

- `flag_anticipatory`, `flag_timeout` and `response_type` are now measured from
  picture onset instead of beep onset. Exported RTs are referenced to the beep,
  but the picture appears `STIMULUS_ONSET_AFTER_BEEP_MS` (default 500 ms) later,
  so the anticipatory flag previously caught only speech before the picture and
  the timeout flag fired 500 ms early. A trial with no detected speech is now
  always flagged as timeout in the exported CSV. Exported RT values are
  unchanged.

### Changed

- The processing pipeline is maintained in this repository. It was a
  generated copy of a separate project that had to be edited there and
  re-vendored here; that project was never published, so the workflow was
  impossible to follow from a clone. Edit `src/leximetra/processing/`
  directly and run `tests/test_processing_regression.py`.

- Every artifact the app writes is renamed. For a recording `p001.m4a` it now
  writes `p001_output.csv` and a `p001_output/` folder holding `Slices/`,
  `p001_Full_Analysis_Results.csv` and `p001_Analysis_Results.csv`. Backups
  and Save-As copies follow the CSV, as `p001_output_backup.csv` and
  `p001_output_edited.csv`.
- Recordings analysed by 0.2.x keep working. Where one has only its original
  CSV and not the new one, the app loads that file and keeps using its name
  for that recording — backups and edited copies included — so a single
  recording's files never split across two naming schemes. Nothing needs
  renaming by hand.
- The import package is `leximetra`. The distribution and the `leximetra`
  command were already named that; only the import path lagged.
- Environment variables now take the `LEXIMETRA_` prefix, including
  `LEXIMETRA_FFMPEG_DIR` and `LEXIMETRA_BUNDLE_FFMPEG`, which the Windows
  build documents.
- The legacy console-script alias is gone. `leximetra` is the only entry
  point, so shells and notes still calling the old command need updating.

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

Anything that matched the 0.2.x artifact names needs repointing: the output
CSV is `<recording>_output.csv` and the per-trial audio is in
`<recording>_output/Slices/`. Scripts reading only CSVs already written by
0.2.x are unaffected — those files keep their original names.

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
