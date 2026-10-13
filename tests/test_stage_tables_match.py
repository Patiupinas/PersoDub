"""The two stage tables -- Python's and the UI's -- must stay in step.

The pipeline logs its progress as "N/6 …" lines and the UI parses them back
into a progress bar, so the ordered list of stages is a contract spanning two
languages. It used to be spelled out twice by hand (a dozen numbered literals
in app/pipeline.py, a regex plus two lookup tables in ui/src/dubApi.mjs), and
nothing noticed when one side changed. Each side now has exactly one table;
this test is the pin that stops them drifting.

How it reads the JS side: a regex over ui/src/dubApi.mjs's source text, not a
JS runtime. That is enough because the table is a literal array of literal
objects written one per line, which is also the only shape the regex accepts --
if someone builds the array some other way the regex finds nothing and this
test fails loudly rather than passing on an empty list. It deliberately does
NOT check the fields only one side uses (weights, floors, kind): those are the
UI's own arithmetic, and pinning them here would just be a second copy.
"""
import re
from pathlib import Path

from app.pipeline import STAGES, stage_marker

_JS = Path(__file__).resolve().parent.parent / "ui" / "src" / "dubApi.mjs"

# One row of the JS table: { name: "separate", label: "Separating audio", ... }
_ROW = re.compile(r'\{\s*name:\s*"([^"]+)",\s*label:\s*"([^"]+)"')


def _js_stages():
    """The (name, label) pairs of ui/src/dubApi.mjs's exported STAGES array."""
    src = _JS.read_text(encoding="utf-8")
    m = re.search(r"export const STAGES = \[(.*?)\];", src, re.S)
    assert m, "ui/src/dubApi.mjs no longer exports a STAGES array literal"
    return _ROW.findall(m.group(1))


def test_stage_names_and_labels_match_the_ui_table():
    assert _js_stages() == [(name, label) for name, label in STAGES]


def test_the_two_tables_are_the_same_length():
    # The length is what the "N/6" markers count up to on both sides, so this
    # is the assertion that actually breaks a half-finished seventh stage.
    assert len(_js_stages()) == len(STAGES)


def test_stage_marker_numbers_the_stages_from_one():
    markers = [stage_marker(name) for name, _label in STAGES]
    assert markers == [f"{i + 1}/{len(STAGES)}" for i in range(len(STAGES))]


def test_the_language_tables_match_on_both_sides():
    """dub_start refuses a code the backend does not know (config.LANGUAGE_NAMES);
    the page offers ui/src/dubApi.mjs LANGUAGES. One list on each side, pinned
    equal, so a language added to one never disappears from the other."""
    import os
    import re

    from app import config
    page = os.path.join(os.path.dirname(__file__), "..", "ui", "src", "dubApi.mjs")
    with open(page, encoding="utf-8") as f:
        block = f.read().split("export const LANGUAGES = [")[1].split("];")[0]
    codes = re.findall(r'code: "([a-z]+)"', block)
    assert codes == list(config.LANGUAGE_NAMES.keys()), (codes, list(config.LANGUAGE_NAMES))


# The percent arithmetic lives on both sides now (app/stages.py progress_of
# for the Dub Agent, ui/src/dubApi.mjs parseProgress for the screen), so the
# weights and floors are pinned too.
_NUM = re.compile(r'\{\s*name:\s*"([^"]+)".*?weight:\s*(\d+)(?:.*?floor:\s*(\d+))?')


def test_stage_weights_and_floors_match_the_ui_table():
    from app.stages import STAGE_FLOOR, STAGE_WEIGHT, VOICE_CAP
    src = _JS.read_text(encoding="utf-8")
    body = re.search(r"export const STAGES = \[(.*?)\];", src, re.S).group(1)
    for name, weight, floor in _NUM.findall(body):
        assert STAGE_WEIGHT[name] == int(weight), name
        assert STAGE_FLOOR.get(name) == (int(floor) if floor else None), name
    assert re.search(r"const VOICE_CAP = %d;" % VOICE_CAP, src)


def test_progress_of_reads_the_logs_the_way_the_screen_does():
    from app.stages import progress_of
    assert progress_of([]) == {"stage": 0, "label": "Waiting to start", "percent": 0}
    assert progress_of(["1/6 Separating…"])["percent"] == 3
    assert progress_of(["1/6 a", "2/6 b"]) == {"stage": 2, "label": "Transcribing", "percent": 18}
    mid = ["1/6 a", "2/6 b", "3/6 c", "4 dialogue lines prepared", "4/6 d",
           "   line 0: chose take 1", "   line 1: chose take 0"]
    assert progress_of(mid) == {"stage": 4, "label": "Dubbing", "percent": 75}
    assert progress_of(mid + ["5/6 e"])["percent"] == 96
    assert progress_of(mid + ["5/6 e", "6/6 f"])["percent"] == 97
    assert progress_of(["Uploading the video to Perso", "Perso is dubbing"])["percent"] == 55
