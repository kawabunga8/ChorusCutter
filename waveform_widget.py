"""
waveform_widget.py — Matplotlib waveform embedded in a PyQt6 widget.

Features:
  - Downsampled waveform drawn as a filled amplitude envelope.
  - Vertical lines for detected segment boundaries (subtle).
  - A draggable red marker line for the chorus start point.
  - Scroll-wheel zoom centered on cursor; middle-mouse-drag to pan.
  - zoom_in() / zoom_out() / reset_zoom() public methods for toolbar buttons.
  - Emits `marker_moved(float)` signal (seconds) whenever the marker moves.
"""

import numpy as np
from PyQt6.QtCore import pyqtSignal
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

_MIN_SPAN = 0.5   # minimum visible window width in seconds
_ZOOM_STEP = 0.6  # span multiplier per zoom-in step (< 1 = zoom in)


class WaveformWidget(FigureCanvasQTAgg):
    """Interactive waveform canvas with zoom and pan."""

    marker_moved = pyqtSignal(float)   # new chorus start in seconds
    fade_changed  = pyqtSignal(float)  # new fade-in duration in seconds

    def __init__(self, parent=None) -> None:
        fig = Figure(figsize=(8, 2.2), tight_layout=True)
        fig.patch.set_facecolor("#111114")
        super().__init__(fig)
        self.setParent(parent)

        self._ax = fig.add_subplot(111)
        self._setup_axes()

        self._duration: float = 1.0
        self._view_start: float = 0.0
        self._view_end: float = 1.0

        self._y_ds: np.ndarray | None = None   # downsampled waveform (stored for rescaling)
        self._times: np.ndarray | None = None
        self._boundaries: list[float] = []
        self._scale: float = 1.0

        self._marker_time: float = 0.0
        self._marker_line = None

        self._fade_in_duration: float = 0.0
        self._fade_in_artists: list = []
        self._fade_curve: str = "linear"

        self._dragging: bool = False          # left-drag = move marker
        self._dragging_fade: bool = False     # left-drag = resize fade end
        self._panning: bool = False           # middle-drag = pan view
        self._pan_x0: float = 0.0            # pixel x at pan start
        self._pan_vs0: float = 0.0           # view_start at pan start
        self._pan_ve0: float = 1.0           # view_end at pan start

        self.mpl_connect("button_press_event",   self._on_press)
        self.mpl_connect("motion_notify_event",  self._on_motion)
        self.mpl_connect("button_release_event", self._on_release)
        self.mpl_connect("scroll_event",         self._on_scroll)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(
        self,
        y: np.ndarray,
        sr: int,
        duration: float,
        boundaries: list[float],
        chorus_start: float,
    ) -> None:
        """Render the waveform for a new audio file."""
        self._duration = duration
        self._view_start = 0.0
        self._view_end = duration
        self._scale = 1.0

        # Downsample once and cache for later rescaling.
        step = max(1, len(y) // 4000)
        self._y_ds = y[::step]
        self._times = np.linspace(0.0, duration, len(self._y_ds))
        self._boundaries = boundaries

        self._ax.cla()
        self._marker_line = None
        self._fade_in_artists = []
        self._setup_axes()
        self._draw_waveform()

        self._ax.set_xlim(0, duration)
        self._ax.set_ylim(-1.05, 1.05)
        self._set_marker(chorus_start, emit=False)
        self.draw()

    def set_scale(self, scale: float) -> None:
        """Rescale the displayed waveform (e.g. to reflect gain / normalize)."""
        if self._y_ds is None:
            return
        self._scale = scale
        # Redraw only the waveform fill+lines, keep marker and fade overlay.
        xlim = self._ax.get_xlim()
        self._ax.cla()
        self._marker_line = None
        self._fade_in_artists = []
        self._setup_axes()
        self._draw_waveform()
        self._ax.set_xlim(*xlim)
        self._ax.set_ylim(-1.05, 1.05)
        self._set_marker(self._marker_time, emit=False)
        self._redraw_fade_in()
        self.draw()

    def _draw_waveform(self) -> None:
        """Draw fill + envelope lines using current _y_ds * _scale."""
        y  = np.clip(self._y_ds * self._scale, -1.0, 1.0)
        t  = self._times
        self._ax.fill_between(t, y, -y, color="#3d7ef0", alpha=0.35, linewidth=0)
        self._ax.plot(t,  y, color="#5b9cf6", linewidth=0.7, alpha=0.9)
        self._ax.plot(t, -y, color="#5b9cf6", linewidth=0.7, alpha=0.9)
        for b in self._boundaries:
            if 0.0 < b < self._duration:
                self._ax.axvline(b, color="#48484d", linewidth=0.8,
                                 linestyle="--", alpha=0.7)

    def set_marker(self, time_seconds: float) -> None:
        """Move the chorus marker (called externally, e.g. from spinbox)."""
        self._set_marker(time_seconds, emit=False)
        self.draw()

    def set_fade_in(self, duration_seconds: float) -> None:
        """Draw (or erase) the fade-in ramp overlay. 0 = hidden."""
        self._fade_in_duration = max(0.0, duration_seconds)
        self._redraw_fade_in()
        self.draw()

    def set_fade_curve(self, curve: str) -> None:
        """Redraw the overlay with a new curve shape ('linear', 'exponential',
        'logarithmic', 's-curve')."""
        self._fade_curve = curve
        self._redraw_fade_in()
        self.draw()

    def zoom_in(self) -> None:
        """Zoom in centred on the current marker position."""
        self._zoom(self._marker_time, _ZOOM_STEP)

    def zoom_out(self) -> None:
        """Zoom out centred on the current marker position."""
        self._zoom(self._marker_time, 1.0 / _ZOOM_STEP)

    def reset_zoom(self) -> None:
        """Restore full-track view."""
        self._view_start = 0.0
        self._view_end = self._duration
        self._ax.set_xlim(0.0, self._duration)
        self.draw()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _setup_axes(self) -> None:
        ax = self._ax
        ax.set_facecolor("#111114")
        ax.tick_params(colors="#48484d", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#38383d")
        ax.set_xlabel("Time (s)", color="#48484d", fontsize=8)
        ax.set_ylabel("Amplitude", color="#48484d", fontsize=8)

    def _set_marker(self, t: float, emit: bool = True) -> None:
        t = float(np.clip(t, 0.0, self._duration))
        self._marker_time = t
        if self._marker_line is not None:
            self._marker_line.remove()
        self._marker_line = self._ax.axvline(
            t, color="#ff6b6b", linewidth=1.8, zorder=5,
        )
        # Keep fade-in overlay anchored to the marker.
        self._redraw_fade_in()
        if emit:
            self.marker_moved.emit(t)

    def _fade_start(self) -> float:
        """Time where the fade-in begins (left of the red marker line)."""
        return max(0.0, self._marker_time - self._fade_in_duration)

    def _redraw_fade_in(self) -> None:
        """Remove and re-draw the fade-in ramp overlay using the current curve.

        The fade culminates *at* the red chorus-start marker.
        The draggable yellow line marks the beginning of the fade.
        """
        for artist in self._fade_in_artists:
            try:
                artist.remove()
            except ValueError:
                pass
        self._fade_in_artists = []

        if self._fade_in_duration <= 0:
            return

        t0 = self._fade_start()          # fade begins here (draggable yellow line)
        t1 = self._marker_time           # fade ends here  (culminates at red line)
        if t1 <= t0:
            return

        n = 200
        norm = np.linspace(0.0, 1.0, n)
        x    = np.linspace(t0, t1, n)

        if self._fade_curve == "exponential":
            ramp = norm ** 2
        elif self._fade_curve == "logarithmic":
            ramp = np.sqrt(norm)
        elif self._fade_curve == "s-curve":
            ramp = 0.5 * (1.0 - np.cos(np.pi * norm))
        else:
            ramp = norm

        # Filled volume envelope.
        fill = self._ax.fill_between(
            x, ramp * 1.05, -ramp * 1.05,
            color="#ffd60a", alpha=0.13, linewidth=0, zorder=3,
        )
        # Curve guide lines (top + bottom mirror).
        (lt,) = self._ax.plot(x,  ramp * 1.05, color="#ffd60a",
                              linewidth=1.2, alpha=0.6, zorder=3)
        (lb,) = self._ax.plot(x, -ramp * 1.05, color="#ffd60a",
                              linewidth=1.2, alpha=0.6, zorder=3)
        # Draggable start line at t0 — solid, slightly brighter.
        vl = self._ax.axvline(t0, color="#ffd60a", linewidth=2.0,
                              linestyle="-", alpha=0.8, zorder=4)
        self._fade_in_artists = [fill, lt, lb, vl]

    def _grab_threshold(self) -> float:
        """Marker grab radius scales with the current view span."""
        span = self._view_end - self._view_start
        return max(0.05, span * 0.02)   # 2 % of visible window

    def _time_from_event(self, event) -> float | None:
        if event.inaxes != self._ax or event.xdata is None:
            return None
        return float(np.clip(event.xdata, 0.0, self._duration))

    def _zoom(self, center: float, factor: float) -> None:
        """Zoom the view by *factor* around *center* (data seconds)."""
        span = self._view_end - self._view_start
        new_span = span * factor
        new_span = max(_MIN_SPAN, min(self._duration, new_span))

        # Keep center fixed relative to its position within the old window.
        ratio = (center - self._view_start) / span if span > 0 else 0.5
        new_start = center - ratio * new_span
        new_end = new_start + new_span

        # Clamp to [0, duration].
        if new_start < 0:
            new_start = 0.0
            new_end = new_span
        if new_end > self._duration:
            new_end = self._duration
            new_start = max(0.0, new_end - new_span)

        self._view_start, self._view_end = new_start, new_end
        self._ax.set_xlim(self._view_start, self._view_end)
        self.draw()

    # ── Mouse / scroll handlers ───────────────────────────────────────────────

    def _on_press(self, event) -> None:
        if event.button == 1:
            t = self._time_from_event(event)
            if t is None:
                return
            # Prioritise fade-start handle when it's active.
            if self._fade_in_duration > 0:
                if abs(t - self._fade_start()) <= self._grab_threshold():
                    self._dragging_fade = True
                    return
            self._set_marker(t)
            self._dragging = True
            self.draw()

        elif event.button == 2:                  # middle — start pan
            if event.x is not None:
                self._panning = True
                self._pan_x0 = event.x
                self._pan_vs0 = self._view_start
                self._pan_ve0 = self._view_end

    def _on_motion(self, event) -> None:
        if self._dragging_fade:
            t = self._time_from_event(event)
            if t is not None:
                # Duration = distance from cursor to the red marker line.
                new_dur = max(0.1, self._marker_time - t)
                self._fade_in_duration = new_dur
                self._redraw_fade_in()
                self.draw()
                self.fade_changed.emit(new_dur)

        elif self._dragging:
            t = self._time_from_event(event)
            if t is not None:
                self._set_marker(t)
                self.draw()

        elif self._panning and event.x is not None:
            span = self._pan_ve0 - self._pan_vs0
            # Convert pixel delta → data delta using axes bounding box.
            bbox = self._ax.get_window_extent()
            ax_width_px = bbox.width
            if ax_width_px > 0:
                dx_data = -(event.x - self._pan_x0) / ax_width_px * span
            else:
                dx_data = 0.0

            new_start = self._pan_vs0 + dx_data
            new_end = self._pan_ve0 + dx_data

            # Clamp so we don't pan off the edge.
            if new_start < 0:
                new_start = 0.0
                new_end = span
            if new_end > self._duration:
                new_end = self._duration
                new_start = max(0.0, new_end - span)

            self._view_start, self._view_end = new_start, new_end
            self._ax.set_xlim(self._view_start, self._view_end)
            self.draw()

    def _on_release(self, event) -> None:
        self._dragging = False
        self._dragging_fade = False
        self._panning = False

    def _on_scroll(self, event) -> None:
        """Scroll up = zoom in, scroll down = zoom out, centred on cursor."""
        if event.inaxes != self._ax or event.xdata is None:
            return
        factor = _ZOOM_STEP if event.step > 0 else 1.0 / _ZOOM_STEP
        self._zoom(event.xdata, factor)
