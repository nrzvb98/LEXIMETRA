"""Proof that the vendored pipeline still reproduces the validated one.

``src/hala_rt/processing`` is a generated copy of the ``Hala_Processing``
package (see ``tools/sync_processing.py``). These tests run it on the committed
sample recording and compare against baselines frozen from upstream *before*
the copy was made — so a mistake in vendoring, a dependency that resolves
differently on this Python, or an accidental edit to the copy all show up here.

This is the vendoring gate, not the full fidelity gate: upstream's
``regression_check.py`` additionally byte-compares two longer recordings
against 2.1 GB of frozen notebook references that cannot live in this repo.

Skipped when the ``processing`` extra is not installed:

    python -m pip install -e ".[processing]"
"""

import filecmp
import hashlib
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_AUDIO = PROJECT_ROOT / "examples" / "audio" / "trial_sample.m4a"
BASELINE_DIR = PROJECT_ROOT / "tests" / "data" / "processing_baseline"
STEM = SAMPLE_AUDIO.stem

CSV_NAMES = [
    f"{STEM}_HALA_Full_Analysis_Results.csv",
    f"{STEM}_HALA_Analysis_Results.csv",
    f"{STEM}_hala_output.csv",
]

pytestmark = pytest.mark.slow

process_audio = pytest.importorskip(
    "hala_rt.processing", reason="the 'processing' extra is not installed"
).process_audio


@pytest.fixture(scope="module")
def pipeline_output(tmp_path_factory):
    """Run the vendored pipeline once; every assertion reads the same run."""
    if not SAMPLE_AUDIO.is_file():
        pytest.skip(f"sample recording missing: {SAMPLE_AUDIO}")

    output_dir = tmp_path_factory.mktemp("vendored_run")
    process_audio(SAMPLE_AUDIO, output_dir=output_dir)
    return output_dir


@pytest.mark.parametrize("csv_name", CSV_NAMES)
def test_csv_matches_frozen_baseline(pipeline_output, csv_name):
    produced = pipeline_output / csv_name
    baseline = BASELINE_DIR / csv_name

    assert produced.is_file(), f"pipeline did not write {csv_name}"
    assert baseline.is_file(), f"missing baseline {baseline}"

    if not filecmp.cmp(baseline, produced, shallow=False):
        expected = baseline.read_text().splitlines()
        actual = produced.read_text().splitlines()
        # Show the first differing row rather than the whole table.
        for row, (want, got) in enumerate(zip(expected, actual), start=1):
            if want != got:
                pytest.fail(
                    f"{csv_name} differs from the frozen baseline at line {row}:\n"
                    f"  baseline: {want}\n"
                    f"  produced: {got}"
                )
        pytest.fail(
            f"{csv_name} differs in length: baseline has {len(expected)} lines, "
            f"produced has {len(actual)}"
        )


def test_slices_match_frozen_hashes(pipeline_output):
    expected = {}
    for line in (BASELINE_DIR / "slices.sha256").read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            expected[name.strip()] = digest

    slice_dir = pipeline_output / "HALA_Slices"
    produced = sorted(slice_dir.glob("*.wav"))

    assert {p.name for p in produced} == set(expected), (
        "trial slices differ from the baseline set: "
        f"produced {sorted(p.name for p in produced)}"
    )

    mismatched = [
        wav.name
        for wav in produced
        if hashlib.sha256(wav.read_bytes()).hexdigest() != expected[wav.name]
    ]
    assert not mismatched, f"slice audio differs from baseline: {mismatched}"


def test_output_csv_loads_through_the_app(pipeline_output):
    """The pipeline's export must satisfy the app's own loader and validation.

    This is the actual integration contract: schema, formatting, and the
    controller's rule that trials tile the recording without gaps.
    """
    from hala_rt.data.csv_io import load_output_csv
    from hala_rt.ui.main_window import HALAMainWindow

    trials = load_output_csv(pipeline_output / f"{STEM}_hala_output.csv")

    assert trials, "pipeline produced no trials"
    for trial in trials:
        trial.validate()

    adjustments = HALAMainWindow._noncontiguous_trial_starts(trials)
    assert not adjustments, (
        "pipeline output is not contiguous; the app would rewrite these starts: "
        f"{adjustments}"
    )
