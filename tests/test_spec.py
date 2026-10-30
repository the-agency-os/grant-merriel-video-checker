# ruff: noqa: E501  (STDERR holds real ffmpeg output lines verbatim)
from video_checker import detect, spec

STDERR = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'ad.mp4':
  Duration: 00:01:00.03, start: 0.000000, bitrate: 4221 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1080x1920 [SAR 1:1 DAR 9:16], 3999 kb/s, 29.97 fps, 30 tbr, 15360 tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706d), 48000 Hz, stereo, fltp, 128 kb/s (default)
"""

EBUR = """
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -16.2 LUFS
    Threshold: -26.4 LUFS

  True peak:
    Peak:        -0.4 dBFS
"""


def test_parse_streams():
    s = spec.parse_streams(STDERR)
    assert s == {"vcodec": "h264", "fps": 29.97, "acodec": "aac", "duration": 60.03}


def test_parse_streams_without_audio():
    s = spec.parse_streams(STDERR.split("  Stream #0:1")[0])
    assert s["acodec"] is None


def test_parse_loudness():
    assert spec.parse_loudness(EBUR) == (-16.2, -0.4)


def test_spec_rules():
    ok = spec.judge_spec(1080, 1920, "h264", 30.0, True, 50_000_000)
    assert ok.status == "PASS"
    low = spec.judge_spec(720, 1280, "h264", 30.0, True, 50_000_000)
    assert low.status == "WARN" and "1080" in " ".join(low.lines)
    odd = spec.judge_spec(1080, 1920, "prores", 120.0, False, 50_000_000)
    assert odd.status == "WARN" and len([x for x in odd.lines if "WARN" in x]) == 3
    huge = spec.judge_spec(1080, 1920, "h264", 30.0, True, 5 * 1024**3)
    assert huge.status == "FAIL"


def test_sound_rules():
    assert spec.judge_sound(-14.0, -1.5, True).status == "PASS"
    quiet = spec.judge_sound(-24.0, -6.0, True)
    assert quiet.status == "WARN" and "quiet" in " ".join(quiet.lines)
    hot = spec.judge_sound(-9.0, 0.2, True)
    assert hot.status == "WARN" and "loud" in " ".join(hot.lines) and "clip" in " ".join(hot.lines)
    assert spec.judge_sound(None, None, False).status == "INFO"


def test_real_file(tmp_path):
    src = tmp_path / "v.mp4"
    detect.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=1080x1920:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(src),
        ]
    )
    checks = spec.check_file(src, 1080, 1920)
    assert [c.key for c in checks] == ["spec", "sound"]
    assert checks[0].status == "PASS"
    assert checks[1].status in ("PASS", "WARN") and "LUFS" in " ".join(checks[1].lines)
