# One-shot prompt: 9:16 safe-zone check

For anyone. Open Claude (desktop app, Claude Code) or Codex, or ChatGPT, paste everything in the box
below, and attach the finished video or videos.

It tells the AI to install **Grant Merriel's video safe-zone checker** (`grant-merriel-video-safezone`,
code at https://github.com/the-agency-os/grant-merriel-video-safezone) into a folder and run it, so
every check uses the same tested code. Where the AI can't run code or download anything (ChatGPT's
sandbox usually can't), it falls back to the by-hand method at the end of the prompt.

Numbers: geometry `2026-10-30.3`, from the package's `safezone/assets/safe-zones.json`. If that file
changes, update THE BACKUP METHOD numbers below to match.

---

```
You're my ad safe-zone checker. Check my finished vertical video ads and tell me exactly which text sits under Instagram, Facebook or YouTube Shorts' on-screen buttons, sits on someone's face, or gets cut off in the 4:5 Feed crop, and exactly how to move it.
Keep every reply short: no intro, no recap of what I said.

WHAT I'VE GIVEN YOU
With this message I've given you one or more finished video files (MP4 or MOV).
If there's no video, stop and ask me for it before you do anything else.

THE TOOL
Use Grant Merriel's video safe-zone checker: the Python package grant-merriel-video-safezone.
- Work in a folder called "Safe zone check". Make a Python virtual environment in Safe zone check/.tools and install it there: pip install grant-merriel-video-safezone
  If pip can't find it, install it from GitHub instead: pip install git+https://github.com/the-agency-os/grant-merriel-video-safezone
- It brings its own ffmpeg and text reader. Never install anything system-wide.
- On a Mac it reads text with Apple Vision. If it says Xcode Command Line Tools are missing, reinstall it with the extra reader instead of asking me: pip install "grant-merriel-video-safezone[ocr]"
- Run it on each video: safezone check "<video>" --out "Safe zone check/<video name>"
- If you can't run code or can't download it here, say so in one line, then use THE BACKUP METHOD at the end.

STEP 1: RUN IT.
For each video, run the tool and read what it prints and the files it writes (summary.txt, report.html, findings.json, and the annotated frames in frames/).

STEP 2: TELL ME.
1. The verdict line, as a small table: Master, Meta, YouTube Shorts, 4:5 crop, Text on the face (PASS, WARN or FAIL).
2. What to fix: one line per block, in plain words, with the time and the tool's exact fix. Say which are FAIL (must fix) and which are only WARN (check it reads).
3. Show me the annotated frame for each block that needs fixing.
4. Where report.html is.
Use the tool's numbers and fixes exactly. Don't re-measure or second-guess them.

RULES
- Never edit or re-export my video. You only read it.
- Never say the ad is approved. You report PASS, WARN or FAIL; a person approves it and previews it in Ads Manager.
- Logos, products and graphics with no text aren't checked. Say so once.

Then say only: "Tell me which fixes to make, with the time."

THE BACKUP METHOD (only if the tool can't run)
Do the same check by hand. You'll need ffmpeg (imageio-ffmpeg gives it without installing anything), a text reader that returns a box for every line (Apple Vision, RapidOCR, EasyOCR or Tesseract), and a face detector (Apple Vision or OpenCV's YuNet). Keep anything you install inside Safe zone check/.tools. If you can't run code at all, ask me for screenshots, one per second, and judge by eye; mark that report [BY EYE].
THE NUMBERS. All are pixels on a 1080 x 1920 frame. Scale any other size to 1080 x 1920 first.
Hard edges (text past them is covered or cut off):
- MASTER zone, the one my editors design to: x 65-1014, y 288-1247.
- Caption box, where captions should sit: x 89-990, y 312-1223 (24 px inside the master).
- Meta (Instagram + Facebook, Reels + Stories): x 65-1014, y 269-1247. Below y 1247, Meta's page name, "Paid for by", ad text and Learn more button cover the video (Facebook Reels' interface starts at about y 1281).
- YouTube Shorts ads: x 48-1031, y 288-1247.
- 4:5 Feed crop of a 9:16 video: x 0-1079, y 285-1634. Text cut by this line disappears in Feed.
- 1:1 square crop: y 420-1499. Report it, but it never fails.
Icon rails (see-through like/comment/share buttons; text can sit under them but must still read). The master zone has both rails too:
- Meta: x 853 and right, from y 1152 down.
- YouTube Shorts: x 870 and right, from y 1343 down (below the master, so it rarely matters).
If the video itself is 4:5 (1080 x 1350), use one hard edge instead: x 65-1014, y 65-1284.

HOW TO JUDGE IT
- Big text (36 px tall or more: captions, the hook headline, CTA words, prices, disclaimers) is must-read.
  Past a hard edge = FAIL. Under an icon rail = WARN. Less than 24 px inside a hard edge = WARN (exactly 24 px is fine).
- Small text (under 36 px tall, like the body of a screenshot) is detail: at most WARN.
- Measure each line from its letters, not the reader's box: many text readers pad the box 10-20 px below all-caps text. If unsure, use the box.
- Ignore text shorter than 18 px. It's noise.
- A face more than 10% past a hard edge = WARN (a person decides).
- Text on the face = WARN: in the same frame, a text box overlapping the eyes-to-mouth part of a face box (trim the top 10% and bottom 12% of the face box first) by 15% or more of the smaller box, for at least half a second. Hairline and under-the-chin text is fine.
- Logos, products, GIFs and graphics with no text: you can't detect them reliably. Say so; don't guess.
- One placement's verdict is its worst result: FAIL beats WARN beats PASS.
- Fixes aim at the caption box. A fix doesn't have to clear the icon rails (they're WARN only); if a line can't clear them by moving, say "or split it onto two lines".

STEP 1: LOOK AT THE VIDEO.
For each file give me one line: name, size, ratio, length, fps. If a file isn't 9:16 or 4:5, say so and skip it.

STEP 2: FIND EVERY PIECE OF TEXT.
- Pull 4 frames per second from the very first frame, scaled to 1080 x 1920 (or 1080 x 1350 for 4:5).
- Run OCR and face detection on every frame. Keep each box in pixels, top-left origin.
- The same words in the same place across frames are one element, with a start and end time.
- Lines sitting within 40 px of each other vertically form one block (for example "the caption band" or "the hook card"). Judge every element, then give each block ONE fix: the most it needs to move to fit the caption box. For example: "lift the block 38 px; keep lines 22 px narrower on the right".

STEP 2B: SHOW ME 3 STILLS FIRST.
Before the full report, show me 3 frames with the master zone drawn on (green line, red shade outside it, amber over the icon rails, white dashed caption box) and every text box outlined, coloured by result. Pick the first frame, the worst breach (the one failing the most placements; on a tie, the biggest overshoot) and one clean frame if there is one.
If the boxes don't sit on the text, fix your OCR scaling before going on. Otherwise carry on.

STEP 3: THE REPORT.
1. A verdict table: one row each for Master, Meta, YouTube Shorts, 4:5 crop, Text on the face and 1:1 crop (info). Columns: Verdict (PASS, WARN or FAIL), then how many text pieces passed, warned and failed.
2. What to fix: one row per block that isn't all PASS. Columns: where (y range), how many lines, when (time range), result per placement, and the one fix.
3. The worst frame for each block, annotated as in Step 2B.
4. Every failing or warning line in a list underneath (time, text, placement, result, fix).
5. Limits, word for word: "Logos, products and graphics with no text were not checked. A person approves this ad and previews it in Ads Manager before launch."
Save it as Safe zone check/report/report.html (images embedded) plus findings.json, and show me the tables here.

STEP 4: CHECK BEFORE YOU HAND IT OVER.
- Re-open every FAIL frame and confirm the box sits on real text, not a shadow, logo or background sign.
- Step through the video at 1 frame per second and confirm no on-screen text was missed.
- Check your arithmetic on every fix against the caption box numbers.
If anything's wrong, fix it before you show me.
Then report exactly as in STEP 2, saving report.html and findings.json in Safe zone check/report.
```
