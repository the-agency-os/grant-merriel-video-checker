from pathlib import Path

from PIL import Image, ImageDraw

from video_checker import judge, readability
from video_checker.detect import Detection, FrameDetections
from video_checker.zones import Rect


def frame(tmp_path, name, fill_bg, fill_text, box):
    im = Image.new("RGB", (1080, 1920), fill_bg)
    ImageDraw.Draw(im).rectangle(
        (box[0] + 10, box[1] + 10, box[2] - 10, box[3] - 10), fill=fill_text
    )
    p = tmp_path / f"{name}.png"
    im.save(p)
    return p


def elements(tmp_path, specs, fps=4):
    """specs: list of (t, text, box, bg, fg)."""
    frames = []
    for t, text, box, bg, fg in specs:
        p = frame(tmp_path, f"f{t}", bg, fg, box)
        frames.append(FrameDetections(t, p, [Detection("text", text, 1.0, Rect(*box))]))
    return judge.group(frames, fps)


def test_no_hook_is_info_not_fail(tmp_path):
    els = elements(tmp_path, [(1.0, "late caption", (200, 1100, 800, 1180), "black", "white")])
    c = readability.hook_check(els)
    assert c.status == "INFO" and "no on-screen hook" in c.lines[0]


def test_hook_long_enough_passes(tmp_path):
    specs = [(t / 4, "HOOK LINE", (200, 400, 800, 480), "black", "white") for t in range(12)]
    c = readability.hook_check(elements(tmp_path, specs))
    assert c.status == "PASS" and "3.0 s" in c.lines[0]


def test_hook_gone_too_fast_warns(tmp_path):
    specs = [(t / 4, "HOOK LINE", (200, 400, 800, 480), "black", "white") for t in range(4)]
    c = readability.hook_check(elements(tmp_path, specs))
    assert c.status == "WARN" and "1.0 s" in c.lines[0]


def test_readable_text_passes(tmp_path):
    els = elements(tmp_path, [(0, "CLEAR", (200, 1100, 800, 1180), "black", "white")])
    assert readability.readability_check(els).status == "PASS"


def test_low_contrast_warns(tmp_path):
    els = elements(
        tmp_path, [(0, "FAINT", (200, 1100, 800, 1180), (205, 205, 205), (235, 235, 235))]
    )
    c = readability.readability_check(els)
    assert c.status == "WARN" and "contrast" in " ".join(c.lines)


def test_small_must_read_text_warns(tmp_path):
    els = elements(tmp_path, [(0, "TINY BUT MUST READ", (200, 1100, 800, 1140), "black", "white")])
    for e in els:
        e.tier = "must-read"
    c = readability.readability_check(els)
    assert c.status == "WARN" and "small" in " ".join(c.lines)


def test_contrast_ratio_formula():
    assert round(readability.contrast(255, 0), 1) == 21.0
    assert readability.contrast(128, 128) == 1.0
    assert Path(readability.__file__).exists()


def test_contrast_is_judged_after_a_fade_in(tmp_path):
    box = (200, 1100, 800, 1180)
    specs = [(0.0, "FADING IN", box, (205, 205, 205), (225, 225, 225))]
    specs += [(t / 4, "FADING IN", box, "black", "white") for t in range(1, 8)]
    c = readability.readability_check(elements(tmp_path, specs))
    assert c.status == "PASS"
