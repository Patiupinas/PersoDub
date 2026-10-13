"""The dubbing progress stages, and the "N/6" markers built from them.

A leaf module on purpose: it imports nothing from the app. The stage table is
needed both by the orchestrator (app/pipeline.py, which logs a marker at every
step) and by app/source_fetch.py, which only wants the "0/6" prefix for the
download it does before stage one. When the table lived in app/pipeline.py,
"download a video" pulled in the whole pipeline -- the TTS engine, the
diarizer, app/qwen_pipeline.py -- to obtain one short string, and inverted the
layering besides. Keeping it here means either side can have it for free.

This tuple is the ONLY place the "N/6" numbering lives: every stage log line is
built from a stage's position here, so inserting a stage renumbers all of them
at once instead of by hand in a dozen string literals.

The second field is the coarser label the UI shows for the stage. Neighbouring
stages that share a label are folded into one step of the progress bar there
(the last three all read as "Dubbing" to the user), so this field is the
contract with ui/src/dubApi.mjs's own STAGES table --
tests/test_stage_tables_match.py reads both and fails if the two drift apart.
"""

STAGES = (
    ("separate", "Separating audio"),
    ("transcribe", "Transcribing"),
    ("translate", "Translating"),
    ("synthesize", "Dubbing"),
    ("check", "Dubbing"),
    ("build", "Dubbing"),
)

_STAGE_NUMBER = {name: i + 1 for i, (name, _label) in enumerate(STAGES)}


def stage_marker(name: str) -> str:
    """The "N/6" prefix a stage's log lines start with, e.g. "3/6"."""
    return f"{_STAGE_NUMBER[name]}/{len(STAGES)}"


def pre_stage_marker() -> str:
    """The "0/6" prefix for progress logged before any stage above starts
    (e.g. fetching the source video)."""
    return f"0/{len(STAGES)}"


# The progress bar's arithmetic, the same as ui/src/dubApi.mjs parseProgress:
# each stage's share of the 100 percent, the floors the last two stages lift
# it to, and how much of the Dubbing step the per-line voice count fills.
# tests/test_stage_tables_match.py pins these numbers to the UI's, so the Dub
# Agent's percent (app/mcp_server.py get_job_status) is the screen's.
STAGE_WEIGHT = {"separate": 10, "transcribe": 25, "translate": 20, "synthesize": 45, "check": 0, "build": 0}
STAGE_FLOOR = {"check": 96, "build": 97}
VOICE_CAP = 40

_STEP_LABELS = [label for i, (_n, label) in enumerate(STAGES) if i == 0 or label != STAGES[i - 1][1]]
_STEP_OF = [_STEP_LABELS.index(label) + 1 for _n, label in STAGES]
_STEP_WEIGHT = [sum(STAGE_WEIGHT[n] for n, l in STAGES if l == label) for label in _STEP_LABELS]
_SYNTH_STEP = _STEP_OF[[n for n, _l in STAGES].index("synthesize")]


def progress_of(logs, line_count=None) -> dict:
    """{"stage", "label", "percent"} from a dub's log lines: the furthest
    "N/6" marker reached, folded into the steps the screen shows, with the
    voice lines counted inside the Dubbing step. A Perso cloud dub logs three
    phases of its own and reads 15 / 55 / 90."""
    import re
    cloud = 0
    for line in logs or []:
        l = str(line)
        if "Uploading the video to Perso" in l:
            cloud = max(cloud, 1)
        if "Perso is dubbing" in l:
            cloud = max(cloud, 2)
        if "Downloading the finished video" in l:
            cloud = max(cloud, 3)
    if cloud:
        return {"stage": cloud, "label": ["Uploading to Perso", "Dubbing at Perso", "Delivering"][cloud - 1],
                "percent": [15, 55, 90][cloud - 1]}
    marker = re.compile(r"^(\d)/%d\s" % len(STAGES))
    raw, voice_done, logged_total = 0, 0, None
    for line in logs or []:
        m = marker.match(str(line).strip())
        if m:
            raw = max(raw, int(m.group(1)))
        if re.match(r"^\s*line \d+: chose take", str(line)):
            voice_done += 1
        t = re.match(r"^\s*(\d+) dialogue lines prepared", str(line))
        if t:
            logged_total = int(t.group(1))
    stage = _STEP_OF[raw - 1] if raw else 0
    total = line_count or logged_total
    percent = sum(_STEP_WEIGHT[s - 1] for s in range(1, stage))
    if stage == _SYNTH_STEP and total:
        percent += round(VOICE_CAP * min(voice_done, total) / total)
    elif stage >= 1:
        percent += round(_STEP_WEIGHT[stage - 1] * 0.3)
    for name, _l in STAGES[:raw]:
        if name in STAGE_FLOOR:
            percent = max(percent, STAGE_FLOOR[name])
    return {"stage": stage, "label": _STEP_LABELS[stage - 1] if stage else "Waiting to start",
            "percent": percent}
