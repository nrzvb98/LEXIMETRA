"""macOS PyInstaller launcher for LEXIMETRA."""

import sys

from leximetra.app import main


if __name__ == "__main__":
    sys.exit(main())
