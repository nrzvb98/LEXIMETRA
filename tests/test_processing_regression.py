"""Proof that the vendored pipeline still reproduces the validated one.

``src/leximetra/processing`` is a generated copy of the ``Hala_Processing``
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

# The pipeline is upstream's, so it still writes upstream's names; the frozen
# copies here carry this app's. Mapping rather than renaming the produced side
# keeps the gate asserting what it always did -- that the bytes match -- while
# recording, in one place, exactly which name the pipeline emits.
CSV_NAMES = {
    f"{STEM}_HALA_Full_Analysis_Results.csv": f"{STEM}_Full_Analysis_Results.csv",
    f"{STEM}_HALA_Analysis_Results.csv": f"{STEM}_Analysis_Results.csv",
    f"{STEM}_hala_output.csv": f"{STEM}_output.csv",
}

pytestmark = pytest.mark.slow

process_audio = pytest.importorskip(
    "leximetra.processing", reason="the 'processing' extra is not installed"
).process_audio


@pytest.fixture(scope="module")
def pipeline_output(tmp_path_factory):
    """Run the vendored pipeline once; every assertion reads the same run."""
    if not SAMPLE_AUDIO.is_file():
        pytest.skip(f"sample recording missing: {SAMPLE_AUDIO}")

    output_dir = tmp_path_factory.mktemp("vendored_run")
    process_audio(SAMPLE_AUDIO, output_dir=output_dir)
    return output_dir


@pytest.mark.parametrize("csv_name,baseline_name", sorted(CSV_NAMES.items()))
def test_csv_matches_frozen_baseline(pipeline_output, csv_name, baseline_name):
    produced = pipeline_output / csv_name
    baseline = BASELINE_DIR / baseline_name

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


def test_service_places_real_pipeline_output(tmp_path):
    """The service's artifact layout, exercised against the real pipeline.

    ``test_processing_service.py`` covers this with the pipeline faked; this is
    the same contract with nothing stubbed, so a mismatch between the fake's
    call signature and the real one cannot hide.
    """
    from leximetra.data.processing_service import ProcessingStatus, run_processing

    audio = tmp_path / "session.m4a"
    audio.write_bytes(SAMPLE_AUDIO.read_bytes())

    stages = []
    outcome = run_processing(audio, on_progress=lambda *args: stages.append(args))

    assert outcome.status is ProcessingStatus.SUCCESS, outcome.message
    assert outcome.trial_count == 12
    assert outcome.csv_path == tmp_path / "session_output.csv"
    assert outcome.csv_path.is_file()
    assert outcome.backup_path is None

    sidecar = tmp_path / "session_output"
    assert len(list((sidecar / "Slices").glob("*.wav"))) == 12
    assert (sidecar / "session_Full_Analysis_Results.csv").is_file()
    assert (sidecar / "session_Analysis_Results.csv").is_file()
    assert not (sidecar / "session_hala_output.csv").exists()

    assert {stage for stage, _, _ in stages} == {"load", "slices", "vad", "export"}


def test_loading_audio_analyzes_it_end_to_end(qapp, tmp_path, monkeypatch):
    """The whole feature, unstubbed: load a recording, get verified trials.

    Everything else mocks something — the pipeline, the worker, or the
    decoder. This drives the real controller path over the real worker thread,
    event loop, and pipeline, which is the only place their interaction is
    actually exercised.
    """
    from leximetra.ui.main_window import LeximetraMainWindow

    audio = tmp_path / "session.m4a"
    audio.write_bytes(SAMPLE_AUDIO.read_bytes())

    window = LeximetraMainWindow()
    try:
        assert window._load_audio_file(audio) is True

        assert len(window.session_data) == 12
        assert "Analyzed 12 trial(s)" in window.status_label.text()
        assert (tmp_path / "session_output.csv").is_file()
        assert len(list((tmp_path / "session_output" / "Slices").glob("*.wav"))) == 12
        assert not window.has_unsaved_changes

        # The trials are usable: the table is populated and a trial is selected.
        assert window.trial_table.rowCount() >= 12
        assert window.current_trial_index == 0
    finally:
        window.close()


def test_output_csv_loads_through_the_app(pipeline_output):
    """The pipeline's export must satisfy the app's own loader and validation.

    This is the actual integration contract: schema, formatting, and the
    controller's rule that trials tile the recording without gaps.
    """
    from leximetra.data.csv_io import load_output_csv
    from leximetra.ui.main_window import LeximetraMainWindow

    trials = load_output_csv(pipeline_output / f"{STEM}_hala_output.csv")

    assert trials, "pipeline produced no trials"
    for trial in trials:
        trial.validate()

    adjustments = LeximetraMainWindow._noncontiguous_trial_starts(trials)
    assert not adjustments, (
        "pipeline output is not contiguous; the app would rewrite these starts: "
        f"{adjustments}"
    )
