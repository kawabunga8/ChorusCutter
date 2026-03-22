"""
exporter.py — Trim and export audio using Pydub.

Requires ffmpeg on $PATH for MP3 support:  brew install ffmpeg
"""

import os
from pydub import AudioSegment, effects


def export(
    source_path: str,
    dest_path: str,
    start_seconds: float,
    end_seconds: float | None = None,
    fade_out_ms: int = 2000,
    normalize: bool = False,
) -> None:
    """
    Load *source_path*, trim from *start_seconds* to *end_seconds*
    (or end of file), optionally apply a fade-out, and write to *dest_path*.

    Output format is inferred from *dest_path*'s extension (.mp3 or .wav).

    Parameters
    ----------
    source_path : str
        Original audio file (MP3 or WAV).
    dest_path : str
        Output path.  Extension must be .mp3 or .wav.
    start_seconds : float
        Trim start (seconds).
    end_seconds : float | None
        Trim end (seconds).  None = use full remaining track.
    fade_out_ms : int
        Duration of the trailing fade-out in milliseconds.  0 to disable.
    """
    ext = os.path.splitext(source_path)[1].lower().lstrip(".")
    audio = AudioSegment.from_file(source_path, format=ext if ext else "mp3")

    start_ms = int(start_seconds * 1000)
    end_ms = int(end_seconds * 1000) if end_seconds is not None else len(audio)

    start_ms = max(0, min(start_ms, len(audio)))
    end_ms = max(start_ms, min(end_ms, len(audio)))

    trimmed = audio[start_ms:end_ms]

    if normalize:
        trimmed = effects.normalize(trimmed)

    if fade_out_ms > 0 and len(trimmed) > fade_out_ms:
        trimmed = trimmed.fade_out(fade_out_ms)

    out_ext = os.path.splitext(dest_path)[1].lower().lstrip(".")
    if out_ext == "mp3":
        trimmed.export(dest_path, format="mp3", bitrate="192k")
    elif out_ext == "wav":
        trimmed.export(dest_path, format="wav")
    else:
        raise ValueError(f"Unsupported output format: .{out_ext}  (use .mp3 or .wav)")
