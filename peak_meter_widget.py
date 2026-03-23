"""
peak_meter_widget.py — Segmented LED peak meter for Chorus Cutter.

Click the widget to reset the clip indicator.
"""

import numpy as np
from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

_DB_MIN = -48.0   # bottom of meter range
_DB_MAX =   0.0   # top  of meter range (0 dBFS)
_SEGS   =  40     # number of LED segments
_YELLOW =  -9.0   # green → yellow boundary (dBFS)
_RED    =  -3.0   # yellow → red   boundary (dBFS)

_HOLD_MS    = 1500  # peak-hold duration before decay starts (ms)
_TICK_MS    =   50  # decay-timer interval
_DECAY_STEP =  0.5  # dB lost per tick once hold expires


class PeakMeterWidget(QWidget):
    """Horizontal segmented LED peak meter with hold-and-decay peak tick."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setToolTip("Click to reset clip indicator")

        self._level: float = _DB_MIN   # current level (dBFS)
        self._peak:  float = _DB_MIN   # held peak tick
        self._hold:  int   = 0         # ms remaining in hold phase
        self._clip:  bool  = False     # has signal hit 0 dBFS?

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._decay)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_level(self, db: float) -> None:
        """Feed a new level (dBFS).  Call from a polling timer during playback."""
        self._level = max(_DB_MIN, db)
        if db > self._peak:
            self._peak = db
            self._hold = _HOLD_MS
            if not self._timer.isActive():
                self._timer.start()
        if db >= -0.1:
            self._clip = True
        self.update()

    def reset(self) -> None:
        """Zero the meter (call when playback stops)."""
        self._level = _DB_MIN
        self._peak  = _DB_MIN
        self._hold  = 0
        self._clip  = False
        self._timer.stop()
        self.update()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decay(self) -> None:
        if self._hold > 0:
            self._hold -= _TICK_MS
        else:
            self._peak -= _DECAY_STEP
            if self._peak <= _DB_MIN:
                self._peak = _DB_MIN
                self._timer.stop()
        self.update()

    def _db_to_frac(self, db: float) -> float:
        return (max(_DB_MIN, min(_DB_MAX, db)) - _DB_MIN) / (_DB_MAX - _DB_MIN)

    def mousePressEvent(self, event) -> None:
        self._clip = False
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        h = self.height()

        # Clip LED occupies the rightmost (h-4) × (h-4) square.
        led_d = h - 4
        led_x = self.width() - led_d - 2
        bar_w = led_x - 6   # width available for the LED bar

        seg_unit = bar_w / _SEGS       # width of one segment slot (body + gap)
        seg_body = max(1.0, seg_unit - 1.0)

        level_frac = self._db_to_frac(self._level) * _SEGS
        peak_frac  = self._db_to_frac(self._peak)  * _SEGS

        for i in range(_SEGS):
            x      = int(round(i * seg_unit))
            seg_db = _DB_MIN + (i / _SEGS) * (_DB_MAX - _DB_MIN)
            lit    = i < level_frac

            if seg_db >= _RED:
                on_c, off_c = QColor("#ff3b30"), QColor("#3d1512")
            elif seg_db >= _YELLOW:
                on_c, off_c = QColor("#ff9f0a"), QColor("#38290f")
            else:
                on_c, off_c = QColor("#30c757"), QColor("#0d2818")

            p.fillRect(QRect(x, 2, int(seg_body), h - 4), on_c if lit else off_c)

        # Peak-hold tick — drawn as a bright single segment.
        if self._peak > _DB_MIN:
            pi  = min(int(peak_frac), _SEGS - 1)
            px  = int(round(pi * seg_unit))
            pdb = _DB_MIN + (pi / _SEGS) * (_DB_MAX - _DB_MIN)
            pc  = (QColor("#ff3b30") if pdb >= _RED else
                   QColor("#ff9f0a") if pdb >= _YELLOW else QColor("#30c757"))
            p.fillRect(QRect(px, 2, int(seg_body), h - 4), pc)

        # Clip LED.
        p.fillRect(QRect(led_x, 2, led_d, led_d),
                   QColor("#ff3b30") if self._clip else QColor("#3d1512"))

        p.end()
