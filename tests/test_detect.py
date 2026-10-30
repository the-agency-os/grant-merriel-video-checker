import shutil
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from safezone import detect

needs_vision = pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"), reason="Apple Vision unavailable"
)
needs_rapidocr = pytest.mark.skipif(
    not detect._rapidocr_available(), reason="RapidOCR not installed"
)


def _font(size):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _frame(path, text, xy, size=(1080, 1920)):
    im = Image.new("RGB", size, (30, 40, 50))
    font = _font(70)
    ImageDraw.Draw(im).text(xy, text, font=font, fill="white")
    im.save(path)
    return path


@needs_vision
def test_helper_finds_text_box_in_pixels(tmp_path):
    d = tmp_path / "with space"
    d.mkdir()
    p = _frame(d / "f.png", "SAFE TEXT", (200, 1000))
    [dets] = detect.run_helper([p])
    texts = [x for x in dets if x.kind == "text"]
    assert texts and "SAFE" in texts[0].text.upper()
    b = texts[0].box
    assert 180 <= b.x0 <= 220 and 990 <= b.y0 <= 1030 and b.y1 < 1100


@needs_vision
def test_detect_video_samples_at_fps_and_normalises(tmp_path):
    frames = [_frame(tmp_path / f"{i:03}.png", "HELLO", (100, 900), (540, 960)) for i in range(30)]
    src = tmp_path / "v.mp4"

    detect.run_ffmpeg(
        [
            "-framerate",
            "30",
            "-i",
            str(tmp_path / "%03d.png"),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(src),
        ]
    )
    out = detect.detect_video(src, tmp_path / "work", fps=4, canvas=(1080, 1920))
    assert [round(f.t, 2) for f in out] == [0.0, 0.25, 0.5, 0.75]
    assert all(Image.open(f.path).size == (1080, 1920) for f in out)
    assert any(d.kind == "text" for d in out[0].detections)
    assert len(frames) == 30


def test_unavailable_when_no_swiftc(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    monkeypatch.setattr(detect, "_cached_binary_ok", lambda: False)
    with pytest.raises(detect.DetectionUnavailable):
        detect.ensure_helper()


@needs_vision
def test_parallel_workers_keep_frame_order(tmp_path):
    words = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO"]
    paths = [_frame(tmp_path / f"{i}.png", w, (200, 1000)) for i, w in enumerate(words)]
    results = detect.run_helper(paths, workers=3)
    found = [next(d.text for d in dets if d.kind == "text").upper() for dets in results]
    assert found == words


def _fake_helper(tmp_path, monkeypatch, body):
    script = tmp_path / "fake-helper"
    script.write_text("#!/usr/bin/env python3\n" + body)
    script.chmod(0o755)
    monkeypatch.setattr(detect, "ensure_helper", lambda: script)


def test_many_frames_do_not_deadlock(tmp_path, monkeypatch):
    _fake_helper(
        tmp_path,
        monkeypatch,
        (
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    p = line.strip()\n"
            "    t = [{'s': 'x' * 40, 'c': 1.0, 'box': [1, 2, 3, 4]}] * 12\n"
            "    d = {'path': p, 'w': 1, 'h': 1, 'text': t, 'faces': []}\n"
            "    print(json.dumps(d), flush=True)\n"
            "    sys.stderr.write('progress ' * 20 + '\\n')\n"
        ),
    )
    paths = [
        tmp_path / "a very long directory name with spaces" / f"f{i:05}.png" for i in range(3000)
    ]
    import threading

    out = {}
    th = threading.Thread(
        target=lambda: out.setdefault("r", detect.run_helper(paths, workers=1)), daemon=True
    )
    th.start()
    th.join(timeout=60)
    assert not th.is_alive(), "run_helper deadlocked"
    assert len(out["r"]) == 3000 and len(out["r"][0]) == 12


def test_helper_error_lines_mean_detection_unavailable(tmp_path, monkeypatch):
    _fake_helper(
        tmp_path,
        monkeypatch,
        (
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    print(json.dumps({'path': line.strip(), 'error': 'unreadable'}), flush=True)\n"
        ),
    )
    with pytest.raises(detect.DetectionUnavailable):
        detect.run_helper([tmp_path / "f00000.png"], workers=1)


def test_sample_frames_clears_stale_frames(tmp_path):

    src = tmp_path / "v.mp4"
    detect.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x2b3a4a:s=540x960:r=30:d=1",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ]
    )
    out = tmp_path / "frames"
    out.mkdir()
    Image.new("RGB", (10, 10)).save(out / "f09999.png")
    frames = detect.sample_frames(src, out, 4, (1080, 1920))
    assert len(frames) == 4 and not (out / "f09999.png").exists()


@needs_rapidocr
def test_rapidocr_finds_text_box_in_pixels(tmp_path):
    p = _frame(tmp_path / "f.png", "SAFE TEXT", (200, 1000))
    [dets] = detect.run_rapidocr([p])
    texts = [x for x in dets if x.kind == "text"]
    assert texts and "SAFE" in texts[0].text.upper()
    b = texts[0].box
    assert 170 <= b.x0 <= 230 and 980 <= b.y0 <= 1040 and b.y1 < 1110


def test_backend_choice(monkeypatch):
    monkeypatch.setenv("SAFEZONE_BACKEND", "rapidocr")
    assert detect.backend() == "rapidocr"
    monkeypatch.setattr(detect, "_vision_possible", lambda: False)
    monkeypatch.setattr(detect, "_rapidocr_available", lambda: False)
    monkeypatch.delenv("SAFEZONE_BACKEND")
    with pytest.raises(detect.DetectionUnavailable):
        detect.backend()


@needs_vision
def test_vision_boxes_are_tightened_to_the_letters(tmp_path):
    im = Image.new("RGB", (1080, 1920), (30, 40, 50))
    font = _font(70)
    d = ImageDraw.Draw(im)
    d.text((265, 1170), "ADVERTISING", font=font, fill="white")
    ink = d.textbbox((265, 1170), "ADVERTISING", font=font)
    p = tmp_path / "caps.png"
    im.save(p)
    [dets] = detect.run_helper([p])
    [t] = [x for x in dets if x.kind == "text"]
    assert abs(t.box.y1 - ink[3]) <= 6 and abs(t.box.y0 - ink[1]) <= 6, (t.box, ink)


def test_tighten_leaves_a_busy_background_alone(tmp_path):
    import random

    random.seed(1)
    im = Image.new("RGB", (400, 200), (0, 0, 0))
    px = im.load()
    for x in range(400):
        for y in range(200):
            v = random.choice((0, 255))
            px[x, y] = (v, v, v)
    box = detect.Rect(10, 10, 390, 190)
    assert detect.tighten(im.convert("L"), box) == box
