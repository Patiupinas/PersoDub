#!/usr/bin/env python3
"""Local CAM++ (campplus.onnx) speaker-diarization worker, run OUTSIDE the
app's Python 3.8 venv under a dedicated interpreter (see
app/diar_campplus_client.py, DIAR_PYTHON) -- same "heavy deps in a separate
process, talk over JSON" convention as app/scripts/demucs_separate.py
(app/separate.py, SEP_PYTHON) and app/scripts/qwen_score_takes.py
(app/qwen_scoring.py, QWEN_SCORER_PYTHON).

CAM++ has NO built-in VAD: it only embeds and labels the pre-existing cue
time-spans (start/end seconds) already produced by STT. Embeds each cue's
audio span (fbank80 + CMN + ONNX), clusters the embeddings (agglomerative,
cosine distance; k fixed or silhouette-estimated over k=2..4), and relabels
clusters by size using relabel_by_size -- pure logic imported from
app/diar_campplus_client.py so both sides share one source of truth.

Usage: python campplus_diarize.py --input job.json --output result.json
Input JSON: {"vocals_wav_path": "<wav path>", "cues": [{"start": float,
             "end": float}, ...], "num_speakers": int|null,
             "campplus_model": "<onnx path>"}
Output JSON: {"ok": true, "speakers": ["SPK0", "SPK1", ...]} (one label per
             input cue, same order) or {"ok": false, "error": "..."}. Prints
"__DIARIZE_DONE__" to stdout on success. Never raises past main(): any
failure is instead reported as {"ok": false, ...} with a non-zero exit code,
so the 3.8-side caller (app/diar_campplus_client.py) can turn it into a
clean RuntimeError for app/pipeline.py to catch and fall back on.
"""
import argparse
import json
import os
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")

# Make the repo root importable regardless of cwd, so we can reuse
# relabel_by_size from app/diar_campplus_client.py and the CAM++ embedding
# from campplus_embed_files.py instead of duplicating them.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from app.diar_campplus_client import relabel_by_size  # noqa: E402
from app.scripts.campplus_embed_files import SR, embed, lazy_imports, load_mono16k  # noqa: E402

K_MIN = 2
K_MAX = 4

# Auto-diarization can over-split a single narrator once the transcript has
# several cues (k=2..4 is always searched). Two clusters whose centroids are
# at least this alike are merged, pair by pair (_merge_alike). First
# calibrated on clean hand-cut 1.5-3s windows (same-speaker sim 0.88,
# cross-speaker sim 0.22), then lowered for real short/noisy Whisper cues
# (job 4ec68328, moon.mp4: one narrator in 3 clusters, sims 0.63/0.50/0.49).
# Measured 2026-10-04 on the Whisper cues of six clips (four with one
# speaker, two with two) and 40 mixes of two different men: the same voice's
# clusters were 0.54-0.84 alike once its sub-second cues were folded in,
# different men's at most 0.18 (whole clips) or 0.35 (one line). 0.30-0.35
# got all 40 mixes and the four one-speaker clips right (Shuka had been 4
# speakers and 2). The two-speaker clips stay one speaker, as they were:
# their two people came out 0.56-0.57 alike (Batman and the Joker, two
# Korean drama voices), as alike as one man's clusters -- no threshold
# tells those apart; Perso's transcript names them right.
DIAR_MERGE_SIM_DEFAULT = 0.35

# A cluster with less speech than this (seconds, all its cues together) is too
# little for its voice to be told apart: CAM++ on one 0.4 s cue put a Shuka
# line 0.31 away from the rest of him. It joins the voice it is closest to.
MIN_SPEECH_SEC = 1.0


def _parse_diar_merge_sim():
    """PERSODUB_DIAR_MERGE_SIM as a float; unset/invalid -> the default."""
    raw = os.environ.get("PERSODUB_DIAR_MERGE_SIM")
    if raw is None:
        return DIAR_MERGE_SIM_DEFAULT
    try:
        return float(raw)
    except ValueError:
        return DIAR_MERGE_SIM_DEFAULT


DIAR_MERGE_SIM = _parse_diar_merge_sim()


def _estimate_k(embs):
    """Auto-estimate speaker count over k=2..4 by silhouette (cosine)."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score
    from sklearn.metrics.pairwise import cosine_distances
    n = len(embs)
    if n < K_MIN + 1:
        return min(n, K_MIN)
    D = cosine_distances(embs)
    best_k, best_s = K_MIN, -2.0
    for k in range(K_MIN, min(K_MAX, n - 1) + 1):
        lab = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average"
        ).fit_predict(embs)
        s = silhouette_score(D, lab, metric="precomputed")
        if s > best_s:
            best_s, best_k = s, k
    return best_k


def _cluster(embs, k):
    """Agglomerative cosine clustering into k clusters -> list[int]."""
    from sklearn.cluster import AgglomerativeClustering
    return list(AgglomerativeClustering(
        n_clusters=k, metric="cosine", linkage="average"
    ).fit_predict(embs))


def _centroid(vecs, np):
    """Mean of a cluster's embeddings, L2-normalized (embeddings from embed
    are unit-norm, but the mean of several unit vectors is not)."""
    dim = len(vecs[0])
    mean = [sum(v[d] for v in vecs) / len(vecs) for d in range(dim)]
    norm = np.linalg.norm(mean) + 1e-9
    return [m / norm for m in mean]


def _merge_alike(embs, durs, labels, np, threshold):
    """Merge the clusters AUTO-estimation found back into the speakers they
    really are: a cluster with under MIN_SPEECH_SEC of speech joins the one
    its voice is closest to, then the two most alike clusters merge while
    their centroids are at least `threshold` alike. Pair by pair, not "every
    pair at once": one Shuka lecture came out as 4 speakers because a single
    pair of its clusters fell under the bar (2026-10-04)."""
    groups = {}
    for i, (e, d, lab) in enumerate(zip(embs, durs, labels)):
        g = groups.setdefault(lab, {"embs": [], "secs": 0.0, "members": []})
        g["embs"].append(e)
        g["secs"] += d
        g["members"].append(i)
    while len(groups) > 1:
        cents = {lab: _centroid(g["embs"], np) for lab, g in groups.items()}
        small = [lab for lab, g in groups.items() if g["secs"] < MIN_SPEECH_SEC]
        if small:
            a = min(small, key=lambda lab: groups[lab]["secs"])
            b = max((lab for lab in groups if lab != a), key=lambda lab: np.dot(cents[a], cents[lab]))
        else:
            pairs = [(x, y) for i, x in enumerate(groups) for y in list(groups)[i + 1:]]
            a, b = max(pairs, key=lambda p: np.dot(cents[p[0]], cents[p[1]]))
            if np.dot(cents[a], cents[b]) < threshold:
                break
        for key in ("embs", "members"):
            groups[b][key] += groups[a][key]
        groups[b]["secs"] += groups[a]["secs"]
        del groups[a]
    out = list(labels)
    for lab, g in groups.items():
        for i in g["members"]:
            out[i] = lab
    return relabel_by_size(out)


def _maybe_collapse(embs, durs, labels, num_speakers, k, np, threshold):
    """Merge an AUTO-estimated result back to its real speakers (see
    _merge_alike). A caller-supplied num_speakers always bypasses this --
    the user's override wins.
    """
    if num_speakers or k < 2:
        return labels
    return _merge_alike(embs, durs, labels, np, threshold)


def diarize(vocals_wav_path, cues, num_speakers, campplus_model):
    """Label each cue with a neutral speaker id using CAM++ embeddings.

    Returns a list of labels ("SPK0", "SPK1", ...), one per cue, same order.
    Ported from the pre-refactor in-process app/diar_campplus_client.py --
    logic unchanged, just parameterized to run standalone in this process.
    """
    np, ort, sf, torch, kaldi = lazy_imports()
    if not cues:
        return []

    sess = ort.InferenceSession(campplus_model, providers=["CPUExecutionProvider"])
    x = load_mono16k(vocals_wav_path, np, sf)

    valid_idx, embs, durs = [], [], []
    for i, c in enumerate(cues):
        a, b = int(float(c["start"]) * SR), int(float(c["end"]) * SR)
        seg = x[a:b]
        if len(seg) <= 0:
            continue
        valid_idx.append(i)
        embs.append(embed(seg, sess, np, torch, kaldi))
        durs.append(len(seg) / SR)

    if len(valid_idx) < 2:
        return ["SPK0"] * len(cues)

    embs = np.array(embs)
    k = int(num_speakers) if num_speakers else _estimate_k(embs)
    k = max(1, min(k, len(valid_idx)))
    raw = _cluster(embs, k) if k > 1 else [0] * len(valid_idx)
    labels = relabel_by_size(raw)
    labels = _maybe_collapse(embs, durs, labels, num_speakers, k, np, DIAR_MERGE_SIM)

    out = [None] * len(cues)
    for pos, i in enumerate(valid_idx):
        out[i] = labels[pos]
    # Empty/degenerate spans (no embedding) inherit the majority speaker.
    majority = Counter(labels).most_common(1)[0][0]
    for i in range(len(out)):
        if out[i] is None:
            out[i] = majority
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    try:
        with open(a.input, encoding="utf-8") as f:
            payload = json.load(f)
        speakers = diarize(
            payload["vocals_wav_path"], payload.get("cues") or [],
            payload.get("num_speakers"),
            payload.get("campplus_model") or "models/campplus/campplus.onnx",
        )
        result = {"ok": True, "speakers": speakers}
    except Exception as e:
        result = {"ok": False, "error": str(e)[:500]}
        with open(a.output, "w", encoding="utf-8") as f:
            json.dump(result, f)
        print("__DIARIZE_ERROR__ %s" % str(e)[:200], file=sys.stderr)
        sys.exit(1)

    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print("__DIARIZE_DONE__")


if __name__ == "__main__":
    main()
