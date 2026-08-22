"""Silero VAD plus the notebook's per-trial boundary refinement.

Refinement avoids adding a global offset: each detected segment is
trimmed/split using its own local energy profile. The onset clip-guard keeps
Silero's soft onset whenever the peak-relative refinement would clip a gradual
speech ramp (soft-onset fix validated against the hand-edited ground truth).
"""
from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

import numpy as np
import torch

from .audio_io import load_audio_app_style
from .config import HalaConfig

logger = logging.getLogger("leximetra.processing")

_MODEL_CACHE = None

SILERO_DIR_ENV = "HALA_SILERO_DIR"
# A silero-vad checkout shipped inside the package, if one was placed there.
# Absent in this repo (torch.hub's cache serves development); a host app that
# must run offline can vendor one here instead of fetching from GitHub.
_BUNDLED_SILERO_DIR = Path(__file__).resolve().parent / "silero"


def _local_silero_dir():
    """Return a local silero-vad checkout to load, or None to fetch it.

    Checked in order: the ``HALA_SILERO_DIR`` override, then a copy bundled
    inside the package. A bad override is an error rather than a silent
    fallback -- a packaged app that quietly reaches for GitHub instead of the
    copy it shipped would fail later, offline, in front of a user.
    """
    override = os.environ.get(SILERO_DIR_ENV)
    if override:
        candidate = Path(override)
        if not (candidate / "hubconf.py").is_file():
            raise RuntimeError(
                f"{SILERO_DIR_ENV} is set to {candidate}, which is not a "
                "silero-vad checkout (no hubconf.py)."
            )
        return candidate
    if (_BUNDLED_SILERO_DIR / "hubconf.py").is_file():
        return _BUNDLED_SILERO_DIR
    return None


def get_model():
    """Lazy-load Silero VAD once per process. Returns (model, get_speech_ts)."""
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        local_dir = _local_silero_dir()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if local_dir is not None:
                logger.debug("Loading Silero VAD from %s", local_dir)
                model, utils = torch.hub.load(
                    repo_or_dir=str(local_dir),
                    model='silero_vad',
                    source='local',
                    onnx=False,
                )
            else:
                model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False,
                    trust_repo=True,
                )
        (get_speech_ts, _, _, _, _) = utils
        _MODEL_CACHE = (model, get_speech_ts)
    return _MODEL_CACHE


def read_audio_safe(path, target_sr=16000):
    y, sr = load_audio_app_style(str(path), target_sr=target_sr)
    return torch.FloatTensor(y).unsqueeze(0), y, sr


def frame_rms_db(y, start, end, sr, frame_ms=20, hop_ms=5):
    frame_len = max(1, int(frame_ms * sr / 1000))
    hop_len = max(1, int(hop_ms * sr / 1000))
    start = max(0, int(start))
    end = min(len(y), int(end))
    if end - start < frame_len:
        return np.array([start]), np.array([-120.0])

    frame_starts = np.arange(start, end - frame_len + 1, hop_len)
    dbs = []
    for frame_start in frame_starts:
        frame = y[frame_start:frame_start + frame_len]
        rms = float(np.sqrt(np.mean(frame ** 2)))
        dbs.append(-120.0 if rms <= 1e-12 else 20 * np.log10(rms))
    return frame_starts, np.asarray(dbs)


def recover_pre_vad_onset(original_start, end, y, sr, cfg: HalaConfig):
    if original_start < int(cfg.PRE_VAD_MIN_ORIGINAL_START_MS * sr / 1000):
        return original_start

    search_start = max(0, int(original_start - cfg.PRE_VAD_LOOKBACK_MS * sr / 1000))
    frame_starts, dbs = frame_rms_db(
        y, search_start, end, sr,
        frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
        hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
    )
    if len(dbs) <= 1:
        return original_start

    peak_db = float(np.max(dbs))
    noise_db = float(np.percentile(dbs, 20))
    trigger_db = max(noise_db + cfg.PRE_VAD_NOISE_DB, peak_db - cfg.PRE_VAD_REL_DB, cfg.PRE_VAD_FLOOR_DB)
    active = dbs >= trigger_db
    run = 0
    for idx, is_active in enumerate(active):
        run = run + 1 if is_active else 0
        if run >= cfg.PRE_VAD_RUN_FRAMES:
            candidate = int(frame_starts[idx - cfg.PRE_VAD_RUN_FRAMES + 1])
            shift_ms = (original_start - candidate) / sr * 1000
            if cfg.PRE_VAD_MIN_SHIFT_MS <= shift_ms <= cfg.PRE_VAD_MAX_SHIFT_MS:
                return candidate
            return original_start

    return original_start


def refine_speech_boundaries(speech_timestamps, y, sr, cfg: HalaConfig):
    refined = []
    min_samples = int(cfg.MIN_SPEECH_DUR_MS * sr / 1000)

    for ts in speech_timestamps:
        original_start = max(0, int(ts['start']))
        start = original_start
        original_end = min(len(y), int(ts['end']))
        end = original_end
        frame_starts, dbs = frame_rms_db(
            y, start, end, sr,
            frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
            hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
        )

        if len(dbs) > 1:
            peak_db = float(np.max(dbs))
            noise_db = float(np.percentile(dbs, 20))
            trigger_db = max(noise_db + 6, peak_db - cfg.BOUNDARY_REFINE_REL_DB, cfg.BOUNDARY_REFINE_FLOOR_DB)
            active = np.where(dbs >= trigger_db)[0]
            if len(active):
                frame_len = int(cfg.BOUNDARY_REFINE_FRAME_MS * sr / 1000)
                refined_start = int(frame_starts[active[0]])
                if refined_start - original_start <= int(cfg.ONSET_CLIP_GUARD_MS * sr / 1000):
                    start = refined_start
                end = min(len(y), int(frame_starts[active[-1]] + frame_len))

        if start == original_start:
            start = recover_pre_vad_onset(original_start, original_end, y, sr, cfg)

        if end - start >= min_samples:
            refined.append({'start': start, 'end': end})

    return refined


def split_long_speech_on_internal_pauses(speech_timestamps, y, sr, cfg: HalaConfig):
    split_timestamps = []
    min_segment_samples = int(cfg.INTERNAL_SPLIT_MIN_SEGMENT_MS * sr / 1000)
    min_pause_samples = int(cfg.INTERNAL_SPLIT_MIN_PAUSE_MS * sr / 1000)
    min_part_samples = int(cfg.INTERNAL_SPLIT_MIN_PART_MS * sr / 1000)
    frame_len = int(cfg.BOUNDARY_REFINE_FRAME_MS * sr / 1000)

    for ts in speech_timestamps:
        start = int(ts['start'])
        end = int(ts['end'])
        if end - start < min_segment_samples:
            split_timestamps.append(ts)
            continue

        frame_starts, dbs = frame_rms_db(
            y, start, end, sr,
            frame_ms=cfg.BOUNDARY_REFINE_FRAME_MS,
            hop_ms=cfg.BOUNDARY_REFINE_HOP_MS
        )
        if len(dbs) < 3:
            split_timestamps.append(ts)
            continue

        peak_db = float(np.max(dbs))
        active_db = max(peak_db - cfg.INTERNAL_SPLIT_REL_DB, cfg.INTERNAL_SPLIT_FLOOR_DB)
        active_idx = np.where(dbs >= active_db)[0]
        if len(active_idx) == 0:
            split_timestamps.append(ts)
            continue

        raw_parts = []
        part_start = active_idx[0]
        prev = active_idx[0]
        for idx in active_idx[1:]:
            if idx != prev + 1:
                raw_parts.append((int(frame_starts[part_start]), int(frame_starts[prev] + frame_len)))
                part_start = idx
            prev = idx
        raw_parts.append((int(frame_starts[part_start]), int(frame_starts[prev] + frame_len)))

        parts = [(s, e) for s, e in raw_parts if e - s >= min_part_samples]
        if len(parts) < 2:
            split_timestamps.append(ts)
            continue

        merged_parts = [parts[0]]
        for s, e in parts[1:]:
            prev_s, prev_e = merged_parts[-1]
            if s - prev_e < min_pause_samples:
                merged_parts[-1] = (prev_s, e)
            else:
                merged_parts.append((s, e))

        if len(merged_parts) >= 2:
            split_timestamps.extend({'start': s, 'end': e} for s, e in merged_parts)
        else:
            split_timestamps.append(ts)

    return split_timestamps


def get_trial_speech_timestamps(wav_tensor, y, sr, cfg: HalaConfig, model=None):
    """Raw Silero VAD -> boundary refinement -> internal-pause splitting."""
    if model is None:
        model = get_model()
    silero_model, get_speech_ts = model

    raw_timestamps = get_speech_ts(
        wav_tensor,
        silero_model,
        threshold=cfg.VAD_THRESHOLD,
        min_speech_duration_ms=cfg.MIN_SPEECH_DUR_MS,
        min_silence_duration_ms=cfg.MIN_SILENCE_DUR_MS,
        speech_pad_ms=cfg.SPEECH_PAD_MS
    )
    refined = refine_speech_boundaries(raw_timestamps, y, sr, cfg)
    refined = split_long_speech_on_internal_pauses(refined, y, sr, cfg)
    return refined
