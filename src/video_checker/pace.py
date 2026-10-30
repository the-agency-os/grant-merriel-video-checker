"""Pace: how fast the ad talks, where it drags, and whether captions can be read in time.

Reported against published reference points, not fixed for anyone:
- Conversational English is about 150 words a minute (National Center for Voice and Speech); ad
  voice-overs run 150-160. Under 140 reads as slow for a social ad; over 210 is hard to follow.
- Captions: up to 17 characters a second (Netflix adult subtitle reading speed).
- Dead air and a slow start are measured from the word timings (house rule: gaps over 0.6 s, first
  word after 1 s). A slow stretch is any 10 s window under 120 words a minute.
"""

from __future__ import annotations

from .captions import Word
from .judge import Element
from .spec import Check, _worst

SLOW_WPM, FAST_WPM = 140, 210
STRETCH_WPM = 120  # a 10 s window this slow is unmistakable; word counts in 10 s are noisy
DEAD_AIR = 0.6  # seconds between words
SLOW_START = 1.0  # seconds before the first word
WINDOW = 10.0  # seconds, for finding slow stretches
MAX_CPS = 17  # caption characters a second
SOURCE = (
    "Conversation ~150 wpm (NCVS), ad voice-over 150-160; captions up to 17 characters a second "
    "(Netflix); dead air over 0.6 s and first word after 1 s are house rules"
)


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def _slow_stretches(words: list[Word]) -> list[tuple[float, float, float]]:
    first, last = words[0].start, words[-1].end
    starts = [w.start for w in words]
    stretches: list[list[float]] = []
    t = first
    while t + WINDOW <= last + 1e-6:
        wpm = sum(t <= s < t + WINDOW for s in starts) * 60 / WINDOW
        if wpm < STRETCH_WPM:
            if stretches and t < stretches[-1][1]:  # overlapping slow windows are one stretch
                stretches[-1][1] = t + WINDOW
                stretches[-1][2] = min(stretches[-1][2], wpm)
            else:
                stretches.append([t, t + WINDOW, wpm])
        t += 1.0
    return [(a, b, w) for a, b, w in stretches]


def pace_check(words: list[Word], captions: list[Element], limit: int = 8) -> Check:
    if not words:
        return Check("pace", "Pace", "INFO", ["INFO · no speech to measure"], SOURCE)
    words = sorted(words, key=lambda w: w.start)
    span = max(words[-1].end - words[0].start, 0.1)
    wpm = len(words) * 60 / span
    gaps = [
        (a.end, b.start - a.end)
        for a, b in zip(words, words[1:], strict=False)
        if b.start - a.end >= DEAD_AIR
    ]
    talking = span - sum(g for _t, g in gaps)
    lines = []
    summary = f"{wpm:.0f} words a minute ({len(words)} words in {span:.1f} s)"
    if wpm < SLOW_WPM:
        lines.append(f"WARN · {summary}: slow for a social ad (conversation is about 150)")
    elif wpm > FAST_WPM:
        lines.append(f"WARN · {summary}: very fast, hard to follow")
    else:
        lines.append(f"PASS · {summary}")
    if gaps:
        lines.append(
            f"INFO · {len(words) * 60 / max(talking, 0.1):.0f} words a minute while talking"
        )
    if words[0].start > SLOW_START:
        lines.append(
            f"WARN · first word at {_ts(words[0].start)}: the opening is silent; "
            "start talking sooner"
        )
    if gaps:
        shown = "; ".join(f"{_ts(t)} ({g:.1f} s)" for t, g in gaps[:limit])
        more = f" … and {len(gaps) - limit} more" if len(gaps) > limit else ""
        lines.append(f"WARN · {len(gaps)} pauses over {DEAD_AIR:g} s: {shown}{more}")
    for a, b, w in _slow_stretches(words)[:3]:
        lines.append(f"WARN · slow stretch {_ts(a)}–{_ts(b)}: about {w:.0f} words a minute")
    fast = []
    for e in captions:
        shown_for = max(e.end - e.start, 0.01)
        cps = len(e.text.strip()) / shown_for
        if cps > MAX_CPS:
            fast.append((e, cps))
    if fast:
        ex = "; ".join(f'{_ts(e.start)} "{e.text}" ({c:.0f} chars a second)' for e, c in fast[:5])
        lines.append(
            f"INFO · {len(fast)} of {len(captions)} captions are faster than the {MAX_CPS} "
            f"characters a second subtitle standard (normal for word-by-word captions that follow "
            f"the voice; viewers can't re-read them): {ex}"
        )
    judged = [ln.split(" ·")[0] for ln in lines if not ln.startswith("INFO")]
    return Check("pace", "Pace", _worst(judged), lines, SOURCE)
