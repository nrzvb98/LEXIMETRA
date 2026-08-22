# Frozen pipeline baseline

Outputs of the processing pipeline for `examples/audio/trial_sample.m4a`
(24.5 s, 12 trials), used by `tests/test_processing_regression.py` to hold
`src/leximetra/processing/` to the behaviour it was validated with.

**Neither the recording nor these baselines are in this repository — only this
file is.** Both are the sample session's data: a real voice recording, and the
timings derived from it. This repository is public, so both are gitignored and
kept locally, the recording at `examples/audio/trial_sample.m4a` and the
baselines beside this README. With them present the gate runs; without them,
`tests/test_processing_regression.py` skips itself, which is what a fresh clone
does.

**Captured 2026-08-12**, from the pipeline at package version 1.0.0, before it
was brought into this repository. They are a record of validated behaviour, not
of this repository's own output — which is what makes them worth comparing
against at all. A baseline regenerated from the current code would only ever
confirm that the code equals itself.

The data files, when present locally:

| File | Contents |
|---|---|
| `trial_sample_Full_Analysis_Results.csv` | Absolute beep/speech/hesitation timings per trial |
| `trial_sample_Analysis_Results.csv` | RT + response-type summary subset |
| `trial_sample_output.csv` | Software-format export the app loads |
| `slices.sha256` | SHA-256 of each `Slices/Trial_NNN.wav` |

Slices are hashed rather than stored: they are 12 WAVs cut from the recording,
and a hash catches a change just as well as the bytes would.

They double as the worked example of what the pipeline produces:
`examples/audio/trial_sample.m4a` in, these out.

## Obtaining them

They cannot be regenerated from this repository, by design — see the note above.
Ask the maintainer for the session data.

Failing that, a baseline of your own works for catching *your* regressions:
run the pipeline over a recording you hold, keep the outputs here, and treat the
first run as the reference. It will not tell you whether the pipeline is
correct, only whether you changed it — which is the weaker of the two guarantees
but still the one that catches accidents.

## Scope

This is a behavioural gate over one 24.5-second recording. It proves the
pipeline still does what it did; it does not prove the pipeline is right, and
one short session does not cover every recording condition — quiet beeps, long
hesitations, and unusual cue tones are all under-represented. Treat a green run
as "nothing moved", not as "this is correct".

## Re-baselining

Only when the pipeline's outputs are *intended* to change. Confirm the diff the
test reports is exactly the change you meant to make, refresh these files from
that run, and say why in the commit message — a re-baseline with no explanation
is indistinguishable from silencing a real regression.
