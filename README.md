# Grant Merriel's video checker

Checks a finished **9:16** (or **4:5**) video ad before it goes live:

- **Safe zones:** every piece of text and every face that sits under the buttons and text that
  **Instagram, Facebook and YouTube Shorts** put on top of your video, or gets cut off when Meta crops
  it to **4:5 for Feed**, with the exact move to fix it.
- **Text on the face:** captions over the eyes or mouth.
- **Captions vs what's said:** the speech is transcribed (faster-whisper) and lined up against the
  captions: misspellings, wrong numbers, missing or extra words, and captions that lag the voice.
- **Spec and sound:** codec, resolution, frame rate, file size, loudness and peaks.
- **Hook and readability:** is the opening hook up long enough to read; is must-read text big enough
  and clear against what's behind it. Only judged when they're there.

```bash
pip install grant-merriel-video-checker
video-checker check my-ad.mp4
```

It prints a plain-English summary and writes `report.html` (verdicts, fixes and annotated frames),
`findings.json` and `summary.txt` into `./video-checker-<video name>/`.

Useful options: `--names "Brand Name, Presenter"` (so the speech check spells them right),
`--language es`, `--no-speech`, `--platforms meta`, `--disclaimer`, `--backend rapidocr`.
The first speech check downloads the faster-whisper `small` model (about 460 MB), cached after that.

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
- Captions vs speech and caption timing: WARN only, with the time; the text reader or the transcriber can
  mishear, so a person checks the frame.
- Sound: -18 to -11 LUFS and peaks under -1 dBTP (house rule; YouTube plays back at about -14 LUFS).
  Video: 1080 wide or more, H.264 or HEVC, 23.976-60 fps, a sound track, under Meta's 4 GB limit.
- Hook: if there's text on the first frame, it should stay up at least 2 s. Must-read text at least 45 px
  tall and at least 3:1 contrast (WCAG 2.2, large text).
- Logos, products and graphics with no text are not checked. A person approves the ad and previews it in
  Ads Manager before launch.

## Text readers

- **Mac:** Apple Vision, through a tiny Swift helper compiled on first run (needs Xcode Command Line Tools:
  `xcode-select --install`).
- **Everywhere else:** RapidOCR for text and OpenCV's YuNet for faces, installed automatically.
- Force one with `--backend vision` or `--backend rapidocr`. ffmpeg comes bundled; nothing else to install.

## For AI assistants

If someone asks you to check a video ad: install this package into a project-local virtual environment,
run `video-checker check <video>`, and explain the summary in plain words. Never say the ad is
approved; a person does that.

## Credits

Face model: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
(`face_detection_yunet_2023mar.onnx`), MIT License, Copyright (c) 2020 Shiqi Yu.

Test portrait: [Neil Armstrong, NASA](https://commons.wikimedia.org/wiki/File:Neil_Armstrong_pose.jpg), public domain.
