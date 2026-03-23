#!/usr/bin/env python3
"""
create_app.py — Builds ChorusCutter.app and places it on the Desktop.

Usage:
    .venv/bin/python create_app.py
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
APP_NAME    = "ChorusCutter"
BUNDLE      = PROJECT_DIR / f"{APP_NAME}.app"
VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"
DESKTOP     = Path.home() / "Desktop" / f"{APP_NAME}.app"


# ── Icon ──────────────────────────────────────────────────────────────────────

def _make_icon(resources_dir: Path) -> str | None:
    """Render a 512×512 icon PNG with matplotlib, then convert to ICNS."""
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    fig = plt.figure(figsize=(1, 1), dpi=512)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # ── Background — rounded dark square ──
    bg = FancyBboxPatch(
        (0.04, 0.04), 0.92, 0.92,
        boxstyle="round,pad=0.0,rounding_size=0.18",
        facecolor="#111114", edgecolor="none",
        transform=ax.transData, clip_on=False,
    )
    ax.add_patch(bg)

    # ── Waveform envelope ──
    x = np.linspace(0.1, 0.9, 300)
    env = 0.28 * np.exp(-((x - 0.5) ** 2) / 0.04) + 0.06
    env *= (1 + 0.4 * np.sin(x * 38))
    y_top =  0.5 + env
    y_bot =  0.5 - env
    ax.fill_between(x, y_top, y_bot, color="#3d7ef0", alpha=0.45, linewidth=0)
    ax.plot(x, y_top, color="#5b9cf6", linewidth=1.4)
    ax.plot(x, y_bot, color="#5b9cf6", linewidth=1.4)

    # ── Chorus marker line ──
    ax.plot([0.5, 0.5], [0.14, 0.86], color="#ff6b6b", linewidth=3.5,
            solid_capstyle="round")

    # ── Small handle nub on the marker ──
    ax.plot(0.5, 0.86, "o", color="#ff6b6b", markersize=7)

    fig.patch.set_facecolor("#111114")

    png_path  = resources_dir / "AppIcon.png"
    icns_path = resources_dir / "AppIcon.icns"

    fig.savefig(str(png_path), dpi=512, bbox_inches=None, pad_inches=0)
    plt.close(fig)

    result = subprocess.run(
        ["sips", "-s", "format", "icns", str(png_path), "--out", str(icns_path)],
        capture_output=True,
    )
    png_path.unlink(missing_ok=True)

    if result.returncode == 0 and icns_path.exists():
        return "AppIcon"
    return None


# ── Bundle construction ───────────────────────────────────────────────────────

def build() -> None:
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)

    macos_dir     = BUNDLE / "Contents" / "MacOS"
    resources_dir = BUNDLE / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)

    print("  Generating icon…", end=" ", flush=True)
    icon_file = _make_icon(resources_dir) or ""
    print("done" if icon_file else "skipped (sips unavailable)")

    # Write the Python startup script (not the executable — see below).
    startup = PROJECT_DIR / "_app_startup.py"
    startup.write_text(
        f"import os, sys\n"
        f"os.chdir(r'{PROJECT_DIR}')\n"
        f"sys.path.insert(0, r'{PROJECT_DIR}')\n"
        f"for _b in ('/opt/homebrew/bin', '/usr/local/bin'):\n"
        f"    if _b not in os.environ.get('PATH', ''):\n"
        f"        os.environ['PATH'] = _b + ':' + os.environ.get('PATH', '')\n"
        f"from PyQt6.QtWidgets import QApplication\n"
        f"from ui.main_window import MainWindow\n"
        f"_app = QApplication(sys.argv)\n"
        f"_win = MainWindow()\n"
        f"_win.show()\n"
        f"_win.raise_()\n"
        f"_win.activateWindow()\n"
        f"sys.exit(_app.exec())\n"
    )

    # Compile a real Mach-O launcher.  A Python shebang script is NOT
    # treated as a proper GUI app by macOS Launch Services — it bounces in
    # the Dock forever and never registers a window.  A compiled binary as
    # CFBundleExecutable gets registered immediately; it then exec()s Python.
    launcher = macos_dir / APP_NAME
    c_src = macos_dir / "launcher.c"
    c_src.write_text(f"""\
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static const char *PYTHON  = "{VENV_PYTHON}";
static const char *STARTUP = "{startup}";

int main(int argc, char *argv[]) {{
    /* Build new argv: python startup.py [original args except argv[0]] */
    char **args = malloc((argc + 2) * sizeof(char *));
    if (!args) return 1;
    args[0] = (char *)PYTHON;
    args[1] = (char *)STARTUP;
    for (int i = 1; i < argc; i++) args[i + 1] = argv[i];
    args[argc + 1] = NULL;
    execv(PYTHON, args);
    perror("ChorusCutter: execv failed");
    return 1;
}}
""")
    result = subprocess.run(
        ["clang", "-O2", "-o", str(launcher), str(c_src)],
        capture_output=True, text=True,
    )
    c_src.unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"  WARNING: clang failed ({result.stderr.strip()})")
        print("  Falling back to Python shebang launcher (may not open from Finder)")
        launcher.write_text(
            f"#!{VENV_PYTHON}\n"
            f"exec(open(r'{startup}').read())\n"
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    else:
        print("  Compiled Mach-O launcher: ok")

    # Info.plist
    (BUNDLE / "Contents" / "Info.plist").write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>             <string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key>      <string>Chorus Cutter</string>
  <key>CFBundleIdentifier</key>       <string>com.choruscutter.app</string>
  <key>CFBundleVersion</key>          <string>1.0</string>
  <key>CFBundlePackageType</key>      <string>APPL</string>
  <key>CFBundleExecutable</key>       <string>{APP_NAME}</string>
  <key>CFBundleIconFile</key>         <string>{icon_file}</string>
  <key>LSMinimumSystemVersion</key>   <string>12.0</string>
  <key>NSHighResolutionCapable</key>  <true/>
  <key>NSPrincipalClass</key>         <string>NSApplication</string>
</dict>
</plist>
""")
    print(f"  Bundle created:  {BUNDLE}")


def install_to_desktop() -> None:
    if DESKTOP.exists():
        shutil.rmtree(DESKTOP)
    shutil.copytree(BUNDLE, DESKTOP)
    print(f"  Installed to:    {DESKTOP}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not VENV_PYTHON.exists():
        print("ERROR: .venv not found.  Run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
        sys.exit(1)

    print(f"Building {APP_NAME}.app…")
    build()
    install_to_desktop()
    print("\nDone — double-click ChorusCutter on your Desktop to launch.")
