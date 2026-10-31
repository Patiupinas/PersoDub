"""Validate and score a bounded corpus-labeled audio tagging research pilot.

Keep source event type, speech emotion and vocal technique as separate axes.
Clip-level source labels are not human-verified event boundaries. This module
must never generate A1 gold or A4 dubbing decisions.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

AUDIO_GROUPS = frozenset((
    "speech", "singing", "laughing", "crying_baby", "coughing", "sneezing",
    "breathing",
))
EMOTIONS_SUPPORTED = frozenset(("neutral", "happy", "sad", "angry"))
DATASETS = frozenset((
    "ESC-50", "NUS-48E", "VocalSet-subset", "RAVDESS-speech",
))
_SHA_SIZE = 64


class AudioTagBenchmarkError(ValueError):
    """Source, model prediction or benchmark contract is inconsistent."""


def _object(obj, keys, where):
    if type(obj) is not dict or set(obj) != set(keys):
        raise AudioTagBenchmarkError(f"{where}: unexpected or missing fields")
    return obj


def _sha(value, where):
    if (
        type(value) is not str or len(value) != _SHA_SIZE
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise AudioTagBenchmarkError(f"{where}: invalid SHA-256")
    return value


def _integer(value, where, minimum=0):
    if type(value) is not int or value < minimum:
        raise AudioTagBenchmarkError(f"{where}: invalid integer")
    return value


def _text(value, where):
    if type(value) is not str or not value.strip():
        raise AudioTagBenchmarkError(f"{where}: expected nonempty string")
    return value


def _probability(value, where):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise AudioTagBenchmarkError(f"{where}: invalid model score")
    return value


def _canonical_sha(obj):
    canonical = json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _ground_event_group(source):
    category, label = source["dataset"], source["dataset_label"]
    if category == "ESC-50":
        if label not in AUDIO_GROUPS - {"speech", "singing"}:
            raise AudioTagBenchmarkError("ESC-50 label is outside selected group ontology")
        return label
    if category == "NUS-48E":
        if label not in ("read", "sing"):
            raise AudioTagBenchmarkError("NUS read/sing pair has invalid label")
        return "speech" if label == "read" else "singing"
    if category == "VocalSet-subset":
        if label not in ("scale", "passagio"):
            raise AudioTagBenchmarkError("VocalSet clip lacks supported technique annotation")
        return "singing"
    if category == "RAVDESS-speech":
        if label not in (
            "neutral", "calm", "happy", "sad", "angry", "fearful",
            "disgusted", "surprised",
        ):
            raise AudioTagBenchmarkError("RAVDESS emotion label is not in its publisher ontology")
        return "speech"
    raise AudioTagBenchmarkError("unrecognized source dataset")


def _validate_sources(sources):
    expected = {
        "schema_version", "artifact_kind", "selection_policy",
        "source_revisions", "esc50_original_csv_sha256",
        "dataset_license", "annotation_scope", "clips",
    }
    _object(sources, expected, "sources")
    if sources["schema_version"] != 1 or (
        sources["artifact_kind"] != "frozen_independent_publisher_clip_labels"
    ):
        raise AudioTagBenchmarkError("source schema not recognized")
    _text(sources["annotation_scope"], "annotation_scope")
    _sha(sources["esc50_original_csv_sha256"], "esc50_original_csv_sha256")
    if not isinstance(sources["source_revisions"], dict):
        raise AudioTagBenchmarkError("missing source revisions")
    for val in sources["source_revisions"].values():
        if type(val) is not str or len(val) != 40 or any(c not in "0123456789abcdef" for c in val):
            raise AudioTagBenchmarkError("source commit revision must be a 40-character Git SHA")
    if not isinstance(sources["dataset_license"], dict) or (
        set(sources["dataset_license"]) != DATASETS
    ):
        raise AudioTagBenchmarkError("corpus terms missing")
    if type(sources["clips"]) is not list or len(sources["clips"]) != 32:
        raise AudioTagBenchmarkError("this frozen pilot requires exactly 32 source clips")
    lookup = {}
    for item in sources["clips"]:
        if type(item) is not dict or any(field in item for field in ("local_path", "action", "human_gold")):
            raise AudioTagBenchmarkError("unportable or forbidden source field")
        dataset = item.get("dataset")
        if dataset not in DATASETS:
            raise AudioTagBenchmarkError("unsupported selected dataset")
        key = dataset + "::" + _text(item.get("path"), "source.path")
        if item.get("id") != key or key in lookup:
            raise AudioTagBenchmarkError("source identity collision")
        _text(item.get("dataset_label"), "dataset_label")
        _ground_event_group(item)
        _sha(item.get("wav_sha256"), "wav_sha256")
        _integer(item.get("wav_bytes"), "wav_bytes", 1)
        url = _text(item.get("url"), "url")
        if not url.startswith("https://"):
            raise AudioTagBenchmarkError("not a pinned remote source")
        if item.get("label_scope") != "clip":
            raise AudioTagBenchmarkError("publisher labels are clip-level")
        if dataset == "NUS-48E":
            _sha(item.get("annotation_sha256"), "NUS manual alignment")
            if not str(item.get("annotation_url", "")).startswith("https://"):
                raise AudioTagBenchmarkError("NUS original annotation link missing")
        lookup[key] = item
    return lookup


def _scores(row, ontology):
    if type(row) is not dict or set(row) != ontology:
        raise AudioTagBenchmarkError("score vector does not match model ontology")
    for k, v in row.items():
        _probability(v, f"score.{k}")
    return sorted(row, key=lambda k: -row[k])


def _check_model_provenance(provenance):
    if type(provenance) is not dict or set(provenance) != {"ast", "sensevoice", "emotion"}:
        raise AudioTagBenchmarkError("model identities are missing")
    for name, details in provenance.items():
        if type(details) is not dict:
            raise AudioTagBenchmarkError("missing model provenance")
        _sha(details.get("weights_sha256"), name + ".weights_sha256")
        _text(details.get("revision"), name + ".revision")
        _text(details.get("id"), name + ".id")
    ast = provenance["ast"]["ontology"]
    if type(ast) is not dict or set(ast) != AUDIO_GROUPS:
        raise AudioTagBenchmarkError("AST class groups have changed")
    if any(type(v) not in (list, tuple) or not v for v in ast.values()):
        raise AudioTagBenchmarkError("AST class group has no AudioSet labels")
    event_tags = provenance["sensevoice"]["event_tag_to_group"]
    if type(event_tags) is not dict or not set(event_tags.values()) <= AUDIO_GROUPS:
        raise AudioTagBenchmarkError("SenseVoice event conversion is inconsistent")
    if set(provenance["emotion"]["ontology"]) != EMOTIONS_SUPPORTED:
        raise AudioTagBenchmarkError("emotion class ontology changed")
    return event_tags


def score_audio_tag_pilot(sources, evidence):
    """Compare only original source clip labels; preserve separate task axes."""
    lookup = _validate_sources(sources)
    expected_root = {
        "schema_version", "artifact_kind", "source_manifest_canonical_sha256",
        "model_provenance", "ast_predictions", "sensevoice_predictions",
        "emotion_predictions", "unreviewed_navy_timeline",
        "no_automatic_dubbing_actions",
    }
    _object(evidence, expected_root, "evidence")
    if evidence["schema_version"] != 1 or evidence["artifact_kind"] != (
        "frozen_real_automatic_audio_annotation_pilot"
    ):
        raise AudioTagBenchmarkError("unexpected evidence schema")
    if evidence["no_automatic_dubbing_actions"] is not True:
        raise AudioTagBenchmarkError("benchmark must not produce dubbing actions")
    if _sha(evidence["source_manifest_canonical_sha256"], "source manifest") != _canonical_sha(sources):
        raise AudioTagBenchmarkError("source manifest identity differs")
    mapping = _check_model_provenance(evidence["model_provenance"])
    primary = [k for k, v in lookup.items() if v["dataset"] != "RAVDESS-speech" or
               v.get("actor") not in ("07", "08")]
    # The emotional addendum actors must not accidentally become extra AST/SenseVoice trials.
    if len(primary) != 24:
        raise AudioTagBenchmarkError("original pilot set identity changed")
    results = {}
    misses = {}
    ast_crops = {}
    for backend, field in (("AST", "ast_predictions"), ("SenseVoice", "sensevoice_predictions")):
        entries = evidence[field]
        if type(entries) is not list or len(entries) != 24:
            raise AudioTagBenchmarkError(f"{backend}: pilot source count changed")
        seen = set()
        by_dataset = Counter()
        matched = Counter()
        wrong = []
        for r in entries:
            if type(r) is not dict:
                raise AudioTagBenchmarkError(f"{backend}: invalid prediction row")
            expected_row_fields = (
                {"source_id", "wav_sha256", "crop_start_seconds", "crop_end_seconds",
                 "category_scores", "category_ranking", "top_labels", "inference_seconds"}
                if backend == "AST" else
                {"source_id", "wav_sha256", "crop_start_seconds", "crop_end_seconds",
                 "audio_event_tags", "recognized_groups", "inference_seconds"}
            )
            _object(r, expected_row_fields, f"{backend}.prediction")
            source_id = r.get("source_id")
            if source_id not in primary or source_id in seen:
                raise AudioTagBenchmarkError(f"{backend}: missing/duplicated/unselected source")
            seen.add(source_id)
            source = lookup[source_id]
            if r.get("wav_sha256") != source["wav_sha256"]:
                raise AudioTagBenchmarkError(f"{backend}: source content identity mismatch")
            a, b = r.get("crop_start_seconds"), r.get("crop_end_seconds")
            if type(a) not in (int,float) or type(b) not in (int,float) or not math.isfinite(a+b) or not 0 <= a < b <= 600:
                raise AudioTagBenchmarkError(f"{backend}: crop clock invalid")
            elapsed = r["inference_seconds"]
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise AudioTagBenchmarkError(f"{backend}: invalid runtime")
            if backend == "AST":
                ast_crops[source_id] = (a, b)
                if type(r["top_labels"]) is not list or not 1 <= len(r["top_labels"]) <= 12:
                    raise AudioTagBenchmarkError("AST top-label evidence missing")
                for label in r["top_labels"]:
                    _object(label, {"label", "score"}, "ast.top_label")
                    _text(label["label"], "ast.top_label.label")
                    _probability(label["score"], "ast.top_label.score")
            elif ast_crops.get(source_id) != (a, b):
                raise AudioTagBenchmarkError("A/B model input crop differs")
            gold = _ground_event_group(source)
            if backend == "AST":
                best = _scores(r.get("category_scores"), AUDIO_GROUPS)
                if r.get("category_ranking") != best:
                    raise AudioTagBenchmarkError("AST category ranking is inconsistent with logits")
                match = best[0] == gold
            else:
                tags = r.get("audio_event_tags")
                groups = r.get("recognized_groups")
                if type(tags) is not list or any(type(x) is not str for x in tags):
                    raise AudioTagBenchmarkError("SenseVoice raw event tags missing")
                if type(groups) is not list or groups != sorted({mapping[t] for t in tags if t in mapping}):
                    raise AudioTagBenchmarkError("SenseVoice event conversion inconsistent")
                match = gold in groups
            by_dataset[source["dataset"]] += 1
            matched[source["dataset"]] += bool(match)
            if not match:
                wrong.append({"source_id":source_id, "expected":gold})
        if set(seen) != set(primary):
            raise AudioTagBenchmarkError("missing source from matched A/B benchmark")
        results[backend] = {
            "correct":sum(matched.values()), "total":len(primary),
            "correct_by_dataset":{k:{"correct":matched[k],"total":by_dataset[k]}
                                  for k in sorted(by_dataset)},
        }
        misses[backend] = wrong

    emotions = evidence["emotion_predictions"]
    if type(emotions) is not list or len(emotions) != 14:
        raise AudioTagBenchmarkError("RAVDESS emotion selection changed")
    seen_emotions = set()
    per_emotion = Counter()
    emotion_matched = Counter()
    ineligible = []
    for row in emotions:
        if type(row) is not dict:
            raise AudioTagBenchmarkError("emotion prediction must be an object")
        _object(row, {
            "source_id", "wav_sha256", "ground_truth_emotion",
            "predicted_emotion", "emotion_supported",
            "emotion_probabilities", "inference_seconds",
        }, "emotion.prediction")
        duration = row["inference_seconds"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise AudioTagBenchmarkError("emotion runtime invalid")
        identifier = row.get("source_id")
        if identifier not in lookup or lookup[identifier]["dataset"] != "RAVDESS-speech" or identifier in seen_emotions:
            raise AudioTagBenchmarkError("emotion source identity duplicate or invalid")
        seen_emotions.add(identifier)
        source = lookup[identifier]
        if row.get("wav_sha256") != source["wav_sha256"]:
            raise AudioTagBenchmarkError("emotion source WAV identity mismatch")
        target = source["dataset_label"]
        if row.get("ground_truth_emotion") != target:
            raise AudioTagBenchmarkError("emotion was compared to an invented label")
        is_supported = target in EMOTIONS_SUPPORTED
        if type(row.get("emotion_supported")) is not bool or row["emotion_supported"] != is_supported:
            raise AudioTagBenchmarkError("unsupported emotions must not enter denominator")
        ranking = _scores(row.get("emotion_probabilities"), EMOTIONS_SUPPORTED)
        if not abs(sum(row["emotion_probabilities"].values()) - 1) < 0.0002:
            raise AudioTagBenchmarkError("emotion distribution must be normalized")
        if row.get("predicted_emotion") != ranking[0]:
            raise AudioTagBenchmarkError("emotion label disagrees with model scores")
        if is_supported:
            per_emotion[target] += 1
            emotion_matched[target] += row["predicted_emotion"] == target
        else:
            ineligible.append(identifier)
    if sum(per_emotion.values()) != 12 or set(per_emotion.values()) != {3}:
        raise AudioTagBenchmarkError("the balanced four-emotion benchmark changed")
    _validate_timeline(evidence["unreviewed_navy_timeline"])
    return {
        "schema_version":1,
        "status":"research_clip_level_scores_and_unreviewed_timeline",
        "source_manifest_canonical_sha256":_canonical_sha(sources),
        "event_group_scores":results,
        "event_group_misses":misses,
        "acted_speech_emotion":{
            "correct":sum(emotion_matched.values()),
            "eligible":sum(per_emotion.values()),
            "by_emotion":{k:{"correct":emotion_matched[k],"total":per_emotion[k]}
                          for k in sorted(per_emotion)},
            "out_of_ontology_excluded":ineligible,
        },
        "unreviewed_navy_windows":len(evidence["unreviewed_navy_timeline"]["windows"]),
        "human_segment_level_accuracy":None,
        "vocal_technique_accuracy":None,
        "no_automatic_dubbing_actions":True,
    }


def _validate_timeline(timeline):
    expected = {
        "source_name", "source_wav_sha256", "source_offset_samples",
        "sample_rate", "total_samples", "window_samples", "stride_samples",
        "status", "windows",
    }
    _object(timeline, expected, "timeline")
    if timeline["source_wav_sha256"] != (
        "d409c8994bf9aa05e05e1ba1ec6bfde9e19e000ad33de34224c9136bbc9afc43"
    ):
        raise AudioTagBenchmarkError("unrelated vocal lesson derivative")
    for key, val in (
        ("source_offset_samples", 960000), ("sample_rate",16000),
        ("total_samples",960000), ("window_samples",64000),
        ("stride_samples",32000),
    ):
        if type(timeline[key]) is not int or timeline[key] != val:
            raise AudioTagBenchmarkError("timeline source clock does not match A1")
    if "unreviewed" not in timeline["status"]:
        raise AudioTagBenchmarkError("machine timeline cannot become human gold")
    windows = timeline["windows"]
    if type(windows) is not list or len(windows) != 29:
        raise AudioTagBenchmarkError("window count or time grid changed")
    for i, row in enumerate(windows):
        if type(row) is not dict or set(row) != {
            "start_sample", "end_sample", "scores", "top_categories",
        }:
            raise AudioTagBenchmarkError("unexpected time window fields")
        start = 960000 + i * 32000
        if (
            type(row["start_sample"]) is not int or row["start_sample"] != start
            or type(row["end_sample"]) is not int or row["end_sample"] != start + 64000
        ):
            raise AudioTagBenchmarkError("model timestamp differs from source PCM")
        ranks = _scores(row["scores"], AUDIO_GROUPS)
        if row["top_categories"] != ranks[:3]:
            raise AudioTagBenchmarkError("time series scores disagree with category rankings")


def main(argv=None):
    parser=argparse.ArgumentParser(description="Score preselected, source-hashed audio model predictions")
    parser.add_argument("--sources",type=Path,required=True)
    parser.add_argument("--observations",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    if args.out.exists() or args.out.resolve() in {
        args.sources.resolve(), args.observations.resolve(),
    }:
        parser.error("output must be new and distinct from input")
    try:
        report=score_audio_tag_pilot(
            json.loads(args.sources.read_text(encoding="utf-8")),
            json.loads(args.observations.read_text(encoding="utf-8")),
        )
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2,f"benchmark rejected: {exc}\n")
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"Frozen pilot report: {args.out}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
