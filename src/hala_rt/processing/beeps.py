"""Beep detection and trial slicing.

Two detectors coexist on purpose (same as the notebook):

- Template Matched v5.3 (`detect_beeps_template_matched`) drives the slicing:
  per template the bandpass band, duration floor and a phase-coherent
  tone-match gate are derived from the reference recording itself; a candidate
  is accepted if it matches ANY template, overlapping detections deduped by
  best match.
- The legacy fixed-band detector (`detect_beeps_legacy`) produces the beep
  timestamps written to the final CSVs (beep_timestamp_global / trial
  windows), exactly as the notebook's final-CSV cell always has. The two
  detectors must agree on beep count for the outputs to align.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.signal
import soundfile as sf

from .audio_io import load_audio_app_style
from .config import HalaConfig

logger = logging.getLogger("hala_rt.processing")


def analyze_beep_template(path, target_sr=16000):
    """Load a reference beep and measure its dominant frequency and duration.

    The template is trimmed to its active region (envelope above 10% of peak)
    so leading/trailing silence in the file doesn't skew the duration.
    """
    tpl, sr = load_audio_app_style(str(path), target_sr=target_sr)
    env = np.abs(scipy.signal.hilbert(tpl))
    active = np.where(env > 0.1 * env.max())[0]
    tpl = tpl[active[0]:active[-1] + 1]

    spec = np.abs(np.fft.rfft(tpl * np.hanning(len(tpl))))
    freqs = np.fft.rfftfreq(len(tpl), 1 / sr)
    peak_freq = float(freqs[np.argmax(spec)])
    duration_s = len(tpl) / sr
    return tpl, peak_freq, duration_s


def detect_beeps_template_matched(y, sr, cfg: HalaConfig):
    """Return [(start_sample, end_sample), ...] of accepted beeps."""
    # Wide (Noise Reference) — shared across templates
    sos_wide = scipy.signal.butter(2, [200, 4000], 'bandpass', fs=sr, output='sos')
    y_wide = scipy.signal.sosfiltfilt(sos_wide, y)

    accepted = []  # (start, end, match, template_index)

    for tpl_idx, tpl_path in enumerate(cfg.resolved_template_paths()):
        if not os.path.isfile(tpl_path):
            logger.warning("Template not found, skipping: %s", tpl_path)
            continue

        tpl, tpl_freq, tpl_dur = analyze_beep_template(tpl_path, target_sr=sr)
        band_lo = tpl_freq - cfg.BEEP_BAND_HALF_WIDTH_HZ
        band_hi = tpl_freq + cfg.BEEP_BAND_HALF_WIDTH_HZ
        logger.info(
            "Template %d: %s | %.0f Hz | %.0f ms | band %.0f-%.0f Hz",
            tpl_idx + 1, os.path.basename(tpl_path), tpl_freq, tpl_dur * 1000, band_lo, band_hi,
        )

        # Target (Beep) — band centered on this template's dominant frequency
        sos_beep = scipy.signal.butter(2, [band_lo, band_hi], 'bandpass', fs=sr, output='sos')
        y_beep = scipy.signal.sosfiltfilt(sos_beep, y)

        # Band-filtered analytic template for the tone-match check
        tpl_band = scipy.signal.sosfiltfilt(sos_beep, tpl)
        tpl_analytic = scipy.signal.hilbert(tpl_band)
        tpl_norm = np.linalg.norm(tpl_analytic)

        # Envelope & trigger
        env = np.abs(scipy.signal.hilbert(y_beep))
        noise_floor = np.median(env)
        peak_level = np.percentile(env, 99.5)
        trigger = max(noise_floor * 5, peak_level * 0.1, 0.005)

        is_loud = env > trigger
        diffs = np.diff(np.concatenate(([0], is_loud, [0])))
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]

        MIN_DURATION_HARD = cfg.BEEP_MIN_DUR_FRACTION * tpl_dur
        PURITY_THRESHOLD = cfg.BEEP_PURITY_THRESHOLD

        def tone_match(s):
            """Phase-coherent match between a candidate and the template tone.

            ~1.0 for the actual beep (same frequency, coherent over the full
            template length); low (<0.4) for speech that merely has energy in
            the beep band. Insensitive to level and to constant phase offset.
            """
            seg = y_beep[s:s + len(tpl_band)]
            if len(seg) < len(tpl_band):
                return 0.0
            z = scipy.signal.hilbert(seg)
            return float(np.abs(np.vdot(z, tpl_analytic)) / (np.linalg.norm(z) * tpl_norm + 1e-12))

        for s, e in zip(starts, ends):
            dur = (e - s) / sr

            check_len = min(e - s, len(tpl_band))
            slice_beep = y_beep[s: s + check_len]
            slice_wide = y_wide[s: s + check_len]

            rms_beep = np.sqrt(np.mean(slice_beep ** 2))
            rms_wide = np.sqrt(np.mean(slice_wide ** 2)) + 1e-9
            purity = rms_beep / rms_wide
            match = tone_match(s)

            if dur < MIN_DURATION_HARD:
                status = f"too short (<{MIN_DURATION_HARD:.3f}s)"
            elif purity < PURITY_THRESHOLD:
                status = f"too dirty ({purity:.2f})"
            elif match < cfg.BEEP_MATCH_THRESHOLD:
                status = f"no tone match ({match:.2f})"
            else:
                status = "ACCEPT"
                accepted.append((s, e, match, tpl_idx))

            if status == "ACCEPT" or dur > 0.05:
                logger.debug(
                    "  %8.3fs | %6.3fs | purity %5.2f | match %5.2f | %s",
                    s / sr, dur, purity, match, status,
                )

    # Merge across templates: the same physical beep can be detected by several
    # templates; keep the detection with the best match score whenever intervals overlap.
    accepted.sort(key=lambda b: b[0])
    merged = []
    for beep in accepted:
        if merged and beep[0] < merged[-1][1]:  # overlaps previous detection
            if beep[2] > merged[-1][2]:
                merged[-1] = beep
        else:
            merged.append(beep)

    valid_beeps = [(s, e) for s, e, _, _ in merged]
    logger.info("Merged %d detections into %d beeps across templates.", len(accepted), len(valid_beeps))
    return valid_beeps


def slice_trials(y, sr, valid_beeps, slice_dir, cfg: HalaConfig):
    """Write one WAV per trial (beep END -> next beep start, or +SLICE_TAIL_S).

    Slices are written as 16-bit PCM (soundfile's WAV default) and downstream
    VAD reads them back from disk — the quantization round-trip is part of the
    validated pipeline behavior, so do not switch this to in-memory float32.
    """
    slice_dir = Path(slice_dir)
    slice_dir.mkdir(parents=True, exist_ok=True)
    slice_files = []

    for i, (s, e) in enumerate(valid_beeps):
        t_start = e
        t_end = valid_beeps[i + 1][0] if i < len(valid_beeps) - 1 else t_start + int(cfg.SLICE_TAIL_S * sr)
        t_end = min(t_end, len(y))

        audio_slice = y[t_start:t_end]
        fname = slice_dir / f"Trial_{i + 1:03d}.wav"
        sf.write(str(fname), audio_slice, sr)
        slice_files.append(fname)

    logger.info("Saved %d trial slices to %s", len(slice_files), slice_dir)
    return slice_files


def detect_beeps_legacy(y, sr, cfg: HalaConfig) -> pd.DataFrame:
    """Fixed-band beep timings for the final CSV (notebook's final-CSV cell, verbatim)."""
    sos_beep = scipy.signal.butter(
        2, [cfg.LEGACY_BEEP_BAND_LO_HZ, cfg.LEGACY_BEEP_BAND_HI_HZ], 'bandpass', fs=sr, output='sos'
    )
    y_beep = scipy.signal.sosfiltfilt(sos_beep, y)

    sos_wide = scipy.signal.butter(2, [200, 4000], 'bandpass', fs=sr, output='sos')
    y_wide = scipy.signal.sosfiltfilt(sos_wide, y)

    env = np.abs(scipy.signal.hilbert(y_beep))
    trigger = max(np.median(env) * 5, np.percentile(env, 99.5) * 0.1, 0.005)
    is_loud = env > trigger
    diffs = np.diff(np.concatenate(([0], is_loud.astype(int), [0])))
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]

    rows = []
    for s, e in zip(starts, ends):
        dur = (e - s) / sr
        check_len = min(e - s, int(0.1 * sr))
        if check_len <= 0:
            continue

        rms_beep = np.sqrt(np.mean(y_beep[s:s + check_len] ** 2))
        rms_wide = np.sqrt(np.mean(y_wide[s:s + check_len] ** 2)) + 1e-9
        purity = rms_beep / rms_wide

        if dur >= cfg.LEGACY_BEEP_MIN_DUR_S and purity >= cfg.BEEP_PURITY_THRESHOLD:
            beep_timestamp_global = s / sr
            rows.append({
                'trial_name': f'Trial_{len(rows) + 1:03d}',
                'beep_timestamp_global': beep_timestamp_global,
                'beep_start_ms': beep_timestamp_global * 1000,
                'beep_end_ms': (e / sr) * 1000,
            })

    return pd.DataFrame(rows)
