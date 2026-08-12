"""The QThread wrapper's wiring: forwarding, cancellation, and outcome delivery.

``run()`` is called directly rather than via ``start()``, so the assertions run
against a finished result instead of racing the thread. What is under test is
the wiring, not Qt's threading.
"""

import pytest

from hala_rt.data.processing_service import ProcessingOutcome, ProcessingStatus
from hala_rt.ui import processing_worker
from hala_rt.ui.processing_worker import ProcessingWorker


@pytest.fixture
def service(monkeypatch):
    """Replace the service with a recorder, returning the calls it received."""
    calls = {}

    def install(outcome, emit_stages=()):
        def run_processing(audio_path, on_progress=None, should_cancel=None, output_csv_path=None):
            calls["audio_path"] = audio_path
            calls["output_csv_path"] = output_csv_path
            for stage in emit_stages:
                if should_cancel is not None and should_cancel():
                    calls["cancelled_after"] = stage
                    break
                if on_progress is not None:
                    on_progress(*stage)
            return outcome

        monkeypatch.setattr(processing_worker, "run_processing", run_processing)
        return calls

    return install


def test_outcome_is_delivered_on_completed(qapp, service):
    outcome = ProcessingOutcome(status=ProcessingStatus.SUCCESS, message="done", trial_count=7)
    service(outcome)
    worker = ProcessingWorker("/sessions/p001.m4a")
    received = []
    worker.completed.connect(received.append)

    worker.run()

    assert received == [outcome]
    assert received[0].trial_count == 7


def test_failures_arrive_on_completed_too(qapp, service):
    """There is no error signal: the service reports failures as outcomes."""
    outcome = ProcessingOutcome(status=ProcessingStatus.NO_BEEPS, message="no beeps")
    service(outcome)
    worker = ProcessingWorker("/sessions/p001.m4a")
    received = []
    worker.completed.connect(received.append)

    worker.run()

    assert received[0].status is ProcessingStatus.NO_BEEPS


def test_progress_is_relayed(qapp, service):
    service(
        ProcessingOutcome(status=ProcessingStatus.SUCCESS, message="done"),
        emit_stages=(("load", 0, 1), ("vad", 2, 12)),
    )
    worker = ProcessingWorker("/sessions/p001.m4a")
    seen = []
    worker.progress.connect(lambda stage, done, total: seen.append((stage, done, total)))

    worker.run()

    assert seen == [("load", 0, 1), ("vad", 2, 12)]


def test_cancel_is_visible_to_the_service(qapp, service):
    calls = service(
        ProcessingOutcome(status=ProcessingStatus.CANCELLED, message="cancelled"),
        emit_stages=(("load", 0, 1), ("vad", 1, 12), ("vad", 2, 12)),
    )
    worker = ProcessingWorker("/sessions/p001.m4a")
    worker.progress.connect(lambda *args: worker.cancel())

    worker.run()

    assert calls["cancelled_after"] == ("vad", 1, 12)


def test_an_unexpected_exception_never_escapes_run(qapp, monkeypatch):
    """PyQt6 turns an exception escaping QThread.run() into a fatal abort.

    A packaged build did exactly this: torch raised RuntimeError on import and
    the whole application died rather than falling back to manual trial
    cutting. The service is written not to raise; this is the backstop.
    """
    def explode(*args, **kwargs):
        raise RuntimeError("Unable to find torch_shm_manager")

    monkeypatch.setattr(processing_worker, "run_processing", explode)
    worker = ProcessingWorker("/sessions/p001.m4a")
    received = []
    worker.completed.connect(received.append)

    worker.run()

    assert len(received) == 1
    assert received[0].status is ProcessingStatus.ERROR
    assert "torch_shm_manager" in received[0].message


def test_output_path_is_passed_through(qapp, service):
    calls = service(ProcessingOutcome(status=ProcessingStatus.SUCCESS, message="done"))
    worker = ProcessingWorker("/sessions/p001.m4a", output_csv_path="/tmp/custom.csv")

    worker.run()

    assert calls["audio_path"] == "/sessions/p001.m4a"
    assert calls["output_csv_path"] == "/tmp/custom.csv"
