from pathlib import Path

from video_checker import pace
from video_checker.captions import Word
from video_checker.judge import Element
from video_checker.zones import Rect


def steady(n, step, start=0.0):
    return [Word(f"w{i}", start + i * step, start + i * step + step * 0.8) for i in range(n)]


def text(i, s, start, end):
    return Element(f"t{i}", "text", s, start, end, Rect(150, 1130, 930, 1210), 1.0, Path("f.png"))


def test_steady_conversational_pace_passes():
    c = pace.pace_check(steady(75, 0.4), [])
    assert c.status == "PASS"
    assert "150 words a minute" in c.lines[0]


def test_slow_pace_warns():
    c = pace.pace_check(steady(60, 0.5), [])
    assert c.status == "WARN" and "120 words a minute" in " ".join(c.lines)
    assert "slow" in " ".join(c.lines)


def test_dead_air_is_listed_with_its_time():
    words = steady(12, 0.4) + steady(12, 0.4, start=4.8 + 1.2)
    c = pace.pace_check(words, [])
    joined = " ".join(c.lines)
    assert c.status == "WARN" and "0:04.7" in joined and "1.3 s" in joined


def test_slow_start_warns():
    c = pace.pace_check(steady(40, 0.4, start=1.6), [])
    assert c.status == "WARN" and "first word at 0:01.6" in " ".join(c.lines)


def test_slow_stretch_is_located():
    words = steady(30, 0.35) + steady(17, 0.6, start=10.5)
    c = pace.pace_check(words, [])
    assert "slow stretch" in " ".join(c.lines)


def test_caption_too_fast_to_read_warns():
    caps = [
        text(1, "THIS IS A VERY LONG CAPTION LINE HERE", 0.0, 1.0),
        text(2, "SHORT ONE", 1.0, 2.0),
    ]
    c = pace.pace_check(steady(75, 0.4), caps)
    joined = " ".join(c.lines)
    assert "chars a second" in joined and "LONG CAPTION" in joined
    assert "SHORT ONE" not in joined


def test_no_speech_is_info():
    assert pace.pace_check([], []).status == "INFO"


def test_one_slow_patch_is_not_smeared_across_fast_speech():
    words = steady(29, 0.35) + steady(17, 0.6, start=10.2) + steady(57, 0.35, start=20.4)
    c = pace.pace_check(words, [])
    stretch = [ln for ln in c.lines if "slow stretch" in ln]
    assert stretch and "–0:2" in stretch[0]  # ends in the 20s, not at the end of the ad


def test_fast_captions_are_information_not_a_warning():
    caps = [text(1, "THIS IS A VERY LONG CAPTION LINE HERE", 0.0, 1.0)]
    c = pace.pace_check(steady(75, 0.4), caps)
    assert c.status == "PASS"
    assert any(ln.startswith("INFO") and "17 characters a second" in ln for ln in c.lines)


def test_two_slow_patches_with_fast_speech_between_stay_separate():
    words = (
        steady(29, 0.35)
        + steady(17, 0.6, start=10.2)
        + steady(23, 0.35, start=20.4)
        + steady(17, 0.6, start=28.5)
        + steady(29, 0.35, start=38.6)
    )
    c = pace.pace_check(words, [])
    assert len([ln for ln in c.lines if "slow stretch" in ln]) == 2
