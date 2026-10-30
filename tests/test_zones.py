from video_checker import zones
from video_checker.zones import Rect

G = zones.load()


def test_master_is_the_intersection_of_its_members():
    assert zones.derive_master(G) == G.master.rects


def test_master_published_numbers():
    assert G.master.rects == (Rect(65, 288, 1015, 1248),)
    assert G.caption_box.rects == (Rect(89, 312, 991, 1224),)


def test_contains_is_exact_on_half_open_edges():
    yt = G.placements["youtube-shorts"]
    assert yt.contains(Rect(48, 288, 1032, 1248))
    assert not yt.contains(Rect(48, 288, 1033, 1248))
    assert not yt.contains(Rect(47, 300, 100, 320))


def test_icon_rails_are_soft_not_hard():
    meta = G.placements["meta"]
    box = Rect(900, 1140, 1000, 1170)
    assert meta.contains(box)
    assert meta.rail_overlap(box) == 100
    assert meta.rail_overlap(Rect(900, 1000, 1000, 1100)) == 0  # above Meta's rail
    yt = G.placements["youtube-shorts"]
    assert yt.rail_overlap(Rect(800, 400, 950, 450)) == 0  # no YouTube icons above y 1343
    assert yt.rail_overlap(Rect(800, 1400, 950, 1450)) == 80
    assert set(G.master.soft) >= set(G.placements["meta"].soft)


def test_overflow_reports_pixels_outside_per_side():
    meta = G.placements["meta"]
    o = meta.overflow(Rect(100, 1325, 1057, 1638))
    assert o["bottom"] == 1638 - 1248
    assert o["right"] == 1057 - 1015
    assert o["top"] == 0 and o["left"] == 0


def test_investorkit_frame_fails_every_platform():
    box = Rect(267, 1325, 1057, 1638)
    for key in ("meta", "youtube-shorts"):
        assert not G.placements[key].contains(box)


def test_zones_for_selects_by_aspect_and_flags():
    keys = [z.key for z in G.zones_for("9:16", None, False)]
    assert keys == ["master", "meta", "youtube-shorts", "crop-4x5", "crop-1x1"]
    keys = [z.key for z in G.zones_for("9:16", ["meta"], True)]
    assert keys == ["master", "meta-disclaimer", "crop-4x5", "crop-1x1"]
    assert [z.key for z in G.zones_for("4:5", None, False)] == ["feed-4x5"]
    assert G.zones_for("16:9", None, False) == []


def test_tiktok_is_gone():
    assert "tiktok" not in G.placements
