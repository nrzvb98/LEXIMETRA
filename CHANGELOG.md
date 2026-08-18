# Changelog

User-visible changes to LEXIMETRA, newest first. Each release also names the
vendored processing pipeline it ships (`hala_rt` version and upstream commit;
the live values are in `src/hala_rt/processing/VERSION`), because most
behaviour changes arrive through pipeline syncs rather than app code.

Add to **Unreleased** in the same commit as the change it describes; a
`release:` commit moves that section under a version heading with the date.
Versions follow `pyproject.toml`.

## Unreleased

Vendored pipeline: `hala_rt` 1.3.0 (upstream `4f3180d`).

### Changed

- Beeps that reach the microphone as a burst of 2–4 lobes are merged into one
  beep instead of being counted as two to four trials. Affected recordings now
  produce the correct trial count (the worst research-corpus case dropped from
  269 detections to its true 102 trials), the "no speech detected" sliver rows
  between lobes disappear, and reaction times anchor on the true beep onset.
  Recordings without lobed beeps produce byte-identical output.
- Reprocessing a recording that previously over-detected therefore yields
  fewer trials, renumbered from the first merged beep on. The status bar and
  outcome message say how many double-lobed beeps were merged, and the sidecar
  anomaly report carries one `merged_double_lobe` row per merged beep.

## 0.2.1 — 2026-08-18

Vendored pipeline: `hala_rt` 1.2.0 (upstream `8970af9`).

### Added

- LEXIMETRA name and application icon (previously "HALA RT").
- Beeps too quiet for the detector's trigger are recovered: candidates are
  found by matched filter and confirmed exactly against the beep template
  before acceptance. The status bar reports how many quiet beeps were
  recovered so the extra trials don't appear unexplained.

### Fixed

- Exported beep timestamps are paired to their trial slices rather than by row
  order, so a missed or spurious detection no longer shifts every later beep
  against the wrong trial's speech.

## 0.2.0 — 2026-08-12

Vendored pipeline: `hala_rt` 1.0.0 (upstream `84c0355`).

### Added

- Automatic analysis on load: the vendored HALA processing pipeline (beep
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
