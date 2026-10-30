"""Safe-zone check outputs: findings.json, annotated frames and a self-contained report.html."""

from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .judge import STATUS_ORDER, Block, Element
from .zones import Rect, Zone

LIMITS = [
    "Logos, products and graphics without text are not detected; check them by eye.",
    "A person signs APPROVE / APPROVE WITH FIXES / REJECT and previews the configured ad in "
    "Meta Ads Manager or Google Ads before launch.",
]

COLOURS = {"FAIL": "#E5484D", "WARN": "#F5A524", "INFO": "#8E8E93", "PASS": "#2BD47D"}


CSS = """
body{font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:0;
background:#f6f7f9;color:#1d232a}
header{background:#143347;color:#fff;padding:20px 24px}
header h1{margin:0 0 4px;font-size:22px}
main{padding:16px 24px;max-width:1200px}
table{border-collapse:collapse;background:#fff;width:100%;margin:8px 0 24px}
th,td{border:1px solid #e1e4e8;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#eef1f4}
.pill{color:#fff;border-radius:10px;padding:1px 9px;font-weight:600;font-size:12px}
.src{color:#5b6670;font-size:12px}
.fix{font-size:13px}
figure{display:inline-block;margin:0 12px 12px 0}
figcaption{font-size:12px;color:#5b6670}
.block{display:flex;gap:16px;background:#fff;border:1px solid #e1e4e8;padding:12px;margin:0 0 16px}
.block h3{margin:0 0 4px;font-size:16px}
.wrap{overflow-x:auto}
"""


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def annotate(frame: Path, zone: Zone, boxes: list[tuple[Rect, str, str]], out: Path) -> Path:
    """Shade outside the zone, draw its edge, then each box coloured by status with a label."""
    base = Image.open(frame).convert("RGBA").resize(zone.canvas)
    mask = Image.new("L", zone.canvas, 110)
    md = ImageDraw.Draw(mask)
    for r in zone.rects:
        md.rectangle((r.x0, r.y0, r.x1 - 1, r.y1 - 1), fill=0)
    red = Image.new("RGBA", zone.canvas, (220, 36, 52, 0))
    red.putalpha(mask)
    base = Image.alpha_composite(base, red)
    d = ImageDraw.Draw(base)
    d.line([*zone.polygon(), zone.polygon()[0]], fill=COLOURS["PASS"], width=4)
    font = _font(34)
    for box, status, label in boxes:
        colour = COLOURS.get(status, "#FFFFFF")
        d.rectangle((box.x0, box.y0, box.x1 - 1, box.y1 - 1), outline=colour, width=6)
        text = f"{status} {label}"
        tb = d.textbbox((0, 0), text, font=font)
        ty = box.y0 - (tb[3] - tb[1]) - 18 if box.y0 > 60 else box.y1 + 6
        d.rectangle((box.x0, ty, box.x0 + tb[2] - tb[0] + 16, ty + tb[3] - tb[1] + 12), fill=colour)
        d.text((box.x0 + 8, ty + 2), text, font=font, fill="white")
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, "JPEG", quality=85)
    return out


def _element_dict(e: Element) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "text": e.text,
        "start": round(e.start, 2),
        "end": round(e.end, 2),
        "box": [e.box.x0, e.box.y0, e.box.x1, e.box.y1],
        "confidence": round(e.confidence, 3),
        "results": {
            k: {"status": r.status, "overflow": r.overflow, "fix": r.fix}
            for k, r in e.results.items()
        },
    }


def block_label(i: int, b: Block) -> str:
    return f"b{i + 1}"


def _block_dict(i: int, b: Block) -> dict:
    return {
        "id": block_label(i, b),
        "y": [b.y0, b.y1],
        "count": b.count,
        "start": round(b.elements[0].start, 2),
        "end": round(max(e.end for e in b.elements), 2),
        "examples": [e.text for e in b.elements[:3]],
        "status": b.status,
        "counts": b.counts,
        "fix": b.fix,
        "worst": b.worst.id,
    }


def write_findings(
    out_dir, meta: dict, verdicts: dict, elements: list[Element], zones, blocks=None, checks=None
) -> Path:
    data = {
        **meta,
        "verdicts": verdicts,
        "blocks": [_block_dict(i, b) for i, b in enumerate(blocks or [])],
        "zones": [
            {"key": z.key, "title": z.title, "source": z.source, "note": z.note} for z in zones
        ],
        "elements": [_element_dict(e) for e in elements],
        "checks": [
            {
                "key": c.key,
                "title": c.title,
                "status": c.status,
                "lines": c.lines,
                "source": c.source,
            }
            for c in checks or []
        ],
        "limits": LIMITS,
    }
    p = Path(out_dir) / "findings.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return p


def _img64(path: Path, width: int = 360) -> str:
    im = Image.open(path).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _pill(status: str) -> str:
    return f'<span class="pill" style="background:{COLOURS.get(status, "#999")}">{status}</span>'


def _worst(e: Element) -> str:
    return max((r.status for r in e.results.values()), key=STATUS_ORDER.index, default="PASS")


def write_html(
    out_dir, meta, verdicts, elements: list[Element], zones, annotated, blocks=None, checks=None
) -> Path:
    esc = html.escape
    rows = "".join(
        f"<tr><td>{esc(z.title)}</td><td>{_pill(verdicts.get(z.key, 'PASS'))}</td>"
        f"<td class='src'>{esc(z.source)}</td></tr>"
        for z in zones
    ) + "".join(
        f"<tr><td>{esc(c.title)}</td><td>{_pill(c.status)}</td>"
        f"<td class='src'>{esc(c.source)}</td></tr>"
        for c in checks or []
    )
    other = "".join(
        f"<h3>{esc(c.title)} {_pill(c.status)}</h3><ul>"
        + "".join(f"<li>{esc(line)}</li>" for line in c.lines)
        + "</ul>"
        for c in checks or []
    )
    breaches = [e for e in elements if _worst(e) in ("FAIL", "WARN")]
    brows = ""
    for e in breaches:
        cells = "".join(f"<td>{_pill(e.results[z.key].status)}</td>" for z in zones)
        fixes = "<br>".join(
            f"<b>{esc(z.title)}:</b> {esc(e.results[z.key].fix)}"
            for z in zones
            if e.results[z.key].status in ("FAIL", "WARN") and e.results[z.key].fix
        )
        label = esc(e.text) if e.kind == "text" else "<i>face</i>"
        brows += (
            f"<tr><td>{_ts(e.start)}–{_ts(e.end)}</td><td>{label}</td>{cells}"
            f"<td class='fix'>{fixes}</td></tr>"
        )
    heads = "".join(f"<th>{esc(z.title)}</th>" for z in zones)
    todo = ""
    for i, b in enumerate(blocks or []):
        bad = [z for z in zones if b.status[z.key] in ("FAIL", "WARN")]
        if not bad:
            continue
        lines = "".join(
            f"<tr><td>{esc(z.title)}</td><td>{_pill(b.status[z.key])} "
            f"{b.counts[z.key]['FAIL']} fail · {b.counts[z.key]['WARN']} warn of {b.count}</td>"
            f"<td>{esc(b.fix[z.key])}</td></tr>"
            for z in bad
        )
        examples = esc(" / ".join(e.text for e in b.elements[:3]))
        img = annotated.get(block_label(i, b))
        pic = f'<img src="data:image/jpeg;base64,{_img64(img)}" width=300>' if img else ""
        todo += (
            f"<section class=block><div>{pic}</div><div><h3>{block_label(i, b)} · text at "
            f"y {b.y0}–{b.y1 - 1} · {b.count} lines · {_ts(b.elements[0].start)}–"
            f"{_ts(max(e.end for e in b.elements))}</h3><p class=src>{examples}</p>"
            f"<table><tr><th>Placement</th><th>Result</th><th>Fix</th></tr>{lines}</table>"
            f"</div></section>"
        )
    figs = "".join(
        f'<figure><img src="data:image/jpeg;base64,{_img64(p)}" width=360>'
        f"<figcaption>{esc(k)} · {_ts(next((e.start for e in elements if e.id == k), 0))}"
        f"</figcaption></figure>"
        for k, p in annotated.items()
        if k not in {block_label(i, b) for i, b in enumerate(blocks or [])}
    )
    text_count = sum(1 for e in elements if e.kind == "text")
    summary = (
        "No text detected."
        if text_count == 0
        else f"{text_count} text elements checked; {len(breaches)} need attention."
    )
    limits = "".join(f"<li>{esc(s)}</li>" for s in LIMITS)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safe-zone check — {esc(str(meta.get("source", "")))}</title>
<style>
{CSS}
</style></head><body>
<header><h1>Safe-zone check</h1>{esc(str(meta.get("source", "")))}
· {esc(str(meta.get("aspect", "")))}
· geometry {esc(str(meta.get("geometry_version", "")))}</header><main>
<p><b>{esc(summary)}</b></p>
<h2>Verdicts</h2><table><tr><th>Placement</th><th>Verdict</th><th>Source</th></tr>{rows}</table>
<h2>What to fix</h2>{todo or "<p>Nothing to fix.</p>"}
<h2>Other checks</h2>{other or "<p>None run.</p>"}
<h2>Frames</h2>{figs or "<p>No other breach frames.</p>"}
<details><summary><b>Every line that needs attention ({len(breaches)})</b></summary>
<div class="wrap"><table><tr><th>Time</th><th>Element</th>{heads}<th>Fix</th></tr>
{brows or "<tr><td colspan=99>None.</td></tr>"}</table></div></details>
<h2>Limits</h2><ul>{limits}</ul>
<p><b>A person signs APPROVE / APPROVE WITH FIXES / REJECT</b> in audit-summary.md; this report
never does.</p></main></body></html>"""
    p = Path(out_dir) / "report.html"
    p.write_text(page)
    return p
