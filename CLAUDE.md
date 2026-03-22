# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Python 3.13 via Homebrew — always use the project venv.

```bash
# First-time setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the app
.venv/bin/python main.py

# Quick smoke-test the analyzer against a file
.venv/bin/python -c "from analyzer import analyze; r = analyze('path/to/file.mp3'); print(r.bpm, r.chorus_start)"
```

`pydub` requires `ffmpeg` for MP3 support: `brew install ffmpeg`

## Architecture

| File | Role |
|------|------|
| `main.py` | Entry point; creates `QApplication` and `MainWindow` |
| `analyzer.py` | Pure analysis: loads audio with librosa, returns `AnalysisResult` (BPM, chorus start, segment boundaries, raw samples) |
| `waveform_widget.py` | Matplotlib figure embedded in PyQt6 via `FigureCanvasQTAgg`; draws waveform and movable chorus marker |
| `exporter.py` | Trims audio from a given start time using Pydub and writes MP3/WAV |
| `ui/main_window.py` | Main window: file open dialog, wires analyzer → waveform widget → exporter |

### Analysis pipeline (`analyzer.py`)

1. `librosa.load` → mono float32 array + sample rate
2. `librosa.beat.beat_track` → BPM + beat frame indices
3. `librosa.feature.chroma_cqt` synced to beats → beat-synchronous chroma matrix
4. Foote checkerboard novelty on the recurrence matrix → segment boundary beats
5. Cosine similarity between segment mean chromas → highest-scoring segment after the first 20 % of the track = chorus candidate

`AnalysisResult` is a dataclass; it carries `y` and `sr` so downstream code doesn't reload the file.

### Key design decisions

- **Analysis runs on a `QThread`** (`_AnalysisWorker` in `main_window.py`) so the UI stays responsive during librosa's load + processing. `finished`/`error` signals marshal results back to the main thread.
- **Chorus heuristic** — the "most repeated" segment after 20 % of track duration. Works well for verse/chorus pop structures; may need tuning for other genres.
- `pydub` requires `ffmpeg` on `$PATH` for MP3 support (`brew install ffmpeg`).
