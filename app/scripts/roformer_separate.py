#!/usr/bin/env python3
# The network below follows the Mel-Band RoFormer architecture as published in
# Phil Wang's BS-RoFormer project (https://github.com/lucidrains/BS-RoFormer),
# MIT License -- see NOTICE. Written for inference only, so it needs nothing
# beyond torch, numpy, librosa and soundfile (all already in the engines venv).
"""Local vocals/background separation with Kim's Mel-Band RoFormer vocal model
(MelBandRoformer.ckpt, MIT, https://huggingface.co/KimberleyJSN/melbandroformer),
run OUTSIDE the app's venv under SEP_PYTHON, the same JSON-in/JSON-out shape as
demucs_separate.py, which stays the fallback when this model is not downloaded.

Two passes: the model takes the voice out of the mix, then looks again at what
is left (the background) and moves any voice it still hears there over to the
vocals. One pass of htdemucs left the original speaker readable in the
background (about -64 dBFS, whole sentences a transcriber could read); two
passes of this model leave none (measured 2026-10-02 on three clips).

Usage: python roformer_separate.py --input job.json --output result.json
Input JSON: {"input": "<video_or_audio_path>", "out_dir": "<dir>",
             "model_path": "<.../MelBandRoformer.ckpt>", "device": optional}
Output JSON: {"ok": true, "vocals": "<path>", "background": "<path>"} or
             {"ok": false, "error": "..."}; never raises past main().
"""
import argparse
import json
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")

MODEL_SR = 44100
TARGET_SR = 48000
CHUNK = 352800        # 8 s, the length the model was trained on (801 STFT frames)
FADE = CHUNK // 10    # cross-fade between neighbouring chunks
PASSES = 2
TIME_ROWS = 10        # bands per attention call along time
# The weights' shape (Kim's published config for this checkpoint).
CONFIG = {"dim": 384, "depth": 6, "num_bands": 60, "heads": 8, "dim_head": 64, "mask_depth": 2,
          "sr": MODEL_SR, "n_fft": 2048, "hop": 441}


def build_model(torch):
    """The network, built lazily so --help needs no torch."""
    import librosa
    nn, F = torch.nn, torch.nn.functional

    class RMSNorm(nn.Module):
        def __init__(self, dim):
            super().__init__()
            self.scale = dim ** 0.5
            self.gamma = nn.Parameter(torch.ones(dim))

        def forward(self, x):
            return F.normalize(x, dim=-1) * self.scale * self.gamma

    class Rotary(nn.Module):
        """Rotary positions along the sequence (pairs interleaved)."""
        def __init__(self, dim_head):
            super().__init__()
            self.freqs = nn.Parameter(1.0 / (10000 ** (torch.arange(0, dim_head, 2).float() / dim_head)),
                                      requires_grad=False)

        def forward(self, t):
            ang = torch.arange(t.shape[-2], device=t.device, dtype=torch.float32)[:, None] * self.freqs
            ang = ang.repeat_interleave(2, dim=-1).to(t.dtype)
            pairs = t.unflatten(-1, (-1, 2))
            turned = torch.stack((-pairs[..., 1], pairs[..., 0]), dim=-1).flatten(-2)
            return t * ang.cos() + turned * ang.sin()

    class Attention(nn.Module):
        def __init__(self, dim, heads, dim_head):
            super().__init__()
            self.heads = heads
            self.norm = RMSNorm(dim)
            self.to_qkv = nn.Linear(dim, heads * dim_head * 3, bias=False)
            self.to_gates = nn.Linear(dim, heads)
            self.to_out = nn.Sequential(nn.Linear(heads * dim_head, dim, bias=False))
            self.rotary_embed = Rotary(dim_head)

        def forward(self, x):
            x = self.norm(x)
            b, n, _ = x.shape
            q, k, v = self.to_qkv(x).view(b, n, 3, self.heads, -1).permute(2, 0, 3, 1, 4)
            out = F.scaled_dot_product_attention(self.rotary_embed(q), self.rotary_embed(k), v)
            out = out * self.to_gates(x).transpose(1, 2).unsqueeze(-1).sigmoid()
            return self.to_out(out.transpose(1, 2).reshape(b, n, -1))

    class FeedForward(nn.Module):
        def __init__(self, dim):
            super().__init__()
            self.net = nn.Sequential(RMSNorm(dim), nn.Linear(dim, dim * 4), nn.GELU(), nn.Dropout(0.0),
                                     nn.Linear(dim * 4, dim), nn.Dropout(0.0))

        def forward(self, x):
            return self.net(x)

    class Transformer(nn.Module):
        def __init__(self, dim, heads, dim_head):
            super().__init__()
            self.layers = nn.ModuleList([nn.ModuleList([Attention(dim, heads, dim_head), FeedForward(dim)])])
            self.norm = RMSNorm(dim)

        def forward(self, x):
            for attn, ff in self.layers:
                x = attn(x) + x
                x = ff(x) + x
            return self.norm(x)

    def mask_mlp(dim, dim_out, depth):
        dims = [dim] + [dim * 4] * depth + [dim_out]
        layers = []
        for i in range(len(dims) - 1):
            layers.append(nn.Linear(dims[i], dims[i + 1]))
            if i < len(dims) - 2:
                layers.append(nn.Tanh())
        return nn.Sequential(nn.Sequential(*layers), nn.GLU(dim=-1))

    class MelBandRoformer(nn.Module):
        def __init__(self, dim, depth, num_bands, heads, dim_head, mask_depth, sr, n_fft, hop):
            super().__init__()
            self.n_fft, self.hop = n_fft, hop
            self.layers = nn.ModuleList([
                nn.ModuleList([Transformer(dim, heads, dim_head), Transformer(dim, heads, dim_head)])
                for _ in range(depth)])
            mel = torch.from_numpy(librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=num_bands))
            mel[0, 0] = 1.0
            mel[-1, -1] = 1.0
            bands = mel > 0                                          # (bands, freqs), overlapping
            idx = torch.arange(bands.shape[1]).repeat(num_bands, 1)[bands]
            self.freq_indices = (idx[:, None] * 2 + torch.arange(2)).reshape(-1)   # stereo pairs
            self.bands_per_freq = bands.sum(0).repeat_interleave(2).clamp(min=1)
            self.dims = tuple(int(n) * 4 for n in bands.sum(1))      # 2 channels x (real, imag)
            self.band_split = nn.Module()
            self.band_split.to_features = nn.ModuleList(
                [nn.Sequential(RMSNorm(d), nn.Linear(d, dim)) for d in self.dims])
            estimator = nn.Module()
            estimator.to_freqs = nn.ModuleList([mask_mlp(dim, d * 2, mask_depth) for d in self.dims])
            self.mask_estimators = nn.ModuleList([estimator])

        def forward(self, audio):
            """(b, 2, t) on the CPU -> the voice, (b, 2, t) on the CPU. The
            STFT and the complex maths stay on the CPU (MPS has no complex
            numbers everywhere); the network runs where the weights are."""
            weight = self.band_split.to_features[0][1].weight
            b, s, t = audio.shape
            win = torch.hann_window(self.n_fft)
            spec = torch.stft(audio.reshape(b * s, t), self.n_fft, self.hop, window=win, return_complex=True)
            frames = spec.shape[-1]
            spec = spec.reshape(b, s, -1, frames).transpose(1, 2).reshape(b, -1, frames)
            x = torch.view_as_real(spec[:, self.freq_indices]).permute(0, 2, 1, 3).reshape(b, frames, -1)
            x = x.to(weight.device, weight.dtype)
            x = torch.stack([f(p) for f, p in zip(self.band_split.to_features, x.split(self.dims, -1))],
                            dim=-2)
            for across_time, across_bands in self.layers:            # x: (b, frames, bands, dim)
                _, n, k, d = x.shape
                x = x.transpose(1, 2).reshape(b * k, n, d)
                # A few bands at a time: all 60 at once held 2 GB more on a Mac
                # for the same speed (2026-10-02).
                x = torch.cat([across_time(part) for part in x.split(TIME_ROWS)])
                x = x.reshape(b, k, n, d).transpose(1, 2)
                x = across_bands(x.reshape(b * n, k, d)).reshape(b, n, k, d)
            est = self.mask_estimators[0]
            mask = torch.cat([m(p) for m, p in zip(est.to_freqs, x.unbind(-2))], dim=-1)
            mask = torch.view_as_complex(mask.float().cpu().reshape(b, frames, -1, 2).contiguous()).transpose(1, 2)
            summed = torch.zeros_like(spec).index_add_(1, self.freq_indices, mask)
            out = spec * (summed / self.bands_per_freq[None, :, None])
            out = out.reshape(b, -1, s, frames).transpose(1, 2).reshape(b * s, -1, frames)
            return torch.istft(out, self.n_fft, self.hop, window=win, length=t).reshape(b, s, t)

    return MelBandRoformer(**CONFIG)


def pick_device(torch, wanted=None):
    """The fastest place this machine has: an NVIDIA card, Apple's GPU, else the CPU."""
    if wanted:
        return wanted
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def voice_of(torch, model, mix):
    """mix: (2, t) float32 tensor at 44.1 kHz -> the voice in it, (2, t).
    8 s chunks that overlap only by the 0.8 s cross-fade (overlapping by half
    took twice as long and left the same, measured 2026-10-02); edges mirrored
    so the first and last words are not cut by a chunk border."""
    F = torch.nn.functional
    t = mix.shape[-1]
    step = CHUNK - FADE
    border = FADE
    x = F.pad(mix[None], (border, border), mode="reflect" if t > border else "constant")[0]
    starts = list(range(0, max(x.shape[-1] - CHUNK, 0) + step, step))
    x = F.pad(x, (0, starts[-1] + CHUNK - x.shape[-1]))
    window = torch.ones(CHUNK)
    window[:FADE] = torch.linspace(0, 1, FADE)
    window[-FADE:] = torch.linspace(1, 0, FADE)
    acc = torch.zeros_like(x)
    weight = torch.zeros(x.shape[-1])
    with torch.no_grad():
        for s in starts:
            acc[:, s:s + CHUNK] += model(x[None, :, s:s + CHUNK])[0] * window
            weight[s:s + CHUNK] += window
    return (acc / weight.clamp(min=1e-8))[:, border:border + t]


def separate(input_path, out_dir, model_path, device=None):
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio

    os.makedirs(out_dir, exist_ok=True)
    extracted = os.path.join(out_dir, "sep_extracted_44k.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", input_path, "-ac", "2", "-ar", str(MODEL_SR),
                    "-f", "wav", extracted], check=True)
    mix, _sr = sf.read(extracted, dtype="float32", always_2d=True)
    mix = torch.from_numpy(mix.T.copy())

    model = build_model(torch)
    # weights_only: the checkpoint is a plain dict of tensors, so nothing in
    # the file can run code while it loads.
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True), strict=True)
    model = model.to(pick_device(torch, device)).eval()

    vocals = torch.zeros_like(mix)
    background = mix
    for _ in range(PASSES):
        found = voice_of(torch, model, background)
        vocals = vocals + found
        background = background - found

    paths = {}
    for name, stem in (("vocals", vocals), ("background", background)):
        stem = torchaudio.functional.resample(stem, MODEL_SR, TARGET_SR)
        paths[name] = os.path.join(out_dir, name + ".wav")
        sf.write(paths[name], np.clip(stem.numpy().T, -1.0, 1.0), TARGET_SR, subtype="PCM_16")
    os.remove(extracted)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    try:
        with open(a.input, encoding="utf-8") as f:
            payload = json.load(f)
        paths = separate(payload["input"], payload["out_dir"], payload["model_path"],
                         payload.get("device") or os.environ.get("SEP_DEVICE"))
        result = {"ok": True, "vocals": paths["vocals"], "background": paths["background"]}
    except Exception as e:
        with open(a.output, "w", encoding="utf-8") as f:
            json.dump({"ok": False, "error": str(e)[:500]}, f)
        print("__SEPARATE_ERROR__ %s" % str(e)[:200], file=sys.stderr)
        sys.exit(1)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(result, f)
    print("__SEPARATE_DONE__")


if __name__ == "__main__":
    main()
