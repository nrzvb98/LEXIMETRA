"""End-to-end LEXIMETRA processing: audio in, three CSVs out.

    from leximetra.processing import process_audio, LeximetraConfig
    result = process_audio("recording.m4a", LeximetraConfig(), output_dir="out")
    result.df_output          # software-format table (…_output.csv)

Outputs written to `output_dir` (default: current directory):
    Slices/Trial_NNN.wav             per-trial audio (starts at beep END)
    <stem>_Full_Analysis_Results.csv absolute timings, one row per trial
    <stem>_Analysis_Results.csv      RT/hesitation summary subset
    <stem>_output.csv                software-format export
    <stem>_beep_pairing_report.csv        only if some beep did not pair 1:1

The pre-existing Slices folder under `output_dir` is removed before
slicing (it is a generated artifact of this pipeline); nothing else is deleted.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import beeps as beeps_mod
from . import metrics as metrics_mod
from .config import LeximetraConfig
from .audio_io import load_audio_app_style
from .export import save_software_csv
from .vad import get_model, get_trial_speech_timestamps, read_audio_safe

logger = logging.getLogger("leximetra.processing")

FINAL_COLUMNS = [
    'trial_name',
    'beep_timestamp_global',
    'beep_start_ms',
    'beep_end_ms',
    'speech_start_ms_abs',
    'speech_end_ms_abs',
    'hesitation_start_ms_abs',
    'hesitation_end_ms_abs',
    'rt_first_speech_ms',
    'rt_main_response_ms',
    'response_type',
    'hesitation_pattern',
]


@dataclass
class LeximetraResult:
    df_full: pd.DataFrame        # absolute timings per trial (Full_Analysis CSV)
    df_analysis: pd.DataFrame    # summary subset (Analysis CSV)
    df_output: pd.DataFrame      # software-format export (output CSV)
    slice_dir: Path
    csv_paths: dict[str, Path]   # keys: full, analysis, output (+ pairing_report), empty if not written
    beep_anomalies: list[dict] = field(default_factory=list)  # beeps that did not pair 1:1


def process_audio(
    audio_path: str | Path,
    config: LeximetraConfig | None = None,
    output_dir: str | Path | None = None,
    model=None,
    on_progress=None,
    write_outputs: bool = True,
) -> LeximetraResult:
    """Run the full LEXIMETRA pipeline on one recording.

    model: optional preloaded (silero_model, get_speech_ts) tuple from
        leximetra.processing.vad.get_model(), so a host app can load Silero once.
    on_progress: optional callable(stage: str, done: int, total: int).
    """
    cfg = config or LeximetraConfig()
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Source audio not found: {audio_path}")
    output_dir = Path(output_dir) if output_dir is not None else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = audio_path.stem

    def progress(stage, done, total):
        if on_progress is not None:
            on_progress(stage, done, total)

    # 1. Load once; both beep detectors and slicing share the same waveform.
    logger.info("Processing %s", audio_path.name)
    progress("load", 0, 1)
    y, sr = load_audio_app_style(str(audio_path), target_sr=cfg.TARGET_SR)
    progress("load", 1, 1)

    # 2. Template-matched beeps -> trial slices on disk.
    valid_beeps = beeps_mod.detect_beeps_template_matched(y, sr, cfg)
    if not valid_beeps:
        raise RuntimeError(f"No beeps detected in {audio_path.name}")

    # Recover beeps the trigger floor clipped below the duration gate. Additive:
    # returns nothing unless a rejected fragment re-measures into a real beep.
    rescued_beeps, rescue_anomalies = beeps_mod.rescue_short_beeps(y, sr, valid_beeps, cfg)
    if rescued_beeps:
        valid_beeps = sorted(valid_beeps + rescued_beeps)

    slice_dir = output_dir / "Slices"
    if slice_dir.exists():
        shutil.rmtree(slice_dir)
    slice_files = beeps_mod.slice_trials(y, sr, valid_beeps, slice_dir, cfg)
    progress("slices", len(slice_files), len(slice_files))

    # 3. VAD + metrics per trial (slices are re-read from disk: the 16-bit PCM
    # round-trip is part of the validated behavior).
    if model is None:
        model = get_model()

    results = []
    relative_rows = []
    n = len(slice_files)
    logger.info("Running VAD + metrics on %d trials...", n)
    for i, slice_path in enumerate(sorted(slice_files)):
        trial_name = slice_path.stem
        wav_tensor, trial_y, trial_sr = read_audio_safe(slice_path, target_sr=cfg.TARGET_SR)
        segments = get_trial_speech_timestamps(wav_tensor, trial_y, trial_sr, cfg, model=model)

        trial_result, merged_bursts = metrics_mod.process_trial_data(
            trial_name, segments, trial_sr, cfg, y=trial_y
        )
        results.append(trial_result)
        relative_rows.append(
            metrics_mod.relative_timings(trial_name, trial_result['hesitation_pattern'], merged_bursts)
        )
        progress("vad", i + 1, n)

    df_results = pd.DataFrame(results)
    df_speech_hesitation_rel = pd.DataFrame(relative_rows)

    # 4. Legacy fixed-band beep timings, matched to each slice by beep START
    # time rather than by detection order, then merged onto the trial results.
    # Rows are anchored to slices, so a detector disagreement can no longer
    # shift beeps against speech (see beeps.pair_beeps_to_slices).
    df_legacy = beeps_mod.detect_beeps_legacy(y, sr, cfg)
    df_beep_timings, beep_anomalies = beeps_mod.pair_beeps_to_slices(valid_beeps, df_legacy, sr, cfg)
    if beep_anomalies:
        scores = beeps_mod.tone_match_scores(
            y, sr, cfg, [int(a['time_s'] * sr) for a in beep_anomalies]
        )
        for anomaly, score in zip(beep_anomalies, scores):
            anomaly['tone_match'] = round(score, 3)

    if rescue_anomalies:
        # Number the rescued beeps now that trials are fixed, then drop the
        # pairing's "filled_from_template" row for each: the legacy detector was
        # blind to these for the same reason the duration gate was, so the fill
        # is implied by the rescue and two rows for one beep only confuse.
        # Matched on trial index, never on float time — the fill's time_s is
        # derived via ms and is not bit-equal to s/sr.
        rescued_trials = set()
        for anomaly, beep in zip(rescue_anomalies, rescued_beeps):
            index = valid_beeps.index(beep)
            anomaly['trial_name'] = f"Trial_{index + 1:03d}"
            rescued_trials.add(anomaly['trial_name'])
        beep_anomalies = [
            a for a in beep_anomalies
            if not (a['kind'] == 'filled_from_template' and a['trial_name'] in rescued_trials)
        ]
        beep_anomalies.extend(rescue_anomalies)
        beep_anomalies.sort(key=lambda a: a['time_s'])

    df_combined_timings = pd.merge(df_beep_timings, df_speech_hesitation_rel, on='trial_name', how='left')
    df_final_results = pd.merge(df_combined_timings, df_results, on='trial_name', how='left')

    # Trial slices start immediately after beep_end_ms, so relative speech timings use beep_end_ms.
    # RT columns are reported relative to beep_start_ms for manual comparison.
    beep_duration_ms = df_final_results['beep_end_ms'] - df_final_results['beep_start_ms']
    df_final_results['speech_start_ms_abs'] = df_final_results['beep_end_ms'] + df_final_results['speech_start_ms_rel']
    df_final_results['speech_end_ms_abs'] = df_final_results['beep_end_ms'] + df_final_results['speech_end_ms_rel']
    df_final_results['hesitation_start_ms_abs'] = df_final_results['beep_end_ms'] + df_final_results['hesitation_start_ms_rel']
    df_final_results['hesitation_end_ms_abs'] = df_final_results['beep_end_ms'] + df_final_results['hesitation_end_ms_rel']
    df_final_results['rt_first_speech_ms'] = df_final_results['rt_first_speech_ms'] + beep_duration_ms
    df_final_results['rt_main_response_ms'] = df_final_results['rt_main_response_ms'] + beep_duration_ms

    df_final_results = df_final_results[FINAL_COLUMNS]

    if df_final_results.empty:
        raise RuntimeError(f"No final results produced for {audio_path.name}")
    if df_final_results['beep_timestamp_global'].isna().any():
        missing_trials = df_final_results.loc[
            df_final_results['beep_timestamp_global'].isna(), 'trial_name'
        ].tolist()
        raise RuntimeError(f"Missing beep timings for trials: {missing_trials}")

    df_analysis = df_final_results[[
        'trial_name',
        'rt_first_speech_ms',
        'rt_main_response_ms',
        'response_type',
        'hesitation_pattern',
    ]]

    # The software-format export derives prefiller_present from the timings
    # (consistent with each row's own RT columns and with how the hand-edited
    # ground truth is scored), and carries the real per-trial VAD segment
    # count. The Full/Analysis CSVs above are unchanged by this.
    df_export_input = df_final_results.merge(
        df_results[['trial_name', 'segments_count']], on='trial_name', how='left'
    )
    df_export_input['prefiller_present'] = (
        df_export_input['rt_main_response_ms'] - df_export_input['rt_first_speech_ms']
    ) > cfg.PREFILLER_MIN_GAP_MS

    # 5. Write CSVs.
    csv_paths: dict[str, Path] = {}
    df_output = None
    if write_outputs:
        full_path = output_dir / f"{stem}_Full_Analysis_Results.csv"
        analysis_path = output_dir / f"{stem}_Analysis_Results.csv"
        output_path = output_dir / f"{stem}_output.csv"

        df_final_results.to_csv(full_path, index=False)
        df_analysis.to_csv(analysis_path, index=False)
        save_software_csv(
            df_export_input,
            audio_path=audio_path,
            output_path=output_path,
            anticipatory_threshold_ms=cfg.ANTICIPATORY_THRESHOLD_MS,
            timeout_threshold_ms=cfg.TIMEOUT_THRESHOLD_MS,
            next_beep_margin_s=cfg.NEXT_BEEP_MARGIN_S,
        )
        csv_paths = {"full": full_path, "analysis": analysis_path, "output": output_path}
        df_output = pd.read_csv(output_path)
        logger.info("Wrote %s, %s, %s", full_path.name, analysis_path.name, output_path.name)

        # Sidecar, written only when something did not pair 1:1 — the three
        # CSVs above keep their schema so clean recordings stay byte-identical.
        if beep_anomalies:
            report_path = output_dir / f"{stem}_beep_pairing_report.csv"
            pd.DataFrame(beep_anomalies).to_csv(report_path, index=False)
            csv_paths["pairing_report"] = report_path
            logger.warning("Wrote %s (%d anomalies)", report_path.name, len(beep_anomalies))
    else:
        from .export import build_software_export
        df_output = build_software_export(
            df_export_input,
            audio_path=audio_path,
            anticipatory_threshold_ms=cfg.ANTICIPATORY_THRESHOLD_MS,
            timeout_threshold_ms=cfg.TIMEOUT_THRESHOLD_MS,
            next_beep_margin_s=cfg.NEXT_BEEP_MARGIN_S,
        )

    progress("export", 1, 1)
    return LeximetraResult(
        df_full=df_final_results,
        df_analysis=df_analysis,
        df_output=df_output,
        slice_dir=slice_dir,
        csv_paths=csv_paths,
        beep_anomalies=beep_anomalies,
    )
