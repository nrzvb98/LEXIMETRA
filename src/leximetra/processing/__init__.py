"""LEXIMETRA reaction-time pipeline: beep detection -> trial slicing -> Silero VAD
-> RT/hesitation metrics -> CSV export.

Extracted from hala_proc.ipynb (Template Matched v5.3); outputs are
regression-locked to the notebook's.

    from leximetra.processing import process_audio, LeximetraConfig
    result = process_audio("recording.m4a", output_dir="out")
"""
from .config import LeximetraConfig
from .pipeline import LeximetraResult, process_audio
from .vad import get_model

__version__ = "1.2.0"

__all__ = ["LeximetraConfig", "LeximetraResult", "process_audio", "get_model", "__version__"]
