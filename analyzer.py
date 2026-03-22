"""
analyzer.py — Audio analysis module for Chorus Cutter.

Detects BPM and estimates the chorus start time using librosa's
self-similarity / structural segmentation approach.
"""

from dataclasses import dataclass

import numpy as np
import librosa
import librosa.segment
import librosa.feature


@dataclass
class AnalysisResult:
    """Results returned by analyze()."""
    bpm: float
    chorus_start: float          # seconds
    section_boundaries: list[float]  # seconds, all detected segment boundaries
    duration: float              # seconds
    y: np.ndarray                # raw audio samples
    sr: int                      # sample rate


def analyze(filepath: str) -> AnalysisResult:
    """
    Load and analyze an audio file.

    Steps:
      1. Load audio (mono, native sample rate).
      2. Detect BPM via beat tracking.
      3. Compute beat-synchronous chroma features.
      4. Build a recurrence matrix and derive a novelty / boundary curve.
      5. Segment the track and pick the most-repeated segment as the chorus.

    Parameters
    ----------
    filepath : str
        Path to an MP3 or WAV file.

    Returns
    -------
    AnalysisResult
    """
    y, sr = librosa.load(filepath, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # ── 1. BPM detection ─────────────────────────────────────────────────────
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])

    # ── 2. Beat-synchronous chroma features ──────────────────────────────────
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
    chroma_sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)

    # ── 3. Recurrence matrix (self-similarity) ────────────────────────────────
    # width=3 suppresses the main diagonal so we see non-trivial repetitions.
    R = librosa.segment.recurrence_matrix(
        chroma_sync,
        width=3,
        mode="affinity",
        sym=True,
    )

    # ── 4. Novelty / boundary curve ───────────────────────────────────────────
    # The recurrence-enhanced novelty curve highlights segment boundaries.
    novelty = _recurrence_novelty(R)

    # Pick peaks in the novelty curve as segment boundaries.
    boundary_beats = _pick_boundary_beats(novelty, beat_frames, min_gap_beats=8)

    # Convert boundary beat indices → time in seconds.
    if len(beat_frames) > 0:
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        boundary_times = [float(beat_times[b]) for b in boundary_beats
                          if b < len(beat_times)]
    else:
        boundary_times = []

    # Always include 0 and track end as boundaries.
    boundary_times = sorted(set([0.0] + boundary_times + [duration]))

    # ── 5. Identify the chorus segment ───────────────────────────────────────
    chorus_start = _find_chorus_start(
        chroma_sync, beat_frames, boundary_beats, beat_times=beat_times
        if len(beat_frames) > 0 else np.array([]), duration=duration
    )

    return AnalysisResult(
        bpm=round(bpm, 1),
        chorus_start=round(chorus_start, 2),
        section_boundaries=boundary_times,
        duration=round(duration, 2),
        y=y,
        sr=sr,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _recurrence_novelty(R: np.ndarray) -> np.ndarray:
    """
    Derive a 1-D novelty curve from a recurrence matrix using a
    checkerboard kernel (Foote novelty).  High values indicate
    likely segment boundaries.
    """
    n = R.shape[0]
    kernel_size = max(4, n // 16)

    # Build a checkerboard kernel.
    k = kernel_size
    checker = np.block([
        [ np.ones((k, k)), -np.ones((k, k))],
        [-np.ones((k, k)),  np.ones((k, k))],
    ])

    novelty = np.zeros(n)
    half = k  # checker is 2k × 2k

    for i in range(half, n - half):
        patch = R[i - half: i + half, i - half: i + half]
        if patch.shape == checker.shape:
            novelty[i] = float(np.sum(patch * checker))

    # Normalise to [0, 1].
    if novelty.max() > 0:
        novelty /= novelty.max()

    return novelty


def _pick_boundary_beats(
    novelty: np.ndarray,
    beat_frames: np.ndarray,
    min_gap_beats: int = 8,
) -> list[int]:
    """
    Pick local maxima in the novelty curve as segment boundary beat indices.
    Returns indices into *beat_frames* (not raw frame indices).
    """
    from scipy.signal import find_peaks

    if len(novelty) == 0:
        return []

    peaks, _ = find_peaks(novelty, distance=min_gap_beats, height=0.2)
    return peaks.tolist()


def _find_chorus_start(
    chroma_sync: np.ndarray,
    beat_frames: np.ndarray,
    boundary_beats: list[int],
    beat_times: np.ndarray,
    duration: float,
) -> float:
    """
    Identify the most likely chorus start time.

    Strategy:
      - Divide the track into segments defined by boundary_beats.
      - Compute a "repetition score" for each segment: the mean similarity
        of that segment's chroma to all other segments.
      - The segment with the highest score that starts *after* 20 % of the
        track (skipping the intro) is returned as the chorus.
      - Falls back to 25 % of duration if no good candidate is found.
    """
    n_beats = chroma_sync.shape[1]

    if n_beats == 0 or len(beat_times) == 0:
        return duration * 0.25

    # Build segment list: (start_beat, end_beat).
    boundaries = sorted(set([0] + [b for b in boundary_beats if 0 < b < n_beats]
                             + [n_beats]))
    segments = [(boundaries[i], boundaries[i + 1])
                for i in range(len(boundaries) - 1)
                if boundaries[i + 1] - boundaries[i] >= 4]  # at least 4 beats

    if len(segments) < 2:
        return duration * 0.25

    # Mean chroma vector per segment.
    seg_means = [chroma_sync[:, s:e].mean(axis=1) for s, e in segments]
    seg_means = np.stack(seg_means)  # (n_seg, 12)

    # Normalise rows.
    norms = np.linalg.norm(seg_means, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    seg_means_norm = seg_means / norms

    # Cosine similarity matrix between segments.
    sim = seg_means_norm @ seg_means_norm.T  # (n_seg, n_seg)
    np.fill_diagonal(sim, 0.0)              # exclude self-similarity

    # Repetition score = mean similarity to all other segments.
    scores = sim.mean(axis=1)

    # Only consider segments starting after 20 % of the track.
    early_cutoff = duration * 0.20
    best_score = -1.0
    best_start = duration * 0.25

    for idx, (s_beat, _) in enumerate(segments):
        if s_beat >= len(beat_times):
            continue
        t = float(beat_times[s_beat])
        if t < early_cutoff:
            continue
        if scores[idx] > best_score:
            best_score = scores[idx]
            best_start = t

    return best_start
