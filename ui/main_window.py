"""
main_window.py — Main PyQt6 window for Chorus Cutter.

Layout
──────
  ┌─ Header bar ──────────────────────────────────────────┐
  │  [Open…]    filename.mp3          BPM: 128   3:24     │
  ├───────────────────────────────────────────────────────┤
  │                    Waveform                           │
  ├─ Transport bar ───────────────────────────────────────┤
  │  ⏱ 0:00.00   − + ⟳        [▶ Play from here] [Export]│
  └───────────────────────────────────────────────────────┘
"""

import os
from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QDoubleSpinBox, QPushButton, QFileDialog,
    QMessageBox, QSizePolicy,
)

from analyzer import analyze, AnalysisResult
from waveform_widget import WaveformWidget
from exporter import export


# ── Palette ───────────────────────────────────────────────────────────────────

_BG        = "#111114"
_SURFACE   = "#1c1c1f"
_SURFACE2  = "#28282c"
_BORDER    = "#38383d"
_TEXT      = "#f2f2f7"
_TEXT2     = "#8e8e93"
_TEXT3     = "#48484d"
_BLUE      = "#0a84ff"
_GREEN     = "#30c757"
_AMBER     = "#ff9f0a"
_RED       = "#ff453a"


# ── Background analysis worker ────────────────────────────────────────────────

class _AnalysisWorker(QThread):
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, filepath: str) -> None:
        super().__init__()
        self._filepath = filepath

    def run(self) -> None:
        try:
            self.finished.emit(analyze(self._filepath))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chorus Cutter")
        self.resize(980, 540)
        self.setMinimumSize(680, 400)

        self._source_path: str | None = None
        self._result: AnalysisResult | None = None
        self._worker: _AnalysisWorker | None = None

        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(1.0)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._make_header())
        root_layout.addWidget(self._make_divider())
        root_layout.addWidget(self._make_waveform_area(), stretch=1)
        root_layout.addWidget(self._make_divider())
        root_layout.addWidget(self._make_transport())

        self._apply_style()

    def _make_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("header")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        self._open_btn = QPushButton("Open…")
        self._open_btn.setObjectName("openBtn")
        self._open_btn.setFixedSize(72, 30)
        self._open_btn.setShortcut("Ctrl+O")
        self._open_btn.clicked.connect(self._open_file)
        layout.addWidget(self._open_btn)

        layout.addSpacing(8)

        self._filename_label = QLabel("No file loaded")
        self._filename_label.setObjectName("filenameLabel")
        layout.addWidget(self._filename_label, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label)

        self._bpm_chip = _Chip("BPM", "—")
        self._bpm_chip.setVisible(False)
        layout.addWidget(self._bpm_chip)

        self._dur_chip = _Chip("", "")
        self._dur_chip.setVisible(False)
        layout.addWidget(self._dur_chip)

        return bar

    def _make_waveform_area(self) -> QWidget:
        container = QWidget()
        container.setObjectName("waveformArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._waveform = WaveformWidget(container)
        self._waveform.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._waveform.marker_moved.connect(self._on_marker_moved)
        layout.addWidget(self._waveform)
        return container

    def _make_transport(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("transport")
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        # ── Chorus start time ──
        layout.addWidget(_muted_label("Start"))

        self._start_spin = QDoubleSpinBox()
        self._start_spin.setObjectName("startSpin")
        self._start_spin.setRange(0.0, 9999.0)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.25)
        self._start_spin.setFixedWidth(88)
        self._start_spin.setEnabled(False)
        self._start_spin.valueChanged.connect(self._on_spin_changed)
        layout.addWidget(self._start_spin)

        self._duration_label = _muted_label("")
        layout.addWidget(self._duration_label)

        layout.addSpacing(20)

        # ── Zoom controls ──
        layout.addWidget(_muted_label("Zoom"))
        layout.addSpacing(4)

        for symbol, tip, fn in [
            ("−", "Zoom out (scroll)", self._waveform.zoom_out),
            ("+", "Zoom in (scroll)",  self._waveform.zoom_in),
            ("⟳", "Reset zoom",        self._waveform.reset_zoom),
        ]:
            btn = QPushButton(symbol)
            btn.setObjectName("zoomBtn")
            btn.setFixedSize(28, 28)
            btn.setToolTip(tip)
            btn.clicked.connect(fn)
            layout.addWidget(btn)

        layout.addStretch()

        # ── Normalize toggle ──
        self._norm_btn = QPushButton("Normalize")
        self._norm_btn.setObjectName("normBtn")
        self._norm_btn.setCheckable(True)
        self._norm_btn.setFixedSize(90, 34)
        self._norm_btn.setToolTip("Peak-normalize audio on export")
        layout.addWidget(self._norm_btn)

        layout.addSpacing(8)

        # ── Play / Export ──
        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setObjectName("playBtn")
        self._play_btn.setFixedSize(120, 34)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_playback)
        layout.addWidget(self._play_btn)

        layout.addSpacing(8)

        self._export_btn = QPushButton("Export…")
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.setFixedSize(100, 34)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export)
        layout.addWidget(self._export_btn)

        return bar

    def _make_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    # ── Stylesheet ────────────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        sys_font = "-apple-system, 'Helvetica Neue', Arial, sans-serif"
        self.setStyleSheet(f"""
            /* ── Base ── */
            QMainWindow, QWidget#root {{
                background: {_BG};
            }}

            /* ── Header ── */
            QWidget#header {{
                background: {_SURFACE};
            }}
            QLabel#filenameLabel {{
                color: {_TEXT};
                font: bold 13px {sys_font};
            }}
            QLabel#statusLabel {{
                color: {_TEXT2};
                font: 11px {sys_font};
            }}

            /* ── Waveform area ── */
            QWidget#waveformArea {{
                background: {_BG};
            }}

            /* ── Transport bar ── */
            QWidget#transport {{
                background: {_SURFACE};
            }}
            QLabel.muted {{
                color: {_TEXT3};
                font: 10px {sys_font};
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}

            /* ── Spinbox ── */
            QDoubleSpinBox#startSpin {{
                background: {_SURFACE2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                padding: 3px 6px;
                font: 13px {sys_font};
                selection-background-color: {_BLUE};
            }}
            QDoubleSpinBox#startSpin:disabled {{
                color: {_TEXT3};
                border-color: {_SURFACE2};
            }}
            QDoubleSpinBox#startSpin::up-button, QDoubleSpinBox#startSpin::down-button {{
                width: 0; height: 0;
            }}

            /* ── Zoom buttons ── */
            QPushButton#zoomBtn {{
                background: transparent;
                color: {_TEXT2};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font: bold 14px {sys_font};
                padding: 0;
            }}
            QPushButton#zoomBtn:hover  {{ background: {_SURFACE2}; color: {_TEXT}; }}
            QPushButton#zoomBtn:pressed {{ background: {_BORDER}; }}

            /* ── Open button ── */
            QPushButton#openBtn {{
                background: {_SURFACE2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 7px;
                font: 12px {sys_font};
                padding: 0;
            }}
            QPushButton#openBtn:hover  {{ background: {_BORDER}; }}
            QPushButton#openBtn:pressed {{ background: #3e3e44; }}

            /* ── Play button ── */
            QPushButton#playBtn {{
                background: {_GREEN};
                color: #000000;
                border: none;
                border-radius: 8px;
                font: bold 13px {sys_font};
            }}
            QPushButton#playBtn:hover   {{ background: #38d966; }}
            QPushButton#playBtn:pressed {{ background: #25a845; }}
            QPushButton#playBtn:disabled {{
                background: {_SURFACE2};
                color: {_TEXT3};
            }}

            /* ── Export button ── */
            QPushButton#exportBtn {{
                background: {_BLUE};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font: bold 13px {sys_font};
            }}
            QPushButton#exportBtn:hover   {{ background: #1a8fff; }}
            QPushButton#exportBtn:pressed {{ background: #0070e0; }}
            QPushButton#exportBtn:disabled {{
                background: {_SURFACE2};
                color: {_TEXT3};
            }}

            /* ── Normalize toggle ── */
            QPushButton#normBtn {{
                background: transparent;
                color: {_TEXT2};
                border: 1px solid {_BORDER};
                border-radius: 8px;
                font: 12px {sys_font};
            }}
            QPushButton#normBtn:hover   {{ background: {_SURFACE2}; color: {_TEXT}; }}
            QPushButton#normBtn:checked {{
                background: #0e7a5e;
                color: #ffffff;
                border-color: #0e7a5e;
                font: bold 12px {sys_font};
            }}
            QPushButton#normBtn:checked:hover {{ background: #13956f; }}

            /* ── Divider ── */
            QFrame#divider {{ background: {_BORDER}; border: none; }}

            /* ── Chip widget internals ── */
            QWidget#chip {{
                background: {_SURFACE2};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
            QLabel#chipKey {{
                color: {_TEXT3};
                font: 10px {sys_font};
            }}
            QLabel#chipVal {{
                color: {_TEXT};
                font: bold 12px {sys_font};
            }}
        """)


    # ── Slots ─────────────────────────────────────────────────────────────────

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio File", "",
            "Audio Files (*.mp3 *.wav);;All Files (*)"
        )
        if not path:
            return

        self._source_path = path
        self._player.stop()
        self._set_controls_enabled(False)
        self._status_label.setText("Analysing…")
        self._bpm_chip.setVisible(False)
        self._dur_chip.setVisible(False)
        fname = os.path.basename(path)
        self._filename_label.setText(fname)

        # Disconnect and discard any previous worker before starting a new one.
        if self._worker is not None:
            self._worker.finished.disconnect()
            self._worker.error.disconnect()
            self._worker = None

        self._worker = _AnalysisWorker(path)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_done(self, result: AnalysisResult) -> None:
        self._result = result

        self._waveform.load(
            y=result.y,
            sr=result.sr,
            duration=result.duration,
            boundaries=result.section_boundaries,
            chorus_start=result.chorus_start,
        )

        self._bpm_chip.set_value(f"{result.bpm:.0f}")
        self._bpm_chip.setVisible(True)

        mins, secs = divmod(result.duration, 60)
        self._dur_chip.set_key("")
        self._dur_chip.set_value(f"{int(mins)}:{secs:05.2f}")
        self._dur_chip.setVisible(True)

        self._start_spin.blockSignals(True)
        self._start_spin.setMaximum(result.duration)
        self._start_spin.setValue(result.chorus_start)
        self._start_spin.blockSignals(False)

        mins, secs = divmod(result.duration, 60)
        self._duration_label.setText(f"/ {int(mins)}:{secs:05.2f}")

        self._status_label.setText("")
        self._set_controls_enabled(True)

        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(self._source_path or ""))

    def _on_analysis_error(self, message: str) -> None:
        self._status_label.setText("Analysis failed.")
        QMessageBox.critical(self, "Analysis Error", message)

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.setPosition(int(self._start_spin.value() * 1000))
            self._player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._play_btn.setText("⏸  Pause")
            self._play_btn.setStyleSheet(f"""
                QPushButton#playBtn {{
                    background: {_AMBER};
                    color: #000000;
                    border: none; border-radius: 8px;
                    font: bold 13px -apple-system;
                }}
                QPushButton#playBtn:hover   {{ background: #ffb340; }}
                QPushButton#playBtn:pressed {{ background: #e08800; }}
            """)
        else:
            self._play_btn.setText("▶  Play")
            self._play_btn.setStyleSheet("")   # revert to global stylesheet

    def _on_marker_moved(self, t: float) -> None:
        self._start_spin.blockSignals(True)
        self._start_spin.setValue(t)
        self._start_spin.blockSignals(False)

    def _on_spin_changed(self, value: float) -> None:
        self._waveform.set_marker(value)

    def _export(self) -> None:
        if self._result is None or self._source_path is None:
            return
        dest_path, _ = QFileDialog.getSaveFileName(
            self, "Export Trimmed Audio", "",
            "MP3 (*.mp3);;WAV (*.wav)"
        )
        if not dest_path:
            return
        try:
            export(
                source_path=self._source_path,
                dest_path=dest_path,
                start_seconds=self._start_spin.value(),
                normalize=self._norm_btn.isChecked(),
            )
        except FileNotFoundError as exc:
            if "ffprobe" in str(exc) or "ffmpeg" in str(exc):
                QMessageBox.critical(
                    self, "ffmpeg Not Found",
                    "Exporting MP3 requires ffmpeg.\n\n"
                    "Install it with:\n    brew install ffmpeg\n\n"
                    "Then try again."
                )
            else:
                QMessageBox.critical(self, "Export Error", str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", str(exc))

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._start_spin.setEnabled(enabled)
        self._play_btn.setEnabled(enabled)
        self._export_btn.setEnabled(enabled)


# ── Helper widgets ─────────────────────────────────────────────────────────────

def _muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("class", "muted")
    lbl.setObjectName("mutedLabel")
    lbl.setStyleSheet(f"color: #48484d; font: 10px -apple-system;")
    return lbl


class _Chip(QWidget):
    """Small pill showing a key + value pair (e.g. 'BPM  128')."""

    def __init__(self, key: str, value: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chip")
        self.setFixedHeight(30)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(5)

        self._key_lbl = QLabel(key)
        self._key_lbl.setObjectName("chipKey")
        layout.addWidget(self._key_lbl)

        self._val_lbl = QLabel(value)
        self._val_lbl.setObjectName("chipVal")
        layout.addWidget(self._val_lbl)

        self._update_width()

    def set_key(self, key: str) -> None:
        self._key_lbl.setText(key)
        self._update_width()

    def set_value(self, value: str) -> None:
        self._val_lbl.setText(value)
        self._update_width()

    def _update_width(self) -> None:
        key = self._key_lbl.text()
        val = self._val_lbl.text()
        chars = len(key) + len(val) + (2 if key else 0)
        self.setFixedWidth(max(60, chars * 8 + 20))
