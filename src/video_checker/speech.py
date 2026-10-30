"""Speech to text with word timings (faster-whisper), for checking captions against the voice.

Audio is decoded with the same ffmpeg the checker already uses and handed to faster-whisper as raw
16 kHz samples, so its own audio decoder (PyAV) isn't involved. The model downloads on first use
(`small` is about 460 MB) and is cached after that.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import detect
from .captions import Word

DEFAULT_MODEL = "small"  # base mishears ("add account"); small gets names and numbers right
RATE = 16000
_MODELS: dict[str, object] = {}


class SpeechUnavailable(RuntimeError):
    """faster-whisper isn't installed or the model can't be loaded."""


def decode_audio(source: Path):
    """Mono 16 kHz float32 samples; empty when the file has no sound track."""
    import numpy as np

    r = subprocess.run(
        [
            detect.ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
    )
    return np.frombuffer(r.stdout, dtype=np.float32)


def transcribe(
    source: Path,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    names: list[str] | None = None,
) -> list[Word]:
    """Words with times. `names` (brands, people) are given to whisper as hotwords so it spells
    them the way the captions should."""
    audio = decode_audio(source)
    if len(audio) < RATE // 4:
        return []
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechUnavailable(
            "speech check needs faster-whisper: pip install grant-merriel-video-checker"
        ) from exc
    if model not in _MODELS:
        try:
            _MODELS[model] = WhisperModel(model, device="cpu", compute_type="int8")
        except Exception as exc:  # download or load failure
            raise SpeechUnavailable(f"could not load the speech model '{model}': {exc}") from exc
    segments, _info = _MODELS[model].transcribe(
        audio,
        word_timestamps=True,
        vad_filter=True,
        language=language,
        hotwords=", ".join(names) if names else None,
    )
    return [
        Word(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in s.words or []
    ]
