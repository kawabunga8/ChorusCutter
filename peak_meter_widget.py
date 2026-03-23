"""
peak_meter_widget.py — Vertical segmented LED peak meter for Chorus Cutter.

Segments run bottom (quiet) → top (loud).  Click to reset the clip indicator.
"""

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

_DB_MIN = -48.0   # bottom of meter range
_DB_MAX =   0.0   # top of meter range (0 dBFS)
_SEGS   =  40     # number of LED segments
_YELLOW =  -9.0   # green → yellow boundary (dBFS)
_RED    =  -3.0   # yellow → red   boundary (dBFS)

_HOLD_MS    = 1500  # peak-hold duration before decay starts (ms)
_TICK_MS    =   50  # decay-timer interval
_DECAY_STEP =  0.5  # dB lost per tick once hold expires


class PeakMeterWidget(QWidget):
    """Vertical segmented LED peak meter with hold-and-decay peak tick."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(22)
        self.setToolTip("Click to reset clip indicator")

        self._level: float = _DB_MIN
        self._peak:  float = _DB_MIN
        self._hold:  int   = 0
        self._clip:  bool  = False

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._decay)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_level(self, db: float) -> None:
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
        p   = QPainter(self)
        w   = self.width()
        h   = self.height()

        # Clip LED: small square at the very top.
        led_d = w - 4
        led_y = 2
        bar_h = h - led_d - 6   # height available for LED segments

        seg_unit = bar_h / _SEGS        # height of one segment slot (body + gap)
        seg_body = max(1.0, seg_unit - 1.0)

        level_frac = self._db_to_frac(self._level) * _SEGS
        peak_frac  = self._db_to_frac(self._peak)  * _SEGS

        bar_top = led_y + led_d + 4   # y-coordinate where bar starts (below LED)

        for i in range(_SEGS):
            # Segment 0 = bottom (quiet), segment _SEGS-1 = top (loud).
            seg_db = _DB_MIN + (i / _SEGS) * (_DB_MAX - _DB_MIN)
            lit    = i < level_frac

            if seg_db >= _RED:
                on_c, off_c = QColor("#ff3b30"), QColor("#3d1512")
            elif seg_db >= _YELLOW:
                on_c, off_c = QColor("#ff9f0a"), QColor("#38290f")
            else:
                on_c, off_c = QColor("#30c757"), QColor("#0d2818")

            # Draw from the bottom: segment 0 is at the bottom of the bar.
            y = int(round(bar_top + bar_h - (i + 1) * seg_unit))
            p.fillRect(QRect(2, y, w - 4, int(seg_body)), on_c if lit else off_c)

        # Peak-hold tick.
        if self._peak > _DB_MIN:
            pi  = min(int(peak_frac), _SEGS - 1)
            pdb = _DB_MIN + (pi / _SEGS) * (_DB_MAX - _DB_MIN)
            pc  = (QColor("#ff3b30") if pdb >= _RED else
                   QColor("#ff9f0a") if pdb >= _YELLOW else QColor("#30c757"))
            py  = int(round(bar_top + bar_h - (pi + 1) * seg_unit))
            p.fillRect(QRect(2, py, w - 4, int(seg_body)), pc)

        # Clip LED at top.
        p.fillRect(QRect(2, led_y, led_d, led_d),
                   QColor("#ff3b30") if self._clip else QColor("#3d1512"))

        p.end()
