"""Single configuration surface for the HALA pipeline.

Field names deliberately keep the UPPER_CASE names used in hala_proc.ipynb and
HALA_Pipeline_Spec so values can be cross-referenced 1:1. Values here are the
validated defaults from the notebook (Template Matched v5.3).
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class HalaConfig:
    # --- Audio ---
    TARGET_SR: int = 16000

    # --- Beep detection: template matched (drives slicing) ---
    # None -> use the templates shipped inside the package (beep_york, beep_old).
    BEEP_TEMPLATE_PATHS: list[str] | None = None
    BEEP_BAND_HALF_WIDTH_HZ: float = 100      # bandpass = template peak freq +/- this
    BEEP_MIN_DUR_FRACTION: float = 0.85       # duration floor = fraction of template duration
    BEEP_MATCH_THRESHOLD: float = 0.60        # tone-match coherence gate (real beeps ~0.97+, speech <0.4)
    BEEP_PURITY_THRESHOLD: float = 0.80       # min in-band/wide-band RMS ratio

    # --- Beep detection: legacy fixed-band (drives the final CSV timestamps) ---
    # Kept separate from the template-matched detector on purpose: the exported
    # beep_timestamp_global / trial windows have always come from this detector.
    LEGACY_BEEP_BAND_LO_HZ: float = 900
    LEGACY_BEEP_BAND_HI_HZ: float = 1100
    LEGACY_BEEP_MIN_DUR_S: float = 0.09

    # --- Slicing ---
    SLICE_TAIL_S: float = 3.0                 # window after the last beep

    # --- Silero VAD ---
    VAD_THRESHOLD: float = 0.4
    MIN_SPEECH_DUR_MS: int = 50
    MIN_SILENCE_DUR_MS: int = 100
    SPEECH_PAD_MS: int = 0

    # --- Per-trial boundary refinement ---
    BOUNDARY_REFINE_FRAME_MS: int = 20
    BOUNDARY_REFINE_HOP_MS: int = 5
    BOUNDARY_REFINE_REL_DB: float = 28
    BOUNDARY_REFINE_FLOOR_DB: float = -50
    ONSET_CLIP_GUARD_MS: int = 30             # if refinement clips more than this, keep Silero's soft onset
    INTERNAL_SPLIT_MIN_SEGMENT_MS: int = 500
    INTERNAL_SPLIT_MIN_PAUSE_MS: int = 120
    INTERNAL_SPLIT_MIN_PART_MS: int = 120
    INTERNAL_SPLIT_REL_DB: float = 18
    INTERNAL_SPLIT_FLOOR_DB: float = -45
    PRE_VAD_LOOKBACK_MS: int = 150
    PRE_VAD_MIN_ORIGINAL_START_MS: int = 150
    PRE_VAD_MIN_SHIFT_MS: int = 60
    PRE_VAD_MAX_SHIFT_MS: int = 90
    PRE_VAD_NOISE_DB: float = 6
    PRE_VAD_REL_DB: float = 35
    PRE_VAD_FLOOR_DB: float = -45
    PRE_VAD_RUN_FRAMES: int = 3

    # --- Main-response (valley / second-burst) detection ---
    MAIN_RESPONSE_MIN_DELAY_MS: int = 120
    MAIN_RESPONSE_MIN_WORD_MS: int = 150
    MAIN_RESPONSE_MIN_PAUSE_MS: int = 60
    MAIN_RESPONSE_VALLEY_PROM_DB: float = 8
    MAIN_RESPONSE_VALLEY_FLOOR_REL_DB: float = -0.4
    MAIN_RESPONSE_MODERATE_PROM_DB: float = 6
    MAIN_RESPONSE_MODERATE_FLOOR_REL_DB: float = 4.5
    MAIN_RESPONSE_RISE_GAIN_DB: float = 1.5
    MAIN_RESPONSE_SECOND_BURST_MIN_DELAY_MS: int = 50
    MAIN_RESPONSE_SECOND_BURST_MIN_ADJUST_MS: int = 100
    MAIN_RESPONSE_SECOND_BURST_BACKSCAN_MS: int = 250
    MAIN_RESPONSE_SECOND_BURST_ONSET_DB: float = -44
    MAIN_RESPONSE_SECOND_BURST_ONSET_RUN_FRAMES: int = 3
    MAIN_RESPONSE_SECOND_BURST_EARLY_MAX_DB: float = -36
    MAIN_RESPONSE_IMMEDIATE_RISE_MS: int = 80
    MAIN_RESPONSE_IMMEDIATE_RISE_DB: float = 6

    # --- Burst merging / hesitation classification ---
    MAX_GAP_FOR_MERGE_MS: int = 100
    MIN_FIRST_BURST_DUR_MS: int = 75
    MIN_SECOND_BURST_DUR_MS: int = 150
    MIN_PAUSE_BETWEEN_BURSTS_MS: int = 100
    ANTICIPATORY_THRESHOLD_MS: float = 150
    TIMEOUT_THRESHOLD_MS: float = 3000

    # --- Software-format export ---
    NEXT_BEEP_MARGIN_S: float = 0.05
    # prefiller_present is timing-derived: main response later than first speech
    # by more than this gap. Matches the rule used to score the hand-edited
    # ground truth (see validate_gt.py), unlike the stricter burst classifier
    # behind hesitation_pattern.
    PREFILLER_MIN_GAP_MS: float = 1.0

    def resolved_template_paths(self) -> list[Path]:
        if self.BEEP_TEMPLATE_PATHS:
            return [Path(p) for p in self.BEEP_TEMPLATE_PATHS]
        return [_TEMPLATE_DIR / "beep_york.wav", _TEMPLATE_DIR / "beep_old.wav"]

    def to_json(self, path: str | Path | None = None) -> str:
        text = json.dumps(dataclasses.asdict(self), indent=2)
        if path is not None:
            Path(path).write_text(text + "\n")
        return text

    @classmethod
    def from_json(cls, path: str | Path) -> "HalaConfig":
        data = json.loads(Path(path).read_text())
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        return cls(**data)
