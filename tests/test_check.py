import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from video_checker import check, cli, detect

FONT = "/System/Library/Fonts/Helvetica.ttc" if sys.platform == "darwin" else None
FACE_FRAME = Path(__file__).parent / "fixtures" / "face-frame.jpg"
BACKENDS = [
    pytest.param(
        "vision",
        marks=pytest.mark.skipif(
            sys.platform != "darwin" or not shutil.which("swiftc"), reason="no Apple Vision"
        ),
    ),
    pytest.param(
        "rapidocr", marks=pytest.mark.skipif(not detect._rapidocr_available(), reason="no RapidOCR")
    ),
]


def _font(size):
    if FONT:
        return ImageFont.truetype(FONT, size)
    return ImageFont.load_default(size=size)


def text_video(dst, text, xy, seconds=2, size=(1080, 1920), bg=None):
    frames = dst.parent / f".{dst.stem}-frames"
    frames.mkdir(parents=True, exist_ok=True)
    im = Image.open(bg).convert("RGB").resize(size) if bg else Image.new("RGB", size, (30, 40, 50))
    ImageDraw.Draw(im).text(xy, text, font=_font(70), fill="white")
    for i in range(int(seconds * 30)):
        im.save(frames / f"{i:04}.png")
    detect.run_ffmpeg(
        [
            "-framerate",
            "30",
            "-i",
            str(frames / "%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ]
    )
    shutil.rmtree(frames)
    return dst


def test_aspects():
    assert check.classify_aspect(1080, 1920) == "9:16"
    assert check.classify_aspect(1080, 1350) == "4:5"
    assert check.classify_aspect(1920, 1080) == "16:9"


def test_probe_reads_size_and_duration(tmp_path):
    src = text_video(tmp_path / "v.mp4", "HI", (100, 100), seconds=1, size=(540, 960))
    w, h, d = check.probe(src)
    assert (w, h) == (540, 960) and 0.9 <= d <= 1.1


@pytest.mark.parametrize("which", BACKENDS)
def test_breach_fails_meta_and_master(tmp_path, which):
    src = text_video(tmp_path / "b.mp4", "everything figured out", (267, 1400))
    r = check.check_video(src, tmp_path / "out", which=which)
    assert r["verdicts"]["meta"] == "FAIL" and r["verdicts"]["master"] == "FAIL"
    assert "lift the block" in r["summary"]
    assert (tmp_path / "out" / "report.html").exists()
    assert (tmp_path / "out" / "summary.txt").exists()


@pytest.mark.parametrize("which", BACKENDS)
def test_safe_line_passes(tmp_path, which):
    src = text_video(tmp_path / "s.mp4", "SAFE LINE", (300, 800))
    r = check.check_video(src, tmp_path / "out", which=which)
    zone_keys = {"master", "meta", "youtube-shorts", "crop-4x5", "face"}
    assert {k: v for k, v in r["verdicts"].items() if k in zone_keys} == {
        "master": "PASS",
        "meta": "PASS",
        "youtube-shorts": "PASS",
        "crop-4x5": "PASS",
        "face": "PASS",
    }


@pytest.mark.parametrize("which", BACKENDS)
def test_text_across_a_real_mouth_warns(tmp_path, which):
    src = text_video(tmp_path / "m.mp4", "ACROSS THE MOUTH", (240, 790), bg=FACE_FRAME)
    r = check.check_video(src, tmp_path / "out", which=which)
    assert r["verdicts"]["face"] == "WARN"


def test_16x9_is_not_checked(tmp_path):
    src = text_video(tmp_path / "w.mp4", "WIDE", (100, 100), seconds=1, size=(960, 540))
    r = check.check_video(src, tmp_path / "out")
    assert r["verdicts"] == {} and "9:16 and 4:5" in r["summary"]


def test_cli_prints_summary(tmp_path, capsys):
    src = text_video(tmp_path / "c.mp4", "SAFE LINE", (300, 800), seconds=1)
    assert cli.main(["check", str(src), "--out", str(tmp_path / "o")]) == 0
    assert "Safe-zone check:" in capsys.readouterr().out


def test_cli_rejects_unknown_platform(capsys):
    assert cli.main(["check", "x.mp4", "--platforms", "tiktok"]) == 2
    assert "unknown platform" in capsys.readouterr().err


@pytest.mark.parametrize("which", BACKENDS)
def test_text_on_the_chest_does_not_warn(tmp_path, which):
    src = text_video(tmp_path / "c.mp4", "ON THE CHEST", (300, 1120), bg=FACE_FRAME)
    r = check.check_video(src, tmp_path / "out", which=which)
    assert r["verdicts"]["face"] == "PASS"


EXTRA_KEYS = {"spec", "sound", "hook", "readability", "spelling", "timing"}


def test_every_extra_row_is_reported(tmp_path):
    src = text_video(tmp_path / "x.mp4", "SAFE LINE", (300, 800))
    r = check.check_video(src, tmp_path / "out", speech=False)
    assert EXTRA_KEYS <= set(r["verdicts"])
    assert r["verdicts"]["hook"] == "PASS" and r["verdicts"]["spec"] == "WARN"  # no sound track
    assert r["verdicts"]["spelling"] == "INFO"
    assert "Other checks" in (tmp_path / "out" / "report.html").read_text()


SPEECH_READY = (
    sys.platform == "darwin"
    and shutil.which("say")
    and (Path.home() / ".cache/huggingface/hub/models--Systran--faster-whisper-small").exists()
)


@pytest.mark.skipif(not SPEECH_READY, reason="needs macOS 'say' and the cached whisper model")
def test_caption_typo_against_real_speech(tmp_path):
    import subprocess

    aiff = tmp_path / "s.aiff"
    subprocess.run(["say", "-o", str(aiff), "So this morning I had a new lead"], check=True)
    silent = text_video(tmp_path / "v.mp4", "I HAD A NEW LEED", (180, 1120), seconds=3)
    src = tmp_path / "talk.mp4"
    detect.run_ffmpeg(
        ["-i", str(silent), "-i", str(aiff), "-c:v", "copy", "-c:a", "aac", "-shortest", str(src)]
    )
    r = check.check_video(src, tmp_path / "out")
    assert r["verdicts"]["spelling"] == "WARN"
    assert "LEED" in r["summary"]
