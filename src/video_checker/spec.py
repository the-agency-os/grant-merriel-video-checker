"""Video spec and sound: what the file is, and whether it will upload and play well."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import detect

META_MAX_BYTES = 4 * 1024**3  # Meta ads: video files up to 4 GB
LUFS_RANGE = (-18.0, -11.0)  # house rule; YouTube plays back at about -14 LUFS
PEAK_MAX = -1.0  # dBTP; above this, platform transcodes can clip
FPS_RANGE = (23.0, 60.0)
CODECS = {"h264", "hevc"}


@dataclass
class Check:
    """One extra row in the report: a verdict plus the lines that explain it."""

    key: str
    title: str
    status: str
    lines: list[str] = field(default_factory=list)
    source: str = ""


def _worst(statuses: list[str]) -> str:
    order = ["PASS", "INFO", "WARN", "FAIL"]
    return max(statuses or ["PASS"], key=order.index)


def parse_streams(stderr: str) -> dict:
    out = {"vcodec": None, "fps": None, "acodec": None, "duration": None}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", stderr)
    if m:
        out["duration"] = round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 2)
    for line in stderr.splitlines():
        if "Video:" in line and out["vcodec"] is None:
            out["vcodec"] = line.split("Video:")[1].split()[0].strip(",")
            f = re.search(r"([\d.]+) fps", line)
            out["fps"] = float(f[1]) if f else None
        elif "Audio:" in line and out["acodec"] is None:
            out["acodec"] = line.split("Audio:")[1].split()[0].strip(",")
    return out


def parse_loudness(stderr: str) -> tuple[float | None, float | None]:
    summary = stderr.split("Summary:")[-1]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    p = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return (float(i[1]) if i else None, float(p[1]) if p else None)


def judge_spec(width, height, vcodec, fps, has_audio, size_bytes) -> Check:
    lines = []
    short = min(width, height)
    if short >= 1080:
        lines.append(f"PASS · {width}×{height}")
    else:
        lines.append(f"WARN · {width}×{height}: export at 1080 wide or more (1080×1920 for 9:16)")
    if vcodec in CODECS:
        lines.append(f"PASS · video codec {vcodec}")
    else:
        lines.append(
            f"WARN · video codec {vcodec}: re-export as H.264 (Meta and YouTube recommend it)"
        )
    if fps and FPS_RANGE[0] <= fps <= FPS_RANGE[1]:
        lines.append(f"PASS · {fps:g} fps")
    else:
        lines.append(f"WARN · {fps} fps: use 24, 25, 30 or 60 fps")
    if has_audio:
        lines.append("PASS · sound track present")
    else:
        lines.append("WARN · no sound track: most people watch Reels and Shorts with sound on")
    gb = size_bytes / 1024**3
    if size_bytes > META_MAX_BYTES:
        lines.append(f"FAIL · file is {gb:.1f} GB: Meta takes video files up to 4 GB")
    else:
        lines.append(f"PASS · file size {size_bytes / 1024**2:.0f} MB")
    status = _worst([ln.split(" ·")[0] for ln in lines])
    return Check(
        "spec",
        "Video spec",
        status,
        lines,
        "Meta ads video specs (4 GB max); Meta and Google recommend H.264",
    )


def judge_sound(lufs, peak, has_audio) -> Check:
    if not has_audio or lufs is None:
        return Check("sound", "Sound", "INFO", ["INFO · no sound to measure"], "")
    lines = []
    lo, hi = LUFS_RANGE
    if lufs < lo:
        lines.append(f"WARN · {lufs:.1f} LUFS: quiet next to other ads; aim for about -14 LUFS")
    elif lufs > hi:
        lines.append(
            f"WARN · {lufs:.1f} LUFS: loud; platforms will turn it down, aim for about -14"
        )
    else:
        lines.append(f"PASS · {lufs:.1f} LUFS")
    if peak is not None and peak > PEAK_MAX:
        lines.append(f"WARN · peaks reach {peak:.1f} dBTP: may clip after upload; keep under -1")
    elif peak is not None:
        lines.append(f"PASS · peaks {peak:.1f} dBTP")
    status = _worst([ln.split(" ·")[0] for ln in lines])
    return Check(
        "sound",
        "Sound",
        status,
        lines,
        "House rule -18 to -11 LUFS, peaks under -1 dBTP; YouTube plays back at about -14",
    )


def check_file(source: Path, width: int, height: int) -> list[Check]:
    """Probe the file and measure loudness with ffmpeg; return the spec and sound rows."""
    ff = detect.ffmpeg_exe()
    info = subprocess.run([ff, "-hide_banner", "-i", str(source)], capture_output=True, text=True)
    s = parse_streams(info.stderr)
    has_audio = s["acodec"] is not None
    lufs = peak = None
    if has_audio:
        r = subprocess.run(
            [
                ff,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-vn",
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
        )
        lufs, peak = parse_loudness(r.stderr)
    return [
        judge_spec(width, height, s["vcodec"], s["fps"], has_audio, os.path.getsize(source)),
        judge_sound(lufs, peak, has_audio),
    ]
