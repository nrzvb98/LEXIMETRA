"""macOS PyInstaller launcher for HALA RT."""

import sys

from hala_rt.app import main


if __name__ == "__main__":
    sys.exit(main())
