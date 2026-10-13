"""Auto speaker-count estimation over-splits single-narrator audio: k=2..4 is
always searched, so a single speaker with several transcript cues gets >=2
phantom speakers. _merge_alike() catches this after the fact: a cluster with
under a second of speech joins the voice it is closest to, then the two most
alike clusters merge while their centroids are at least a threshold alike.
_maybe_collapse() wires that into the AUTO path only -- an explicit
num_speakers always bypasses it.

Same stub/injection pattern as tests/test_campplus_input_name.py -- none of
the heavy deps (numpy, onnxruntime, torch, sklearn) live in the app venv
that runs this suite, so a small FakeNp stands in for the two numpy calls
_merge_alike actually needs (linalg.norm, dot).
"""
import importlib.util
import math
import os

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "scripts", "campplus_diarize.py",
)
_spec = importlib.util.spec_from_file_location("campplus_diarize", SCRIPT)
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


class _FakeLinalg:
    @staticmethod
    def norm(v):
        return math.sqrt(sum(x * x for x in v))


class FakeNp:
    linalg = _FakeLinalg

    @staticmethod
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))


def _unit(angle_deg):
    r = math.radians(angle_deg)
    return [math.cos(r), math.sin(r)]


def _three_vectors_with_pairwise_sims(sim_ab, sim_ac, sim_bc):
    """Three unit vectors a/b/c whose pairwise cosine similarities are
    exactly sim_ab/sim_ac/sim_bc. Three independent pairwise constraints
    don't fit in 2D (fixing a-b and a-c leaves b-c fully determined by the
    other two, not free), so this solves the 3x3 Gram system in 3D: place a
    and b in the xy-plane at the given angle, then solve c's three
    coordinates from its two dot-product constraints plus unit length."""
    a = [1.0, 0.0, 0.0]
    b = [sim_ab, math.sqrt(1 - sim_ab ** 2), 0.0]
    c0 = sim_ac
    c1 = (sim_bc - sim_ab * c0) / b[1]
    c2 = math.sqrt(max(0.0, 1 - c0 ** 2 - c1 ** 2))
    return a, b, [c0, c1, c2]


def _merge(embs, labels, threshold, durs=None):
    return cd._merge_alike(embs, durs or [3.0] * len(embs), labels, FakeNp, threshold)


# --- _merge_alike: centroid similarity, pair by pair ------------------------

def test_near_identical_centroids_merge():
    a = [1.0, 0.0]
    b = [0.99, math.sqrt(1 - 0.99 ** 2)]  # cosine similarity ~0.99
    assert _merge([a, b], ["SPK0", "SPK1"], 0.65) == ["SPK0", "SPK0"]


def test_clearly_separated_centroids_stay_apart():
    a = [1.0, 0.0]
    b = [0.2, math.sqrt(1 - 0.2 ** 2)]  # cosine similarity exactly 0.2
    assert _merge([a, b], ["SPK0", "SPK1"], 0.65) == ["SPK0", "SPK1"]


def test_three_clusters_all_pairwise_above_threshold_merge():
    # pairwise cosines: cos15=0.966, cos15=0.966, cos30=0.866 -- all >= 0.65
    embs = [_unit(0), _unit(15), _unit(30)]
    assert _merge(embs, ["SPK0", "SPK1", "SPK2"], 0.65) == ["SPK0"] * 3


def test_one_pair_under_the_bar_no_longer_keeps_a_speaker_split():
    """The Shuka lecture (2026-10-04): every cluster was its neighbour's
    voice, but one pair of them fell under the bar, and "every pair at once"
    left one man as 4 speakers. A with B and B with C are 0.6 alike, A with
    C only 0.3: merged pair by pair, A+B is 0.5 alike with C."""
    a, b, c = _three_vectors_with_pairwise_sims(0.6, 0.30, 0.6)
    assert _merge([a, b, c], ["SPK0", "SPK1", "SPK2"], 0.35) == ["SPK0"] * 3


def test_a_far_voice_stays_its_own_speaker():
    # 0 and 15 merge (0.966); their centroid at 7.5 is cos 72.5 = 0.30 from 80.
    out = _merge([_unit(0), _unit(15), _unit(80)], ["SPK0", "SPK1", "SPK2"], 0.65)
    assert out[0] == out[1] != out[2]
    assert len(set(out)) == 2


def test_centroid_is_the_mean_not_a_single_embedding():
    # cluster A: two embeddings symmetric around angle 0 (+/-80 deg) average
    # to angle 0 exactly; cluster B sits right at angle 0. A buggy
    # "centroid = first embedding" implementation would see 80 degrees apart
    # (cos ~= 0.17) and refuse to merge; the correct mean-based centroid
    # sees a perfect match.
    embs = [_unit(80), _unit(-80), _unit(0)]
    assert _merge(embs, ["SPK0", "SPK0", "SPK1"], 0.99) == ["SPK0"] * 3


def test_single_label_is_left_as_it_is():
    embs = [[1.0, 0.0], [0.0, 1.0]]  # unrelated directions, doesn't matter
    assert _merge(embs, ["SPK0", "SPK0"], 0.99) == ["SPK0", "SPK0"]


def test_a_sub_second_cluster_joins_the_closest_voice():
    """Shuka (2026-10-04): one 0.4 s cue landed 0.31 away from the rest of
    him, under the bar, and he came out as two speakers."""
    stray = [0.31, math.sqrt(1 - 0.31 ** 2)]
    embs = [_unit(0), _unit(5), _unit(-5), stray]
    out = _merge(embs, ["SPK0", "SPK0", "SPK0", "SPK1"], 0.35, durs=[3.0, 3.0, 3.0, 0.4])
    assert out == ["SPK0"] * 4


def test_a_minor_speaker_with_real_speech_is_kept():
    other = [0.1, math.sqrt(1 - 0.1 ** 2)]
    embs = [_unit(0), _unit(5), _unit(-5), other]
    out = _merge(embs, ["SPK0", "SPK0", "SPK0", "SPK1"], 0.35, durs=[3.0, 3.0, 3.0, 2.0])
    assert out == ["SPK0", "SPK0", "SPK0", "SPK1"]


def test_merged_labels_are_numbered_by_size():
    # SPK1 and SPK2 are one voice; together they outnumber SPK0, so the
    # merged speaker is SPK0 and the old SPK0 becomes SPK1.
    embs = [_unit(0), _unit(90), _unit(90), _unit(90)]
    out = _merge(embs, ["SPK0", "SPK1", "SPK2", "SPK2"], 0.65)
    assert out == ["SPK1", "SPK0", "SPK0", "SPK0"]


# --- _maybe_collapse: AUTO-path wiring, explicit override wins -------------

def test_auto_path_merges_when_num_speakers_not_given():
    a = [1.0, 0.0]
    b = [0.999, math.sqrt(1 - 0.999 ** 2)]  # near-identical
    out = cd._maybe_collapse([a, b], [3.0, 3.0], ["SPK0", "SPK1"], None, 2, FakeNp, 0.65)
    assert out == ["SPK0", "SPK0"]


def test_explicit_num_speakers_bypasses_merging():
    a = [1.0, 0.0]
    b = [0.999, math.sqrt(1 - 0.999 ** 2)]  # same near-identical centroids
    out = cd._maybe_collapse([a, b], [3.0, 3.0], ["SPK0", "SPK1"], 2, 2, FakeNp, 0.65)
    assert out == ["SPK0", "SPK1"]


def test_auto_path_with_k_below_2_is_left_alone():
    out = cd._maybe_collapse([[1.0, 0.0], [0.0, 1.0]], [3.0, 3.0], ["SPK0", "SPK0"], None, 1, FakeNp, 0.0)
    assert out == ["SPK0", "SPK0"]


def test_auto_path_keeps_speakers_whose_centroids_differ():
    a = [1.0, 0.0]
    b = [0.2, math.sqrt(1 - 0.2 ** 2)]
    out = cd._maybe_collapse([a, b], [3.0, 3.0], ["SPK0", "SPK1"], None, 2, FakeNp, 0.65)
    assert out == ["SPK0", "SPK1"]


# --- Regression: job 4ec68328 (moon.mp4, real short/noisy Whisper cues) ----
# Real STT cues are much shorter (0.44-2.46s) than the clean 1.5-3s windows
# first calibrated on, so CAM++ embeddings are noisier: a real single-narrator
# job split into 3 spurious clusters (measured pairwise centroid sims
# 0.6283 / 0.4964 / 0.4918). These two tests pin the default against both
# edges: it must still merge this exact real case, and must still keep the
# measured cross-speaker case from the original calibration apart.

def test_real_moon_job_spurious_clusters_merge_under_default():
    a, b, c = _three_vectors_with_pairwise_sims(0.6283, 0.4964, 0.4918)
    out = _merge([a, b, c], ["SPK0", "SPK1", "SPK2"], cd.DIAR_MERGE_SIM_DEFAULT)
    assert out == ["SPK0"] * 3


def test_default_threshold_keeps_measured_cross_speaker_apart():
    a = [1.0, 0.0]
    b = [0.2154, (1 - 0.2154 ** 2) ** 0.5]  # measured cross-speaker centroid sim
    assert _merge([a, b], ["SPK0", "SPK1"], cd.DIAR_MERGE_SIM_DEFAULT) == ["SPK0", "SPK1"]


# --- PERSODUB_DIAR_MERGE_SIM env parsing -------------------------------------

def test_merge_sim_env_unset_uses_default(monkeypatch):
    monkeypatch.delenv("PERSODUB_DIAR_MERGE_SIM", raising=False)
    assert cd._parse_diar_merge_sim() == cd.DIAR_MERGE_SIM_DEFAULT


def test_merge_sim_env_valid_float(monkeypatch):
    monkeypatch.setenv("PERSODUB_DIAR_MERGE_SIM", "0.7")
    assert cd._parse_diar_merge_sim() == 0.7


def test_merge_sim_env_garbage_uses_default(monkeypatch):
    monkeypatch.setenv("PERSODUB_DIAR_MERGE_SIM", "banana")
    assert cd._parse_diar_merge_sim() == cd.DIAR_MERGE_SIM_DEFAULT
