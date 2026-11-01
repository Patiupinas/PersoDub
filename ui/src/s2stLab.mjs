// Isolated opt-in S2ST lab in the finished-job Overdub dialog.
// This never approves an Overdub event, replaces a Qwen line or edits a source.
import { escapeHtml, errorText } from "./format.mjs";

export const S2ST_PAGE_SIZE = 50;
export const S2ST_MAX_SELECTION = 6;
const CLOCK = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: (token) => clearTimeout(token),
};

function fmt(seconds) {
  if (!Number.isFinite(seconds)) return "?";
  const min = Math.floor(seconds / 60);
  const sec = (seconds - min * 60).toFixed(2).padStart(5, "0");
  return `${min}:${sec}`;
}

export function speechRowsHtml(cues, selected = new Set(), audioBase = "", token = "") {
  return cues.map((cue) => `<div class="s2st-row">
    <input type="checkbox" aria-label="Select source cue #${cue.index}" data-s2st-index="${cue.index}"
      ${selected.has(cue.index) ? "checked" : ""}
      ${cue.selectable ? "" : "disabled"}>
    <span class="s2st-time">${fmt(cue.start)}-${fmt(cue.end)}</span>
    <span>#${cue.index} · ${escapeHtml(cue.speaker || "unknown")}</span>
    ${cue.selectable && audioBase && token
      ? `<audio controls preload="none" aria-label="Original speech #${cue.index}"
        src="${escapeHtml(audioBase)}/source/${cue.index}?source_token=${encodeURIComponent(token)}"></audio>`
      : ""}
    <small>${(cue.end - cue.start) < 2 ? "Short source: review" :
      !cue.selectable ? "Long interval: split first" : ""}</small>
  </div>`).join("");
}

export function s2stResultsHtml(results) {
  if (!Array.isArray(results) || !results.length) return "";
  return results.map((row) => {
    const state = row.state === "TIMING_CANDIDATE_ONLY"
      ? "Timing candidate, not quality-verified"
      : row.state === "REVIEW_REQUIRED" ? "Review required" : "Not completed";
    const reasons = Array.isArray(row.reasons) ? row.reasons.join(", ") : "";
    const links = [
      ["original_audio_url", "Original WAV"], ["russian_audio_url", "Russian WAV"],
      ["preview_video_url", "Two-track MP4"],
    ].filter(([key]) => typeof row[key] === "string"
      && /^\/api\/dub\/jobs\//.test(row[key])).map(([key, name]) =>
      `<a href="${escapeHtml(row[key])}" target="_blank" rel="noopener">${name}</a>`).join(" · ");
    return `<div class="s2st-result">
      <strong>Source #${row.index}</strong><span>${escapeHtml(state)}</span>
      <span class="s2st-result-links">${links}</span>
      ${reasons ? `<small>${escapeHtml(reasons)}</small>` : ""}
    </div>`;
  }).join("");
}

export function initS2stLab({ $, fetchFn = (...args) => fetch(...args), clock = CLOCK }) {
  const panel = $("s2stLabPanel");
  const message = $("s2stLabStatus");
  const candidateList = $("s2stLabCandidates");
  const results = $("s2stLabResults");
  const pageBack = $("s2stLabPrev");
  const pageForward = $("s2stLabNext");
  const pageText = $("s2stLabPage");
  const review = $("s2stLabReviewed");
  const start = $("s2stLabStart");
  let jobId = null;
  let version = "";
  let total = 0;
  let page = 0;
  let rows = [];
  let picked = new Set();
  let modelAvailable = false;
  let running = false;
  let busy = false;
  let run = null;
  let generation = 0;
  let pollTimer = null;
  let lastError = "";

  function clearPoll() {
    if (pollTimer != null) clock.clear(pollTimer);
    pollTimer = null;
  }
  function paint() {
    candidateList.innerHTML = speechRowsHtml(rows, picked,
      jobId ? base() : "", version);
    pageText.textContent = total
      ? `${page * S2ST_PAGE_SIZE + 1}-${Math.min((page + 1) * S2ST_PAGE_SIZE, total)} / ${total}`
      : "0 / 0";
    pageBack.disabled = busy || running || page <= 0;
    pageForward.disabled = busy || running || (page + 1) * S2ST_PAGE_SIZE >= total;
    start.textContent = picked.size
      ? `Generate ${picked.size} reviewed Russian speech clip${picked.size > 1 ? "s" : ""}`
      : "Generate reviewed Russian speech";
    start.disabled = busy || running || !modelAvailable
      || picked.size === 0 || picked.size > S2ST_MAX_SELECTION || !review.checked;
    review.disabled = busy || running || picked.size === 0;
    results.innerHTML = s2stResultsHtml(run?.results || []);
    if (lastError) {
      message.textContent = lastError;
    } else if (run?.status === "running") {
      const p = run.progress;
      message.textContent = p
        ? `Generating Russian audio: ${p.done} / ${p.total} segments processed.`
        : "Starting local audio-to-audio model…";
    } else if (run?.status === "done") {
      message.textContent = `Research run complete. Check every translation before using it. ${run.results?.length || 0} timing records.`;
    } else if (run?.status === "error") {
      message.textContent = `Research run did not complete (${run.error || "process stopped"}).`;
    } else if (!modelAvailable) {
      message.textContent = "Local SeamlessM4T v2 model or Python runtime is not installed.";
    } else {
      message.textContent = `${picked.size} / ${S2ST_MAX_SELECTION} speech clips selected. The original video is unchanged.`;
    }
  }
  async function request(path, options) {
    const response = await fetchFn(path, options);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || "S2ST lab request failed");
    }
    return response.json();
  }
  function base() {
    return `/api/dub/jobs/${encodeURIComponent(jobId)}/s2st`;
  }
  function schedulePoll() {
    clearPoll();
    if (!jobId || !panel.open || run?.status !== "running") return;
    const id = jobId;
    const gen = generation;
    pollTimer = clock.set(async () => {
      pollTimer = null;
      try {
        const answer = await request(`${base()}/status`);
        if (gen !== generation || id !== jobId || !panel.open) return;
        run = answer.run;
        running = run?.status === "running";
        lastError = "";
        paint();
        schedulePoll();
      } catch (err) {
        if (gen !== generation || id !== jobId || !panel.open) return;
        lastError = errorText(err);
        paint();
        schedulePoll();
      }
    }, 2000);
  }
  async function load() {
    if (!jobId || busy || !panel.open) return;
    const id = jobId;
    const gen = ++generation;
    busy = true;
    lastError = "";
    message.textContent = "Loading original speech intervals…";
    paint();
    try {
      const answer = await request(`${base()}?page=${page}`);
      if (gen !== generation || id !== jobId || !panel.open) return;
      if (version && version !== answer.source_token) {
        picked.clear();
        review.checked = false;
      }
      version = answer.source_token;
      rows = answer.cues || [];
      total = answer.total_cues || 0;
      modelAvailable = answer.model_available === true;
      run = answer.run;
      running = run?.status === "running";
    } catch (err) {
      if (gen !== generation || id !== jobId || !panel.open) return;
      rows = [];
      lastError = errorText(err);
    } finally {
      if (gen === generation) {
        busy = false;
        paint();
        schedulePoll();
      }
    }
  }
  function open(id) {
    clearPoll();
    ++generation;
    jobId = id;
    version = "";
    rows = [];
    total = 0;
    page = 0;
    picked = new Set();
    modelAvailable = false;
    running = false;
    busy = false;
    run = null;
    lastError = "";
    review.checked = false;
    panel.open = false;
    paint();
  }
  function close() {
    clearPoll();
    ++generation;
    jobId = null;
    panel.open = false;
    rows = [];
    picked.clear();
    run = null;
    running = false;
    busy = false;
  }
  panel.addEventListener("toggle", () => {
    if (!panel.open) {
      clearPoll();
      ++generation;
    } else if (jobId) {
      load();
    }
  });
  candidateList.addEventListener("change", (event) => {
    const field = event.target.closest("[data-s2st-index]");
    if (!field || busy || running) return;
    const index = Number(field.dataset.s2stIndex);
    const row = rows.find((cue) => cue.index === index && cue.selectable);
    if (!row) return;
    if (field.checked) {
      if (picked.size >= S2ST_MAX_SELECTION) {
        lastError = `Select no more than ${S2ST_MAX_SELECTION} speech intervals.`;
        paint();
        return;
      }
      picked.add(index);
    } else {
      picked.delete(index);
    }
    lastError = "";
    review.checked = false;
    paint();
  });
  review.addEventListener("change", paint);
  pageBack.addEventListener("click", async () => {
    if (page > 0 && !busy && !running) { page--; await load(); }
  });
  pageForward.addEventListener("click", async () => {
    if ((page + 1) * S2ST_PAGE_SIZE < total && !busy && !running) {
      page++;
      await load();
    }
  });
  start.addEventListener("click", async () => {
    if (!jobId || busy || running || !modelAvailable || !review.checked
      || !picked.size || picked.size > S2ST_MAX_SELECTION) return;
    const id = jobId;
    const gen = ++generation;
    busy = true;
    lastError = "";
    message.textContent = "Starting reviewed speech segments in the local model…";
    paint();
    try {
      const answer = await request(`${base()}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          indices: [...picked].sort((a, b) => a - b),
          source_token: version,
          speech_review_confirmed: true,
        }),
      });
      if (gen !== generation || id !== jobId || !panel.open) return;
      picked.clear();
      review.checked = false;
      run = { ...answer, progress: null, results: [] };
      running = true;
    } catch (err) {
      if (gen !== generation || id !== jobId || !panel.open) return;
      run = null;
      lastError = errorText(err);
    } finally {
      if (gen === generation) {
        busy = false;
        paint();
        schedulePoll();
      }
    }
  });
  return { open, close };
}
