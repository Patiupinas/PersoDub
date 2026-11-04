"""Opt-in Antigravity CLI translator using the existing TranslationEngine contract."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.text.dub_prompt import parse_json_array
from app.translation_gate import review_ru_lines


class AntigravityCLI:
    """Short CLI calls, strict response validation and resumable per-prompt cache.

    The CLI's SUCCESS status alone is insufficient; the first full-lesson test
    returned SUCCESS and an empty response. All prompts are data-only in a
    temporary working directory; model identity remains unknown if CLI omits it.
    """

    id = "antigravity"
    display_name = "Antigravity CLI (experimental)"
    model = None
    format_tries = 1
    max_budget_retries = 0
    recheck_script = False
    length_rules = True
    plain_lines = False
    answers_dir = None
    before_ask = None

    def __init__(self, binary=None, timeout=85):
        self.binary = binary or shutil.which("antigravity")
        self.timeout = timeout

    def ask(self, prompt):
        if self.before_ask:
            self.before_ask()
        if not self.binary:
            raise RuntimeError("Antigravity CLI is not installed")
        key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cached = Path(self.answers_dir) / (key + ".txt") if self.answers_dir else None
        if cached and cached.is_file():
            return cached.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="persodub-argon-") as temp:
            argv = [self.binary, "--print", prompt, "--mode", "plan", "--effort", "low",
                    "--output-format", "json", "--print-timeout", f"{int(self.timeout)}s"]
            try:
                proc = subprocess.run(argv, cwd=temp, capture_output=True, text=True,
                                      timeout=self.timeout + 15, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Antigravity translation timed out") from exc
            if proc.returncode:
                raise RuntimeError(f"Antigravity CLI failed (exit {proc.returncode})")
            try:
                payload = json.loads(proc.stdout)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("Antigravity returned invalid CLI JSON") from exc
            result = payload.get("response")
            if payload.get("status") != "SUCCESS" or not isinstance(result, str) or not result.strip():
                raise RuntimeError("Antigravity returned no usable translation")
            if cached:
                cached.parent.mkdir(parents=True, exist_ok=True)
                staging = cached.with_suffix(".part")
                staging.write_text(result, encoding="utf-8")
                os.replace(staging, cached)
            return result

    def translate(self, texts, target_lang, source_lang=None, durations=None, fuller=False):
        if not texts:
            return []
        if target_lang.lower() not in ("russian", "ru"):
            raise ValueError("Antigravity trial currently supports Russian only")
        if durations is None or len(durations) != len(texts):
            raise ValueError("Source-clock durations required for Antigravity")
        source_names = {
            "en": "English", "english": "English",
            "de": "German", "german": "German", "deutsch": "German",
            "es": "Spanish", "spanish": "Spanish", "español": "Spanish",
        }
        name = (source_lang or "").strip().lower()
        if name not in source_names:
            raise ValueError("Antigravity requires explicit English, German or Spanish source language")
        source_name = source_names[name]
        answers = []
        for start in range(0, len(texts), 4):
            part = texts[start:start + 4]
            seconds = durations[start:start + 4]
            context_before = texts[start-1] if start else ""
            context_after = texts[start+len(part)] if start+len(part)<len(texts) else ""
            cues = [{"seconds": round(d, 2), "max_ru_words": max(2, math.ceil(d * 2.3) + 1),
                     "source": t} for t, d in zip(part, seconds)]
            prompt = (
                f"Translate exactly {len(part)} separate {source_name} vocal-instruction cues "
                "into fluent, faithful spoken Russian. Address viewers with informal 'ты'. "
                "One output per input cue, same order, no omissions or additions. "
                "A source subtitle may end mid-sentence: preserve its meaning using the "
                "adjacent context, but make each Russian cue independently pronounceable. "
                "Preserve negation, numbers, questions, anatomy, breath control, pitch, "
                "resonance, vocal registers and exercise instructions. "
                "Keep German/Spanish musical terms accurate in natural Russian. "
                "Do not confuse German 'Stütze' with a literal physical support, "
                "or Spanish 'apoyo' with a literal prop, when discussing vocal breath support. "
                "Do not translate singing, hummed notes or vocal exercises into extra spoken text; "
                "they are preserved on the original audio by the separate A4 event plan. "
                "Do not invent gender, claims or extra instructions. "
                "Strictly keep within max_ru_words for each cue. "
                f"Source language: {source_name}. "
                f"Context only (do not translate): {context_before!r}, {context_after!r}. "
                f"Respond with ONLY a JSON array of exactly {len(part)} Russian strings. "
                f"INPUT: {json.dumps(cues, ensure_ascii=False)}"
            )
            reply = parse_json_array(self.ask(prompt), len(part))
            flags = review_ru_lines(
                part, reply, seconds, informal=True, male_narrator=False,
                allow_source_continuations=True,
            )
            if flags:
                indices = [start + row["cue"] for row in flags]
                raise ValueError(f"Antigravity output needs review: source cues {indices}, "
                                 "no automatic dub generated")
            answers.extend(reply)
        return answers
