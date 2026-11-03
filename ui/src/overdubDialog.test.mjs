// UI contract: AST is a suggestion, never an automatic translation action.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  ACTIONS, OVERDUB_RATE, initOverdubDialog,
  nextPossibleExerciseIndex, overDubRowsHtml, restoredDraftRows,
  reviewedEvents, splitOverdubInterval,
} from "./overdubDialog.mjs";

const FRAME = OVERDUB_RATE;
const rows = [
  { start_frame: 0, end_frame: FRAME, action: "REVIEW",
    suggested_action: "TRANSLATE", hint: "speech", score: 0.88 },
  { start_frame: FRAME, end_frame: 2 * FRAME, action: "REVIEW",
    suggested_action: "PRESERVE", hint: "singing", score: 0.84 },
];
const preview = {
  source_wav_sha256: "a".repeat(64), total_frames: 2 * FRAME,
  sample_rate: FRAME, ast_available: true, analysis: "ast_observations",
  suggestions: rows,
};

function element(id) {
  const classes = new Set();
  return {
    id, value: "", checked: false, disabled: false, hidden: false,
    textContent: "", listeners: {}, children: [], currentTime: 0, src: "",
    playCalls: 0, pauseCalls: 0, loadCalls: 0,
    play() { this.playCalls += 1; return Promise.resolve(); },
    pause() { this.pauseCalls += 1; },
    load() { this.loadCalls += 1; },
    removeAttribute(name) { if (name === "src") this.src = ""; },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    appendChild(node) { this.children.push(node); },
    set innerHTML(value) { this._html = value; },
    get innerHTML() { return this._html || ""; },
  };
}

function harness({ response = preview, onExport = () => {}, onRegenerate = () => {} } = {}) {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: element };
  const all = new Map();
  const $ = (name) => {
    if (!all.has(name)) all.set(name, element(name));
    return all.get(name);
  };
  $("overdubOriginalDb").value = "-16";
  $("overdubTranslationDb").value = "-2";
  $("overdubFadeMs").value = "300";
  const calls = [];
  let prepared = response;
  const fetchFn = async (url, opts) => {
    const body = JSON.parse(opts.body);
    calls.push({ url, body });
    return {
      ok: true,
      json: async () => url.endsWith("/prepare") ? prepared :
        url.endsWith("/draft") ? { saved: true, revision: "c".repeat(64), review_confirmed: false } :
        url.endsWith("/regenerate") ? { job_id: "1234abcd", approved_for_tts: 1 } :
        { file: "finished-overdub.mp4",
          download_url: "/api/dub/jobs/abc/overdub/files/finished-overdub.mp4" },
    };
  };
  const modal = initOverdubDialog({ $, fetchFn, onExport, onRegenerate });
  return {
    $, modal, calls, setResponse: (next) => { prepared = next; },
    reset: () => { globalThis.document = previousDocument; },
  };
}

test("model hints only populate suggestions; all actions begin REVIEW", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubOverlay").classList.contains("open"), true);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0].body, { analyze: false });
  assert.equal(h.$("overdubExport").disabled, true);
  const markup = h.$("overdubList").innerHTML;
  assert.match(markup, /speech · Model score 0\.88/);
  assert.match(markup, /singing · Model score 0\.84/);
  assert.equal([...markup.matchAll(/<option value="REVIEW" selected>/g)].length, 2);
});

test("applying machine proposals requires separate confirmation before export", async (t) => {
  const emitted = [];
  const h = harness({ onExport: (jobId, filename) => emitted.push([jobId, filename]) });
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubUseHints").listeners.click();
  assert.equal(h.$("overdubExport").disabled, true);
  const values = [...h.$("overdubList").innerHTML.matchAll(/<option value="(TRANSLATE|PRESERVE)" selected>/g)]
    .map((match) => match[1]);
  assert.deepEqual(values, ["TRANSLATE", "PRESERVE"]);
  h.$("overdubReviewed").checked = true;
  h.$("overdubReviewed").listeners.change();
  assert.equal(h.$("overdubExport").disabled, false);
  await h.$("overdubExport").listeners.click();
  const submission = h.calls[1];
  assert.equal(submission.body.review_confirmed, true);
  assert.deepEqual(submission.body.events, [
    { start_frame: 0, end_frame: FRAME, action: "TRANSLATE" },
    { start_frame: FRAME, end_frame: 2 * FRAME, action: "PRESERVE" },
  ]);
  assert.equal(submission.body.original_speech_db, -16);
  assert.equal(h.$("overdubResult").hidden, false);
  assert.match(h.$("overdubResult").children[0].href, /finished-overdub\.mp4/);
  assert.deepEqual(emitted, [["abc", "finished-overdub.mp4"]]);
});

test("editing an event invalidates confirmation and does not edit neighboring boundaries", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubReviewed").checked = true;
  h.$("overdubReviewed").listeners.change();
  assert.equal(h.$("overdubExport").disabled, false);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "1" }, value: "PRESERVE" }) },
  });
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  h.$("overdubSplitAt").value = "0.5";
  h.$("overdubSplit").listeners.click();
  assert.equal([...h.$("overdubList").innerHTML.matchAll(/data-od-index/g)].length, 3);
  assert.equal(h.$("overdubExport").disabled, true);
});

test("AST analysis explicitly requested and does not auto-approve the result", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  await h.$("overdubAnalyze").listeners.click();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[1].body, { analyze: true });
  assert.equal(h.$("overdubExport").disabled, true);
});

test("unconfigured AST is reflected in UI without blocking manual segmentation", async (t) => {
  const h = harness({ response: { ...preview, ast_available: false, analysis: "model_not_configured" } });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubAnalyze").disabled, true);
  assert.equal(h.$("overdubSplit").disabled, false);
  assert.match(h.$("overdubStatus").textContent, /not configured/);
});

test("pure editor rejects bad boundaries and unapproved actions", () => {
  assert.deepEqual(ACTIONS, ["REVIEW", "TRANSLATE", "PRESERVE"]);
  const modified = splitOverdubInterval(rows, 0.5);
  assert.equal(modified.length, 3);
  assert.equal(modified[0].end_frame, FRAME / 2);
  assert.equal(modified[1].start_frame, FRAME / 2);
  assert.equal(rows.length, 2);
  assert.throws(() => splitOverdubInterval(rows, 1), /inside/);
  assert.throws(() => splitOverdubInterval(rows, -1), /valid/);
  assert.throws(() => reviewedEvents([{ start_frame: 0, end_frame: FRAME, action: "DELETE" }]), /intervals/);
  assert.throws(() => reviewedEvents([
    { start_frame: 0, end_frame: FRAME, action: "REVIEW" },
    { start_frame: FRAME - 1, end_frame: 2 * FRAME, action: "PRESERVE" },
  ]), /intervals/);
  assert.equal(reviewedEvents(rows)[0].action, "REVIEW");
  assert.match(overDubRowsHtml(rows), /Keep original \/ vocal exercise/);
});

test("dialog markup exposes Overdub only through the existing export screen", () => {
  const page = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
  for (const id of [
    "exportOverdubAction", "exportOverdubBtn", "overdubOverlay", "overdubAnalyze",
    "overdubList", "overdubReviewed", "overdubExport", "overdubClose",
  ]) assert.match(page, new RegExp(`id="${id}"`));
});

test("multi-hour Overdub review keeps a bounded DOM page and stable global actions", async (t) => {
  const segments = 6 * 3600 / 2;
  const hints = Array.from({ length: segments }, (_, i) => ({
    start_frame: i * 2 * FRAME, end_frame: (i + 1) * 2 * FRAME,
    action: "REVIEW", suggested_action: i % 2 ? "PRESERVE" : "TRANSLATE",
    hint: i % 2 ? "singing" : "speech", score: 0.9,
  }));
  const h = harness({
    response: { ...preview, total_frames: segments * 2 * FRAME, suggestions: hints },
  });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubPageLabel").textContent, "1-100 / 10800");
  assert.equal(h.$("overdubPagePrev").disabled, true);
  assert.equal(h.$("overdubPageNext").disabled, false);
  assert.equal([...h.$("overdubList").innerHTML.matchAll(/data-od-index/g)].length, 100);
  assert.doesNotMatch(h.$("overdubList").innerHTML, /data-od-index="101"/);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "3" }, value: "PRESERVE" }) },
  });
  h.$("overdubPageNext").listeners.click();
  assert.equal(h.$("overdubPageLabel").textContent, "101-200 / 10800");
  assert.match(h.$("overdubList").innerHTML, /data-od-index="101"/);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "102" }, value: "TRANSLATE" }) },
  });
  h.$("overdubPagePrev").listeners.click();
  assert.match(h.$("overdubList").innerHTML, /data-od-index="3"/);
  assert.match(h.$("overdubList").innerHTML, /<option value="PRESERVE" selected>/);
  assert.equal([...h.$("overdubList").innerHTML.matchAll(/data-od-index/g)].length, 100);
  // Every reviewed action remains in the full source-clock plan on export.
  h.$("overdubReviewed").checked = true;
  h.$("overdubReviewed").listeners.change();
  await h.$("overdubExport").listeners.click();
  assert.equal(h.calls[1].body.events.length, segments);
  assert.equal(h.calls[1].body.events[3].action, "PRESERVE");
  assert.equal(h.calls[1].body.events[102].action, "TRANSLATE");
  assert.equal(h.calls[1].body.events.at(-1).end_frame, 6 * 3600 * FRAME);
});

test("A4 review plays the original source at event boundaries without approving it", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("job with spaces");
  const video = h.$("overdubSourcePlayer");
  assert.equal(video.src, "/api/dub/jobs/job%20with%20spaces/overdub/source");
  assert.match(h.$("overdubList").innerHTML, /data-od-play="1"/);

  const playRow = (index) => h.$("overdubList").listeners.click({
    target: { closest: () => ({ dataset: { odPlay: String(index) } }) },
  });
  playRow(1);
  assert.equal(video.currentTime, 0.6);
  assert.equal(video.playCalls, 1);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);

  video.currentTime = 1.9;
  video.listeners.timeupdate();
  const paused = video.pauseCalls;
  video.currentTime = 2.0;
  video.listeners.timeupdate();
  assert.equal(video.pauseCalls, paused + 1);

  h.modal.close();
  assert.equal(video.src, "");
  assert.equal(video.loadCalls, 1);
  assert.equal(h.calls.length, 1);
});

test("A4 event seek remains source-clock accurate after splitting an interval", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubSplitAt").value = "1.25";
  h.$("overdubSplit").listeners.click();
  assert.equal([...h.$("overdubList").innerHTML.matchAll(/data-od-play/g)].length, 3);
  h.$("overdubList").listeners.click({
    target: { closest: () => ({ dataset: { odPlay: "2" } }) },
  });
  assert.equal(h.$("overdubSourcePlayer").currentTime, 0.85);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
});


test("exercise navigator prioritizes unreviewed non-speech hints and wraps", () => {
  const events = [
    { hint: "speech", action: "REVIEW" },
    { hint: "singing", action: "PRESERVE" },
    { hint: "coughing", action: "REVIEW" },
    { hint: "breathing", action: "REVIEW" },
    { hint: "unknown", action: "REVIEW" },
  ];
  assert.equal(nextPossibleExerciseIndex(events), 2);
  assert.equal(nextPossibleExerciseIndex(events, 2), 3);
  assert.equal(nextPossibleExerciseIndex(events, 3), 2);
  assert.equal(nextPossibleExerciseIndex(events.map(row => ({ ...row, action: "PRESERVE" }))), -1);
  assert.equal(nextPossibleExerciseIndex([]), -1);
});

test("possible exercise button jumps to source without applying classifier action", async (t) => {
  const hints = Array.from({ length: 230 }, (_, i) => ({
    start_frame: i * FRAME, end_frame: (i + 1) * FRAME, action: "REVIEW",
    suggested_action: "TRANSLATE", hint: "speech", score: 0.8,
  }));
  hints[121] = { ...hints[121], hint: "coughing", suggested_action: "PRESERVE" };
  hints[128] = { ...hints[128], hint: "breathing", suggested_action: "PRESERVE" };
  hints[215] = { ...hints[215], hint: "singing", suggested_action: "PRESERVE", action: "PRESERVE" };
  const h = harness({
    response: { ...preview, total_frames: 230 * FRAME, suggestions: hints },
  });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubNextExercise").disabled, false);
  assert.equal(h.$("overdubReviewed").checked, false);

  h.$("overdubNextExercise").listeners.click();
  assert.equal(h.$("overdubPageLabel").textContent, "101-200 / 230");
  assert.match(h.$("overdubList").innerHTML, /data-od-index="121"/);
  assert.equal(h.$("overdubSourcePlayer").currentTime, 120.6);
  assert.equal(h.$("overdubSourcePlayer").playCalls, 1);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.match(h.$("overdubStatus").textContent, /Possible vocal exercise near 121.00s/);

  h.$("overdubNextExercise").listeners.click();
  assert.equal(h.$("overdubSourcePlayer").currentTime, 127.6);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  // Model suggestions remain unapproved; only an explicit human change alters actions.
  assert.equal(h.calls.length, 1);
  assert.match(h.$("overdubList").innerHTML, /data-od-index="128"/);
});


test("A4 rebuild starts a separate job with confirmed exact source decisions", async (t) => {
  const opened = [];
  const h = harness({ onRegenerate: id => opened.push(id) });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubRegenerate").disabled, true);
  h.$("overdubUseHints").listeners.click();
  h.$("overdubReviewed").checked = true;
  h.$("overdubReviewed").listeners.change();
  assert.equal(h.$("overdubRegenerate").disabled, false);
  await h.$("overdubRegenerate").listeners.click();
  assert.deepEqual(opened, ["1234abcd"]);
  assert.equal(h.$("overdubOverlay").classList.contains("open"), false);
  assert.equal(h.calls.length, 2);
  assert.match(h.calls[1].url, /\/overdub\/regenerate$/);
  assert.deepEqual(h.calls[1].body.events, [
    { start_frame: 0, end_frame: FRAME, action: "TRANSLATE" },
    { start_frame: FRAME, end_frame: 2 * FRAME, action: "PRESERVE" },
  ]);
  assert.equal(h.calls[1].body.review_confirmed, true);
  assert.equal(h.calls[1].body.source_wav_sha256, preview.source_wav_sha256);
  assert.equal(h.calls[1].body.original_speech_db, -16);
  assert.equal(h.$("overdubSourcePlayer").src, "");
});

test("review changes disable both reuse and fresh synthesis", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubReviewed").checked = true;
  h.$("overdubReviewed").listeners.change();
  assert.equal(h.$("overdubExport").disabled, false);
  assert.equal(h.$("overdubRegenerate").disabled, false);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "1" }, value: "PRESERVE" }) },
  });
  assert.equal(h.$("overdubExport").disabled, true);
  assert.equal(h.$("overdubRegenerate").disabled, true);
});

test("secondary AST singing evidence opens review even with speech as top class", async (t) => {
  const hints = [
    { start_frame: 0, end_frame: 2 * FRAME,
      action: "REVIEW", suggested_action: "TRANSLATE",
      hint: "speech", score: 0.82, singing_score: 0.006 },
    { start_frame: 2 * FRAME, end_frame: 4 * FRAME,
      action: "REVIEW", suggested_action: "REVIEW",
      hint: "speech", score: 0.34, singing_score: 0.146299 },
    { start_frame: 4 * FRAME, end_frame: 6 * FRAME,
      action: "REVIEW", suggested_action: "TRANSLATE",
      hint: "speech", score: 0.63, singing_score: 0.01 },
  ];
  assert.equal(nextPossibleExerciseIndex(hints), 1);
  const h = harness({ response: {
    ...preview, total_frames: 6 * FRAME, suggestions: hints,
  } });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubNextExercise").disabled, false);
  assert.match(h.$("overdubList").innerHTML, /Singing score 0\.15/);
  h.$("overdubNextExercise").listeners.click();
  assert.equal(h.$("overdubSourcePlayer").currentTime, 1.6);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  assert.equal(h.$("overdubRegenerate").disabled, true);
  // Applying the generic model proposals may not promote this mixed cue.
  h.$("overdubUseHints").listeners.click();
  assert.match(h.$("overdubList").innerHTML, /<option value="REVIEW" selected>/);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.calls.length, 1);
});


test("low secondary singing scores do not replace original non-speech review hints", () => {
  const hints = [
    { hint: "speech", action: "REVIEW", suggested_action: "TRANSLATE", singing_score: 0.009 },
    { hint: "coughing", action: "REVIEW", suggested_action: "PRESERVE", singing_score: 0.012 },
    { hint: "speech", action: "REVIEW", suggested_action: "TRANSLATE", singing_score: 0.025 },
  ];
  assert.equal(nextPossibleExerciseIndex(hints), 1);
  hints[1].action = "PRESERVE";
  assert.equal(nextPossibleExerciseIndex(hints), -1);
});

// The same source-bound A4 decision partition survives navigation and reopening.
test("save progress stores a draft without approving a split vocal interval", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubSplitAt").value = "1.25";
  h.$("overdubSplit").listeners.click();
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "2" }, value: "PRESERVE" }) },
  });
  h.$("overdubOriginalDb").value = "-12";
  h.$("overdubOriginalDb").listeners.change();
  assert.equal(h.$("overdubSaveDraft").disabled, false);
  await h.$("overdubSaveDraft").listeners.click();
  assert.equal(h.calls.length, 2);
  assert.match(h.calls[1].url, /\/overdub\/draft$/);
  assert.deepEqual(h.calls[1].body.events, [
    { start_frame: 0, end_frame: FRAME, action: "REVIEW" },
    { start_frame: FRAME, end_frame: 1.25*FRAME, action: "REVIEW" },
    { start_frame: 1.25*FRAME, end_frame: 2*FRAME, action: "PRESERVE" },
  ]);
  assert.equal(h.calls[1].body.expected_revision, null);
  assert.equal(h.calls[1].body.original_speech_db, -12);
  assert.equal(h.calls[1].body.review_confirmed, undefined);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  assert.equal(h.$("overdubSaveDraft").disabled, true);
  assert.match(h.$("overdubStatus").textContent, /saved/i);
});

test("resume draft retains manual boundaries, gains, and still requires confirmation", async (t) => {
  const saved = {
    events: [
      { start_frame: 0, end_frame: FRAME / 2, action: "TRANSLATE" },
      { start_frame: FRAME / 2, end_frame: FRAME, action: "PRESERVE" },
      { start_frame: FRAME, end_frame: 2*FRAME, action: "REVIEW" },
    ],
    original_speech_db: -9, dub_speech_db: -5, fade_ms: 150,
    review_confirmed: false,
  };
  const h = harness({ response: { ...preview, review_draft: saved, draft_revision: "d".repeat(64) } });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubList").innerHTML.match(/data-od-index/g).length, 3);
  assert.match(h.$("overdubList").innerHTML, /<option value="PRESERVE" selected>/);
  assert.equal(h.$("overdubOriginalDb").value, "-9");
  assert.equal(h.$("overdubTranslationDb").value, "-5");
  assert.equal(h.$("overdubFadeMs").value, "150");
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "2" }, value: "PRESERVE" }) },
  });
  await h.$("overdubSaveDraft").listeners.click();
  assert.equal(h.calls[1].body.expected_revision, "d".repeat(64));
});

test("closing a changed review saves it before releasing the original player", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "1" }, value: "PRESERVE" }) },
  });
  assert.equal(h.$("overdubOverlay").classList.contains("open"), true);
  await h.$("overdubClose").listeners.click();
  assert.equal(h.calls.length, 2);
  assert.match(h.calls[1].url, /\/overdub\/draft$/);
  assert.equal(h.$("overdubOverlay").classList.contains("open"), false);
  assert.equal(h.$("overdubSourcePlayer").src, "");
});

test("new AST observations cannot erase split or manually preserved A4 actions", async (t) => {
  const h = harness();
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "1" }, value: "PRESERVE" }) },
  });
  await h.$("overdubAnalyze").listeners.click();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[1].body, { analyze: true });
  assert.match(h.$("overdubList").innerHTML, /<option value="PRESERVE" selected>/);
  assert.equal(h.$("overdubReviewed").checked, false);
});

test("stale source drafts are not applied to a changed original recording", async (t) => {
  const h = harness({ response: {
    ...preview, review_draft: null,
    draft_stale: true, draft_revision: "e".repeat(64),
  } });
  t.after(h.reset);
  await h.modal.open("abc");
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal((h.$("overdubList").innerHTML.match(/<option value="REVIEW" selected>/g) || []).length, 2);
  assert.match(h.$("overdubStatus").textContent, /different source/i);
  h.$("overdubList").listeners.change({
    target: { closest: () => ({ dataset: { odIndex: "1" }, value: "PRESERVE" }) },
  });
  await h.$("overdubSaveDraft").listeners.click();
  assert.equal(h.calls[1].body.expected_revision, "e".repeat(64));
});

test("source and translated transcript follow original audio playback without changing A4", async (t) => {
  const cues = [{ start: 0.2, end: 1.0, text: "<source> & breath" }];
  const translations = [{ start: 0.2, end: 1.0, text: "Russian draft" }];
  const h = harness({ response: {
    ...preview, source_cues: cues, translated_cues: translations,
  } });
  t.after(h.reset);
  await h.modal.open("abc");
  h.$("overdubList").listeners.click({
    target: { closest: () => ({ dataset: { odPlay: "0" } }) },
  });
  assert.match(h.$("overdubSourceTranscript").textContent, /<source> & breath/);
  assert.match(h.$("overdubTranslationTranscript").textContent, /Russian draft/);
  assert.equal(h.$("overdubReviewed").checked, false);
  assert.equal(h.$("overdubExport").disabled, true);
  h.$("overdubList").listeners.click({
    target: { closest: () => ({ dataset: { odPlay: "1" } }) },
  });
  assert.equal(h.$("overdubSourceTranscript").textContent, "");
  assert.equal(h.$("overdubTranslationTranscript").textContent, "");
  h.modal.close();
  assert.equal(h.$("overdubSourceTranscript").textContent, "");
  assert.equal(h.$("overdubTranslationTranscript").textContent, "");
});

test("a refreshed AST grid overlays source-bound decisions without discarding boundaries", () => {
  const sourceDecisions = [
    { start_frame: 0, end_frame: FRAME / 2, action: "TRANSLATE" },
    { start_frame: FRAME / 2, end_frame: FRAME, action: "PRESERVE" },
    { start_frame: FRAME, end_frame: 2 * FRAME, action: "REVIEW" },
  ];
  const newModelBins = [
    { start_frame: 0, end_frame: 0.75 * FRAME, action: "REVIEW",
      hint: "speech", suggested_action: "TRANSLATE", score: 0.9 },
    { start_frame: 0.75 * FRAME, end_frame: 1.5 * FRAME, action: "REVIEW",
      hint: "singing", suggested_action: "PRESERVE", score: 0.5 },
    { start_frame: 1.5 * FRAME, end_frame: 2 * FRAME, action: "REVIEW",
      hint: "speech", suggested_action: "TRANSLATE", score: 0.9 },
  ];
  const merged = restoredDraftRows(newModelBins, sourceDecisions);
  assert.deepEqual(merged.map((r) => [r.start_frame / FRAME, r.end_frame / FRAME, r.action]), [
    [0, 0.5, "TRANSLATE"], [0.5, 0.75, "PRESERVE"],
    [0.75, 1.0, "PRESERVE"], [1.0, 1.5, "REVIEW"], [1.5, 2, "REVIEW"],
  ]);
  assert.equal(nextPossibleExerciseIndex(merged), 3);
  assert.equal(merged[3].hint, "singing");
  assert.equal(merged[3].suggested_action, "PRESERVE");
  assert.deepEqual(merged.map(x => x.action), [
    "TRANSLATE", "PRESERVE", "PRESERVE", "REVIEW", "REVIEW",
  ]);
  assert.deepEqual(sourceDecisions, [
    { start_frame: 0, end_frame: FRAME / 2, action: "TRANSLATE" },
    { start_frame: FRAME / 2, end_frame: FRAME, action: "PRESERVE" },
    { start_frame: FRAME, end_frame: 2 * FRAME, action: "REVIEW" },
  ]);
});

test("source review replay refuses mismatched hint clocks instead of dropping edits", () => {
  assert.throws(() => restoredDraftRows([
    { start_frame: 0, end_frame: FRAME, action: "REVIEW" },
  ], [
    { start_frame: 0, end_frame: 2 * FRAME, action: "PRESERVE" },
  ]), /source clock/);
});
