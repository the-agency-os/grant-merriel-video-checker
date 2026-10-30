from pathlib import Path

from video_checker import captions
from video_checker.captions import Word
from video_checker.judge import Element
from video_checker.zones import Rect

CAPTION_BOX = Rect(150, 1130, 930, 1210)


def cap(i, text, start, end, box=CAPTION_BOX):
    return Element(f"t{i}", "text", text, start, end, box, 1.0, Path("f.png"))


def said(text, start=0.0, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append(Word(w, t, t + step * 0.9))
        t += step
    return out


def run(caps, words):
    issues, stats = captions.compare(caps, words)
    return issues, stats


def kinds(issues):
    return [i.kind for i in issues]


def test_exact_captions_have_no_issues():
    caps = [cap(1, "SO THIS MORNING,", 0.0, 1.2), cap(2, "I HAD A NEW LEAD", 1.2, 2.8)]
    issues, stats = run(caps, said("So this morning, I had a new lead"))
    assert issues == [] and stats["matched"] == 1.0
    assert captions.spelling_check(issues, stats).status == "PASS"


def test_misspelling_is_flagged():
    caps = [cap(1, "EFFECTIVELY SPECIALSING IN", 0.0, 1.2)]
    issues, _ = run(caps, said("effectively specialising in"))
    assert kinds(issues) == ["spelling"] and issues[0].shown == "SPECIALSING"


def test_wrong_number_is_flagged():
    caps = [cap(1, "COSTING THEM $2,600 A MONTH", 0.0, 2.0)]
    issues, _ = run(caps, said("costing them $2,660 a month"))
    assert kinds(issues) == ["number"] and issues[0].shown == "2600" and issues[0].said == "2660"


def test_spoken_contractions_match_written_forms():
    caps = [cap(1, "ALRIGHT, AGENCY OWNERS,", 0.0, 1.2), cap(2, "I'M GOING TO", 1.2, 2.4)]
    issues, _ = run(caps, said("All right, agency owners, I'm gonna"))
    assert issues == []


def test_three_uncaptioned_words_flag_but_fillers_do_not():
    caps = [cap(1, "THIS HAS TO END", 0.0, 1.6), cap(2, "THIS HAS TO STOP", 3.6, 5.2)]
    issues, _ = run(caps, said("this has to end and nobody talks about it this has to stop", 0.0))
    assert kinds(issues) == ["missing"] and "nobody talks about it" in issues[0].said.lower()
    issues, _ = run(
        caps[:1] + [cap(2, "THIS HAS TO STOP", 2.0, 3.6)],
        said("this has to end um uh this has to stop"),
    )
    assert issues == []


def test_late_caption_is_flagged():
    caps = [cap(1, "SO THIS MORNING,", 1.4, 2.4)]
    issues, _ = run(caps, said("So this morning,", 0.6))
    assert kinds(issues) == ["late"]
    assert captions.timing_check(issues, {"captions": 1}).status == "WARN"


def test_text_that_is_never_spoken_is_not_a_caption():
    hook = cap(1, "THE INDUSTRY BURNED YOUR NEXT CLIENT", 0.0, 5.0, Rect(120, 240, 950, 310))
    caps = [hook, cap(2, "SO THIS MORNING,", 0.0, 1.2)]
    issues, stats = run(caps, said("So this morning,"))
    assert issues == [] and stats["captions"] == 1


def test_no_speech_and_no_captions_are_info():
    assert captions.spelling_check([], {"spoken": 0, "captions": 3, "matched": 0}).status == "INFO"
    assert captions.spelling_check([], {"spoken": 9, "captions": 0, "matched": 0}).status == "INFO"


def test_hook_words_spoken_later_do_not_make_it_a_caption():
    hook = cap(1, "YOUR NEXT CLIENT", 0.0, 5.0, Rect(120, 240, 950, 310))
    caps = [hook, cap(2, "SO THIS MORNING,", 0.0, 1.2)]
    words = said("So this morning,") + said("your next client is waiting", 10.0)
    issues, stats = run(caps, words)
    assert stats["captions"] == 1 and "extra" not in kinds(issues)


def test_second_line_of_a_two_line_caption_is_not_timed():
    caps = [
        cap(1, "OWNER, RIGHT,", 0.0, 2.0, Rect(150, 1088, 930, 1160)),
        cap(2, "THEY'RE", 0.0, 2.0, Rect(300, 1167, 700, 1241)),
    ]
    words = [Word("owner,", 0.0, 0.4), Word("right,", 0.5, 0.9), Word("they're", 1.3, 1.6)]
    issues, _ = run(caps, words)
    assert issues == []


def test_reader_mangled_word_is_flagged_as_possible_misread():
    caps = [cap(1, "THAD A NEW LEAD", 0.0, 1.6)]
    issues, _ = run(caps, said("I had a new lead"))
    assert kinds(issues) == ["spelling"] and "text reader" in issues[0].note
