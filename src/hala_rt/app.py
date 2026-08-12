"""
HALA RT Verification Interface
Manual trial cutting, playback, and CSV output editing

Installation:
------------
python -m pip install -e .

System Requirements:
-------------------
FFmpeg must be installed on your system for M4A support:
- Windows: Download from https://ffmpeg.org/download.html
- macOS: brew install ffmpeg
- Linux: sudo apt-get install ffmpeg

Usage:
------
python -m hala_rt

Then click "Load Audio" and select a WAV, MP3, FLAC, or M4A file.
Click or drag the Global Timeline to place the trial end cursor, then click "Add Trial End".
Press Play or Spacebar to start playback.
"""

import sys

from PyQt6.QtWidgets import QApplication

from hala_rt.audio.manager import (
    PYDUB_AVAILABLE,
    SOUNDDEVICE_AVAILABLE,
    SOUNDFILE_AVAILABLE,
    AudioManager,
)
from hala_rt.ui.main_window import HALAMainWindow


def main():
    # Check dependencies
    print("\n" + "=" * 60)
    print("HALA RT Verification Interface - Manual Trial Editor")
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

    app = QApplication(sys.argv)
    window = HALAMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
