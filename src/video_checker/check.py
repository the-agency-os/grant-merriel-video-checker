"""Check one finished video: sample frames, find text and faces, judge them, write the report."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import __version__, captions, detect, judge, pace, readability, report, spec, speech, zones
from .spec import Check

BACKEND_NAMES = {"vision": "Apple Vision", "rapidocr": "RapidOCR + OpenCV"}


def classify_aspect(width: int, height: int, tolerance: float = 0.015) -> str:
    """Return the aspect-ratio family or ``unsupported``."""
    if not width or not height:
        return "unsupported"
    ratio = width / height
    candidates = {"9:16": 9 / 16, "16:9": 16 / 9, "4:5": 4 / 5, "1:1": 1.0}
    name, target = min(candidates.items(), key=lambda item: abs(ratio - item[1]))
    return name if abs(ratio - target) / target <= tolerance else "unsupported"


def probe(source: Path) -> tuple[int, int, float]:
    """Display size (after phone rotation) and duration, using only ffmpeg."""
    tmp = Path(tempfile.mkdtemp(prefix="video-checker-probe-"))
    try:
        r = subprocess.run(
            [detect.ffmpeg_exe(), "-y", "-i", str(source), "-frames:v", "1", str(tmp / "f.png")],
            capture_output=True,
            text=True,
        )
        if not (tmp / "f.png").exists():
            raise detect.DetectionUnavailable(f"could not read the video: {r.stderr[-300:]}")
        w, h = Image.open(tmp / "f.png").size
        duration = 0.0
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                hh, mm, ss = line.split("Duration:")[1].split(",")[0].strip().split(":")
                duration = int(hh) * 3600 + int(mm) * 60 + float(ss)
                break
        return w, h, duration
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def _speech_checks(source, elements, enabled, model, language, names=None) -> list[Check]:
    if not enabled:
        off = ["INFO · not checked (--no-speech)"]
        return [
            Check("spelling", "Captions vs speech", "INFO", off),
            Check("timing", "Caption timing", "INFO", off),
            Check("pace", "Pace", "INFO", off),
        ]
    try:
        words = speech.transcribe(source, model, language, names)
    except speech.SpeechUnavailable as exc:
        why = [f"INFO · not checked: {exc}"]
        return [
            Check("spelling", "Captions vs speech", "INFO", why),
            Check("timing", "Caption timing", "INFO", why),
            Check("pace", "Pace", "INFO", why),
        ]
    issues, stats = captions.compare(elements, words)
    spk = [(t, w) for w in words for t in captions.tokens(w.text)]
    return [
        captions.spelling_check(issues, stats),
        captions.timing_check(issues, stats),
        pace.pace_check(words, captions.caption_elements(elements, spk)),
    ]


def summary_text(
    meta: dict, verdicts: dict, blocks: list, cols: list, out: Path | None, extras=()
) -> str:
    titles = {z.key: z.title for z in cols}
    titles.update({c.key: c.title for c in extras})
    lines = [
        f"Safe-zone check: {Path(meta['source']).name} ({meta['aspect']}, "
        f"{meta['duration']:.1f} s, {meta['frames']} frames, "
        f"text reader: {BACKEND_NAMES.get(meta['backend'], meta['backend'])})",
        " · ".join(f"{titles.get(k, k)}: {v}" for k, v in verdicts.items()),
        "",
    ]
    todo = [b for b in blocks if any(s in ("FAIL", "WARN") for s in b.status.values())]
    if not blocks:
        lines.append("No text detected.")
    elif not todo:
        lines.append("Nothing to fix.")
    else:
        lines.append("What to fix:")
        for i, b in enumerate(blocks):
            if b not in todo:
                continue
            lines.append(
                f"- {report.block_label(i, b)}: text at y {b.y0}–{b.y1 - 1}, {b.count} lines, "
                f"{_ts(b.elements[0].start)}–{_ts(max(e.end for e in b.elements))}"
            )
            for k, st in b.status.items():
                if st in ("FAIL", "WARN"):
                    c = b.counts[k]
                    lines.append(
                        f"    {titles.get(k, k)}: {st} ({c['FAIL']} fail, {c['WARN']} warn "
                        f"of {b.count}) — {b.fix[k]}"
                    )
    if extras:
        lines += ["", "Other checks:"]
        for c in extras:
            shown = c.lines if c.status in ("WARN", "FAIL") else c.lines[:1]
            lines.append(f"- {c.title}: {c.status}")
            lines += [f"    {ln.split(' · ', 1)[-1]}" for ln in shown]
    lines += ["", *report.LIMITS]
    if out:
        lines.append(f"Report: {out / 'report.html'}")
    return "\n".join(lines)


def check_video(
    source: str | Path,
    out: str | Path | None = None,
    *,
    platforms: list[str] | None = None,
    disclaimer: bool = False,
    fps: float = 4.0,
    which: str | None = None,
    speech: bool = True,
    whisper_model: str = "small",
    language: str | None = None,
    names: list[str] | None = None,
) -> dict:
    """Run the full check. Returns verdicts, blocks and the plain-words summary."""
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    out = Path(out or Path.cwd() / f"video-checker-{source.stem}").expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    geo = zones.load()
    w, h, duration = probe(source)
    aspect = classify_aspect(w, h)
    extras: list[Check] = spec.check_file(source, w, h)
    zone_list = geo.zones_for(aspect, platforms, disclaimer)
    if not zone_list:
        text = f"{source.name} is {w}x{h} ({aspect}). This checker covers 9:16 and 4:5 videos only."
        (out / "summary.txt").write_text(text + "\n")
        return {"source": str(source), "aspect": aspect, "verdicts": {}, "summary": text}
    used = detect.backend(which)
    work = Path(tempfile.mkdtemp(prefix="video-checker-"))
    try:
        canvas = zone_list[0].canvas
        frames = detect.detect_video(source, work, fps, canvas, used)
        if not frames:
            raise detect.DetectionUnavailable("no frames could be sampled")
        elements = judge.group(frames, fps)
        verdicts = judge.judge(elements, zone_list, geo.inset)
        verdicts[judge.FACE_KEY] = judge.face_check(elements)
        blocks = judge.blocks(elements, zone_list, geo.inset)
        extras += [readability.hook_check(elements), readability.readability_check(elements)]
        extras += _speech_checks(source, elements, speech, whisper_model, language, names)
        verdicts.update({c.key: c.status for c in extras})
        frame_zone = geo.master if aspect == "9:16" else geo.feed_4x5
        annotated = {}
        for i, b in enumerate(blocks):
            worst = max(b.status.values(), key=judge.STATUS_ORDER.index)
            if worst not in ("FAIL", "WARN"):
                continue
            label = report.block_label(i, b)
            frame, boxes = b.worst.frame, [(b.worst.box, worst, label)]
            on_face = [
                m
                for m in b.elements
                if m.results.get(judge.FACE_KEY) and m.results[judge.FACE_KEY].status == "WARN"
            ]
            if on_face and b.status.get(judge.FACE_KEY) == "WARN":
                t, box, frame = next(
                    (t, bx, p) for t, bx, p in on_face[0].track if judge.faces_at(elements, t)
                )
                boxes = [(box, "WARN", f"{label} on face")]
                boxes += [(fb, "INFO", "face") for fb in judge.faces_at(elements, t)]
            annotated[label] = report.annotate(
                frame, frame_zone, boxes, out / "frames" / f"{label}.jpg"
            )
        meta = {
            "source": str(source),
            "aspect": aspect,
            "duration": duration,
            "canvas": list(canvas),
            "fps": fps,
            "frames": len(frames),
            "backend": used,
            "geometry_version": geo.version,
            "tool_version": __version__,
        }
        cols = [*zone_list, judge.FACE_ZONE]
        report.write_findings(out, meta, verdicts, elements, cols, blocks, extras)
        report.write_html(out, meta, verdicts, elements, cols, annotated, blocks, extras)
        text = summary_text(meta, verdicts, blocks, cols, out, extras)
        (out / "summary.txt").write_text(text + "\n")
        return {
            "source": str(source),
            "aspect": aspect,
            "backend": used,
            "verdicts": verdicts,
            "blocks": json.loads((out / "findings.json").read_text())["blocks"],
            "summary": text,
            "report": str(out / "report.html"),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
