// Finished-job Overdub editor: review coarse event hints before re-export.
// Classifier output is never permission to translate; every action begins REVIEW.
import { escapeHtml, errorText } from "./format.mjs";
import { t } from "./i18n.mjs";
import { initS2stLab } from "./s2stLab.mjs";

export const OVERDUB_RATE = 48000;
export const REVIEW_PAGE_SIZE = 100;
export const ACTIONS = ["REVIEW", "TRANSLATE", "PRESERVE"];

export function reviewedEvents(items) {
  if (!Array.isArray(items) || !items.length) throw new Error("No reviewed events");
  let end = 0;
  return items.map((item) => {
    const { start_frame, end_frame, action } = item;
    if (!Number.isSafeInteger(start_frame) || !Number.isSafeInteger(end_frame)
      || start_frame !== end || end_frame <= start_frame || !ACTIONS.includes(action)) {
      throw new Error("Overdub intervals must cover the exact original audio clock");
    }
    end = end_frame;
    return { start_frame, end_frame, action };
  });
}

export function splitOverdubInterval(items, seconds) {
  const point = Math.round(Number(seconds) * OVERDUB_RATE);
  if (!Number.isSafeInteger(point) || point <= 0) throw new Error("Enter a valid split time");
  const at = items.findIndex((item) => item.start_frame < point && point < item.end_frame);
  if (at < 0) throw new Error("Split time must be inside a segment");
  const original = items[at];
  return [
    ...items.slice(0, at),
    { ...original, end_frame: point },
    { ...original, start_frame: point },
    ...items.slice(at + 1),
  ];
}

function atTime(frames) { return (frames / OVERDUB_RATE).toFixed(2); }

export function overDubRowsHtml(items, indexOffset = 0) {
  return items.map((entry, localIndex) => {
    const index = indexOffset + localIndex;
    const hint = entry.hint === "speech-cue" ? t("Speech cue") :
      entry.hint === "unknown" ? t("Unknown") : entry.hint;
    // AST group scores are not calibrated probabilities; never display them as confidence percentages.
    const certainty = entry.score == null ? "" : ` · ${t("Model score")} ${Number(entry.score).toFixed(2)}`;
    const choices = [
      ["REVIEW", t("Keep original / review")],
      ["TRANSLATE", t("Original quiet + translation")],
      ["PRESERVE", t("Keep original / vocal exercise")],
    ];
    return `<div class="overdub-row">
      <span class="overdub-clock">${atTime(entry.start_frame)}-${atTime(entry.end_frame)}s</span>
      <span class="overdub-hint">${escapeHtml(hint || t("Unknown"))}${certainty}</span>
      <select data-od-index="${index}" aria-label="${t("Treatment for audio interval")} ${index + 1}">
        ${choices.map(([value, name]) => `<option value="${value}"${entry.action === value ? " selected" : ""}>${escapeHtml(name)}</option>`).join("")}
      </select></div>`;
  }).join("");
}

/**
 * Render a source-bound event review dialog for a *completed local* Qwen job.
 * No full replacement option is changed. Final download is a separate MP4.
 */
export function initOverdubDialog({ $, fetchFn = (...args) => fetch(...args), onExport = () => {} }) {
  let jobId = null;
  let preview = null;
  let events = [];
  let busy = false;
  let generation = 0;
  let page = 0;
  const s2stLab = initS2stLab({ $, fetchFn });
  const overlay = $("overdubOverlay");
  const status = $("overdubStatus");
  const list = $("overdubList");
  const confirm = $("overdubReviewed");
  const exportButton = $("overdubExport");
  const analyze = $("overdubAnalyze");
  const useHints = $("overdubUseHints");
  const split = $("overdubSplit");
  const result = $("overdubResult");
  const previousPage = $("overdubPagePrev");
  const nextPage = $("overdubPageNext");
  const pageLabel = $("overdubPageLabel");

  const allReview = () => events.every((row) => row.action === "REVIEW");
  function paint() {
    const scroll = list.scrollTop;
    const pages = Math.max(1, Math.ceil(events.length / REVIEW_PAGE_SIZE));
    page = Math.max(0, Math.min(page, pages - 1));
    const first = page * REVIEW_PAGE_SIZE;
    const last = Math.min(first + REVIEW_PAGE_SIZE, events.length);
    list.innerHTML = overDubRowsHtml(events.slice(first, last), first);
    list.scrollTop = scroll;
    previousPage.disabled = busy || page <= 0;
    nextPage.disabled = busy || page >= pages - 1;
    pageLabel.textContent = events.length ? `${first + 1}-${last} / ${events.length}` : "0 / 0";
    const hasSource = !!preview;
    analyze.disabled = busy || !hasSource || !preview.ast_available;
    useHints.disabled = busy || !hasSource || !events.length;
    split.disabled = busy || !hasSource;
    confirm.disabled = busy || !hasSource;
    exportButton.disabled = busy || !hasSource || !confirm.checked;
    $("overdubClose").disabled = busy;
    $("overdubOriginalDb").disabled = busy;
    $("overdubTranslationDb").disabled = busy;
    $("overdubFadeMs").disabled = busy;
  }
  function message(note) { status.textContent = note; }
  async function api(path, body) {
    const response = await fetchFn(`/api/dub/jobs/${encodeURIComponent(jobId)}/overdub/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || t("Overdub request failed"));
    }
    return response.json();
  }
  async function prepare(analyzeWithAst = false) {
    if (!jobId || busy) return;
    if (analyzeWithAst && !allReview()) {
      message(t("Clear reviewed choices before analyzing again."));
      return;
    }
    const currentJob = jobId;
    const currentGen = ++generation;
    busy = true;
    confirm.checked = false;
    result.hidden = true;
    message(analyzeWithAst ? t("Analyzing voice and singing with AST…") : t("Preparing the original audio…"));
    paint();
    try {
      const answer = await api("prepare", { analyze: analyzeWithAst });
      if (currentGen !== generation || currentJob !== jobId) return;
      preview = answer;
      events = answer.suggestions.map((row) => ({ ...row, action: "REVIEW" }));
      page = 0;
      if (answer.analysis === "ast_observations") {
        message(t("AST event suggestions are ready. Review every interval before export."));
      } else if (answer.analysis === "model_failed") {
        message(t("AST analysis did not complete. Using speech-cue suggestions."));
      } else if (!answer.ast_available) {
        message(t("AST is not configured. Using speech-cue suggestions; split and review intervals."));
      } else {
        message(t("Review the intervals or analyze with AST before export."));
      }
    } catch (err) {
      if (currentGen !== generation || currentJob !== jobId) return;
      preview = null;
      events = [];
      message(errorText(err));
    } finally {
      if (currentGen === generation) { busy = false; paint(); }
    }
  }
  function close() {
    if (busy) return;
    ++generation;
    jobId = null;
    s2stLab.close();
    overlay.classList.remove("open");
  }
  async function open(jid) {
    if (!jid || busy) return;
    jobId = jid;
    preview = null;
    events = [];
    page = 0;
    confirm.checked = false;
    result.hidden = true;
    overlay.classList.add("open");
    s2stLab.open(jid);
    paint();
    await prepare(false);
  }
  list.addEventListener("change", (event) => {
    const field = event.target.closest("[data-od-index]");
    if (!field || busy) return;
    const i = Number(field.dataset.odIndex);
    if (!events[i] || !ACTIONS.includes(field.value)) return;
    events[i].action = field.value;
    confirm.checked = false;
    paint();
  });
  useHints.addEventListener("click", () => {
    if (busy || !preview) return;
    events = events.map((item) => ({
      ...item, action: ACTIONS.includes(item.suggested_action) ? item.suggested_action : "REVIEW",
    }));
    confirm.checked = false;
    message(t("Suggestions applied. Check each interval and confirm your choices."));
    paint();
  });
  previousPage.addEventListener("click", () => {
    if (busy || page === 0) return;
    page -= 1;
    list.scrollTop = 0;
    paint();
  });
  nextPage.addEventListener("click", () => {
    if (busy || (page + 1) * REVIEW_PAGE_SIZE >= events.length) return;
    page += 1;
    list.scrollTop = 0;
    paint();
  });
  split.addEventListener("click", () => {
    if (busy) return;
    try {
      events = splitOverdubInterval(events, $("overdubSplitAt").value);
      confirm.checked = false;
      message(t("Interval split. Review both sides."));
      paint();
    } catch (err) { message(errorText(err)); }
  });
  confirm.addEventListener("change", paint);
  analyze.addEventListener("click", () => prepare(true));
  exportButton.addEventListener("click", async () => {
    if (!preview || busy || !confirm.checked || !jobId) return;
    busy = true;
    result.hidden = true;
    message(t("Building the Overdub MP4 with two selectable audio tracks…"));
    paint();
    try {
      const actions = reviewedEvents(events);
      if (actions[actions.length - 1].end_frame !== preview.total_frames) {
        throw new Error("Event plan does not cover the complete source");
      }
      const answer = await api("export", {
        source_wav_sha256: preview.source_wav_sha256,
        total_frames: preview.total_frames, events: actions,
        review_confirmed: true,
        original_speech_db: Number($("overdubOriginalDb").value),
        dub_speech_db: Number($("overdubTranslationDb").value),
        fade_ms: Number($("overdubFadeMs").value),
      });
      result.hidden = false;
      result.textContent = "";
      const link = document.createElement("a");
      link.href = answer.download_url;
      link.download = answer.file;
      link.textContent = t("Download Overdub video");
      result.appendChild(link);
      message(t("Export complete. Overdub and Original are selectable audio tracks."));
      onExport(jobId, answer.file);
    } catch (err) {
      message(errorText(err));
    } finally { busy = false; paint(); }
  });
  $("overdubClose").addEventListener("click", close);
  overlay.addEventListener("click", (event) => { if (event.target === overlay) close(); });
  return { open, close };
}
