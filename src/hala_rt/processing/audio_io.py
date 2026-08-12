"""Audio loading identical to the HALA_RT_v1 app: pydub+FFmpeg for M4A/MP3,
soundfile for WAV/FLAC, polyphase resampling to the target rate."""
from __future__ import annotations

import math
import os

import numpy as np
import scipy.signal
import soundfile as sf
from pydub import AudioSegment


def load_audio_app_style(file_path, target_sr=16000):
    """Load audio like HALA_RT_v1: M4A/MP3 via pydub+FFmpeg, WAV/FLAC via soundfile."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".m4a":
        audio = AudioSegment.from_file(file_path, format="m4a")
        sr = audio.frame_rate
        channels = audio.channels
        sample_width = audio.sample_width
        samples = np.array(audio.get_array_of_samples()).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        y = samples / float(1 << (8 * sample_width - 1))
    elif ext == ".mp3":
        audio = AudioSegment.from_mp3(file_path)
        sr = audio.frame_rate
        channels = audio.channels
        sample_width = audio.sample_width
        samples = np.array(audio.get_array_of_samples()).astype(np.float32)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)
        y = samples / float(1 << (8 * sample_width - 1))
    elif ext in [".wav", ".flac"]:
        y, sr = sf.read(file_path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
    else:
        y, sr = sf.read(file_path, dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)

    y = np.asarray(y, dtype=np.float32)
    if sr != target_sr:
        gcd = math.gcd(sr, target_sr)
        y = scipy.signal.resample_poly(y, target_sr // gcd, sr // gcd).astype(np.float32)
        sr = target_sr

    return y, sr
