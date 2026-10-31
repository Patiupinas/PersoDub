"""Independent metrics for PersoDub stage benchmarks, without model downloads.

A prediction is never its own ground truth. Timestamps are source seconds.
"""
from __future__ import annotations

import array
import math
import statistics
import sys
import unicodedata
import wave


def normalize_text(value: str) -> str:
    """Unicode NFKC/case normalization for EN, DE, ES and RU transcripts."""
    if not isinstance(value, str):
        raise ValueError("Transcript must be text")
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return " ".join("".join(
        char if (char.isalnum() or char.isspace()) else " " for char in value
    ).split())


def edit_distance(reference: list, candidate: list) -> int:
    """Minimum substitutions, insertions and deletions; O(min(N,M)) memory."""
    if len(candidate) > len(reference):
        reference, candidate = candidate, reference
    prev = list(range(len(candidate) + 1))
    for i, expected in enumerate(reference, 1):
        row = [i]
        for j, actual in enumerate(candidate, 1):
            row.append(min(
                prev[j] + 1, row[-1] + 1,
                prev[j - 1] + (expected != actual),
            ))
        prev = row
    return prev[-1]


def asr_metrics(reference: str, candidate: str) -> dict:
    expected = normalize_text(reference)
    produced = normalize_text(candidate)
    ref_words = expected.split()
    if not ref_words:
        raise ValueError("Independent ASR reference transcript is empty")
    chars_ref = list(expected.replace(" ", ""))
    chars_pred = list(produced.replace(" ", ""))
    words_wrong = edit_distance(ref_words, produced.split())
    chars_wrong = edit_distance(chars_ref, chars_pred)
    return {
        "reference_words": len(ref_words),
        "word_errors": words_wrong,
        "wer": round(words_wrong / len(ref_words), 6),
        "reference_characters": len(chars_ref),
        "character_errors": chars_wrong,
        "cer": round(chars_wrong / len(chars_ref), 6),
    }


def partition(events: list, duration: float, gold: bool = False) -> list:
    """Reject holes/overlaps: label every source instant TRANSLATE or PRESERVE."""
    if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Finite positive source duration required")
    if not isinstance(events, list) or not events:
        raise ValueError("Complete event partition required")
    result = []
    for item in events:
        if not isinstance(item, dict):
            raise ValueError("Each interval must be an object")
        start, end = item.get("start"), item.get("end")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)):
            raise ValueError("Event timestamps must be finite")
        if start < 0 or end <= start or end > duration + 1e-3:
            raise ValueError("Event lies outside the source")
        label = item.get("action", item.get("label"))
        if label not in ("TRANSLATE", "PRESERVE", "REVIEW"):
            raise ValueError("Unknown event label")
        if gold and label == "REVIEW":
            raise ValueError("Reference truth cannot contain REVIEW")
        result.append((float(start), float(end), label))
    if abs(result[0][0]) > 1e-3 or abs(result[-1][1] - duration) > 1e-3:
        raise ValueError("Events do not cover the entire source")
    if any(abs(a[1] - b[0]) > 1e-3 for a, b in zip(result, result[1:])):
        raise ValueError("Event partition overlaps or contains gaps")
    return result


def event_metrics(reference: list, candidate: list, duration: float) -> dict:
    """Time-weighted speech F1 and mistaken translation of protected exercises."""
    ref = partition(reference, duration, gold=True)
    pred = partition(candidate, duration)
    tp = fp = fn = preserved = exercise_wrong = unreviewed = 0.0
    i = j = 0
    while i < len(ref) and j < len(pred):
        rs, re, rt = ref[i]
        ps, pe, pt = pred[j]
        n = max(0.0, min(re, pe) - max(rs, ps))
        if n:
            if rt == "PRESERVE":
                preserved += n
                if pt == "TRANSLATE":
                    exercise_wrong += n
            if pt == "REVIEW":
                unreviewed += n
            if rt == "TRANSLATE" and pt == "TRANSLATE":
                tp += n
            elif rt != "TRANSLATE" and pt == "TRANSLATE":
                fp += n
            elif rt == "TRANSLATE":
                fn += n
        if re <= pe:
            i += 1
        if pe <= re:
            j += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "speech_precision": round(p, 6),
        "speech_recall": round(r, 6),
        "speech_f1": round((2 * p * r / (p + r)) if p + r else 0.0, 6),
        "protected_seconds": round(preserved, 6),
        "exercise_wrongly_translated_seconds": round(exercise_wrong, 6),
        "unreviewed_seconds": round(unreviewed, 6),
    }


def _utterances(value: list) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError("Non-empty utterance list required")
    out = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Utterances must be objects")
        start, end = row.get("start"), row.get("end")
        if not all(isinstance(x, (float, int)) and math.isfinite(x) for x in (start, end)):
            raise ValueError("Finite utterance timestamps required")
        if start < 0 or end <= start:
            raise ValueError("Invalid utterance times")
        out.append((float(start), float(end)))
    if any(a[0] > b[0] for a, b in zip(out, out[1:])):
        raise ValueError("Utterances are not time ordered")
    return out


def timing_metrics(reference: list, candidate: list) -> dict:
    """One-to-one utterance boundaries, gap retention and audio overlaps."""
    ref = _utterances(reference)
    pred = _utterances(candidate)
    if len(ref) != len(pred):
        raise ValueError("Independent reference and output utterance counts differ")
    start_err = [abs(a[0] - b[0]) for a, b in zip(ref, pred)]
    end_err = [abs(a[1] - b[1]) for a, b in zip(ref, pred)]
    missing_pauses = [
        max(0.0, (b[0] - a[1]) - (d[0] - c[1]))
        for (a, b), (c, d) in zip(zip(ref, ref[1:]), zip(pred, pred[1:]))
        if b[0] - a[1] >= 0.35
    ]
    return {
        "utterances": len(ref),
        "start_mae_s": round(statistics.mean(start_err), 6),
        "end_mae_s": round(statistics.mean(end_err), 6),
        "max_boundary_error_s": round(max(start_err + end_err), 6),
        "source_pauses": len(missing_pauses),
        "total_missing_pause_s": round(sum(missing_pauses), 6),
        "max_missing_pause_s": round(max(missing_pauses, default=0), 6),
        "dub_overlapping_pairs": sum(a[1] > b[0] for a, b in zip(pred, pred[1:])),
    }


class PCM16:
    """Read aligned little-endian PCM16 samples in bounded buffers."""

    def __init__(self, path):
        self.path = str(path)
        self.wav = None

    def __enter__(self):
        self.wav = wave.open(self.path, "rb")
        if self.wav.getsampwidth() != 2 or self.wav.getcomptype() != "NONE":
            self.wav.close()
            raise ValueError("PCM16 uncompressed WAV required")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.wav:
            self.wav.close()

    def read(self, frame_count):
        values = array.array("h")
        values.frombytes(self.wav.readframes(frame_count))
        if sys.byteorder != "little":
            values.byteswap()
        return values

    def seek(self, frame):
        self.wav.setpos(frame)


def _same_clock(a, b):
    if (a.wav.getframerate(), a.wav.getnchannels(), a.wav.getnframes()) != (
        b.wav.getframerate(), b.wav.getnchannels(), b.wav.getnframes()
    ):
        raise ValueError("Source and output must share exact PCM sample clock")


def stem_metrics(ground_truth_wav, separated_wav) -> dict:
    """Streaming scale-invariant SDR. Require independently separated oracle."""
    n = sum_x = sum_y = dot = power_ref = power_pred = 0.0
    with PCM16(ground_truth_wav) as ref, PCM16(separated_wav) as pred:
        _same_clock(ref, pred)
        for _ in range(0, ref.wav.getnframes(), 8192):
            a, b = ref.read(8192), pred.read(8192)
            for x, y in zip(a, b):
                n += 1
                sum_x += x
                sum_y += y
                dot += x * y
                power_ref += x * x
                power_pred += y * y
    if n == 0:
        raise ValueError("Non-empty audio required for SI-SDR")
    # Standard SI-SDR zero-centers both signals. Raw dot products without
    # mean subtraction silently overstate quality for DC-offset candidates.
    cov = dot - sum_x * sum_y / n
    centered_ref = power_ref - sum_x * sum_x / n
    centered_pred = power_pred - sum_y * sum_y / n
    if centered_ref <= 0 or centered_pred <= 0:
        raise ValueError("Non-silent oracle and candidate required for SI-SDR")
    power_signal = cov * cov / centered_ref
    power_noise = centered_pred - power_signal
    if power_noise <= 1e-12:
        return {"si_sdr_db": None, "perfect_reconstruction": True}
    return {
        "si_sdr_db": round(
            10 * math.log10(max(power_signal, 1e-12) / power_noise), 4
        ),
        "perfect_reconstruction": False,
    }


def mix_metrics(source_wav, output_wav, spans: list) -> dict:
    """Aligned source projection in synthetic independent-source mix windows.

    On real correlated English+Russian speech this is diagnostic only, not a
    blind quality gate. A known independent source signal is the oracle.
    """
    with PCM16(source_wav) as ref, PCM16(output_wav) as out:
        _same_clock(ref, out)
        sr = ref.wav.getframerate()
        n = ref.wav.getnframes()
        results = []
        for row in spans:
            if not isinstance(row, dict) or row.get("action") not in (
                "TRANSLATE", "PRESERVE"
            ):
                raise ValueError("Approved mix window action required")
            start, end = row.get("start"), row.get("end")
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)):
                raise ValueError("Finite mix-window timestamps required")
            s, e = round(start * sr), round(end * sr)
            if s < 0 or e <= s or e > n:
                raise ValueError("Mix window outside source audio")
            ref.seek(s)
            out.seek(s)
            dot = energy = residual = 0
            remaining = e - s
            while remaining:
                frames = min(remaining, 4096)
                a, b = ref.read(frames), out.read(frames)
                for x, y in zip(a, b):
                    dot += x * y
                    energy += x * x
                    residual += (y - x) ** 2
                remaining -= frames
            if energy <= 0:
                raise ValueError("The source signal is silent in a mix window")
            coefficient = dot / energy
            results.append({
                "action": row["action"],
                "start": round(start, 6),
                "end": round(end, 6),
                "source_gain_db": (
                    round(20 * math.log10(coefficient), 3)
                    if coefficient > 0 else None
                ),
                "relative_difference_db": (
                    round(10 * math.log10(residual / energy), 3)
                    if residual > 0 else None
                ),
            })
    return {"windows": results}
