"""Module entry point, also usable directly by PyInstaller."""

import sys
from pathlib import Path

# The requested PyInstaller command analyzes this file as a standalone script.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ytdl_gui.ui import main


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from ytdl_gui.selftest import run
        raise SystemExit(run(sys.argv[2]))
    main()
