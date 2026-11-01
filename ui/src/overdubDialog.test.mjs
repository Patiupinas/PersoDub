// UI contract: AST is a suggestion, never an automatic translation action.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  ACTIONS, OVERDUB_RATE, initOverdubDialog,
  overDubRowsHtml, reviewedEvents, splitOverdubInterval,
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

function harness({ response = preview, onExport = () => {} } = {}) {
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
  const fetchFn = async (url, opts) => {
    const body = JSON.parse(opts.body);
    calls.push({ url, body });
    return {
      ok: true,
      json: async () => url.endsWith("/prepare") ? response :
        { file: "finished-overdub.mp4",
          download_url: "/api/dub/jobs/abc/overdub/files/finished-overdub.mp4" },
    };
  };
  const modal = initOverdubDialog({ $, fetchFn, onExport });
  return {
    $, modal, calls, reset: () => { globalThis.document = previousDocument; },
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
