"""Run the processing service off the GUI thread.

Lives in the UI layer rather than beside the service because it is Qt: the data
layer stays GUI-agnostic, so the service can be tested and reused without a
QApplication.

The pipeline takes about 4 s on a short recording and longer on a full session,
which is long enough to freeze the window and trip the "application is not
responding" indicator, so it runs here instead.
"""

from PyQt6.QtCore import QThread, pyqtSignal

from hala_rt.data.processing_service import (
    ProcessingOutcome,
    ProcessingStatus,
    run_processing,
)


class ProcessingWorker(QThread):
    """Runs one recording through the pipeline and reports the outcome.

    ``progress`` carries the pipeline's own stages (``load``, ``slices``,
    ``vad``, ``export``); ``completed`` carries a
    :class:`~hala_rt.data.processing_service.ProcessingOutcome`, including for
    failures — the service does not raise, so there is no error signal.
    """

    progress = pyqtSignal(str, int, int)
    completed = pyqtSignal(object)

    def __init__(self, audio_path, output_csv_path=None, parent=None):
        super().__init__(parent)
        self._audio_path = audio_path
        self._output_csv_path = output_csv_path
        self._cancel_requested = False

    def cancel(self):
        """Ask the run to stop at the next progress callback.

        Advisory: the pipeline can only be interrupted where it reports
        progress, so a cancel during beep detection takes effect once slicing
        finishes.
        """
        self._cancel_requested = True

    def run(self):
        # Nothing may escape this method. PyQt6 routes an unhandled exception
        # in a QThread.run() to qFatal, which aborts the whole application --
        # observed for real when a packaged build raised RuntimeError while
        # importing torch. The service is written not to raise, so this is a
        # backstop, but it is the difference between "analysis failed, cut
        # trials by hand" and the user's window vanishing mid-session.
        try:
            outcome = run_processing(
                self._audio_path,
                on_progress=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
                output_csv_path=self._output_csv_path,
            )
        except BaseException as error:  # noqa: BLE001
            outcome = ProcessingOutcome(
                status=ProcessingStatus.ERROR,
                message=f"{error.__class__.__name__}: {error}",
            )
        self.completed.emit(outcome)
