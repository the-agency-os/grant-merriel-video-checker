import json
from pathlib import Path

from PIL import Image

from video_checker import judge, report, zones
from video_checker.zones import Rect

G = zones.load()
Z = G.zones_for("9:16", None, False)


def _elements(tmp_path):
    f = tmp_path / "f.png"
    Image.new("RGB", (1080, 1920), "grey").save(f)
    bad = judge.Element(
        "t1", "text", "everything figured out", 4.0, 5.5, Rect(267, 1325, 1057, 1638), 0.97, f
    )
    ok = judge.Element("t2", "text", "safe", 1.0, 2.0, Rect(200, 700, 700, 780), 0.99, f)
    verdicts = judge.judge([bad, ok], Z, G.inset)
    return [bad, ok], verdicts


def test_findings_json(tmp_path):
    els, v = _elements(tmp_path)
    p = report.write_findings(tmp_path, {"source": "x.mp4", "aspect": "9:16"}, v, els, Z)
    d = json.loads(p.read_text())
    assert d["verdicts"]["meta"] == "FAIL"
    assert d["elements"][0]["results"]["meta"]["fix"]
    assert any(
        "Logos, products and graphics without text are not detected" in s for s in d["limits"]
    )


def test_html_is_self_contained(tmp_path):
    els, v = _elements(tmp_path)
    ann = {
        "t1": report.annotate(
            els[0].frame, G.master, [(els[0].box, "FAIL", "t1")], tmp_path / "t1.jpg"
        )
    }
    assert Image.open(ann["t1"]).size == (1080, 1920)
    html = report.write_html(tmp_path, {"source": "x.mp4", "aspect": "9:16"}, v, els, Z, ann)
    t = Path(html).read_text()
    assert 'src="data:image/jpeg;base64,' in t and "file://" not in t
    for z in Z:
        assert z.title in t
    assert "A person signs APPROVE / APPROVE WITH FIXES / REJECT" in t


def test_blocks_lead_the_report(tmp_path):
    els, v = _elements(tmp_path)
    bl = judge.blocks(els, Z, G.inset)
    ann = {
        "b1": report.annotate(
            els[0].frame, G.master, [(els[0].box, "FAIL", "b1")], tmp_path / "b1.jpg"
        )
    }
    meta = {"source": "x.mp4", "aspect": "9:16"}
    d = json.loads(report.write_findings(tmp_path, meta, v, els, Z, bl).read_text())
    assert d["blocks"][1]["count"] == 1 and "lift the block" in d["blocks"][1]["fix"]["meta"]
    t = Path(report.write_html(tmp_path, meta, v, els, Z, ann, bl)).read_text()
    assert t.index("What to fix") < t.index("Every line")
    assert "<details>" in t


def test_face_row_in_report(tmp_path):
    els, v = _elements(tmp_path)
    judge.face_check(els)
    v["face"] = "PASS"
    cols = [*Z, judge.FACE_ZONE]
    t = Path(
        report.write_html(tmp_path, {"source": "x.mp4", "aspect": "9:16"}, v, els, cols, {})
    ).read_text()
    assert "Text on the face" in t


def test_other_checks_in_report_and_findings(tmp_path):
    from video_checker.spec import Check

    els, v = _elements(tmp_path)
    checks = [Check("sound", "Sound", "WARN", ["WARN · -24.0 LUFS: quiet"], "house rule")]
    v["sound"] = "WARN"
    meta = {"source": "x.mp4", "aspect": "9:16"}
    d = json.loads(report.write_findings(tmp_path, meta, v, els, Z, [], checks).read_text())
    assert d["checks"][0]["key"] == "sound" and d["checks"][0]["lines"] == [
        "WARN · -24.0 LUFS: quiet"
    ]
    t = Path(report.write_html(tmp_path, meta, v, els, Z, {}, [], checks)).read_text()
    assert "Other checks" in t and "-24.0 LUFS: quiet" in t and t.count(">Sound<") >= 1
