"""The CAM++ ONNX input tensor name is not portable across exports.

The server's bundled campplus.onnx names its input "input", but the public
exports do not (welcomyou -> "feats", Luigi -> "x"). Hardcoding "input" made the
worker fail on any downloaded model, which is why diarization degraded on the
Mac. Read the name off the session instead.

The model is fed in one place, app/scripts/campplus_embed_files.py, and the
diarizer and the take scorer call it. The file worker kept its own hardcoded
"input" until 2026-10-02, so the speaker-identity check
(app/scripts/check_speaker_identity.py) failed on every installed model.

embed() takes np/torch/kaldi as arguments, so this exercises it with stand-ins
-- none of those live in the app venv that runs the suite. The last test runs
the real model when this machine has one.
"""
import importlib.util
import json
import os
import subprocess
import wave

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "scripts", "campplus_diarize.py",
)
_spec = importlib.util.spec_from_file_location("campplus_diarize", SCRIPT)
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


class FakeArray:
    def __init__(self, values):
        self.values = values

    def flatten(self):
        return self

    def __truediv__(self, d):
        return [v / d for v in self.values]


class FakeTensor:
    """Supports exactly the chain embed() performs on the fbank output."""

    def __init__(self, payload=None):
        self.payload = payload

    def unsqueeze(self, _dim):
        return self

    def mean(self, dim=None, keepdim=False):
        return self

    def __sub__(self, _other):
        return self

    def numpy(self):
        return self.payload


class FakeTorch:
    @staticmethod
    def tensor(_arr):
        return FakeTensor()


class FakeKaldi:
    @staticmethod
    def fbank(_x, **_kw):
        return FakeTensor("fbank80")


class _FakeLinalg:
    @staticmethod
    def norm(_e):
        return 1.0


class FakeNp:
    linalg = _FakeLinalg

    @staticmethod
    def pad(arr, _width):
        return arr


class FakeInput:
    def __init__(self, name):
        self.name = name


class FakeSession:
    """Records which feed key the worker used."""

    def __init__(self, input_name):
        self._input_name = input_name
        self.seen_keys = None

    def get_inputs(self):
        return [FakeInput(self._input_name)]

    def run(self, _outputs, feed):
        self.seen_keys = list(feed.keys())
        return [FakeArray([1.0] * 192)]


def _embed_once(input_name):
    sess = FakeSession(input_name)
    seg = [0.0] * cd.SR  # 1s, longer than the 0.2s pad threshold
    cd.embed(seg, sess, FakeNp, FakeTorch, FakeKaldi)
    return sess.seen_keys


def test_uses_feats_input_name():
    assert _embed_once("feats") == ["feats"]


def test_uses_x_input_name():
    assert _embed_once("x") == ["x"]


def test_still_works_with_the_servers_input_name():
    assert _embed_once("input") == ["input"]


# --- Same bug, second site: the best-of-N take scorer ----------------------
# qwen_score_takes.py had its own hardcoded {"input": ...} feed. With a public
# campplus export (input name "feats") the scorer died and best-of-N silently
# degraded to "take 0 for every line" -- High quality mode spent 4x the time
# for Fast-mode results.
SCORER = os.path.join(os.path.dirname(SCRIPT), "qwen_score_takes.py")
_sspec = importlib.util.spec_from_file_location("qwen_score_takes", SCORER)
qs = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(qs)


def _scorer_embed_once(input_name):
    sess = FakeSession(input_name)
    x = [0.0] * qs.SR  # 1s, over the 0.4s minimum
    qs.embed(sess, x, FakeTorch, FakeKaldi)
    return sess.seen_keys


def test_scorer_uses_feats_input_name():
    assert _scorer_embed_once("feats") == ["feats"]


def test_scorer_still_works_with_the_servers_input_name():
    assert _scorer_embed_once("input") == ["input"]


# --- Third site: the file worker behind the speaker-identity check ----------
FILES = os.path.join(os.path.dirname(SCRIPT), "campplus_embed_files.py")
_fspec = importlib.util.spec_from_file_location("campplus_embed_files", FILES)
ef = importlib.util.module_from_spec(_fspec)
_fspec.loader.exec_module(ef)


def test_file_worker_uses_feats_input_name():
    sess = FakeSession("feats")
    ef.embed([0.0] * ef.SR, sess, FakeNp, FakeTorch, FakeKaldi)
    assert sess.seen_keys == ["feats"]


def test_diarizer_and_scorer_use_the_file_workers_embedding():
    assert cd.embed.__module__ == "app.scripts.campplus_embed_files"
    assert "raw_embedding" in qs.embed.__code__.co_names


# --- The real model, when this machine has one ------------------------------

def _kit_setting(name):
    """A setting from the environment, else from an installed kit's kit.env
    (the places desktop/src/config.js puts a kit)."""
    if os.environ.get(name):
        return os.environ[name]
    home = os.path.expanduser("~")
    for kit in (os.environ.get("PERSODUB_KIT_DIR"),
                os.path.join(home, "Library", "Application Support", "PersoDub"),
                os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"), "PersoDub"),
                os.path.join(home, ".persodub")):
        env = os.path.join(kit or "", "kit.env")
        if kit and os.path.isfile(env):
            with open(env, encoding="utf-8") as f:
                for line in f:
                    key, _, value = line.strip().partition("=")
                    if key == name and value:
                        return value
    return None


def test_real_model_embeds_through_all_three_scripts(tmp_path):
    model, py = _kit_setting("PERSODUB_CAMPPLUS_MODEL"), _kit_setting("DIAR_PYTHON")
    if not (model and os.path.isfile(model)):
        pytest.skip("no CAM++ model on this machine (PERSODUB_CAMPPLUS_MODEL or a kit's kit.env)")
    if not (py and os.path.isfile(py)):
        pytest.skip("no interpreter with onnxruntime/torch on this machine (DIAR_PYTHON)")
    # One second of a voiced-like tone with a little noise, 24 kHz like a TTS line.
    import math
    import random
    rnd = random.Random(0)
    wav = str(tmp_path / "tone.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"".join(
            int(8000 * math.sin(2 * math.pi * 140 * n / 24000) + rnd.uniform(-500, 500)).to_bytes(2, "little", signed=True)
            for n in range(24000)))
    job, out = str(tmp_path / "in.json"), str(tmp_path / "out.json")
    with open(job, "w", encoding="utf-8") as f:
        json.dump({"wav_paths": [wav], "campplus_model": model}, f)
    r = subprocess.run([py, FILES, "--input", job, "--output", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    with open(out, encoding="utf-8") as f:
        result = json.load(f)
    assert r.returncode == 0 and result["ok"], result.get("error")
    emb = result["embeddings"][0]
    assert len(emb) > 0 and abs(math.sqrt(sum(v * v for v in emb)) - 1.0) < 1e-3
    # The diarizer and the take scorer, run the same way, give the same voice.
    probe = (
        "import importlib.util, json, sys\n"
        "def load(n, p):\n"
        "    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s)\n"
        "    s.loader.exec_module(m); return m\n"
        "cd = load('cd', sys.argv[1]); qs = load('qs', sys.argv[2])\n"
        "np, ort, sf, torch, kaldi = cd.lazy_imports()\n"
        "sess = ort.InferenceSession(sys.argv[3], providers=['CPUExecutionProvider'])\n"
        "x = cd.load_mono16k(sys.argv[4], np, sf)\n"
        "a = cd.embed(x, sess, np, torch, kaldi); b = qs.embed(sess, x, torch, kaldi)\n"
        "print(json.dumps(float(np.dot(a, b) / np.linalg.norm(b))))\n")
    r = subprocess.run([py, "-c", probe, SCRIPT, SCORER, model, wav],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) > 0.999
