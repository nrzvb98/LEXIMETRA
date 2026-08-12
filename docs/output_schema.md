# Phase 5: Output Schema

CSV output contains one row per trial.

Second-based timestamps are stored with 4 decimal places. Reaction times are stored in milliseconds with 0.1 ms precision.

| Column | Description |
| --- | --- |
| `trial_index` | Sequential ID of the trial, starting at 1. |
| `trial_start_global` | Global timestamp in seconds where the trial starts. Trial 1 starts at `0.0000`; later trials start at the previous trial end. |
| `trial_end_global` | Global timestamp in seconds where the manually placed trial end cursor marks the trial boundary. |
| `beep_timestamp_global` | Global timestamp in seconds of the beep start in the session file. |
| `rt_first_speech_ms` | Reaction time in milliseconds from beep start to the very first sound, including fillers. |
| `rt_main_response_ms` | Reaction time in milliseconds from beep start to the main word, skipping fillers if detected. |
| `prefiller_present` | Boolean indicating whether an `Umm... Word` pattern was detected. |
| `flag_anticipatory` | Boolean indicating that the response was physiologically too fast. |
| `flag_timeout` | Boolean indicating that no response was detected in the trial window. |
| `segments_count` | Number of distinct speech bursts found in this trial. |

## Where the rows come from

Rows are produced two ways, and the schema is identical either way:

- **Automatic analysis** — the vendored pipeline writes this file when a
  recording is loaded (see the README's *Automatic analysis* section). It is
  also the pipeline's own `<stem>_hala_output.csv` export format, which is why
  the two match column for column.
- **By hand** — trials cut in the app, or an existing CSV corrected in the
  output table and saved.

The app makes no distinction on load: a hand-written CSV and an analyzed one are
read by the same loader and held to the same validation, including the rule that
trials tile the recording without gaps.
