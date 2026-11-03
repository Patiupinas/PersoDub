"""Offline Russian TTS voice catalogue trial; no source timbre cloning.

The output contains only original Russian test text and generated model audio.
Model weights remain in the local kit, never in the report or Git tree.
"""
import argparse
import hashlib
import html
import json
import time
import wave
from pathlib import Path

VOICE_IDS = ("aidar", "baya", "kseniya", "eugene", "xenia")
RUSSIAN_CONTROL = (
    "Здравствуйте. Сегодня мы разберём дыхание, резонанс и работу голосовых складок. "
    "Почему тихое пение бывает сложнее громкого? "
    "После небольшой паузы повторим упражнение ещё два раза."
)
SAMPLE_RATE = 48000


def file_sha(path):
    result = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def render_page(rows, sample_text):
    """Build a local listening page with no network resources."""
    elements = []
    for item in rows:
        elements.append(
            "<section><h2>" + html.escape(item["voice"]) + "</h2>"
            + "<audio controls preload='none' src='" + html.escape(item["wav"], quote=True) + "'></audio>"
            + "<p>" + html.escape(sample_text) + "</p></section>"
        )
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<title>Русские голоса PersoDub</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{max-width:780px;margin:2rem auto;font:17px/1.5 system-ui,"
        "sans-serif;padding:0 1rem}section{padding:1rem 0;border-bottom:1px solid #ccc}"
        "audio{display:block;width:100%;max-width:600px}</style></head>"
        "<body><h1>Пять русских голосов - контрольный набор</h1>"
        "<p>Одинаковый текст. Оцените естественность, произношение, тембр "
        "и пригодность для длинной лекции. "
        "Клонирование оригинального голоса не используется.</p>"
        + "".join(elements) + "</body></html>"
    )


def render(model_path, destination, text=RUSSIAN_CONTROL):
    if destination.exists():
        raise FileExistsError("Research output already exists: " + str(destination))
    if not text.strip() or not model_path.is_file():
        raise ValueError("a non-empty Russian text and cached model weights are required")

    import numpy as np
    import torch

    torch.set_num_threads(4)
    destination.mkdir(parents=True)
    started = time.monotonic()
    model = torch.package.PackageImporter(str(model_path)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    assert set(VOICE_IDS).issubset(model.speakers)
    records = []
    for speaker in VOICE_IDS:
        began = time.monotonic()
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=SAMPLE_RATE)
        data = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        if len(data) < SAMPLE_RATE:
            raise RuntimeError("TTS produced no useful speech for " + speaker)
        filename = speaker + ".wav"
        path = destination / filename
        pcm = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm)
        entry = {"voice": speaker, "wav": filename,
                 "seconds": round(len(data) / SAMPLE_RATE, 3),
                 "wall_s": round(time.monotonic() - began, 3),
                 "sha256": file_sha(path)}
        records.append(entry)
        print("GENERATED", speaker, entry["seconds"], "s", flush=True)
    manifest = {
        "status": "REAL_MODEL_AUDIO_NOT_HUMAN_RATED",
        "model": "Silero v5_6_ru",
        "model_sha256": file_sha(model_path),
        "sample_rate": SAMPLE_RATE,
        "text": text,
        "wall_s": round(time.monotonic() - started, 3),
        "human_native_russian_quality_rated": False,
        "source_timbre_cloning": False,
        "voices": records,
    }
    with (destination / "report.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
    (destination / "index.html").write_text(render_page(records, text), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = render(args.model, args.out)
    print("DONE", report["status"], report["wall_s"], "s", flush=True)


if __name__ == "__main__":
    main()
