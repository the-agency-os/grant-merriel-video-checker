import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from video_checker import detect, speech

MODEL_CACHED = (
    Path.home() / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-small"
).exists()


def video_with(tmp_path, audio_args):
    src = tmp_path / "v.mp4"
    detect.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=540x960:r=30:d=3",
            *audio_args,
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ]
    )
    return src


def test_decode_audio_is_16k_mono(tmp_path):
    src = video_with(tmp_path, ["-f", "lavfi", "-i", "sine=f=440:d=3", "-c:a", "aac"])
    audio = speech.decode_audio(src)
    assert 2.8 * 16000 <= len(audio) <= 3.2 * 16000


def test_no_audio_track_gives_no_words(tmp_path):
    src = tmp_path / "silent.mp4"
    detect.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=540x960:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ]
    )
    assert len(speech.decode_audio(src)) == 0
    assert speech.transcribe(src) == []


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("say") or not MODEL_CACHED,
    reason="needs macOS 'say' and the cached whisper small model",
)
def test_transcribes_real_speech_with_word_times(tmp_path):
    aiff = tmp_path / "s.aiff"
    subprocess.run(["say", "-o", str(aiff), "So this morning I had a new lead come in"], check=True)
    src = video_with(tmp_path, ["-i", str(aiff), "-c:a", "aac"])
    words = speech.transcribe(src, model="small", language="en")
    text = " ".join(w.text.lower() for w in words)
    assert "morning" in text and "lead" in text
    assert all(w.end >= w.start for w in words) and words[0].start < 1.0


def test_names_are_passed_to_whisper_as_hotwords(tmp_path, monkeypatch):
    src = video_with(tmp_path, ["-f", "lavfi", "-i", "sine=f=440:d=3", "-c:a", "aac"])
    seen = {}

    class Fake:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return [], None

    monkeypatch.setitem(speech._MODELS, "fake", Fake())
    speech.transcribe(src, model="fake", names=["Valher Media", "Charley"])
    assert seen["hotwords"] == "Valher Media, Charley"
