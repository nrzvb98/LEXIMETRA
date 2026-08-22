"""
LEXIMETRA
Automatic trial analysis and reaction-time verification

Installation:
------------
python -m pip install -e ".[processing]"   # with automatic analysis
python -m pip install -e .                 # verification only

System Requirements:
-------------------
FFmpeg must be installed on your system for M4A support:
- Windows: Download from https://ffmpeg.org/download.html
- macOS: brew install ffmpeg
- Linux: sudo apt-get install ffmpeg

Usage:
------
python -m leximetra

Click "Load Audio File" and select a WAV, MP3, FLAC, or M4A file. The
recording is analyzed on load -- beeps detected, trials cut, speech onsets
marked -- and the trials appear ready to check. Where the analysis is wrong,
or unavailable, place the trial-end cursor on the Global Timeline and click
"Add Trial End" to cut trials by hand. Press Play or Spacebar for playback.
"""

import os
import sys

from PyQt6.QtWidgets import QApplication

from leximetra.audio.manager import (
    PYDUB_AVAILABLE,
    SOUNDDEVICE_AVAILABLE,
    SOUNDFILE_AVAILABLE,
    AudioManager,
)
from leximetra.data.processing_service import processing_available
from leximetra.ui.main_window import HALAMainWindow


def self_test():
    """Prove a packaged build can actually analyze, without opening a window.

    Run by the macOS build script (``HALA_SELF_TEST=1``). Bundling breaks in
    ways no source-tree test can see -- a pruned torch directory, data files
    that did not get collected, a Silero copy that is missing -- and each of
    those only surfaces when a user loads a recording. This turns that into a
    build failure.
    """
    try:
        from leximetra.processing.vad import _local_silero_dir, get_model
    except Exception as error:
        print(f"SELF-TEST FAILED: cannot import the pipeline: "
              f"{error.__class__.__name__}: {error}")
        return 1

    silero_dir = _local_silero_dir()
    if silero_dir is None:
        print("SELF-TEST FAILED: no bundled Silero VAD; the app would try to "
              "download it from GitHub on first use.")
        return 1

    from leximetra.processing import HalaConfig

    missing = [
        str(path)
        for path in HalaConfig().resolved_template_paths()
        if not path.is_file()
    ]
    if missing:
        print(f"SELF-TEST FAILED: beep templates not bundled: {missing}")
        return 1

    try:
        get_model()
    except Exception as error:
        print(f"SELF-TEST FAILED: cannot load the VAD model: "
              f"{error.__class__.__name__}: {error}")
        return 1

    print(f"SELF-TEST OK: pipeline imports, beep templates present, "
          f"Silero loads from {silero_dir}")
    return 0


def main():
    # Check dependencies
    print("\n" + "=" * 60)
    print("LEXIMETRA - Automatic trial analysis and reaction-time verification")
    print("=" * 60)
    print("\nChecking dependencies...")

    missing = []
    if not PYDUB_AVAILABLE:
        missing.append("pydub (for MP3 support)")
    if not SOUNDFILE_AVAILABLE:
        missing.append("soundfile (for WAV/FLAC)")
    if not SOUNDDEVICE_AVAILABLE:
        missing.append("sounddevice (for playback)")

    if missing:
        print("\n⚠ Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with: pip install pydub soundfile sounddevice")
        print("\nContinuing with limited functionality...\n")
    else:
        print("✓ All dependencies installed\n")

    # Check FFmpeg
    audio_mgr = AudioManager()
    if not audio_mgr.ffmpeg_available:
        print("⚠ FFmpeg not found - M4A support disabled")
        print("  Install FFmpeg from: https://ffmpeg.org/download.html\n")
    else:
        print("✓ FFmpeg found - M4A support enabled\n")

    # Check automatic processing (optional; the manual workflow never needs it)
    if processing_available():
        print("✓ Automatic analysis available - loading audio will detect trials\n")
    else:
        print("⚠ Automatic analysis unavailable - trials must be cut manually")
        print('  Install with: pip install -e ".[processing]"\n')

    if os.environ.get("HALA_SELF_TEST") == "1":
        return self_test()

    app = QApplication(sys.argv)
    window = HALAMainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
