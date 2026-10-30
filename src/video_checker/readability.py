"""Hook and readability: only judged when the thing is there.

- Hook: text on the very first frame. None is fine (INFO). If there is one, it should stay up long
  enough to read.
- Readability: must-read text big enough for a phone, with enough contrast against what's
  behind it (WCAG 2.2: 3:1 for large text).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .judge import Element
from .spec import Check, _worst

HOOK_START = 0.5  # text must be up by this time to count as the hook
HOOK_MIN_SECONDS = 2.0
MIN_HEIGHT = 45  # px box height on a 1080-wide frame, for must-read text
MIN_CONTRAST = 3.0  # WCAG 2.2 large-text minimum


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def _linear(v: float) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast(a: float, b: float) -> float:
    """WCAG contrast ratio between two grey levels (0-255)."""
    la, lb = sorted((_linear(a), _linear(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _percentile(hist: list[int], share: float) -> int:
    total, target, seen = sum(hist), sum(hist) * share, 0
    for level, n in enumerate(hist):
        seen += n
        if seen >= target and total:
            return level
    return 255


def box_contrast(grey: Image.Image, box) -> float:
    """Contrast between the dark and light ends of the pixels inside a text box: letters and their
    outline or background. 10th vs 90th percentile, so stray pixels don't count."""
    crop = grey.crop(
        (max(0, box.x0), max(0, box.y0), min(grey.width, box.x1), min(grey.height, box.y1))
    )
    hist = crop.histogram()
    return contrast(_percentile(hist, 0.9), _percentile(hist, 0.1))


def _settled_frames(e: Element) -> list[Path]:
    """Frames from the middle of a line's time on screen onward, so a fade-in doesn't count."""
    paths = [Path(p) for _t, _b, p in e.track] or [Path(e.frame)]
    picks = {paths[len(paths) // 2], paths[(3 * len(paths)) // 4], paths[-1]}
    return [p for p in picks if p.exists()]


def hook_check(elements: list[Element]) -> Check:
    texts = [e for e in elements if e.kind == "text"]
    first = min((e.start for e in texts), default=None)
    source = f"House rule: hook text on screen at least {HOOK_MIN_SECONDS:g} s"
    if first is None or first > HOOK_START:
        return Check("hook", "Hook", "INFO", ["INFO · no on-screen hook text at the start"], source)
    hook = [e for e in texts if e.start <= first + 1e-6]
    end = max(e.end for e in hook)
    words = " / ".join(e.text for e in sorted(hook, key=lambda e: e.box.y0))
    shown = end - first
    if shown < HOOK_MIN_SECONDS:
        line = (
            f"WARN · hook only on screen {shown:.1f} s ({_ts(first)}–{_ts(end)}): "
            f"keep it up at least {HOOK_MIN_SECONDS:g} s so people can read it · {words}"
        )
        return Check("hook", "Hook", "WARN", [line], source)
    line = f"PASS · hook on screen {shown:.1f} s ({_ts(first)}–{_ts(end)}) · {words}"
    return Check("hook", "Hook", "PASS", [line], source)


def readability_check(elements: list[Element], limit: int = 5) -> Check:
    texts = [e for e in elements if e.kind == "text" and e.tier == "must-read"]
    source = "WCAG 2.2 contrast 3:1 for large text; house rule must-read text at least 45 px tall"
    if not texts:
        return Check(
            "readability", "Readability", "INFO", ["INFO · no must-read text found"], source
        )
    greys: dict[Path, Image.Image] = {}
    small, faint = [], []
    for e in texts:
        if e.box.h < MIN_HEIGHT:
            small.append(e)
        ratios = []
        for path in _settled_frames(e):
            if path not in greys:
                greys[path] = Image.open(path).convert("L")
            ratios.append(box_contrast(greys[path], e.box))
        if ratios and max(ratios) < MIN_CONTRAST:
            faint.append((e, max(ratios)))
    lines = []
    if small:
        ex = "; ".join(f'{_ts(e.start)} "{e.text}" ({e.box.h} px)' for e in small[:limit])
        lines.append(
            f"WARN · {len(small)} lines are small on a phone (under {MIN_HEIGHT} px tall): {ex}"
        )
    if faint:
        ex = "; ".join(f'{_ts(e.start)} "{e.text}" ({r:.1f}:1)' for e, r in faint[:limit])
        lines.append(
            f"WARN · {len(faint)} lines have low contrast against what's behind them "
            f"(under {MIN_CONTRAST:g}:1; add an outline or a darker backing): {ex}"
        )
    if not lines:
        lines.append(f"PASS · {len(texts)} must-read lines: big enough, clear contrast")
    return Check(
        "readability", "Readability", _worst([ln.split(" ·")[0] for ln in lines]), lines, source
    )
