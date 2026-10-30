"""Group frame detections into on-screen elements and judge them against safe zones."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .detect import FrameDetections
from .zones import Rect, Zone

STATUS_ORDER = ["PASS", "INFO", "WARN", "FAIL"]
FACE_KEY = "face"
FACE_ZONE = Zone(
    FACE_KEY,
    "Text on the face",
    (1080, 1920),
    (),
    severity="warn",
    source="Apple Vision face and text boxes, compared frame by frame",
    note="WARN when a line of text covers a face in the same frame.",
)
FACE_MIN_OVERLAP = 0.15  # share of the smaller box (text or face) that must overlap
FACE_MIN_FRAMES = 2  # at 4 fps, half a second
FACE_CORE = (0.10, 0.12)  # trim from the top and bottom of Vision's face box: eyes to mouth


def face_core(box: Rect) -> Rect:
    """Vision's face box runs from the hairline to below the chin; text there doesn't hide the
    face. Keep the eyes-to-mouth core."""
    top, bottom = FACE_CORE
    return Rect(box.x0, box.y0 + round(box.h * top), box.x1, box.y1 - round(box.h * bottom))


FACE_TOLERANCE = 0.10


@dataclass
class Result:
    status: str
    overflow: dict[str, int]
    fix: str = ""


@dataclass
class Element:
    id: str
    kind: str
    text: str
    start: float
    end: float
    box: Rect
    confidence: float
    frame: Path
    results: dict[str, Result] = field(default_factory=dict)
    tier: str = "must-read"  # "must-read" | "detail" | "face"
    track: list[tuple[float, Rect, Path]] = field(default_factory=list)  # every sighting
    readings: dict[str, int] = field(default_factory=dict)  # OCR reading -> frames read that way


OCR_SAME = 0.85  # two readings this similar, in the same place, are the same caption misread


def _same_text(e: Element, d, key: str) -> bool:
    """Same caption: identical text, or a near-identical reading (the text reader misread a letter)
    of a caption sitting in the same place."""
    mine = _norm(e.text)
    if mine == key:
        return True
    return _iou(e.box, d.box) > 0.6 and SequenceMatcher(None, mine, key).ratio() >= OCR_SAME


def _norm(s: str) -> str:
    """Comparison key for OCR strings; falls back to the raw text for symbol-only lines (€€€)."""
    return re.sub(r"[^a-z0-9]", "", s.lower()) or s.strip()


def _iou(a: Rect, b: Rect) -> float:
    i = a.intersect(b)
    if not i:
        return 0.0
    return i.area / (a.area + b.area - i.area)


def _union(a: Rect, b: Rect) -> Rect:
    return Rect(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _median(values: list[int]) -> int:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else round((v[n // 2 - 1] + v[n // 2]) / 2)


def _settle(e: Element) -> None:
    """Captions are static overlays, but OCR boxes jitter by 10-20 px between frames. Use the
    median of every sighting, edge by edge, so one noisy frame can't fake a breach; the frame
    shown in the report is the sighting closest to that median."""
    boxes = [b for _t, b, _p in e.track]
    e.box = Rect(*(_median([getattr(b, k) for b in boxes]) for k in ("x0", "y0", "x1", "y1")))
    _t, _b, e.frame = min(
        e.track,
        key=lambda s: (
            abs(s[1].x0 - e.box.x0)
            + abs(s[1].y0 - e.box.y0)
            + abs(s[1].x1 - e.box.x1)
            + abs(s[1].y1 - e.box.y1)
        ),
    )


def group(
    frames: list[FrameDetections], fps: float, min_conf=0.0, min_height=18, must_read=36
) -> list[Element]:
    step = 1 / fps
    open_: list[Element] = []
    done: list[Element] = []
    counter = {"text": 0, "face": 0}
    for f in frames:
        seen: set[int] = set()
        for d in f.detections:
            if d.kind == "text" and (d.confidence < min_conf or d.box.h < min_height):
                continue
            key = _norm(d.text)
            if d.kind == "text" and not key:
                continue
            match = next(
                (
                    e
                    for e in open_
                    if id(e) not in seen
                    and e.kind == d.kind
                    and (d.kind == "face" or _same_text(e, d, key))
                    and _iou(e.box, d.box) > 0.3
                    and f.t - e.end <= step * 1.5
                ),
                None,
            )
            if match:
                match.end = f.t + step
                grown = _union(match.box, d.box)
                if grown.area > match.box.area:
                    match.frame = f.path
                match.box = grown
                match.track.append((f.t, d.box, f.path))
                if d.kind == "text":
                    match.readings[d.text] = match.readings.get(d.text, 0) + 1
                    match.text = max(match.readings, key=match.readings.get)
                seen.add(id(match))
            else:
                counter[d.kind] += 1
                e = Element(
                    f"{d.kind[0]}{counter[d.kind]}",
                    d.kind,
                    d.text,
                    f.t,
                    f.t + step,
                    d.box,
                    d.confidence,
                    f.path,
                    tier="face"
                    if d.kind == "face"
                    else ("detail" if d.box.h < must_read else "must-read"),
                )
                e.track.append((f.t, d.box, f.path))
                if d.kind == "text":
                    e.readings[d.text] = 1
                open_.append(e)
                seen.add(id(e))
        still = []
        for e in open_:
            (still if f.t - e.end <= step * 1.5 else done).append(e)
        open_ = still
    elements = done + open_
    for e in elements:
        if e.kind == "text" and len(e.track) >= 3:
            _settle(e)
    return sorted(elements, key=lambda e: (e.start, e.id))


def _band(target: Zone, y0: int, y1: int) -> tuple[int, int]:
    """The x range the target allows across rows y0..y1 (half-open)."""
    rows = [r for r in target.rects if r.y0 < y1 and r.y1 > y0] or list(target.rects)
    return max(r.x0 for r in rows), min(r.x1 for r in rows)


def _too_wide(target: Zone, y0: int, y1: int) -> str:
    x0, x1 = _band(target, y0, y1)
    return f"too wide: keep each line under {x1 - x0} px (x {x0}–{x1 - 1})"


def _fix(zone: Zone, box: Rect, o: dict[str, int], target: Zone) -> str:
    t = target.overflow(box)
    parts = []
    if o["bottom"]:
        parts.append(
            f"bottom edge y {box.y1 - 1}, limit {max(r.y1 for r in target.rects) - 1}: "
            f"lift {t['bottom']} px"
        )
    if o["top"]:
        parts.append(
            f"top edge y {box.y0}, limit {min(r.y0 for r in target.rects)}: lower {t['top']} px"
        )
    if o["right"] and o["left"]:
        parts.append(_too_wide(target, box.y0, box.y1))
    elif o["right"]:
        parts.append(
            f"right edge x {box.x1 - 1}: pull in {t['right']} px from the right "
            f"(shorten or break the line)"
        )
    elif o["left"]:
        parts.append(f"left edge x {box.x0}: move {t['left']} px right")
    return "; ".join(parts)


def judge(elements: list[Element], zone_list: list[Zone], inset: int) -> dict[str, str]:
    """Hard edges FAIL, icon rails and the inset buffer WARN; small text never FAILs."""
    verdicts = {z.key: "PASS" for z in zone_list}
    for row in _rows([e for e in elements if e.kind == "text"]):
        if any(m.tier == "must-read" for m in row):
            for m in row:
                m.tier = "must-read"
    for e in elements:
        for z in zone_list:
            o = z.overflow(e.box)
            info = z.severity == "info"
            if e.kind == "face":
                outside = 1 - z.covered(e.box) / e.box.area if e.box.area else 0.0
                bad = outside > FACE_TOLERANCE
                status = ("INFO" if info else "WARN") if bad else "PASS"
                fix = "check the face framing in this placement" if bad else ""
            elif not z.contains(e.box):
                status = "INFO" if info else "FAIL"
                fix = _fix(z, e.box, o, z if info else z.inset(inset))
            else:
                parts = []
                rail = 0 if info else z.rail_overlap(e.box)
                inner = z.inset(inset)
                if not info and not inner.contains(e.box):
                    o = inner.overflow(e.box)
                    parts.append(f"within {inset} px of the edge: " + _fix(z, e.box, o, inner))
                if rail:
                    parts.append(f"runs {rail} px under the icon rail (cosmetic, check it reads)")
                status = "WARN" if parts else "PASS"
                fix = "; ".join(parts)
            if e.tier == "detail" and status == "FAIL":
                status, fix = "WARN", f"small text: {fix}"
            e.results[z.key] = Result(status, o, fix)
            if STATUS_ORDER.index(status) > STATUS_ORDER.index(verdicts[z.key]):
                verdicts[z.key] = status
    return verdicts


BLOCK_GAP = 40


@dataclass
class Block:
    """Text lines that share a screen position (a caption band, a hook card) judged together."""

    kind: str
    y0: int
    y1: int
    elements: list[Element]
    status: dict[str, str]
    counts: dict[str, dict[str, int]]
    fix: dict[str, str]
    worst: Element

    @property
    def count(self) -> int:
        return len(self.elements)


def _block_fix(zone: Zone, members: list[Element], inset: int) -> str:
    target = zone.inset(inset) if zone.severity != "info" else zone
    over = [target.overflow(e.box) for e in members if e.results[zone.key].status != "PASS"]
    if not over:
        return ""
    worst = {k: max(o[k] for o in over) for k in ("top", "bottom", "left", "right")}
    parts = []
    if worst["bottom"]:
        parts.append(f"lift the block {worst['bottom']} px")
    if worst["top"]:
        parts.append(f"lower the block {worst['top']} px")
    if worst["right"] and worst["left"]:
        y0, y1 = min(e.box.y0 for e in members), max(e.box.y1 for e in members)
        parts.append(_too_wide(target, y0, y1))
    elif worst["right"]:
        parts.append(f"keep lines {worst['right']} px narrower on the right")
    elif worst["left"]:
        parts.append(f"move lines {worst['left']} px right")
    rail = max((zone.rail_overlap(e.box) for e in members), default=0)
    if rail and zone.severity != "info":
        parts.append(f"up to {rail} px under the icon rail (cosmetic)")
    return "; ".join(parts)


def _same_row(a: Element, b: Element) -> bool:
    """Same screen position: vertically overlapping by half the shorter line, or stacked within
    BLOCK_GAP px while on screen together. Lines never chain across time through gaps."""
    overlap = min(a.box.y1, b.box.y1) - max(a.box.y0, b.box.y0)
    if overlap >= 0.5 * min(a.box.h, b.box.h):
        return True
    gap = max(a.box.y0, b.box.y0) - min(a.box.y1, b.box.y1)
    together = a.start < b.end and b.start < a.end
    return gap <= BLOCK_GAP and together


def _rows(texts: list[Element]) -> list[list[Element]]:
    """Group lines that share a screen position. Connected groups, so the order lines are seen in
    never splits one caption band (two-line and one-line captions overlap different neighbours)."""
    parent = list(range(len(texts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _same_row(texts[i], texts[j]):
                parent[root(i)] = root(j)
    groups: dict[int, list[Element]] = {}
    for i, e in enumerate(texts):
        groups.setdefault(root(i), []).append(e)
    return sorted(groups.values(), key=lambda g: min(m.box.y0 for m in g))


def blocks(elements: list[Element], zone_list: list[Zone], inset: int) -> list[Block]:
    """Merge judged text elements whose vertical ranges overlap or sit within BLOCK_GAP px."""
    out = []
    for members in _rows([e for e in elements if e.kind == "text"]):
        status, counts, fixes = {}, {}, {}
        for z in zone_list:
            c = {s: 0 for s in STATUS_ORDER}
            for m in members:
                c[m.results[z.key].status] += 1
            counts[z.key] = c
            status[z.key] = max((s for s in STATUS_ORDER if c[s]), key=STATUS_ORDER.index)
            fixes[z.key] = _block_fix(z, members, inset)

        if any(FACE_KEY in m.results for m in members):
            c = {st: 0 for st in STATUS_ORDER}
            for m in members:
                c[m.results.get(FACE_KEY, Result("PASS", {})).status] += 1
            counts[FACE_KEY] = c
            status[FACE_KEY] = "WARN" if c["WARN"] else "PASS"
            fixes[FACE_KEY] = (
                f"{c['WARN']} of {len(members)} lines cover the face: move them above or below it"
                if c["WARN"]
                else ""
            )

        def badness(m: Element) -> tuple[int, int]:
            fails = [r for r in m.results.values() if r.status in ("FAIL", "WARN")]
            return (len(fails), sum(sum(r.overflow.values()) for r in fails))

        out.append(
            Block(
                "text",
                min(m.box.y0 for m in members),
                max(m.box.y1 for m in members),
                sorted(members, key=lambda m: m.start),
                status,
                counts,
                fixes,
                max(members, key=badness),
            )
        )
    return out


def _clock(seconds: float) -> str:
    m, sec = divmod(seconds, 60)
    return f"{int(m)}:{sec:04.1f}"


def faces_at(elements: list[Element], t: float) -> list[Rect]:
    return [
        box for e in elements if e.kind == "face" for ft, box, _p in e.track if abs(ft - t) < 1e-6
    ]


def face_check(elements: list[Element]) -> str:
    """WARN for each text line that sits on a face in the same frames. Compares sightings frame by
    frame, so a face that moves around is never judged by the union of all its positions."""
    verdict = "PASS"
    by_time: dict[float, list[Rect]] = {}
    for e in elements:
        if e.kind == "face":
            for t, box, _p in e.track:
                by_time.setdefault(round(t, 3), []).append(face_core(box))
    for e in elements:
        if e.kind != "text":
            e.results[FACE_KEY] = Result("PASS", {}, "")
            continue
        hits = []
        for t, box, _p in e.track:
            for fb in by_time.get(round(t, 3), []):
                i = box.intersect(fb)
                if i and i.area >= FACE_MIN_OVERLAP * min(box.area, fb.area):
                    hits.append((t, fb))
                    break
        if e.track and len(hits) >= min(FACE_MIN_FRAMES, len(e.track)):
            fb = hits[0][1]
            fix = (
                f"covers the face at {_clock(hits[0][0])}–{_clock(hits[-1][0])} "
                f"(face y {fb.y0}–{fb.y1 - 1}): move the line above or below the face"
            )
            e.results[FACE_KEY] = Result("WARN", {}, fix)
            verdict = "WARN"
        else:
            e.results[FACE_KEY] = Result("PASS", {}, "")
    return verdict
