"""Command line: safezone check <video>."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__

PLATFORMS = {"meta", "youtube-shorts"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="safezone",
        description="Grant Merriel's video safe-zone checker for 9:16 and 4:5 ads "
        "(Instagram, Facebook, YouTube Shorts and the 4:5 Feed crop).",
    )
    p.add_argument("--version", action="version", version=f"safezone {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check one finished video")
    c.add_argument("video")
    c.add_argument("--out", help="report folder (default: ./safezone-<video name>)")
    c.add_argument("--platforms", help="comma list from meta,youtube-shorts (default: both)")
    c.add_argument("--disclaimer", action="store_true", help="Meta's stricter disclaimer bottom")
    c.add_argument("--fps", type=float, default=4.0, help="frames sampled per second")
    c.add_argument(
        "--backend",
        choices=["auto", "vision", "rapidocr"],
        default="auto",
        help="text reader (default: Apple Vision on a Mac, else RapidOCR)",
    )
    c.add_argument("--json", action="store_true", help="print the full result as JSON")
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    from . import check, detect

    platforms = [x.strip() for x in a.platforms.split(",")] if a.platforms else None
    if platforms and not set(platforms) <= PLATFORMS:
        bad = ", ".join(sorted(set(platforms) - PLATFORMS))
        print(f"unknown platform: {bad} (use {', '.join(sorted(PLATFORMS))})", file=sys.stderr)
        return 2
    try:
        result = check.check_video(
            a.video,
            a.out,
            platforms=platforms,
            disclaimer=a.disclaimer,
            fps=a.fps,
            which=None if a.backend == "auto" else a.backend,
        )
    except FileNotFoundError as exc:
        print(f"video not found: {exc}", file=sys.stderr)
        return 2
    except detect.DetectionUnavailable as exc:
        print(f"cannot check this video here: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2) if a.json else result["summary"])
    return 0
