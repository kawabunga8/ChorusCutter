"""
main.py — Entry point for Chorus Cutter.
"""

import os
import sys

# .app bundles launch with a minimal PATH that excludes Homebrew.
for _brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _brew_bin + ":" + os.environ.get("PATH", "")

# CRITICAL: create QApplication *before* importing heavy modules (matplotlib,
# pydub, …).  When launched from Finder, macOS waits for the process to
# register with the window server.  PyQt6.QtWidgets loads in ~0.3 s; if we
# deferred QApplication until after matplotlib (~2-3 s) macOS would declare
# the app "not responding" before the event loop ever starts.
from PyQt6.QtWidgets import QApplication  # noqa: E402
_app = QApplication(sys.argv)
_app.processEvents()          # pump once so macOS sees us as alive

# Heavy imports happen here — safely after the app is registered.
from ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    window = MainWindow()
    window.show()
    sys.exit(_app.exec())


if __name__ == "__main__":
    main()
