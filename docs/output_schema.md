# Output Schema

The canonical format of `<stem>_output.csv` — the per-trial file the app writes,
reads back, and validates. One row per trial, one header row, UTF-8.

## Columns

Written in this order. On load the order does not matter, but all ten must be
present; unrecognised extra columns are ignored.

| Column | Type | Description |
| --- | --- | --- |
| `trial_index` | integer | Sequential ID of the trial, starting at 1. |
| `trial_start_global` | seconds | Where the trial starts. Trial 1 starts at `0.0000`; later trials start at the previous trial's end. |
| `trial_end_global` | seconds | The trial-end boundary, placed by the analysis or by hand. |
| `beep_timestamp_global` | seconds | Start of the onset cue beep, in session time. |
| `rt_first_speech_ms` | milliseconds | Beep start → the very first sound, including fillers. |
| `rt_main_response_ms` | milliseconds | Beep start → the main word, skipping fillers if detected. |
| `prefiller_present` | boolean | Whether an `Umm… Word` pattern was detected. |
| `flag_anticipatory` | boolean | First speech landed at or under 150 ms after the beep — physiologically too fast to be a real response. |
| `flag_timeout` | boolean | No response within 3000 ms of the beep, or none detected at all. |
| `segments_count` | integer | Number of distinct speech bursts found in this trial. |

## Value encoding

| Type | Written as | Accepted on read |
| --- | --- | --- |
| seconds | 4 decimal places, e.g. `2.2818` | any number |
| milliseconds | 1 decimal place, e.g. `499.3` | any non-negative number; negative is an error |
| boolean | lowercase `true` / `false` | `true`/`1`/`yes`/`y` and `false`/`0`/`no`/`n`, any case, plus empty for false |
| integer | plain digits | plain digits; negative is an error |

The writer is stricter than the reader on purpose: it emits one canonical form,
while the reader accepts what a spreadsheet or another tool is likely to produce
after a round trip through Excel or R.

## Absent values

A reaction time is **empty** when there is none to report — the response timed
out, or the marker was never placed:

```csv
trial_index,trial_start_global,trial_end_global,beep_timestamp_global,rt_first_speech_ms,rt_main_response_ms,prefiller_present,flag_anticipatory,flag_timeout,segments_count
7,14.2210,16.8894,14.3902,,,false,false,true,0
```

Empty and `0` both read back as absent, and absent is written back as empty — so
zero is never a legitimate reaction time, and a round trip does not invent one.
An empty `segments_count` reads as `0`, and an empty `trial_index` falls back to
the row's position in the file.

## Validation on load

Every row is checked as it is parsed; a row that fails aborts the load with the
reason rather than being silently dropped.

- `trial_start_global` is not negative
- `trial_end_global` is strictly after `trial_start_global`
- `beep_timestamp_global` lies inside `[trial_start_global, trial_end_global]`
- `segments_count` and both reaction times are not negative

Trials must also tile the recording without gaps: trial *n* starts where trial
*n−1* ended. A loaded file that breaks this is **corrected, not rejected** — the
starts are moved to close the gaps or overlaps and a *Trial Starts Adjusted*
dialog lists what changed. The file on disk is untouched until you save.

## Where the rows come from

Rows are produced two ways, and the schema is identical either way:

- **Automatic analysis** — the vendored pipeline writes this file when a
  recording is loaded (see the README's *Automatic analysis* section). It is
  also the pipeline's own `<stem>_output.csv` export format, which is why the
  two match column for column.
- **By hand** — trials cut in the app, or an existing CSV corrected in the
  output table and saved.

The app makes no distinction on load: a hand-written CSV and an analyzed one are
read by the same loader and held to the same validation.

Writes are atomic. The new file is written to a sibling temporary file, flushed,
then moved onto the target, so a failed or interrupted save leaves the previous
CSV intact rather than truncated. Existing file permissions are preserved.

The two CSVs in the `<stem>_output/` sidecar — `_Full_Analysis_Results.csv` and
`_Analysis_Results.csv` — are the pipeline's own intermediate reports and are
*not* this schema. The app never reads them back; see the README's *Files
written* section.
