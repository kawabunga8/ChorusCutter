"""
main_window.py — Main PyQt6 window for Chorus Cutter.

Layout
──────
  ┌─ Header ─────────────────────────────────────────────────────┐
  │  + Add Files…          PREFIX  [2026] _ [Awards] _  [MP3 ▾] │
  ├─ File list (220px) ─┬─ Waveform ───────────────────────────  │
  │  ☑ song1.mp3        │                                        │
  │    ♩ 128  •  3:24   │                                        │
  │  ☑ song2.mp3        ├─ Transport ─────────────────────────── │
  │    ♩ 95   •  4:01   │  START [spin]  ZOOM − + ⟳  Norm  Play │
  ├─ Export bar ─────────┴────────────────────────────────────── │
  │  [Select All]          [Export Selected (2)]  [Export All(3)]│
  └──────────────────────────────────────────────────────────────┘
"""

import os
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QSize, QThread, QUrl, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QDoubleSpinBox, QPushButton, QFileDialog,
    QMessageBox, QSizePolicy, QListWidget, QListWidgetItem,
    QSplitter, QLineEdit, QComboBox,
)

from analyzer import analyze, AnalysisResult
from waveform_widget import WaveformWidget
from exporter import export


# ── Palette ───────────────────────────────────────────────────────────────────

_BG      = "#111114"
_SURFACE = "#1c1c1f"
_SURF2   = "#28282c"
_BORDER  = "#38383d"
_TEXT    = "#f2f2f7"
_TEXT2   = "#8e8e93"
_TEXT3   = "#48484d"
_BLUE    = "#0a84ff"
_GREEN   = "#30c757"
_AMBER   = "#ff9f0a"


# ── File entry ────────────────────────────────────────────────────────────────

@dataclass
class _FileEntry:
    path: str
    result: AnalysisResult | None = None
    chorus_start: float = 0.0
    status: str = "pending"          # pending | analysing | done | error


# ── Background analysis worker ────────────────────────────────────────────────

class _AnalysisWorker(QThread):
    finished = pyqtSignal(int, object)   # (entry_index, AnalysisResult)
    error    = pyqtSignal(int, str)

    def __init__(self, index: int, filepath: str) -> None:
        super().__init__()
        self._index    = index
        self._filepath = filepath

    def run(self) -> None:
        try:
            self.finished.emit(self._index, analyze(self._filepath))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(self._index, str(exc))


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chorus Cutter")
        self.resize(1120, 600)
        self.setMinimumSize(820, 460)

        self._entries: list[_FileEntry] = []
        self._active_idx: int = -1
        self._worker: _AnalysisWorker | None = None
        self._worker_running: bool = False
        self._queue: list[int] = []

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
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._make_header())
        vbox.addWidget(self._make_divider())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("bodySplitter")
        splitter.setHandleWidth(1)
        splitter.addWidget(self._make_file_list_panel())
        splitter.addWidget(self._make_right_panel())
        splitter.setSizes([230, 890])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        vbox.addWidget(splitter, stretch=1)

        vbox.addWidget(self._make_divider())
        vbox.addWidget(self._make_export_bar())

        self._apply_style()
        self._refresh_export_buttons()

    def _make_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("header")
        bar.setFixedHeight(52)
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 0, 16, 0)
        lo.setSpacing(12)

        add_btn = QPushButton("+ Add Files…")
        add_btn.setObjectName("openBtn")
        add_btn.setFixedSize(110, 30)
        add_btn.setShortcut("Ctrl+O")
        add_btn.clicked.connect(self._add_files)
        lo.addWidget(add_btn)

        lo.addStretch()

        lo.addWidget(_muted("PREFIX"))
        lo.addSpacing(4)

        self._year_edit = QLineEdit("2026")
        self._year_edit.setObjectName("prefixEdit")
        self._year_edit.setFixedWidth(52)
        self._year_edit.setMaxLength(8)
        lo.addWidget(self._year_edit)

        lo.addWidget(_muted("_"))

        self._prefix_edit = QLineEdit("Awards")
        self._prefix_edit.setObjectName("prefixEdit")
        self._prefix_edit.setFixedWidth(110)
        lo.addWidget(self._prefix_edit)

        lo.addWidget(_muted("_ filename"))
        lo.addSpacing(16)

        self._fmt_combo = QComboBox()
        self._fmt_combo.setObjectName("fmtCombo")
        self._fmt_combo.addItems(["MP3", "WAV"])
        self._fmt_combo.setFixedWidth(72)
        lo.addWidget(self._fmt_combo)

        return bar

    def _make_file_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("fileListPanel")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._file_list = QListWidget()
        self._file_list.setObjectName("fileList")
        self._file_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._file_list.setUniformItemSizes(True)
        self._file_list.currentRowChanged.connect(self._on_row_changed)
        # Update export buttons when a checkbox changes.
        self._file_list.itemChanged.connect(lambda _: self._refresh_export_buttons())
        lo.addWidget(self._file_list)

        return panel

    def _make_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("rightPanel")
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._waveform = WaveformWidget(panel)
        self._waveform.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._waveform.marker_moved.connect(self._on_marker_moved)
        self._waveform.fade_changed.connect(self._on_waveform_fade_changed)
        vbox.addWidget(self._waveform, stretch=1)

        vbox.addWidget(self._make_divider())
        vbox.addWidget(self._make_transport())

        return panel

    def _make_transport(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("transport")
        bar.setFixedHeight(56)
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 0, 16, 0)
        lo.setSpacing(8)

        lo.addWidget(_muted("START"))

        self._start_spin = QDoubleSpinBox()
        self._start_spin.setObjectName("startSpin")
        self._start_spin.setRange(0.0, 9999.0)
        self._start_spin.setDecimals(2)
        self._start_spin.setSingleStep(0.25)
        self._start_spin.setFixedWidth(88)
        self._start_spin.setEnabled(False)
        self._start_spin.valueChanged.connect(self._on_spin_changed)
        lo.addWidget(self._start_spin)

        self._dur_label = _muted("")
        lo.addWidget(self._dur_label)
        lo.addSpacing(20)

        lo.addWidget(_muted("ZOOM"))
        lo.addSpacing(4)
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
            lo.addWidget(btn)

        lo.addStretch()

        self._fade_in_btn = QPushButton("Fade In")
        self._fade_in_btn.setObjectName("normBtn")   # reuse ghost/toggle style
        self._fade_in_btn.setCheckable(True)
        self._fade_in_btn.setFixedSize(72, 34)
        self._fade_in_btn.setToolTip("Apply fade-in on export")
        self._fade_in_btn.toggled.connect(self._on_fade_in_toggled)
        lo.addWidget(self._fade_in_btn)

        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setObjectName("startSpin")
        self._fade_in_spin.setRange(0.1, 30.0)
        self._fade_in_spin.setDecimals(1)
        self._fade_in_spin.setSingleStep(0.1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setValue(1.0)
        self._fade_in_spin.setFixedWidth(72)
        self._fade_in_spin.setEnabled(False)
        self._fade_in_spin.valueChanged.connect(self._on_fade_in_duration_changed)
        lo.addWidget(self._fade_in_spin)

        self._fade_curve_combo = QComboBox()
        self._fade_curve_combo.setObjectName("fmtCombo")
        self._fade_curve_combo.addItems(["Linear", "Exponential", "Logarithmic", "S-Curve"])
        self._fade_curve_combo.setFixedWidth(108)
        self._fade_curve_combo.setEnabled(False)
        self._fade_curve_combo.currentTextChanged.connect(self._on_fade_curve_changed)
        lo.addWidget(self._fade_curve_combo)

        lo.addSpacing(8)

        self._norm_btn = QPushButton("Normalize")
        self._norm_btn.setObjectName("normBtn")
        self._norm_btn.setCheckable(True)
        self._norm_btn.setFixedSize(90, 34)
        self._norm_btn.setToolTip("Peak-normalize audio on export")
        lo.addWidget(self._norm_btn)

        lo.addSpacing(8)

        self._play_btn = QPushButton("▶  Play")
        self._play_btn.setObjectName("playBtn")
        self._play_btn.setFixedSize(120, 34)
        self._play_btn.setEnabled(False)
        self._play_btn.clicked.connect(self._toggle_playback)
        lo.addWidget(self._play_btn)

        return bar

    def _make_export_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("exportBar")
        bar.setFixedHeight(52)
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 0, 16, 0)
        lo.setSpacing(12)

        self._sel_all_btn = QPushButton("Select All")
        self._sel_all_btn.setObjectName("ghostBtn")
        self._sel_all_btn.setFixedSize(96, 30)
        self._sel_all_btn.clicked.connect(self._toggle_select_all)
        lo.addWidget(self._sel_all_btn)

        lo.addStretch()

        self._export_sel_btn = QPushButton("Export Selected")
        self._export_sel_btn.setObjectName("exportBtn")
        self._export_sel_btn.setFixedHeight(34)
        self._export_sel_btn.setMinimumWidth(150)
        self._export_sel_btn.setEnabled(False)
        self._export_sel_btn.clicked.connect(
            lambda: self._run_export(selected_only=True)
        )
        lo.addWidget(self._export_sel_btn)

        self._export_all_btn = QPushButton("Export All")
        self._export_all_btn.setObjectName("exportBtn")
        self._export_all_btn.setFixedHeight(34)
        self._export_all_btn.setMinimumWidth(120)
        self._export_all_btn.setEnabled(False)
        self._export_all_btn.clicked.connect(
            lambda: self._run_export(selected_only=False)
        )
        lo.addWidget(self._export_all_btn)

        return bar

    def _make_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    # ── Stylesheet ────────────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        f = "-apple-system, 'Helvetica Neue', Arial, sans-serif"
        self.setStyleSheet(f"""
            QMainWindow, QWidget#root, QWidget#rightPanel {{
                background: {_BG};
            }}
            QWidget#header, QWidget#transport, QWidget#exportBar {{
                background: {_SURFACE};
            }}
            QWidget#fileListPanel {{
                background: {_SURFACE};
            }}
            QSplitter#bodySplitter::handle {{
                background: {_BORDER};
            }}
            QListWidget#fileList {{
                background: {_SURFACE};
                border: none;
                outline: none;
                color: {_TEXT};
                font: 12px {f};
                border-right: 1px solid {_BORDER};
            }}
            QListWidget#fileList::item {{
                padding: 10px 12px;
                border-bottom: 1px solid {_SURF2};
            }}
            QListWidget#fileList::item:selected {{
                background: {_SURF2};
                color: {_TEXT};
            }}
            QListWidget#fileList::item:hover:!selected {{
                background: #202024;
            }}
            QLineEdit#prefixEdit {{
                background: {_SURF2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 5px;
                padding: 3px 6px;
                font: 12px {f};
            }}
            QComboBox#fmtCombo {{
                background: {_SURF2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 5px;
                padding: 3px 6px;
                font: 12px {f};
            }}
            QComboBox#fmtCombo::drop-down {{ border: none; width: 16px; }}
            QComboBox#fmtCombo QAbstractItemView {{
                background: {_SURF2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                selection-background-color: {_BLUE};
            }}
            QDoubleSpinBox#startSpin {{
                background: {_SURF2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                padding: 3px 6px;
                font: 13px {f};
                selection-background-color: {_BLUE};
            }}
            QDoubleSpinBox#startSpin:disabled {{
                color: {_TEXT3};
                border-color: {_SURF2};
            }}
            QDoubleSpinBox#startSpin::up-button,
            QDoubleSpinBox#startSpin::down-button {{ width: 0; height: 0; }}
            QPushButton#zoomBtn {{
                background: transparent;
                color: {_TEXT2};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                font: bold 14px {f};
                padding: 0;
            }}
            QPushButton#zoomBtn:hover  {{ background: {_SURF2}; color: {_TEXT}; }}
            QPushButton#zoomBtn:pressed {{ background: {_BORDER}; }}
            QPushButton#openBtn, QPushButton#ghostBtn {{
                background: {_SURF2};
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 7px;
                font: 12px {f};
                padding: 0;
            }}
            QPushButton#openBtn:hover, QPushButton#ghostBtn:hover {{
                background: {_BORDER};
            }}
            QPushButton#normBtn {{
                background: transparent;
                color: {_TEXT2};
                border: 1px solid {_BORDER};
                border-radius: 8px;
                font: 12px {f};
            }}
            QPushButton#normBtn:hover   {{ background: {_SURF2}; color: {_TEXT}; }}
            QPushButton#normBtn:checked {{
                background: #0e7a5e;
                color: #fff;
                border-color: #0e7a5e;
                font: bold 12px {f};
            }}
            QPushButton#normBtn:checked:hover {{ background: #13956f; }}
            QPushButton#playBtn {{
                background: {_GREEN};
                color: #000;
                border: none;
                border-radius: 8px;
                font: bold 13px {f};
            }}
            QPushButton#playBtn:hover   {{ background: #38d966; }}
            QPushButton#playBtn:pressed {{ background: #25a845; }}
            QPushButton#playBtn:disabled {{ background: {_SURF2}; color: {_TEXT3}; }}
            QPushButton#exportBtn {{
                background: {_BLUE};
                color: #fff;
                border: none;
                border-radius: 8px;
                font: bold 13px {f};
                padding: 0 16px;
            }}
            QPushButton#exportBtn:hover   {{ background: #1a8fff; }}
            QPushButton#exportBtn:pressed {{ background: #0070e0; }}
            QPushButton#exportBtn:disabled {{ background: {_SURF2}; color: {_TEXT3}; }}
            QFrame#divider {{ background: {_BORDER}; border: none; }}
        """)

    # ── File management ───────────────────────────────────────────────────────

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Audio Files", "",
            "Audio Files (*.mp3 *.wav *.m4a *.m4p);;All Files (*)"
        )
        for path in paths:
            if any(e.path == path for e in self._entries):
                continue
            idx = len(self._entries)
            self._entries.append(_FileEntry(path=path))
            self._append_list_item(idx)
            self._enqueue(idx)

        self._refresh_export_buttons()

    def _append_list_item(self, idx: int) -> None:
        # Block signals while building the item so that itemChanged /
        # currentRowChanged don't fire mid-loop while _entries is still
        # being populated.
        self._file_list.blockSignals(True)
        entry = self._entries[idx]
        item = QListWidgetItem()
        item.setText(self._item_text(entry))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, idx)
        item.setSizeHint(QSize(220, 54))
        self._file_list.addItem(item)
        self._file_list.blockSignals(False)
        if self._file_list.count() == 1:
            self._file_list.setCurrentRow(0)

    def _item_text(self, entry: _FileEntry) -> str:
        name = os.path.basename(entry.path)
        if entry.status == "analysing":
            return f"{name}\n···"
        if entry.status == "done" and entry.result:
            dur = entry.result.duration
            m, s = divmod(dur, 60)
            return f"{name}\n♩ {entry.result.bpm:.0f} BPM  ·  {int(m)}:{s:04.1f}s"
        if entry.status == "error":
            return f"{name}\n⚠  Analysis failed"
        return f"{name}\n—"

    def _refresh_item(self, idx: int) -> None:
        item = self._file_list.item(idx)
        if item:
            # Block itemChanged signal to avoid re-entrancy
            self._file_list.blockSignals(True)
            item.setText(self._item_text(self._entries[idx]))
            self._file_list.blockSignals(False)

    # ── Analysis queue ────────────────────────────────────────────────────────

    def _enqueue(self, idx: int) -> None:
        self._queue.append(idx)
        # Kick off the queue only if nothing is running.  We do NOT check
        # isRunning() here to avoid the race where start() hasn't returned
        # yet; instead _process_queue guards itself with _worker_running.
        if not self._worker_running:
            self._process_queue()

    def _process_queue(self) -> None:
        if self._worker_running:
            return
        while self._queue:
            idx = self._queue.pop(0)
            entry = self._entries[idx]
            if entry.path.lower().endswith(".m4p"):
                entry.status = "error"
                self._refresh_item(idx)
                continue
            entry.status = "analysing"
            self._refresh_item(idx)
            # Disconnect previous worker's signals before replacing it.
            if self._worker is not None:
                try:
                    self._worker.finished.disconnect()
                    self._worker.error.disconnect()
                except RuntimeError:
                    pass
            self._worker_running = True
            self._worker = _AnalysisWorker(idx, entry.path)
            self._worker.finished.connect(self._on_analysis_done)
            self._worker.error.connect(self._on_analysis_error)
            self._worker.start()
            return  # one at a time; _worker_running cleared in callbacks

    def _on_analysis_done(self, idx: int, result: AnalysisResult) -> None:
        self._worker_running = False
        entry = self._entries[idx]
        entry.result = result
        entry.chorus_start = result.chorus_start
        entry.status = "done"
        self._refresh_item(idx)
        self._refresh_export_buttons()
        if self._active_idx == idx:
            self._load_active()
        self._process_queue()

    def _on_analysis_error(self, idx: int, _msg: str) -> None:
        self._worker_running = False
        self._entries[idx].status = "error"
        self._refresh_item(idx)
        self._process_queue()

    # ── Active entry ──────────────────────────────────────────────────────────

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        if self._active_idx >= 0:
            self._entries[self._active_idx].chorus_start = self._start_spin.value()
        self._active_idx = row
        self._load_active()

    def _load_active(self) -> None:
        if self._active_idx < 0:
            return
        entry = self._entries[self._active_idx]
        if entry.result is None:
            self._start_spin.setEnabled(False)
            self._play_btn.setEnabled(False)
            self._dur_label.setText("")
            return

        r = entry.result
        self._waveform.load(
            y=r.y, sr=r.sr, duration=r.duration,
            boundaries=r.section_boundaries,
            chorus_start=entry.chorus_start,
        )
        self._start_spin.blockSignals(True)
        self._start_spin.setMaximum(r.duration)
        self._start_spin.setValue(entry.chorus_start)
        self._start_spin.blockSignals(False)

        m, s = divmod(r.duration, 60)
        self._dur_label.setText(f"/ {int(m)}:{s:05.2f}")
        self._start_spin.setEnabled(True)
        self._play_btn.setEnabled(True)

        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(entry.path))

    # ── Transport ─────────────────────────────────────────────────────────────

    def _on_fade_in_toggled(self, checked: bool) -> None:
        self._fade_in_spin.setEnabled(checked)
        self._fade_curve_combo.setEnabled(checked)
        self._waveform.set_fade_in(
            self._fade_in_spin.value() if checked else 0.0
        )

    def _on_fade_in_duration_changed(self, value: float) -> None:
        if self._fade_in_btn.isChecked():
            self._waveform.set_fade_in(value)

    def _on_fade_curve_changed(self, text: str) -> None:
        self._waveform.set_fade_curve(text.lower())

    def _on_waveform_fade_changed(self, duration: float) -> None:
        """Waveform drag updated the fade duration — sync the spinbox."""
        self._fade_in_spin.blockSignals(True)
        self._fade_in_spin.setValue(duration)
        self._fade_in_spin.blockSignals(False)

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._audio_output.setVolume(1.0)
        else:
            self._player.setPosition(int(self._start_spin.value() * 1000))
            if self._fade_in_btn.isChecked():
                fade_ms = int(self._fade_in_spin.value() * 1000)
                # Seek to fade start (before the chorus marker) so playback
                # naturally covers the fade region leading up to the red line.
                fade_start_ms = max(0, int(self._start_spin.value() * 1000) - fade_ms)
                self._audio_output.setVolume(0.0)
                self._player.setPosition(fade_start_ms)
                self._player.play()
                anim = QPropertyAnimation(self._audio_output, b"volume", self)
                anim.setDuration(fade_ms)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.InQuad)
                anim.start()
                self._fade_anim = anim   # keep reference alive
            else:
                self._audio_output.setVolume(1.0)
                self._player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("⏸  Pause" if playing else "▶  Play")
        f = "-apple-system"
        self._play_btn.setStyleSheet(
            f"QPushButton#playBtn {{ background: {_AMBER}; color: #000; border: none;"
            f" border-radius: 8px; font: bold 13px {f}; }}"
            f"QPushButton#playBtn:hover {{ background: #ffb340; }}"
            if playing else ""
        )

    def _on_marker_moved(self, t: float) -> None:
        self._start_spin.blockSignals(True)
        self._start_spin.setValue(t)
        self._start_spin.blockSignals(False)
        if self._active_idx >= 0:
            self._entries[self._active_idx].chorus_start = t

    def _on_spin_changed(self, value: float) -> None:
        self._waveform.set_marker(value)
        if self._active_idx >= 0:
            self._entries[self._active_idx].chorus_start = value

    # ── Export ────────────────────────────────────────────────────────────────

    def _output_filename(self, entry: _FileEntry) -> str:
        year   = self._year_edit.text().strip()
        prefix = self._prefix_edit.text().strip()
        stem   = os.path.splitext(os.path.basename(entry.path))[0]
        ext    = self._fmt_combo.currentText().lower()
        parts  = [p for p in (year, prefix, stem) if p]
        return "_".join(parts) + f".{ext}"

    def _run_export(self, selected_only: bool) -> None:
        to_export = [
            self._entries[i]
            for i in range(self._file_list.count())
            if self._entries[i].result is not None
            and (
                not selected_only
                or self._file_list.item(i).checkState() == Qt.CheckState.Checked
            )
        ]
        if not to_export:
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Choose Export Folder")
        if not dest_dir:
            return

        errors: list[str] = []
        for entry in to_export:
            dest = os.path.join(dest_dir, self._output_filename(entry))
            try:
                export(
                    source_path=entry.path,
                    dest_path=dest,
                    start_seconds=entry.chorus_start,
                    fade_in_ms=int(self._fade_in_spin.value() * 1000)
                    if self._fade_in_btn.isChecked() else 0,
                    fade_in_curve=self._fade_curve_combo.currentText().lower(),
                    normalize=self._norm_btn.isChecked(),
                )
            except FileNotFoundError as exc:
                if "ffprobe" in str(exc) or "ffmpeg" in str(exc):
                    QMessageBox.critical(
                        self, "ffmpeg Not Found",
                        "Exporting requires ffmpeg.\n\nInstall: brew install ffmpeg"
                    )
                    return
                errors.append(f"{os.path.basename(entry.path)}: {exc}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{os.path.basename(entry.path)}: {exc}")

        if errors:
            QMessageBox.warning(self, "Export Errors", "\n".join(errors))

    # ── Select all / none ─────────────────────────────────────────────────────

    def _toggle_select_all(self) -> None:
        n = self._file_list.count()
        all_on = all(
            self._file_list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(n)
        ) if n else False
        state = Qt.CheckState.Unchecked if all_on else Qt.CheckState.Checked
        self._file_list.blockSignals(True)
        for i in range(n):
            self._file_list.item(i).setCheckState(state)
        self._file_list.blockSignals(False)
        self._sel_all_btn.setText("Deselect All" if not all_on else "Select All")
        self._refresh_export_buttons()

    def _refresh_export_buttons(self) -> None:
        n_ready = sum(1 for e in self._entries if e.result is not None)
        n_checked = sum(
            1 for i in range(self._file_list.count())
            if self._entries[i].result is not None
            and self._file_list.item(i).checkState() == Qt.CheckState.Checked
        )
        fmt = self._fmt_combo.currentText()
        self._export_sel_btn.setText(
            f"Export Selected ({n_checked})" if n_checked else "Export Selected"
        )
        self._export_all_btn.setText(
            f"Export All ({n_ready})" if n_ready else "Export All"
        )
        self._export_sel_btn.setEnabled(n_checked > 0)
        self._export_all_btn.setEnabled(n_ready > 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #48484d; font: 10px -apple-system;")
    return lbl
