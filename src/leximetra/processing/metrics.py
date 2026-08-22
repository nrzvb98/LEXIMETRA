"""Burst merging, reaction-time and hesitation metrics per trial.

The main-response logic estimates a later "main word" onset independently of
the hesitation classification: a valley in the smoothed energy contour whose
floor reaches the segment's own silence floor marks a filler->word pause,
while intra-word stop-gaps do not.
"""
from __future__ import annotations

import numpy as np

from .config import LeximetraConfig
from .vad import frame_rms_db


def segment_to_bursts(speech_segments, sr, cfg: LeximetraConfig):
    """Merge speech segments (samples) into bursts (ms) with gaps <= MAX_GAP_FOR_MERGE_MS."""
    merged_bursts = []

    # Ensure segments are sorted by start time, though Silero usually provides them sorted
    speech_segments.sort(key=lambda x: x['start'])

    for segment in speech_segments:
        segment_start_ms = (segment['start'] / sr) * 1000
        segment_end_ms = (segment['end'] / sr) * 1000
        segment_duration_ms = segment_end_ms - segment_start_ms

        if not merged_bursts:
            merged_bursts.append({
                'start_ms': segment_start_ms,
                'end_ms': segment_end_ms,
                'duration_ms': segment_duration_ms
            })
        else:
            last_burst = merged_bursts[-1]
            gap_ms = segment_start_ms - last_burst['end_ms']

            if gap_ms <= cfg.MAX_GAP_FOR_MERGE_MS:
                last_burst['end_ms'] = segment_end_ms
                last_burst['duration_ms'] = last_burst['end_ms'] - last_burst['start_ms']
            else:
                merged_bursts.append({
                    'start_ms': segment_start_ms,
                    'end_ms': segment_end_ms,
                    'duration_ms': segment_duration_ms
                })
    return merged_bursts


def smooth_energy(dbs, window=3):
    if len(dbs) < window:
        return dbs
    return np.convolve(dbs, np.ones(window) / window, mode='same')


def burst_to_samples(burst, sr):
    start = int(burst['start_ms'] * sr / 1000)
    end = int(burst['end_ms'] * sr / 1000)
    return start, end


def has_immediate_rise(start_sample, end_sample, y, sr, cfg: LeximetraConfig):
    rise_end = min(end_sample, start_sample + int(cfg.MAIN_RESPONSE_IMMEDIATE_RISE_MS * sr / 1000))
    frame_starts, dbs = frame_rms_db(
        y, start_sample, rise_end, sr,
        frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
        hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
    )
    if len(dbs) < 2:
        return False
    return float(np.max(dbs) - dbs[0]) >= cfg.MAIN_RESPONSE_IMMEDIATE_RISE_DB


def second_burst_energy_onset_ms(b1, b2, y, sr, cfg: LeximetraConfig):
    second_start, second_end = burst_to_samples(b2, sr)
    search_start_ms = max(
        b1['end_ms'] + cfg.MAIN_RESPONSE_MIN_PAUSE_MS,
        b2['start_ms'] - cfg.MAIN_RESPONSE_SECOND_BURST_BACKSCAN_MS,
    )
    search_start = int(search_start_ms * sr / 1000)
    search_end = min(
        second_end,
        second_start + int(cfg.MAIN_RESPONSE_IMMEDIATE_RISE_MS * sr / 1000),
    )
    frame_starts, dbs = frame_rms_db(
        y, search_start, search_end, sr,
        frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
        hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
    )
    if len(dbs) < cfg.MAIN_RESPONSE_SECOND_BURST_ONSET_RUN_FRAMES:
        return b2['start_ms']

    active = dbs >= cfg.MAIN_RESPONSE_SECOND_BURST_ONSET_DB
    run = 0
    for idx, is_active in enumerate(active):
        run = run + 1 if is_active else 0
        if run >= cfg.MAIN_RESPONSE_SECOND_BURST_ONSET_RUN_FRAMES:
            onset_sample = frame_starts[idx - cfg.MAIN_RESPONSE_SECOND_BURST_ONSET_RUN_FRAMES + 1]
            early_peak_db = float(np.max(dbs[:idx + 1]))
            if early_peak_db > cfg.MAIN_RESPONSE_SECOND_BURST_EARLY_MAX_DB:
                return b2['start_ms']
            return onset_sample / sr * 1000

    return b2['start_ms']


def find_main_response_onset_ms(start_sample, end_sample, y, sr, cfg: LeximetraConfig, min_delay_ms=None):
    if min_delay_ms is None:
        min_delay_ms = cfg.MAIN_RESPONSE_MIN_DELAY_MS
    frame_starts, dbs = frame_rms_db(
        y, start_sample, end_sample, sr,
        frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
        hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
    )
    if len(dbs) < 7:
        return None

    smoothed = smooth_energy(dbs)
    floor_db = float(np.percentile(smoothed, 10))
    min_before = int(min_delay_ms / cfg.BOUNDARY_REFINE_HOP_MS)
    min_after = int(cfg.MAIN_RESPONSE_MIN_WORD_MS / cfg.BOUNDARY_REFINE_HOP_MS)
    best = None

    for idx in range(min_before, len(smoothed) - min_after):
        if not (smoothed[idx] <= smoothed[idx - 1] and smoothed[idx] <= smoothed[idx + 1]):
            continue

        left_peak = float(np.max(smoothed[:idx]))
        right_peak = float(np.max(smoothed[idx + 1:]))
        prominence = min(left_peak, right_peak) - smoothed[idx]
        floor_rel_db = smoothed[idx] - floor_db
        strong_floor_valley = (
            prominence >= cfg.MAIN_RESPONSE_VALLEY_PROM_DB and
            floor_rel_db <= cfg.MAIN_RESPONSE_VALLEY_FLOOR_REL_DB and
            right_peak >= left_peak
        )
        moderate_rising_valley = (
            prominence >= cfg.MAIN_RESPONSE_MODERATE_PROM_DB and
            floor_rel_db <= cfg.MAIN_RESPONSE_MODERATE_FLOOR_REL_DB and
            right_peak - left_peak >= cfg.MAIN_RESPONSE_RISE_GAIN_DB
        )
        if not (strong_floor_valley or moderate_rising_valley):
            continue

        after = smoothed[idx + 1:idx + 1 + min_after * 2]
        if np.sum(after >= right_peak - 12) < min_after:
            continue

        if best is None or prominence > best[0]:
            best = (prominence, idx)

    if best is None:
        return None

    prominence, valley_idx = best
    rise_threshold = smoothed[valley_idx] + max(4.0, prominence * 0.3)
    rise = np.where(smoothed[valley_idx + 1:] >= rise_threshold)[0]
    onset_idx = valley_idx + 1 + (rise[0] if len(rise) else 1)
    return frame_starts[onset_idx] / sr * 1000


def choose_main_response_ms(merged_bursts, y, sr, first_speech_onset_ms, cfg: LeximetraConfig):
    main_response_ms = first_speech_onset_ms

    if len(merged_bursts) >= 2:
        b1 = merged_bursts[0]
        b2 = merged_bursts[1]
        pause_duration_ms = b2['start_ms'] - b1['end_ms']
        if b2['duration_ms'] >= cfg.MAIN_RESPONSE_MIN_WORD_MS and pause_duration_ms >= cfg.MAIN_RESPONSE_MIN_PAUSE_MS:
            main_response_ms = b2['start_ms']

            if y is not None:
                energy_onset_ms = second_burst_energy_onset_ms(b1, b2, y, sr, cfg)
                boundary_adjusted = abs(energy_onset_ms - b2['start_ms']) > 1.0
                main_response_ms = energy_onset_ms
                main_start = int(main_response_ms * sr / 1000)
                _, second_end = burst_to_samples(b2, sr)
                if not boundary_adjusted and not has_immediate_rise(main_start, second_end, y, sr, cfg):
                    later_onset_ms = find_main_response_onset_ms(
                        main_start,
                        second_end,
                        y,
                        sr,
                        cfg,
                        min_delay_ms=cfg.MAIN_RESPONSE_SECOND_BURST_MIN_DELAY_MS,
                    )
                    if (
                        later_onset_ms is not None and
                        later_onset_ms - main_response_ms >= cfg.MAIN_RESPONSE_SECOND_BURST_MIN_ADJUST_MS
                    ):
                        main_response_ms = later_onset_ms

    elif len(merged_bursts) == 1 and y is not None:
        first_start, first_end = burst_to_samples(merged_bursts[0], sr)
        later_onset_ms = find_main_response_onset_ms(first_start, first_end, y, sr, cfg)
        if later_onset_ms is not None and later_onset_ms - first_speech_onset_ms >= cfg.MAIN_RESPONSE_MIN_DELAY_MS:
            main_response_ms = later_onset_ms

    return main_response_ms


def process_trial_data(trial_name, speech_segments, sr, cfg: LeximetraConfig, y=None):
    """Compute per-trial RT/hesitation metrics.

    Returns (trial_results dict, merged_bursts) — the bursts are reused for the
    relative-timings columns without recomputing.
    """
    trial_results = {
        'trial_name': trial_name,
        'rt_first_speech_ms': np.nan,
        'rt_main_response_ms': np.nan,
        'response_type': 'No Response',
        'hesitation_pattern': False,
        'segments_count': len(speech_segments)
    }

    if not speech_segments:
        return trial_results, []

    merged_bursts = segment_to_bursts(speech_segments, sr, cfg)

    first_speech_onset_ms = merged_bursts[0]['start_ms']
    trial_results['rt_first_speech_ms'] = first_speech_onset_ms

    if first_speech_onset_ms <= cfg.ANTICIPATORY_THRESHOLD_MS:
        trial_results['response_type'] = 'Anticipatory'
    elif first_speech_onset_ms > cfg.TIMEOUT_THRESHOLD_MS:
        trial_results['response_type'] = 'Timeout'
    else:
        trial_results['response_type'] = 'Valid Response'

    trial_results['rt_main_response_ms'] = choose_main_response_ms(
        merged_bursts, y, sr, first_speech_onset_ms, cfg
    )

    # Identify hesitation pattern for classification only. Main-response timing is
    # estimated independently because a later main word can occur without a labeled prefiller.
    if len(merged_bursts) >= 2:
        b1 = merged_bursts[0]
        b2 = merged_bursts[1]
        pause_duration_ms = b2['start_ms'] - b1['end_ms']

        if (b1['duration_ms'] >= cfg.MIN_FIRST_BURST_DUR_MS and
                b2['duration_ms'] >= cfg.MIN_SECOND_BURST_DUR_MS and
                pause_duration_ms >= cfg.MIN_PAUSE_BETWEEN_BURSTS_MS):
            trial_results['hesitation_pattern'] = True

    if np.isnan(first_speech_onset_ms) or first_speech_onset_ms > cfg.TIMEOUT_THRESHOLD_MS:
        trial_results['response_type'] = 'Timeout'

    return trial_results, merged_bursts


def relative_timings(trial_name, hesitation_pattern, merged_bursts):
    """Slice-relative speech/hesitation window for one trial."""
    speech_start_ms_rel = np.nan
    speech_end_ms_rel = np.nan
    hesitation_start_ms_rel = np.nan
    hesitation_end_ms_rel = np.nan

    if merged_bursts:
        speech_start_ms_rel = merged_bursts[0]['start_ms']
        speech_end_ms_rel = merged_bursts[-1]['end_ms']

    if hesitation_pattern and len(merged_bursts) >= 2:
        hesitation_start_ms_rel = merged_bursts[0]['end_ms']
        hesitation_end_ms_rel = merged_bursts[1]['start_ms']

    return {
        'trial_name': trial_name,
        'speech_start_ms_rel': speech_start_ms_rel,
        'speech_end_ms_rel': speech_end_ms_rel,
        'hesitation_start_ms_rel': hesitation_start_ms_rel,
        'hesitation_end_ms_rel': hesitation_end_ms_rel
    }
