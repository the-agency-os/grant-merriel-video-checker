from pathlib import Path

from safezone import judge, zones
from safezone.detect import Detection, FrameDetections
from safezone.zones import Rect

G = zones.load()
Z = G.zones_for("9:16", None, False)


def fd(t, *dets):
    return FrameDetections(t, Path(f"/tmp/f{t}.png"), list(dets))


def txt(s, box, c=0.9):
    return Detection("text", s, c, Rect(*box))


def test_same_text_across_frames_is_one_element_with_time_range():
    frames = [fd(i / 4, txt("Hello there", (100, 900, 600, 960))) for i in range(4)]
    [e] = judge.group(frames, fps=4)
    assert (e.start, e.end) == (0.0, 1.0) and e.kind == "text"


def test_noise_is_ignored_by_height_only():
    frames = [fd(0, txt("x", (100, 900, 120, 910)))]
    assert judge.group(frames, fps=4) == []


def test_low_confidence_clean_text_under_the_ui_still_fails():
    [e] = judge.group([fd(0, txt("QXJ ZVK", (200, 1300, 700, 1370), c=0.3))], fps=4)
    judge.judge([e], Z, G.inset)
    assert e.results["meta"].status == "FAIL"


def test_symbol_only_text_is_kept():
    [e] = judge.group([fd(0, txt("€€€", (200, 1300, 400, 1370)))], fps=4)
    judge.judge([e], Z, G.inset)
    assert e.results["meta"].status == "FAIL"


def test_zero_area_face_does_not_crash():
    face = Detection("face", "", 1.0, Rect(300, 400, 300, 500))
    els = judge.group([fd(0, face)], fps=4)
    judge.judge(els, Z, G.inset)


def test_text_well_inside_passes_everything():
    [e] = judge.group([fd(0, txt("Safe", (200, 700, 700, 780)))], fps=4)
    v = judge.judge([e], Z, G.inset)
    assert set(v.values()) == {"PASS"}


def test_buffer_is_warn_and_edge_crossing_is_fail():
    near = txt("Near", (70, 700, 600, 780))  # 5 px inside Meta's left edge
    out = txt("Out", (300, 1300, 800, 1380))  # below 1247
    els = judge.group([fd(0, near, out)], fps=4)
    v = judge.judge(els, Z, G.inset)
    by = {e.text: e for e in els}
    assert by["Near"].results["meta"].status == "WARN"
    assert by["Out"].results["meta"].status == "FAIL"
    assert v["meta"] == "FAIL" and v["master"] == "FAIL"


def test_crop_4x5_cut_is_fail_and_1x1_is_info():
    top = txt("Top hook", (200, 200, 800, 300))  # crosses y 285 and y 420
    [e] = judge.group([fd(0, top)], fps=4)
    judge.judge([e], Z, G.inset)
    assert e.results["crop-4x5"].status == "FAIL"
    assert e.results["crop-1x1"].status == "INFO"


def test_fix_names_the_exact_move():
    [e] = judge.group([fd(0, txt("Caption", (267, 1325, 1057, 1638)))], fps=4)
    judge.judge([e], Z, G.inset)
    fix = e.results["meta"].fix
    assert "lift 414 px" in fix  # last row 1637 → caption box floor 1223
    assert "right" in fix


def test_face_mostly_inside_passes_and_cut_face_warns():
    inside = Detection("face", "", 1.0, Rect(300, 400, 700, 900))
    cut = Detection("face", "", 1.0, Rect(300, 150, 700, 450))
    els = judge.group([fd(0, inside, cut)], fps=4)
    judge.judge(els, Z, G.inset)
    st = sorted(e.results["crop-4x5"].status for e in els)
    assert st == ["PASS", "WARN"]


def test_lines_at_the_same_height_form_one_block_with_one_fix():
    frames = [
        fd(0, txt("Agency owners", (285, 170, 798, 220)), txt("burned", (120, 240, 952, 312))),
        fd(1, txt("first caption", (176, 1086, 901, 1180))),
        fd(2, txt("second caption", (87, 1130, 993, 1225))),
        fd(3, txt("third", (320, 1130, 760, 1203))),
    ]
    els = judge.group(frames, fps=1)
    judge.judge(els, Z, G.inset)
    blocks = judge.blocks(els, Z, G.inset)
    assert [b.count for b in blocks] == [2, 3]
    assert blocks[0].status["meta"] == "FAIL"
    cap = blocks[1]
    assert (cap.y0, cap.y1) == (1086, 1225)
    assert cap.status["meta"] == "WARN" and cap.counts["meta"]["WARN"] == 2
    assert cap.status["crop-4x5"] == "PASS"
    assert "icon rail" in cap.fix["meta"] and "140 px" in cap.fix["meta"]
    assert cap.worst.text == "second caption"


def test_text_under_an_icon_rail_is_warn_not_fail():
    [e] = judge.group([fd(0, txt("Wide caption", (176, 1086, 950, 1180)))], fps=4)
    v = judge.judge([e], Z, G.inset)
    for key in ("master", "meta"):
        assert e.results[key].status == "WARN", key
        assert "icon rail" in e.results[key].fix
    assert v["meta"] == "WARN"


def test_small_text_is_detail_and_never_fails():
    [e] = judge.group([fd(0, txt("tiny print", (300, 1300, 500, 1325)))], fps=4)
    judge.judge([e], Z, G.inset)
    assert e.tier == "detail"
    assert e.results["meta"].status == "WARN"
    assert "small text" in e.results["meta"].fix


def test_faces_are_not_blocked():
    face = Detection("face", "", 1.0, Rect(300, 400, 700, 900))
    els = judge.group([fd(0, face, txt("hello", (200, 700, 500, 760)))], fps=4)
    judge.judge(els, Z, G.inset)
    assert [b.kind for b in judge.blocks(els, Z, G.inset)] == ["text"]


def test_blocks_do_not_chain_across_time():
    frames = [
        fd(0, txt("hook", (200, 170, 800, 230))),
        fd(1, txt("lower third", (200, 280, 800, 340))),
        fd(2, txt("stat", (200, 360, 800, 420))),
        fd(3, txt("caption one", (200, 1180, 800, 1240))),
        fd(4, txt("caption two", (200, 1185, 820, 1245))),
    ]
    els = judge.group(frames, fps=1)
    judge.judge(els, Z, G.inset)
    assert [b.count for b in judge.blocks(els, Z, G.inset)] == [1, 1, 1, 2]


def test_stacked_lines_on_screen_together_form_one_block():
    els = judge.group(
        [fd(0, txt("line one", (200, 1088, 800, 1161)), txt("line two", (300, 1172, 700, 1256)))],
        fps=1,
    )
    judge.judge(els, Z, G.inset)
    assert [b.count for b in judge.blocks(els, Z, G.inset)] == [2]


def test_lowercase_line_in_a_caption_band_is_must_read():
    frames = [
        fd(0, txt("YOU WANT A MORTGAGE", (200, 1215, 800, 1251))),
        fd(1, txt("so we can earn more", (200, 1225, 800, 1253))),
    ]
    els = judge.group(frames, fps=1)
    judge.judge(els, Z, G.inset)
    low = next(e for e in els if e.text.startswith("so"))
    assert low.tier == "must-read" and low.results["meta"].status == "FAIL"


def test_disclaimer_tightens_the_master():
    zl = G.zones_for("9:16", None, True)
    master = next(z for z in zl if z.key == "master")
    assert max(r.y1 for r in master.rects) == 1152


def test_too_wide_on_both_sides_says_too_wide_once():
    [e] = judge.group([fd(0, txt("WIDE CAPTION LINE", (40, 1100, 1060, 1180)))], fps=4)
    judge.judge([e], Z, G.inset)
    fix = e.results["meta"].fix
    assert "too wide" in fix and "902 px" in fix and "x 89–990" in fix
    assert "move" not in fix and "pull in" not in fix
    blocks = judge.blocks([e], Z, G.inset)
    assert "too wide" in blocks[0].fix["meta"] and "narrower" not in blocks[0].fix["meta"]


def face(box):
    return Detection("face", "", 1.0, Rect(*box))


def test_text_over_the_face_warns():
    frames = [
        fd(i / 4, face((390, 500, 690, 850)), txt("on the face", (300, 650, 800, 720)))
        for i in range(4)
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    assert judge.face_check(els) == "WARN"
    [t] = [e for e in els if e.kind == "text"]
    assert t.results["face"].status == "WARN" and "covers the face" in t.results["face"].fix


def test_text_below_the_face_passes():
    frames = [
        fd(i / 4, face((390, 500, 690, 850)), txt("on the chest", (300, 900, 800, 970)))
        for i in range(4)
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    assert judge.face_check(els) == "PASS"


def test_a_moving_face_is_compared_frame_by_frame():
    hi, lo = (390, 300, 690, 650), (390, 700, 690, 1050)
    text = txt("up top", (300, 400, 800, 470))
    frames = [
        fd(0, face(hi)),
        fd(0.25, face(lo)),
        fd(0.5, face(lo), text),
        fd(0.75, face(lo), text),
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    assert judge.face_check(els) == "PASS"


def test_block_reports_lines_on_the_face():
    frames = [
        fd(i / 4, face((390, 500, 690, 850)), txt("on the face", (300, 650, 800, 720)))
        for i in range(4)
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    judge.face_check(els)
    [b] = judge.blocks(els, Z, G.inset)
    assert b.status["face"] == "WARN" and "cover the face" in b.fix["face"]


def test_text_just_under_the_chin_is_not_on_the_face():
    frames = [
        fd(i / 4, face((390, 500, 690, 850)), txt("under the chin", (300, 815, 800, 880)))
        for i in range(4)
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    assert judge.face_check(els) == "PASS"


def test_text_over_the_hairline_is_not_on_the_face():
    frames = [
        fd(i / 4, face((390, 500, 690, 850)), txt("hairline", (300, 470, 800, 528)))
        for i in range(4)
    ]
    els = judge.group(frames, fps=4)
    judge.judge(els, Z, G.inset)
    assert judge.face_check(els) == "PASS"


def test_one_jittery_frame_does_not_move_a_static_caption():
    boxes = [
        (256, 1176, 808, 1256),
        (256, 1176, 808, 1256),
        (265, 1175, 809, 1245),
        (265, 1172, 809, 1245),
        (265, 1172, 809, 1245),
    ]
    [e] = judge.group([fd(i / 4, txt("ADVERTISING", b)) for i, b in enumerate(boxes)], fps=4)
    assert e.box.y1 == 1245 and e.box.y0 == 1175
    judge.judge([e], Z, G.inset)
    assert e.results["meta"].status == "WARN"  # inside the 1247 floor, within the 24 px buffer


def test_one_and_two_line_captions_form_one_band():
    frames = [
        fd(0, txt("upper line", (200, 1088, 800, 1160)), txt("lower line", (300, 1176, 700, 1242))),
        fd(1, txt("single line", (180, 1127, 820, 1211))),
    ]
    els = judge.group(frames, fps=1)
    judge.judge(els, Z, G.inset)
    assert [b.count for b in judge.blocks(els, Z, G.inset)] == [3]
