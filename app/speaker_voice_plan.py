"""Source-bound dubbing voice groups without altering diarization labels.

A speaker embedding cosine score is not a calibrated probability. The 0.80
threshold only decides whether two source clusters share a *dub voice*.
Full-link merging avoids a transitive bridge that can turn two real people
into one voice merely because both sound similar to a third cluster.
"""
import hashlib
import json
import math

from app.text.cues import cue_speaker

DUB_VOICE_COSINE_THRESHOLD = 0.80
SUPPORTED_METRICS = frozenset(("camplus_cosine", "in_session_cosine"))
SILERO_RU_V56 = ("aidar", "baya", "kseniya", "xenia", "eugene")


def _speaker_clock(cues):
    """Identify the exact source-clock labels, not their editable transcripts."""
    return [
        {"start": cue["start"], "end": cue["end"], "speaker": cue_speaker(cue)}
        for cue in cues
    ]


def _clock_sha(cues):
    data = json.dumps(_speaker_clock(cues), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _ordered_speakers(cues):
    return list(dict.fromkeys(spk for c in cues if (spk := cue_speaker(c))))


def build_voice_plan(cues, similarities, threshold=DUB_VOICE_COSINE_THRESHOLD,
                     keep_distinct=(), presets=SILERO_RU_V56):
    """Assign stable Russian dubbing voice slots to source speaker clusters.

    Pairwise evidence is accepted only from within-session embedding cosine,
    not from a provider's uncalibrated 'probability' label. Distinct constraints
    always win, and adding C to {A,B} requires evidence for both A-C and B-C.
    """
    if not (isinstance(threshold, (int, float)) and math.isfinite(threshold)
            and -1 <= threshold <= 1):
        raise ValueError("invalid cosine threshold")
    speakers = _ordered_speakers(cues)
    known = set(speakers)
    ranks = {s: i for i, s in enumerate(speakers)}
    score_by_pair = {}

    for item in similarities:
        a, b = item["a"], item["b"]
        if a not in known or b not in known:
            raise ValueError("unknown source speaker in similarity input")
        if a == b:
            raise ValueError("same speaker cannot be its own similarity pair")
        if item.get("metric") not in SUPPORTED_METRICS:
            raise ValueError("similarity metric must be a supported cosine embedding")
        score = item["similarity"]
        if not (isinstance(score, (int, float)) and math.isfinite(score) and -1 <= score <= 1):
            raise ValueError("invalid speaker cosine similarity")
        key = frozenset((a, b))
        if key in score_by_pair and score_by_pair[key] != score:
            raise ValueError("conflicting speaker similarity evidence")
        score_by_pair[key] = float(score)

    forbidden = set()
    for pair in keep_distinct:
        if len(pair) != 2 or any(s not in known for s in pair):
            raise ValueError("unknown source speaker in keep_distinct")
        forbidden.add(frozenset(pair))

    groups = [[speaker] for speaker in speakers]
    merges = []
    candidates = sorted(
        ((score, *sorted(key, key=ranks.__getitem__)) for key, score in score_by_pair.items()),
        key=lambda row: (-row[0], ranks[row[1]], ranks[row[2]]),
    )
    for score, a, b in candidates:
        if score < threshold:
            break
        left = next(group for group in groups if a in group)
        right = next(group for group in groups if b in group)
        if left is right:
            continue
        crosses = [frozenset((x, y)) for x in left for y in right]
        if any(key in forbidden or score_by_pair.get(key, -1) < threshold for key in crosses):
            continue
        combined = sorted(left + right, key=ranks.__getitem__)
        groups = [group for group in groups if group is not left and group is not right] + [combined]
        groups.sort(key=lambda g: min(ranks[x] for x in g))
        merges.append({"a": a, "b": b, "similarity": score})

    if not presets or any(not isinstance(v, str) or not v for v in presets):
        raise ValueError("a non-empty ordered Russian voice palette is required")
    by_speaker = {}
    entries = []
    for index, group in enumerate(groups):
        group_id = "VOICE_%02d" % (index + 1)
        for spk in group:
            by_speaker[spk] = group_id
        entries.append({"id": group_id, "members": group, "preset": presets[index % len(presets)]})

    return {
        "version": 1,
        "source_clock_sha256": _clock_sha(cues),
        "similarity_metric": "embedding_cosine_not_probability",
        "threshold": threshold,
        "speaker_to_group": by_speaker,
        "groups": entries,
        "merges": merges,
    }


def apply_voice_groups(cues, plan):
    """Tag copies for TTS; original speaker identities remain immutable."""
    if plan["version"] != 1 or plan["source_clock_sha256"] != _clock_sha(cues):
        raise ValueError("speaker voice plan belongs to a different source diarization")
    mapping = plan["speaker_to_group"]
    result = []
    for cue in cues:
        row = dict(cue)
        spk = cue_speaker(cue)
        if spk:
            row["voice_group_id"] = mapping[spk]
        result.append(row)
    return result
