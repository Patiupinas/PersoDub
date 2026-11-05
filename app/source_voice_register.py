"""Source-clock-bound speech register routing for fixed Russian TTS presets.

Never select female/male-sounding speech solely from the ordinal diarization
label. An explicit source cue or local reviewed override takes precedence over
a conservative, bounded speech-only pitch probe.
"""
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from app.config import DIAR_PYTHON
from app.text.cues import cue_speaker

WORKER = Path(__file__).parent / "scripts" / "source_voice_register.py"
OVERRIDES = "russian_voice_register_overrides.json"
RECEIPT = "russian_source_voice_registers.json"
ALLOWED = frozenset(("male", "female"))


def _validated_overrides(path, speakers):
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (type(data) is not dict or set(data) != {"version", "speaker_to_register"}
            or data["version"] != 1
            or type(data["speaker_to_register"]) is not dict
            or any(key not in speakers or value not in ALLOWED
                   for key, value in data["speaker_to_register"].items())):
        raise ValueError("Invalid source voice register override: expected reviewed male/female per group")
    return data["speaker_to_register"]


def _source_cue_registers(source_cues, speakers):
    result = {}
    for cue in source_cues:
        speaker = cue_speaker(cue)
        if speaker not in speakers:
            continue
        label = cue.get("source_voice_register")
        if label is None:
            continue
        if label not in ALLOWED or (speaker in result and result[speaker] != label):
            raise ValueError("Conflicting source voice register labels for one speaker")
        result[speaker] = label
    return result


def _bounded_samples(source_cues, selected, speakers):
    samples = {}
    for speaker in speakers:
        eligible = []
        for cue in source_cues:
            if cue_speaker(cue) != speaker:
                continue
            first, last = cue.get("start"), cue.get("end")
            if not (type(first) in (int, float) and type(last) in (int, float)
                    and math.isfinite(first) and math.isfinite(last) and first >= 0
                    and last - first >= 2.0):
                continue
            # Probe only the portion actually selected for translated speech.
            # A source subtitle can also encompass a protected singing interval.
            for translated in selected:
                approved_start = max(first, translated["start"])
                approved_end = min(last, translated["end"])
                if approved_end - approved_start < 2.0:
                    continue
                start = round(approved_start + 0.15, 3)
                end = round(min(approved_end - 0.12, start + 5.5), 3)
                if end - start >= 1.5:
                    eligible.append({"start": start, "end": end})
        samples[speaker] = sorted(eligible, key=lambda row: row["start"])[:3]
    return samples


def resolve_source_voice_registers(vocals_path, source_cues, selected, speakers, work_dir, log):
    """Return {voice_group: male|female}; persist the evidence before synthesis."""
    speakers = list(dict.fromkeys(speakers))
    if not speakers:
        return {}
    work = Path(work_dir)
    overrides = _validated_overrides(work / OVERRIDES, set(speakers))
    labelled = _source_cue_registers(source_cues, set(speakers))
    chosen = dict(labelled, **overrides)
    evidence = {name: {"register": register, "method": (
        "reviewed_override" if name in overrides else "source_cue_label"
    )} for name, register in chosen.items()}
    remaining = [speaker for speaker in speakers if speaker not in chosen]

    if remaining:
        selections = _bounded_samples(source_cues, selected, remaining)
        missing = [speaker for speaker, spans in selections.items() if not spans]
        if missing:
            raise ValueError("No approved source speech spans for Russian voice register: "
                             + ", ".join(missing) + ". Supply reviewed voice register overrides.")
        payload = {"vocals_wav_path": str(vocals_path), "samples": selections}
        try:
            with tempfile.TemporaryDirectory(prefix="persodub-register-") as temp:
                input_path, output_path = Path(temp) / "input.json", Path(temp) / "output.json"
                input_path.write_text(json.dumps(payload), encoding="utf-8")
                run = subprocess.run(
                    [DIAR_PYTHON, str(WORKER), "--input", str(input_path),
                     "--output", str(output_path)],
                    text=True, capture_output=True, timeout=max(90, 50 * len(remaining)),
                )
                if run.returncode != 0:
                    raise RuntimeError("Speech register probe failed: " + run.stderr[-180:])
                measured = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError("Speech register probe is unavailable; provide a reviewed "
                               "male/female voice register override") from error
        if measured.get("version") != 1 or set(measured.get("speakers", {})) != set(remaining):
            raise ValueError("Speech register probe returned incomplete speaker evidence")
        for speaker in remaining:
            row = measured["speakers"][speaker]
            register = row.get("register")
            evidence[speaker] = dict(row, method="source_speech_pitch")
            if register not in ALLOWED:
                # Do not silently assign a female voice just because VOICE_01
                # was previously first in a fixed palette.
                _save_report(work, evidence)
                raise ValueError(
                    "Source speaking register could not be distinguished for "
                    + speaker + "; provide a reviewed male/female voice register override"
                )
            chosen[speaker] = register

    _save_report(work, evidence)
    for speaker in speakers:
        log("   source speaking register %s: %s (%s)" % (
            speaker, chosen[speaker], evidence[speaker]["method"]
        ))
    return {speaker: chosen[speaker] for speaker in speakers}


def _save_report(work, evidence):
    work.mkdir(parents=True, exist_ok=True)
    path = work / RECEIPT
    part = work / (RECEIPT + ".part")
    part.write_text(json.dumps({"version": 1, "speakers": evidence},
                               ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(part, path)
