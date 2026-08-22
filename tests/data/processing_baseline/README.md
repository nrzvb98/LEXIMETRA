# Frozen pipeline baseline

Outputs of the HALA processing pipeline for `examples/audio/trial_sample.m4a`
(24.5 s, 12 trials), used by `tests/test_processing_regression.py` to prove the
vendored copy in `src/leximetra/processing/` still reproduces the validated
pipeline.

**Generated from upstream, before vendoring** — `Hala_Processing` at commit
`675eeea`, package version 1.0.0, on 2026-08-12. That ordering is the point: a
baseline generated from the vendored copy would only catch future drift, not a
mistake made during the copy itself.

These carry this app's names; the pipeline is upstream's and still writes its
own. `test_csv_matches_frozen_baseline` holds the mapping between the two, so
the produced-side name is in the middle column here.

| File | Compared against | Contents |
|---|---|---|
| `trial_sample_Full_Analysis_Results.csv` | `trial_sample_HALA_Full_Analysis_Results.csv` | Absolute beep/speech/hesitation timings per trial |
| `trial_sample_Analysis_Results.csv` | `trial_sample_HALA_Analysis_Results.csv` | RT + response-type summary subset |
| `trial_sample_output.csv` | `trial_sample_hala_output.csv` | Software-format export the app loads |
| `slices.sha256` | `HALA_Slices/Trial_NNN.wav` | SHA-256 of each trial slice |

Slices are hashed rather than committed: they are 12 WAVs of generated audio,
and a hash catches drift just as well as the bytes would.

These files double as the worked example of what the pipeline produces:
`examples/audio/trial_sample.m4a` in, these out. (An older copy of the export
lived at `examples/outputs/`; it predated the 2026-08-12 re-baseline, carried
`segments_count` as all zeros, and was removed rather than left to contradict
this one.)

## Scope

This is the *vendoring* gate, not the full fidelity gate. `Hala_Processing`
keeps `regression_check.py`, which additionally byte-compares two longer
sessions against frozen notebook outputs — some 2.1 GB
of references plus 43 MB of source recordings that cannot live in this repo.
Changes to the pipeline itself should still be validated upstream.

## Re-baselining

Only when the pipeline's outputs are *intended* to change. Re-run upstream,
confirm the diff is the expected one, refresh these files, and say why in the
commit message.
