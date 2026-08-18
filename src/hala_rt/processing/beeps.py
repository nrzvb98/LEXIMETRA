"""Beep detection and trial slicing.

Two detectors coexist on purpose (same as the notebook):

- Template Matched v5.3 (`detect_beeps_template_matched`) drives the slicing:
  per template the bandpass band, duration floor and a phase-coherent
  tone-match gate are derived from the reference recording itself; a candidate
  is accepted if it matches ANY template, overlapping detections deduped by
  best match.
- The legacy fixed-band detector (`detect_beeps_legacy`) produces the beep
  timestamps written to the final CSVs (beep_timestamp_global / trial
  windows), exactly as the notebook's final-CSV cell always has.

`pair_beeps_to_slices` reconciles the two by beep START time. They used to be
joined on trial_name — i.e. by detection order — so any disagreement silently
misaligned every subsequent row (15 of 96 corpus recordings, drifting up to
69 s). The detectors no longer need to agree on beep count.

`rescue_short_beeps` runs after the template detector and fills the gaps it
left: on quiet recordings the trigger's hard-coded floor clips a beep to a few
milliseconds, so the duration gate discards it despite a near-perfect tone
match. The rescue slides the template along the recording instead, which is
amplitude-invariant, and keeps peaks that land where the detector found
nothing.
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


def merge_double_lobed_beeps(valid_beeps, sr, cfg: HalaConfig):
    """Collapse chains of detections that are lobes of one physical beep.

    Consecutive detections closer than BEEP_MERGE_MAX_GAP_S (start to start)
    are one beep heard as several lobes. The merged beep keeps the first
    lobe's start — beep onset is the RT anchor — and the last lobe's end, so
    the trial slice begins after all beep energy. A recording whose
    detections are all at least the threshold apart passes through untouched.

    Returns (merged_beeps, anomalies); each anomaly carries the merged
    (start, end) under 'beep' for the pipeline to stamp a trial name on.
    """
    max_gap = float(cfg.BEEP_MERGE_MAX_GAP_S)
    if max_gap <= 0 or len(valid_beeps) < 2:
        return list(valid_beeps), []

    chains = [[valid_beeps[0]]]
    for beep in valid_beeps[1:]:
        if (beep[0] - chains[-1][-1][0]) / sr < max_gap:
            chains[-1].append(beep)
        else:
            chains.append([beep])

    merged, anomalies = [], []
    for chain in chains:
        start = chain[0][0]
        end = max(e for _, e in chain)
        merged.append((start, end))
        if len(chain) > 1:
            lobes = ", ".join(f"{s / sr:.3f}s" for s, _ in chain)
            anomalies.append({
                'kind': 'merged_double_lobe',
                'trial_name': '',   # stamped by the pipeline once trials are numbered
                'time_s': start / sr,
                'duration_ms': (end - start) / sr * 1000,
                'detail': f'{len(chain)} detections within {max_gap:.1f}s are lobes of one beep '
                          f'(at {lobes}); kept first start and last end',
                'beep': (start, end),
            })

    if anomalies:
        logger.warning(
            "Lobe merge: %d detections were lobes of %d beeps; %d -> %d beeps total.",
            len(valid_beeps) - len(merged) + len(anomalies), len(anomalies),
            len(valid_beeps), len(merged),
        )
    return merged, anomalies


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


def _match_profile(y, sr, cfg: HalaConfig, tpl_path):
    """Normalised template match at EVERY sample offset, computed exactly.

    match(s) = |<z_s, tpl>| / (||z_s|| * ||tpl||) for the analytic, band-limited
    signal — the same phase-coherent measure the detector gates on, but
    evaluated everywhere instead of only where the envelope crossed a trigger.
    Being normalised it is amplitude-invariant: a beep 20 dB down scores the
    same as a loud one, which is precisely what the trigger floor gets wrong.

    Done as an FFT cross-correlation plus a sliding energy sum, so this costs
    one pass over the recording rather than one dot product per offset.

    Returns (profile, n, exact_at). The profile is fast but approximate near
    silence; `exact_at(i)` recomputes one offset without the shortcut, for
    confirming a candidate before it is accepted.
    """
    tpl, tpl_freq, _ = analyze_beep_template(tpl_path, target_sr=sr)
    sos = scipy.signal.butter(
        2,
        [tpl_freq - cfg.BEEP_BAND_HALF_WIDTH_HZ, tpl_freq + cfg.BEEP_BAND_HALF_WIDTH_HZ],
        'bandpass', fs=sr, output='sos',
    )
    z = scipy.signal.hilbert(scipy.signal.sosfiltfilt(sos, y))
    t = scipy.signal.hilbert(scipy.signal.sosfiltfilt(sos, tpl))
    n = len(t)
    tpl_norm = np.linalg.norm(t)

    def exact_at(i):
        """Match at one offset, window energy summed directly."""
        window = z[i:i + n]
        if len(window) < n:
            return 0.0
        energy = float(np.sum(np.abs(window) ** 2))
        if energy <= 0.0:
            return 0.0
        return float(np.abs(np.vdot(t, window)) / (np.sqrt(energy) * tpl_norm))

    if len(z) < n:
        return np.zeros(0), n, exact_at

    numerator = np.abs(scipy.signal.correlate(z, t, mode='valid'))
    cumulative = np.concatenate(([0.0], np.cumsum(np.abs(z) ** 2)))
    energy = cumulative[n:] - cumulative[:-n]
    denominator = np.sqrt(np.maximum(energy, 1e-20)) * tpl_norm
    profile = numerator / denominator

    # That sliding energy is a difference of two large running totals, and float64
    # cannot resolve it once they dwarf the window. On one corpus recording the
    # total stands at 4.7e4 by the final second while a near-silent window holds
    # 1.6e-10: the subtraction cancels to exactly zero, the 1e-20 floor takes
    # over, and the ratio explodes to 36958 instead of collapsing to 0.29.
    #
    # A normalised match cannot exceed 1.0, so anything that does is a
    # normalisation failure rather than a beep. Clear it HERE, before any
    # peak-picking: find_peaks keeps only the tallest peak per `distance` window,
    # so a spurious 36958 left in place would not merely add itself -- it would
    # suppress every genuine candidate within BEEP_RESCUE_MIN_GAP_S of it.
    profile[~np.isfinite(profile) | (profile > 1.0)] = 0.0
    return profile, n, exact_at


def rescue_short_beeps(y, sr, valid_beeps, cfg: HalaConfig):
    """Recover beeps the trigger floor hid from the detector.

    Additive only: the detector's own beeps are never touched, re-measured or
    re-ordered. This looks exclusively at the gaps between them, so a recording
    whose beeps the detector already found gets nothing added and its output is
    unchanged bit for bit. Returns (rescued_beeps, anomalies).

    See HalaConfig.BEEP_RESCUE_* for why this is a second pass rather than a
    better-behaved threshold in the detector itself.
    """
    if not cfg.BEEP_RESCUE_ENABLED or not valid_beeps:
        return [], []

    # File guard: a recording whose beeps already sit closer together than a
    # trial is counting double-lobed beeps twice. Filling its "gaps" would
    # compound that, so leave it alone.
    starts = np.array([s for s, _ in valid_beeps], dtype=float)
    if len(starts) > 1:
        min_existing_gap = float(np.diff(starts).min()) / sr
        if min_existing_gap < cfg.BEEP_RESCUE_MIN_EXISTING_GAP_S:
            logger.info(
                "Beep rescue skipped: existing beeps are %.2f s apart at the closest, "
                "below the %.2f s over-detection guard.",
                min_existing_gap, cfg.BEEP_RESCUE_MIN_EXISTING_GAP_S,
            )
            return [], []

    profile, beep_len = None, 0
    exact_scorers = []
    for tpl_path in cfg.resolved_template_paths():
        if not os.path.isfile(tpl_path):
            continue
        candidate_profile, n, exact_at = _match_profile(y, sr, cfg, tpl_path)
        if not len(candidate_profile):
            continue
        beep_len = max(beep_len, n)
        exact_scorers.append(exact_at)
        if profile is None:
            profile = candidate_profile
        else:  # a beep counts if it matches ANY template, as in the detector
            shared = min(len(profile), len(candidate_profile))
            profile = np.maximum(profile[:shared], candidate_profile[:shared])
    if profile is None or not len(profile):
        return [], []

    # Peak-picking with a minimum separation is what keeps a double-lobed beep
    # from being read as two: the lobes are ~110-140 ms apart, far inside the
    # separation, so only the better-matching lobe survives.
    separation = int(cfg.BEEP_RESCUE_MIN_GAP_S * sr)
    peaks, _ = scipy.signal.find_peaks(
        profile, height=cfg.BEEP_RESCUE_MATCH_MIN, distance=max(1, separation)
    )

    # Confirm every candidate with an exact energy sum before it can be accepted.
    # Clamping the profile above catches the case where cancellation leaves zero,
    # but it cannot catch the case where it leaves a small POSITIVE residue: at
    # this recording's magnitudes, ~2.6 ULP of leftover is enough to turn a true
    # 0.29 into an apparent 0.85 without ever exceeding 1.0. There are only a
    # handful of peaks per recording, so being exact here is free.
    candidates = []
    for peak in peaks:
        score = max(scorer(int(peak)) for scorer in exact_scorers)
        if score >= cfg.BEEP_RESCUE_MATCH_MIN:
            candidates.append((int(peak), score))

    kept = []
    # Best match first, so which peak survives a clash is decided by fit rather
    # than by scan order.
    for peak, score in sorted(candidates, key=lambda p: -p[1]):
        start, end = int(peak), int(peak + beep_len)
        neighbours = list(valid_beeps) + [(k[0], k[1]) for k in kept]
        if any(start < other_end + separation and other_start < end + separation
               for other_start, other_end in neighbours):
            continue
        kept.append((start, end, float(score)))
    kept.sort(key=lambda k: k[0])

    anomalies = [{
        'kind': 'rescued_beep',
        'trial_name': '',            # stamped by the pipeline once trials are numbered
        'time_s': start / sr,
        'duration_ms': (end - start) / sr * 1000,
        'detail': 'too quiet for the detector trigger; found by template match and accepted',
        'tone_match': round(score, 3),
    } for start, end, score in kept]

    if kept:
        logger.warning(
            "Beep rescue: recovered %d beep(s) the trigger floor hid (match %.2f-%.2f).",
            len(kept), min(k[2] for k in kept), max(k[2] for k in kept),
        )
        if len(kept) > len(valid_beeps):
            logger.warning(
                "Beep rescue supplied MORE beeps (%d) than the detector accepted (%d) — this "
                "recording was largely below the trigger floor; check it by hand.",
                len(kept), len(valid_beeps),
            )
    return [(s, e) for s, e, _ in kept], anomalies

def tone_match_scores(y, sr, cfg: HalaConfig, start_samples) -> list[float]:
    """Best phase-coherent template match at each start sample (audit only).

    Same measure the template detector gates on, recomputed for events it did
    not accept, so the pairing report can show how close a dropped legacy
    detection was to `BEEP_MATCH_THRESHOLD`.
    """
    if not len(start_samples):
        return []

    best = [0.0] * len(start_samples)
    for tpl_path in cfg.resolved_template_paths():
        if not os.path.isfile(tpl_path):
            continue
        tpl, tpl_freq, _ = analyze_beep_template(tpl_path, target_sr=sr)
        sos_beep = scipy.signal.butter(
            2,
            [tpl_freq - cfg.BEEP_BAND_HALF_WIDTH_HZ, tpl_freq + cfg.BEEP_BAND_HALF_WIDTH_HZ],
            'bandpass', fs=sr, output='sos',
        )
        y_beep = scipy.signal.sosfiltfilt(sos_beep, y)
        tpl_analytic = scipy.signal.hilbert(scipy.signal.sosfiltfilt(sos_beep, tpl))
        tpl_norm = np.linalg.norm(tpl_analytic)

        for i, s in enumerate(start_samples):
            seg = y_beep[int(s):int(s) + len(tpl_analytic)]
            if len(seg) < len(tpl_analytic):
                continue
            z = scipy.signal.hilbert(seg)
            match = float(np.abs(np.vdot(z, tpl_analytic)) / (np.linalg.norm(z) * tpl_norm + 1e-12))
            best[i] = max(best[i], match)
    return best


def pair_beeps_to_slices(valid_beeps, df_legacy: pd.DataFrame, sr, cfg: HalaConfig):
    """Match legacy beep timings to trial slices by START time, not by index.

    The template detector defines the trial set — one slice per accepted beep,
    `Trial_001..N` in time order. The legacy detector numbers its own rows
    `Trial_001..M` in *its* detection order. Joining those two on trial_name
    (as the notebook always did) pairs the k-th detection of one with the k-th
    of the other, so a single disagreement silently staples one beep's
    timestamp to a different beep's speech for the rest of the recording.

    Here every slice keeps its own beep. Returns
    ``(df_timings, anomalies)`` where df_timings has one row per slice in slice
    order, carrying the matched legacy values verbatim, and anomalies is a list
    of dicts describing every event that did not pair one-to-one.

    Legacy rows with no slice are dropped: the template detector is the
    authority on what counts as a trial, and these events were not accepted
    into it. (They are not necessarily noise — many are the second lobe of a
    double-lobed beep — hence the tone-match value in the anomaly record.)
    """
    tol_ms = float(cfg.BEEP_PAIR_TOLERANCE_MS)
    tpl_start_ms = np.array([s / sr * 1000 for s, _ in valid_beeps], dtype=float)
    tpl_end_ms = np.array([e / sr * 1000 for _, e in valid_beeps], dtype=float)
    leg_start_ms = df_legacy['beep_start_ms'].to_numpy(dtype=float)

    # The tolerance is only safe if it cannot reach a neighbouring beep. Check
    # that against this recording rather than trusting the constant.
    gaps = [np.diff(a) for a in (tpl_start_ms, leg_start_ms) if len(a) > 1]
    min_gap_ms = float(min(g.min() for g in gaps)) if gaps else float('inf')
    if tol_ms >= 0.5 * min_gap_ms:
        raise RuntimeError(
            f"Beep pairing tolerance {tol_ms:.1f} ms is not safely below half the smallest "
            f"beep-to-beep gap in this recording ({min_gap_ms:.1f} ms). Pairing would be "
            f"ambiguous; lower BEEP_PAIR_TOLERANCE_MS or fix beep detection first."
        )

    # Monotone two-pointer merge: advance whichever sequence is behind. This
    # gives a strictly increasing, one-to-one match by construction — a plain
    # nearest-neighbour argmin does not (in 520 it maps 12 slices onto legacy
    # rows already claimed by their neighbours).
    matched_legacy: list[int | None] = [None] * len(tpl_start_ms)
    unmatched_legacy: list[int] = []
    i = j = 0
    while i < len(tpl_start_ms) and j < len(leg_start_ms):
        delta = leg_start_ms[j] - tpl_start_ms[i]
        if abs(delta) <= tol_ms:
            matched_legacy[i] = j
            i += 1
            j += 1
        elif delta < 0:
            unmatched_legacy.append(j)
            j += 1
        else:
            i += 1
    unmatched_legacy.extend(range(j, len(leg_start_ms)))

    unmatched_slices = [k for k, m in enumerate(matched_legacy) if m is None]
    if unmatched_slices and not cfg.ALLOW_TEMPLATE_BEEP_FALLBACK:
        names = ", ".join(f"Trial_{k + 1:03d}" for k in unmatched_slices[:10])
        more = f" (+{len(unmatched_slices) - 10} more)" if len(unmatched_slices) > 10 else ""
        raise RuntimeError(
            f"{len(unmatched_slices)} trial slice(s) have no legacy beep within {tol_ms:.1f} ms: "
            f"{names}{more}. Set ALLOW_TEMPLATE_BEEP_FALLBACK to use the slice's own beep timing."
        )

    rows = []
    for k, legacy_idx in enumerate(matched_legacy):
        trial_name = f"Trial_{k + 1:03d}"
        if legacy_idx is None:
            # The template beep IS the slice boundary, so this timing is exact
            # by construction for the downstream beep_end -> speech arithmetic.
            rows.append({
                'trial_name': trial_name,
                'beep_timestamp_global': tpl_start_ms[k] / 1000,
                'beep_start_ms': tpl_start_ms[k],
                'beep_end_ms': tpl_end_ms[k],
            })
        else:
            # Carried verbatim: recomputing (e.g. timestamp * 1000) can differ
            # in the last ULP and break the byte-identical regression gate.
            src = df_legacy.iloc[legacy_idx]
            rows.append({
                'trial_name': trial_name,
                'beep_timestamp_global': src['beep_timestamp_global'],
                'beep_start_ms': src['beep_start_ms'],
                'beep_end_ms': src['beep_end_ms'],
            })

    anomalies = [{
        'kind': 'filled_from_template',
        'trial_name': f"Trial_{k + 1:03d}",
        'time_s': tpl_start_ms[k] / 1000,
        'duration_ms': tpl_end_ms[k] - tpl_start_ms[k],
        'detail': 'legacy detector found no beep here; used the slice\'s own beep timing',
    } for k in unmatched_slices]

    for j in unmatched_legacy:
        start_ms = leg_start_ms[j]
        nearest = float(np.min(np.abs(tpl_start_ms - start_ms))) if len(tpl_start_ms) else float('nan')
        anomalies.append({
            'kind': 'dropped_legacy_beep',
            'trial_name': '',
            'time_s': start_ms / 1000,
            'duration_ms': float(df_legacy.iloc[j]['beep_end_ms']) - start_ms,
            'detail': f'not accepted by the template detector; {nearest:.0f} ms from the nearest slice beep',
        })

    if anomalies:
        logger.warning(
            "Beep pairing: %d slice(s) filled from template timing, %d legacy detection(s) dropped "
            "(template %d, legacy %d).",
            len(unmatched_slices), len(unmatched_legacy), len(tpl_start_ms), len(leg_start_ms),
        )
    else:
        logger.info("Beep pairing: %d beeps matched one-to-one.", len(tpl_start_ms))

    return pd.DataFrame(rows), anomalies


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
