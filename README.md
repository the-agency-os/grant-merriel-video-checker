# Grant Merriel's video safe-zone checker

Finds every piece of text and every face in a finished **9:16** (or **4:5**) video ad, and tells you
which ones sit under the buttons and text that **Instagram, Facebook and YouTube Shorts** put on top
of your video, or get cut off when Meta crops it to **4:5 for Feed**. Then it tells you exactly how
to move them.

```bash
pip install grant-merriel-video-safezone
safezone check my-ad.mp4
```

```
Safe-zone check: my-ad.mp4 (9:16, 60.0 s, 240 frames, text reader: Apple Vision)
Master: FAIL · Meta (IG + FB Reels and Stories): FAIL · YouTube Shorts ads: FAIL · 4:5 Feed crop: FAIL · Text on the face: PASS · 1:1 crop (info only): INFO

What to fix:
- b1: text at y 170–448, 4 lines, 0:00.0–0:05.0
    Master: FAIL (2 fail, 1 warn of 4) — lower the block 142 px; too wide: keep each line under 902 px (x 89–990)
- b2: text at y 1082–1260, 71 lines, 0:00.2–0:59.8
    Master: FAIL (3 fail, 42 warn of 71) — lift the block 37 px; too wide: keep each line under 902 px (x 89–990)
```

It also writes `report.html` (verdicts, fixes and annotated frames), `findings.json` and
`summary.txt` into `./safezone-<video name>/`.

## The rules

All numbers are pixels on a 1080 × 1920 frame; any other size is scaled first.

| Zone | Keep must-read text inside | Why |
|---|---|---|
| **Master** (design to this) | x 65–1014, y 288–1247 | Meta + YouTube Shorts ads + the 4:5 crop |
| Caption box | x 89–990, y 312–1223 | 24 px inside the master |
| Meta: IG + FB Reels and Stories | x 65–1014, y 269–1247 | Meta's 14% top, 35% bottom, 6% sides; Facebook Reels' text starts about y 1281 |
| YouTube Shorts ads | x 48–1031, y 288–1247 | Google's official overlay |
| 4:5 Feed crop | y 285–1634 | the centre 1080 × 1350 |

- Past a hard edge: **FAIL**. Less than 24 px inside: **WARN**.
- Under an icon rail (Meta from y 1152 at x 853+, YouTube from y 1343 at x 870+): **WARN**. The icons are
  see-through, so text behind them usually still reads.
- Text on the eyes-to-mouth part of a face for half a second or more: **WARN**.
- Text under 36 px tall on its own is detail: at most **WARN**.
- Logos, products and graphics with no text are not checked. A person approves the ad and previews it in
  Ads Manager before launch.

## Text readers

- **Mac:** Apple Vision, through a tiny Swift helper compiled on first run (needs Xcode Command Line Tools:
  `xcode-select --install`).
- **Everywhere else:** RapidOCR for text and OpenCV's YuNet for faces, installed automatically.
- Force one with `--backend vision` or `--backend rapidocr`. ffmpeg comes bundled; nothing else to install.

## For AI assistants

If someone asks you to check a video's safe zones: install this package into a project-local virtual
environment, run `safezone check <video>`, and explain the summary in plain words. Never say the ad is
approved; a person does that.

## Credits

Face model: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
(`face_detection_yunet_2023mar.onnx`), MIT License, Copyright (c) 2020 Shiqi Yu.

Test portrait: [Neil Armstrong, NASA](https://commons.wikimedia.org/wiki/File:Neil_Armstrong_pose.jpg), public domain.
