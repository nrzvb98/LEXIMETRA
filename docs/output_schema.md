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
