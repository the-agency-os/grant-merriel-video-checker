"""Captions vs what's said: spelling, numbers, missing or extra words, and caption timing.

The captions are the on-screen text that follows the speech (text bands whose words are mostly
spoken); hook cards, labels and end cards aren't compared. Every finding is a WARN with a time: the
text reader can misread a stylised word, so a person checks the frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .judge import Element, _rows
from .spec import Check

SAME_WORD = 0.75  # two words this similar are one word spelt differently
CAPTION_SHARE = 0.5  # a text band is a caption track when half its words are spoken
LATE, EARLY = 0.5, 1.0  # seconds
MISSING_RUN = 3  # this many non-filler spoken words with no caption get flagged
SAME_FORMS = {
    "GONNA": ["GOING", "TO"],
    "WANNA": ["WANT", "TO"],
    "GOTTA": ["GOT", "TO"],
    "ALRIGHT": ["ALL", "RIGHT"],
    "OK": ["OKAY"],
}
FILLERS = {
    "UM",
    "UH",
    "ER",
    "AH",
    "HMM",
    "MM",
    "LIKE",
    "SO",
    "AND",
    "YOU",
    "KNOW",
    "I",
    "MEAN",
    "YEAH",
    "OKAY",
    "RIGHT",
    "OH",
}


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Issue:
    kind: str  # spelling | number | words | extra | missing | late | early
    time: float
    shown: str
    said: str
    note: str = ""


def tokens(text: str) -> list[str]:
    s = text.upper().replace("’", "'").replace("&", " AND ").replace("%", " PERCENT ")
    s = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", s).replace("$", "")
    out: list[str] = []
    for raw in re.split(r"[\s\-/]+", s):
        w = re.sub(r"[^A-Z0-9]", "", raw)
        if w:
            out.extend(SAME_FORMS.get(w, [w]))
    return out


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


WINDOW = 1.5  # a caption's words must be said within this many seconds of it being on screen


def caption_elements(elements: list[Element], spk: list[tuple[str, Word]]) -> list[Element]:
    """Text bands that follow the speech, in reading order: half their words are said while they're
    on screen. Hook cards, labels and end cards aren't, even when their words come up later."""
    bands = _rows([e for e in elements if e.kind == "text"])
    picked: list[Element] = []
    for band in bands:
        hits = total = 0
        for e in band:
            near = {t for t, w in spk if e.start - WINDOW <= w.start <= e.end + WINDOW}
            for t in tokens(e.text):
                total += 1
                hits += t in near
        if total and hits / total >= CAPTION_SHARE:
            picked.extend(band)
    return sorted(picked, key=lambda e: (e.start, e.box.y0))


def compare(elements: list[Element], words: list[Word]) -> tuple[list[Issue], dict]:
    spk: list[tuple[str, Word]] = [(t, w) for w in words for t in tokens(w.text)]
    caps = caption_elements(elements, spk)
    cap: list[tuple[str, Element, bool]] = []
    shown_at: set[float] = set()
    for e in caps:
        timed = round(e.start, 2) not in shown_at  # only the first line of a multi-line caption
        shown_at.add(round(e.start, 2))
        for k, t in enumerate(tokens(e.text)):
            cap.append((t, e, k == 0 and timed))
    stats = {"spoken": len(spk), "captions": len(caps), "matched": 0.0}
    issues: list[Issue] = []
    if not spk or not cap:
        return issues, stats
    sm = SequenceMatcher(None, [t for t, _, _ in cap], [t for t, _ in spk], autojunk=False)
    matched = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        c, s = cap[i1:i2], spk[j1:j2]
        if tag == "equal":
            matched += i2 - i1
            for (_t, e, first), (_t2, w) in zip(c, s, strict=True):
                if not first:
                    continue
                lag = e.start - w.start
                if lag > LATE:
                    issues.append(
                        Issue(
                            "late",
                            e.start,
                            e.text,
                            w.text,
                            f"appears {lag:.1f} s after the word is said",
                        )
                    )
                elif lag < -EARLY:
                    issues.append(
                        Issue(
                            "early",
                            e.start,
                            e.text,
                            w.text,
                            f"appears {-lag:.1f} s before the word is said",
                        )
                    )
        elif tag == "replace":
            issues.extend(_replaced(c, s))
        elif tag == "delete":
            shown = " ".join(t for t, _, _ in c)
            issues.append(Issue("extra", c[0][1].start, shown, "", "on screen but not said"))
        elif tag == "insert":
            said = [t for t, _ in s]
            if len([t for t in said if t not in FILLERS]) >= MISSING_RUN:
                text = " ".join(dict.fromkeys(w.text.strip() for _, w in s))
                issues.append(Issue("missing", s[0][1].start, "", text, "said but not captioned"))
    stats["matched"] = round(matched / len(cap), 3)
    return sorted(issues, key=lambda i: i.time), stats


def _replaced(c, s) -> list[Issue]:
    shown, said = [t for t, _, _ in c], [t for t, _ in s]
    when = c[0][1].start
    if "".join(shown) == "".join(said):
        return []  # only the spacing differs
    if len(shown) == len(said):
        out = []
        for (ct, e, _f), (st, _w) in zip(c, s, strict=True):
            if any(ch.isdigit() for ch in ct + st):
                if re.sub(r"\D", "", ct) != re.sub(r"\D", "", st):
                    out.append(Issue("number", e.start, ct, st, "number differs from what's said"))
            elif SequenceMatcher(None, ct, st).ratio() >= SAME_WORD:
                out.append(
                    Issue(
                        "spelling",
                        e.start,
                        ct,
                        st,
                        "spelling? (check the frame: could be the text reader)",
                    )
                )
            else:
                out.append(Issue("words", e.start, ct, st, "different word from what's said"))
        return out
    a, b = "".join(shown), "".join(said)
    kind = "spelling" if SequenceMatcher(None, a, b).ratio() >= 0.7 else "words"
    return [
        Issue(
            kind,
            when,
            " ".join(shown),
            " ".join(said),
            "spelling? (check the frame: could be the text reader)"
            if kind == "spelling"
            else "different words from what's said",
        )
    ]


LABELS = {
    "spelling": "spelling?",
    "number": "number differs",
    "words": "different words",
    "extra": "on screen, not said",
    "missing": "said, not captioned",
}


def _lines(issues: list[Issue], limit: int) -> list[str]:
    out = []
    for i in issues[:limit]:
        if i.kind == "missing":
            out.append(f'WARN · {_ts(i.time)} {LABELS[i.kind]}: "{i.said}"')
        elif i.kind == "extra":
            out.append(f'WARN · {_ts(i.time)} {LABELS[i.kind]}: "{i.shown}"')
        elif i.kind in ("late", "early"):
            out.append(f'WARN · {_ts(i.time)} "{i.shown}" {i.note}')
        else:
            out.append(
                f'WARN · {_ts(i.time)} {LABELS[i.kind]}: shows "{i.shown}", said "{i.said.lower()}"'
            )
    if len(issues) > limit:
        out.append(f"WARN · … {len(issues) - limit} more in report.html")
    return out


def spelling_check(issues: list[Issue], stats: dict, limit: int = 15) -> Check:
    source = "Speech transcribed with faster-whisper and lined up against the captions"
    if not stats.get("spoken"):
        return Check("spelling", "Captions vs speech", "INFO", ["INFO · no speech found"], source)
    if not stats.get("captions"):
        return Check(
            "spelling",
            "Captions vs speech",
            "INFO",
            ["INFO · no captions found (no on-screen text follows the speech)"],
            source,
        )
    found = [i for i in issues if i.kind not in ("late", "early")]
    if not found:
        return Check(
            "spelling",
            "Captions vs speech",
            "PASS",
            [f"PASS · captions match what's said ({stats['matched']:.0%} of caption words)"],
            source,
        )
    return Check("spelling", "Captions vs speech", "WARN", _lines(found, limit), source)


def timing_check(issues: list[Issue], stats: dict, limit: int = 10) -> Check:
    source = (
        f"Caption should appear within {LATE:g} s after the word, no more than {EARLY:g} s before"
    )
    if not stats.get("captions") or not stats.get("spoken", 1):
        return Check("timing", "Caption timing", "INFO", ["INFO · nothing to time"], source)
    off = [i for i in issues if i.kind in ("late", "early")]
    if not off:
        return Check(
            "timing", "Caption timing", "PASS", ["PASS · captions keep up with the voice"], source
        )
    return Check("timing", "Caption timing", "WARN", _lines(off, limit), source)
