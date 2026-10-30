# Plan 0.2.0 — from safe-zone checker to video checker (Grant, 2026-10-30)

Rename: package grant-merriel-video-checker, module video_checker, command `video-checker check`. DONE.

New checks, each a row in the same report (verdicts dict keys) and a section in summary/report/findings:

1. `speech.py` + `captions.py` — **Spelling vs speech** (`spelling`) and **Caption timing** (`timing`).
   faster-whisper `small`, int8 CPU, audio decoded by our ffmpeg to float32 (avoid PyAV decode).
   Normalise tokens (upper, strip punctuation, digits kept, $2,660 -> 2660; GONNA->GOING TO,
   WANNA->WANT TO, GOTTA->GOT TO, ALRIGHT->ALL RIGHT, OK->OKAY). Align caption tokens (captions in
   time order, from text elements in the caption band) to spoken tokens with SequenceMatcher.
   replace -> spelling? (similar >= .75) / number differs / different words; delete -> extra words on
   screen; insert of >= 3 non-filler words -> not captioned. All WARN (OCR can misread). Timing: caption
   start vs first matched word start: late > 0.5 s or early > 1.0 s -> WARN. No speech / no captions -> INFO.
   group(): merge OCR variants of one caption (same place, contiguous, text similarity >= .85); element
   text = most common reading.
2. `spec.py` — **Video spec** (`spec`) and **Sound** (`sound`). From ffmpeg: codec, size, fps, duration,
   audio stream, file size; loudness via ebur128 (integrated LUFS, true peak). Rules: width >= 1080 for
   9:16 (else WARN); fps 23.976-60; codec h264/hevc (else WARN); no audio -> WARN; > 4 GB -> FAIL (Meta);
   loudness -18..-11 LUFS (house rule; YouTube plays ~-14) else WARN; true peak > -1 dBTP -> WARN.
3. `readability.py` — **Hook** (`hook`) and **Readability** (`readability`), only if there: no text in the
   first 0.5 s -> INFO "no on-screen hook"; hook block on screen < 2.0 s -> WARN. Must-read text box height
   < 40 px -> WARN; contrast (luminance p90 vs p10 inside box, WCAG formula) < 3:1 -> WARN.
4. CLI: --no-speech, --whisper-model (small), --language. Report: "Other checks" section; findings
   "checks" list. Tests first for each; real Charley clip; blind prompt test; CI; deps: faster-whisper, numpy.
