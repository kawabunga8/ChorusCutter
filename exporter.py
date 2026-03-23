"""
exporter.py — Trim and export audio using Pydub.

Requires ffmpeg on $PATH for MP3 support:  brew install ffmpeg
"""

import os
import numpy as np
from pydub import AudioSegment, effects


def export(
    source_path: str,
    dest_path: str,
    start_seconds: float,
    end_seconds: float | None = None,
    fade_in_ms: int = 0,
    fade_in_curve: str = "linear",
    fade_out_ms: int = 2000,
    normalize: bool = False,
    gain_db: float = 0.0,
) -> None:
    """
    Load *source_path*, trim, optionally process, then write.

    Processing chain (in order): gain → normalize → fade-in → fade-out.

    The fade-in is applied to the audio leading up to *start_seconds*; the
    exported clip therefore begins *fade_in_ms* before the chorus start so
    the fade is audible, reaching full volume exactly at start_seconds.

    Parameters
    ----------
    fade_in_curve : str
        One of 'linear', 'exponential', 'logarithmic', 's-curve'.
    gain_db : float
        dB gain applied before normalization.
    """
    ext = os.path.splitext(source_path)[1].lower().lstrip(".")
    audio = AudioSegment.from_file(source_path, format=ext if ext else "mp3")

    # Determine actual clip boundaries.
    fade_start_ms = max(0, int(start_seconds * 1000) - fade_in_ms)
    start_ms = int(start_seconds * 1000)
    end_ms   = int(end_seconds * 1000) if end_seconds is not None else len(audio)

    clip_start = max(0, min(fade_start_ms, len(audio)))
    clip_end   = max(clip_start, min(end_ms, len(audio)))

    trimmed = audio[clip_start:clip_end]

    if gain_db != 0.0:
        trimmed = trimmed + gain_db   # pydub's + operator applies dB gain

    if normalize:
        trimmed = effects.normalize(trimmed)

    # Actual fade length in the trimmed clip (may be shorter if near start).
    actual_fade_ms = start_ms - clip_start
    if actual_fade_ms > 0 and len(trimmed) > actual_fade_ms:
        trimmed = _apply_fade_in(trimmed, actual_fade_ms, fade_in_curve)

    if fade_out_ms > 0 and len(trimmed) > fade_out_ms:
        trimmed = trimmed.fade_out(fade_out_ms)

    out_ext = os.path.splitext(dest_path)[1].lower().lstrip(".")
    if out_ext == "mp3":
        trimmed.export(dest_path, format="mp3", bitrate="192k")
    elif out_ext == "wav":
        trimmed.export(dest_path, format="wav")
    elif out_ext == "m4a":
        trimmed.export(dest_path, format="mp4")
    else:
        raise ValueError(f"Unsupported output format: .{out_ext}  (use .mp3 or .wav)")


def _apply_fade_in(audio: AudioSegment, fade_ms: int, curve: str) -> AudioSegment:
    """Apply a fade-in with the given curve shape using numpy sample manipulation."""
    if curve == "linear":
        return audio.fade_in(fade_ms)

    fade_frames = int(audio.frame_rate * fade_ms / 1000)
    fade_frames = min(fade_frames, int(audio.frame_count()))
    if fade_frames == 0:
        return audio

    t = np.linspace(0.0, 1.0, fade_frames)
    if curve == "exponential":
        gain = t ** 2
    elif curve == "logarithmic":
        gain = np.sqrt(t)
    elif curve == "s-curve":
        gain = 0.5 * (1.0 - np.cos(np.pi * t))
    else:
        gain = t

    sw = audio.sample_width
    ch = audio.channels
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sw, np.int16)

    samples = np.frombuffer(audio.raw_data, dtype=dtype).copy().astype(np.float64)
    gain_ch = np.repeat(gain, ch)[:fade_frames * ch]

    if sw == 1:          # unsigned, centred at 128
        samples[:len(gain_ch)] = (samples[:len(gain_ch)] - 128) * gain_ch + 128
        out = np.clip(samples, 0, 255).astype(np.uint8)
    else:
        samples[:len(gain_ch)] *= gain_ch
        max_v = 2 ** (8 * sw - 1)
        out = np.clip(samples, -max_v, max_v - 1).astype(dtype)

    return audio._spawn(out.tobytes())
