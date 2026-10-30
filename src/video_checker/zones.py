"""Safe-zone geometry: one JSON file, zones as non-overlapping rectangle bands."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT = Path(__file__).parent / "assets" / "safe-zones.json"


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return max(0, self.x1 - self.x0)

    @property
    def h(self) -> int:
        return max(0, self.y1 - self.y0)

    @property
    def area(self) -> int:
        return self.w * self.h

    def inset(self, n: int) -> Rect:
        return Rect(self.x0 + n, self.y0 + n, self.x1 - n, self.y1 - n)

    def intersect(self, o: Rect) -> Rect | None:
        r = Rect(max(self.x0, o.x0), max(self.y0, o.y0), min(self.x1, o.x1), min(self.y1, o.y1))
        return r if r.w and r.h else None


@dataclass(frozen=True)
class Zone:
    key: str
    title: str
    canvas: tuple[int, int]
    rects: tuple[Rect, ...]
    severity: str = "fail"
    source: str = ""
    note: str = ""
    soft: tuple[Rect, ...] = ()

    def rail_overlap(self, box: Rect) -> int:
        """Widest intrusion of the box into a soft zone (an icon rail), in pixels."""
        return max((i.w for r in self.soft if (i := r.intersect(box))), default=0)

    def covered(self, box: Rect) -> int:
        return sum(i.area for r in self.rects if (i := r.intersect(box)))

    def contains(self, box: Rect) -> bool:
        return box.area > 0 and self.covered(box) == box.area

    def overflow(self, box: Rect) -> dict[str, int]:
        rows = [r for r in self.rects if r.y0 < box.y1 and r.y1 > box.y0] or list(self.rects)
        return {
            "top": max(0, min(r.y0 for r in self.rects) - box.y0),
            "bottom": max(0, box.y1 - max(r.y1 for r in self.rects)),
            "left": max(0, max(r.x0 for r in rows) - box.x0),
            "right": max(0, box.x1 - min(r.x1 for r in rows)),
        }

    def inset(self, n: int) -> Zone:
        top, bottom = min(r.y0 for r in self.rects), max(r.y1 for r in self.rects)
        bands = []
        for r in self.rects:
            y0 = r.y0 + n if r.y0 == top else r.y0
            y1 = r.y1 - n if r.y1 == bottom else r.y1
            bands.append(Rect(r.x0 + n, y0, r.x1 - n, y1))
        return replace(self, key=f"{self.key}-inset", rects=tuple(bands))

    def polygon(self) -> list[tuple[int, int]]:
        rs = sorted(self.rects, key=lambda r: r.y0)
        pts: list[tuple[int, int]] = []
        for r in rs:
            pts += [(r.x1, r.y0), (r.x1, r.y1)]
        for r in reversed(rs):
            pts += [(r.x0, r.y1), (r.x0, r.y0)]
        return pts


def _zone(key: str, d: dict, canvas) -> Zone:
    return Zone(
        key,
        d["title"],
        tuple(d.get("canvas", canvas)),
        tuple(Rect(*r) for r in d["rects"]),
        d.get("severity", "fail"),
        d.get("source", ""),
        d.get("note", ""),
        tuple(Rect(*r) for r in d.get("soft", [])),
    )


@dataclass(frozen=True)
class Geometry:
    version: str
    canvas: tuple[int, int]
    inset: int
    placements: dict[str, Zone]
    crops: dict[str, Zone]
    master: Zone
    feed_4x5: Zone
    members: tuple[str, ...] = field(default=())
    must_read_height: int = 36

    @property
    def caption_box(self) -> Zone:
        return self.master.inset(self.inset)

    def zones_for(self, aspect: str, platforms: list[str] | None, disclaimer: bool) -> list[Zone]:
        if aspect == "4:5":
            return [self.feed_4x5]
        if aspect != "9:16":
            return []
        keys = platforms or ["meta", "youtube-shorts"]
        master = self.master
        if disclaimer:
            keys = ["meta-disclaimer" if k == "meta" else k for k in keys]
            floor = max(r.y1 for r in self.placements["meta-disclaimer"].rects)
            clip = Rect(0, 0, self.canvas[0], floor)
            master = replace(
                master, rects=tuple(c for r in master.rects if (c := r.intersect(clip)))
            )
        return [master, *(self.placements[k] for k in keys), *self.crops.values()]


def load(path: str | Path | None = None) -> Geometry:
    d = json.loads(Path(path or DEFAULT).read_text())
    canvas = tuple(d["canvas"])
    placements = {k: _zone(k, v, canvas) for k, v in d["placements"].items()}
    rails = []
    for k in d["master"]["members"]:
        for r in placements[k].soft if k in placements else ():
            if r not in rails:
                rails.append(r)
    master = replace(_zone("master", d["master"], canvas), soft=tuple(rails))
    return Geometry(
        d["version"],
        canvas,
        d["inset"],
        placements,
        {k: _zone(k, v, canvas) for k, v in d["crops"].items()},
        master,
        _zone("feed-4x5", d["feed-4x5"], canvas),
        tuple(d["master"]["members"]),
        d.get("tiers", {}).get("must_read_height", 36),
    )


def derive_master(g: Geometry) -> tuple[Rect, ...]:
    """Intersect the member zones band by band; merge adjacent bands with equal x-spans."""
    zones = [g.placements.get(k) or g.crops[k] for k in g.members]
    ys = sorted({y for z in zones for r in z.rects for y in (r.y0, r.y1)})
    bands: list[Rect] = []
    for y0, y1 in zip(ys, ys[1:], strict=False):
        x0, x1 = 0, g.canvas[0]
        for z in zones:
            row = [r for r in z.rects if r.y0 <= y0 and r.y1 >= y1]
            if not row:
                x1 = x0
                break
            x0, x1 = max(x0, row[0].x0), min(x1, row[0].x1)
        if x1 > x0:
            if bands and bands[-1].x0 == x0 and bands[-1].x1 == x1 and bands[-1].y1 == y0:
                bands[-1] = Rect(x0, bands[-1].y0, x1, y1)
            else:
                bands.append(Rect(x0, y0, x1, y1))
    return tuple(bands)
