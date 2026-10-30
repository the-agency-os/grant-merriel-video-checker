"""Burned-in text and face detection.

Two backends, same output:
- vision: Apple Vision through a small compiled Swift helper (macOS with Xcode Command Line Tools).
- rapidocr: RapidOCR text boxes and OpenCV face boxes (any OS, pure pip install).
`auto` uses vision when it can and rapidocr otherwise. VIDEO_CHECKER_BACKEND forces one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter

from .zones import Rect

SWIFT = Path(__file__).parent / "assets" / "vzones_detect.swift"
FACE_SCORE = 0.7
YUNET = Path(__file__).parent / "assets" / "face_detection_yunet_2023mar.onnx"  # OpenCV Zoo, MIT
BINARY = Path.home() / "Library" / "Caches" / "video-checker" / "vzones-detect"


class DetectionUnavailable(RuntimeError):
    """No detection backend can run on this machine."""


@dataclass(frozen=True)
class Detection:
    kind: str  # "text" | "face"
    text: str
    confidence: float
    box: Rect


@dataclass(frozen=True)
class FrameDetections:
    t: float
    path: Path
    detections: list[Detection]


def _cached_binary_ok() -> bool:
    return BINARY.exists() and BINARY.stat().st_mtime >= SWIFT.stat().st_mtime


def ensure_helper() -> Path:
    if _cached_binary_ok():
        return BINARY
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise DetectionUnavailable("swiftc not found (install Xcode Command Line Tools)")
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [swiftc, "-O", str(SWIFT), "-o", str(BINARY)], capture_output=True, text=True
    )
    if r.returncode != 0:
        raise DetectionUnavailable(f"Vision helper failed to compile: {r.stderr[-400:]}")
    return BINARY


def _parse(stdout: str) -> tuple[dict[str, list[Detection]], list[str]]:
    by_path: dict[str, list[Detection]] = {}
    errors: list[str] = []
    for line in stdout.splitlines():
        d = json.loads(line)
        if "error" in d:
            errors.append(f"{Path(d.get('path', '?')).name}: {d['error']}")
            continue
        dets = [
            Detection("text", t["s"], float(t["c"]), Rect(*t["box"])) for t in d.get("text", [])
        ]
        dets += [Detection("face", "", 1.0, Rect(*b)) for b in d.get("faces", [])]
        by_path[d["path"]] = dets
    return by_path, errors


EDGE = 40  # FIND_EDGES strength that counts as a letter edge
INK_SHARE = 0.15  # a row is "ink" when its edge density is 15% of the densest row
MAX_TRIM = 0.35  # never pull an edge in by more than 35% of the box height
INK_MARGIN = 4  # px kept around the measured letters (anti-aliasing, outline glow)


def tighten(grey: Image.Image, box: Rect) -> Rect:
    """Pull a text box's top and bottom in to where the letters really are.

    Apple Vision's line boxes reserve room for descenders even on all-caps captions, so they run
    15-20 px below the ink. Measure edge density row by row inside the box and keep the rows that
    look like letters. A busy background keeps every row 'inked', so the box is left alone: this can
    only make a box tighter where the evidence is clear, never looser."""
    x0, y0 = max(0, box.x0), max(0, box.y0)
    x1, y1 = min(grey.width, box.x1), min(grey.height, box.y1)
    if x1 - x0 < 4 or y1 - y0 < 8:
        return box
    edges = grey.crop((x0, y0, x1, y1)).filter(ImageFilter.FIND_EDGES)
    edges = edges.point(lambda v: 255 if v >= EDGE else 0)
    rows = list(edges.resize((1, y1 - y0), Image.Resampling.BOX).tobytes())
    peak = max(rows)
    if not peak:
        return box
    inked = [i for i, v in enumerate(rows) if v >= INK_SHARE * peak]
    h = y1 - y0
    top = min(inked[0], int(MAX_TRIM * h))
    bottom = max(inked[-1] + 1, h - int(MAX_TRIM * h))
    new_y0 = y0 + max(0, top - INK_MARGIN)
    new_y1 = y0 + min(h, bottom + INK_MARGIN)
    return Rect(box.x0, new_y0, box.x1, new_y1)


def _tighten_frame(path: Path, dets: list[Detection]) -> list[Detection]:
    if not any(d.kind == "text" for d in dets) or not Path(path).exists():
        return dets
    grey = Image.open(path).convert("L")
    return [
        Detection(d.kind, d.text, d.confidence, tighten(grey, d.box)) if d.kind == "text" else d
        for d in dets
    ]


def run_helper(paths: list[Path], workers: int | None = None) -> list[list[Detection]]:
    """Run Vision over every frame, split across parallel helper processes, order preserved.

    Each process gets its own thread calling communicate(), so large stdin/stdout/stderr volumes
    can never deadlock on a full pipe. Any unreadable frame or failed process means the result
    can't be trusted, so it raises DetectionUnavailable rather than reporting a silent PASS.
    """
    binary = ensure_helper()
    paths = [Path(p) for p in paths]
    if not paths:
        return []
    workers = max(1, min(workers or max(1, (os.cpu_count() or 2) // 2), len(paths)))
    size = -(-len(paths) // workers)
    chunks = [paths[i : i + size] for i in range(0, len(paths), size)]
    results: list[tuple[int, str, str] | None] = [None] * len(chunks)
    procs: list[subprocess.Popen] = []

    def work(i: int, proc: subprocess.Popen, chunk: list[Path]) -> None:
        out, err = proc.communicate("".join(f"{p}\n" for p in chunk))
        results[i] = (proc.returncode, out, err)

    try:
        for _ in chunks:
            procs.append(
                subprocess.Popen(
                    [str(binary)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        threads = [
            threading.Thread(target=work, args=(i, p, c), daemon=True)
            for i, (p, c) in enumerate(zip(procs, chunks, strict=True))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except OSError as exc:
        raise DetectionUnavailable(f"Vision helper could not start: {exc}") from exc
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    by_path: dict[str, list[Detection]] = {}
    errors: list[str] = []
    for res in results:
        code, out, err = res if res else (-1, "", "no result")
        if code != 0:
            raise DetectionUnavailable(f"Vision helper failed: {err[-400:]}")
        got, bad = _parse(out)
        by_path.update(got)
        errors += bad
    missing = [p for p in paths if str(p) not in by_path]
    if errors or missing:
        detail = errors[:3] or [f"{len(missing)} frames returned nothing"]
        raise DetectionUnavailable("Vision could not read every frame: " + "; ".join(detail))
    return [_tighten_frame(p, by_path[str(p)]) for p in paths]


def ffmpeg_exe() -> str:
    """System ffmpeg if present, else the one bundled with imageio-ffmpeg (no install needed)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover - dependency of the package
        raise DetectionUnavailable("ffmpeg not found and imageio-ffmpeg not installed") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str]) -> None:
    r = subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", *args], capture_output=True, text=True
    )
    if r.returncode != 0:
        raise DetectionUnavailable(f"ffmpeg failed: {r.stderr[-400:]}")


def sample_frames(source: Path, out_dir: Path, fps: float, canvas: tuple[int, int]):
    shutil.rmtree(out_dir, ignore_errors=True)  # never judge frames left by an earlier run
    out_dir.mkdir(parents=True)
    w, h = canvas
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-vf",
            f"fps={fps}:start_time=0,scale={w}:{h}:flags=lanczos,setsar=1",
            "-start_number",
            "0",
            str(out_dir / "f%05d.png"),
        ]
    )
    files = sorted(out_dir.glob("f*.png"))
    return [(i / fps, p) for i, p in enumerate(files)]


_RAPID = {}


def _rapidocr_available() -> bool:
    try:
        import cv2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def run_rapidocr(paths: list[Path]) -> list[list[Detection]]:
    """Text boxes from RapidOCR and face boxes from OpenCV's YuNet face detector."""
    if not _rapidocr_available():
        raise DetectionUnavailable(
            "no text reader: install with  pip install 'grant-merriel-video-checker[ocr]'"
        )
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    if "ocr" not in _RAPID:
        # YuNet's own cut-off is 0.6 here; FACE_SCORE below is the real threshold.
        _RAPID.update(
            ocr=RapidOCR(), face=cv2.FaceDetectorYN.create(str(YUNET), "", (540, 960), 0.6)
        )
    ocr, faces = _RAPID["ocr"], _RAPID["face"]
    out: list[list[Detection]] = []
    for p in paths:
        img = cv2.imread(str(p))
        if img is None:
            raise DetectionUnavailable(f"could not read frame {Path(p).name}")
        dets: list[Detection] = []
        result, _ = ocr(img)
        for quad, text, score in result or []:
            xs, ys = [pt[0] for pt in quad], [pt[1] for pt in quad]
            box = Rect(int(min(xs)), int(min(ys)), int(round(max(xs))), int(round(max(ys))))
            dets.append(Detection("text", str(text), float(score), box))
        # Faces are found at half size: YuNet is faster there and more confident on big faces.
        small = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
        faces.setInputSize((small.shape[1], small.shape[0]))
        _n, found = faces.detect(small)
        for f in found if found is not None else []:
            x, y, w, h = (int(v * 2) for v in f[:4])
            score = float(f[-1])
            if score >= FACE_SCORE:
                dets.append(Detection("face", "", score, Rect(x, y, x + w, y + h)))
        out.append(dets)
    return out


def _vision_possible() -> bool:
    return sys.platform == "darwin" and (_cached_binary_ok() or bool(shutil.which("swiftc")))


def backend(requested: str | None = None) -> str:
    """Pick the backend: vision on a Mac that can build the helper, else rapidocr."""
    want = (requested or os.environ.get("VIDEO_CHECKER_BACKEND") or "auto").lower()
    if want == "vision":
        return "vision"
    if want == "rapidocr":
        return "rapidocr"
    if _vision_possible():
        return "vision"
    if _rapidocr_available():
        return "rapidocr"
    raise DetectionUnavailable(
        "no text reader on this machine: on a Mac install Xcode Command Line Tools "
        "(xcode-select --install), anywhere else pip install 'grant-merriel-video-checker[ocr]'"
    )


def detect_frames(paths: list[Path], which: str | None = None) -> list[list[Detection]]:
    return run_helper(paths) if backend(which) == "vision" else run_rapidocr(paths)


def detect_video(
    source, work_dir, fps: float = 4, canvas=(1080, 1920), which: str | None = None
) -> list[FrameDetections]:
    frames = sample_frames(Path(source), Path(work_dir) / "frames", fps, canvas)
    results = detect_frames([p for _, p in frames], which)
    return [FrameDetections(t, p, d) for (t, p), d in zip(frames, results, strict=True)]
