"""
main.py — Entry point for Chorus Cutter.
"""

import os
import sys

# .app bundles launch with a minimal PATH that excludes Homebrew.
# Prepend both Intel and Apple Silicon Homebrew locations so tools
# like ffmpeg/ffprobe are found regardless of how the app was opened.
for _brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _brew_bin + ":" + os.environ.get("PATH", "")
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
