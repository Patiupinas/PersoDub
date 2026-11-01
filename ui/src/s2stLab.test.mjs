// Opt-in S2ST review: no source is sent to the model without explicit approval.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  S2ST_MAX_SELECTION, S2ST_PAGE_SIZE, initS2stLab,
  speechRowsHtml, s2stResultsHtml,
} from "./s2stLab.mjs";

const version = "a".repeat(64);
const candidates = [
  { index: 4, start: 36.18, end: 40.2, speaker: "SPK0", selectable: true },
  { index: 5, start: 40.8, end: 48.94, speaker: "SPK0", selectable: true },
  { index: 19, start: 154.2, end: 155.28, speaker: "SPK1", selectable: true },
  { index: 21, start: 170, end: 220, speaker: "SPK1", selectable: false },
];

function element(id) {
  return {
    id, open: false, checked: false, disabled: false,
    innerHTML: "", textContent: "", listeners: {},
    addEventListener(name, handler) { this.listeners[name] = handler; },
  };
}

function harness({ info = null, polling = null } = {}) {
  const all = new Map();
  const $ = (id) => {
    if (!all.has(id)) all.set(id, element(id));
    return all.get(id);
  };
  const timers = [];
  const clock = {
    set(callback) { timers.push(callback); return timers.length; },
    clear() {},
  };
  const calls = [];
  const apiInfo = info || {
    source_token: version, page: 0, page_size: 50, total_cues: 4,
    max_clips: 6, model_available: true, cues: candidates, run: null,
  };
  const fetchFn = async (url, options = null) => {
    calls.push({ url, options });
    let result = apiInfo;
    if (url.endsWith("/start")) {
      result = { run_id: "a1b2c3d4e5f6", status: "running" };
    } else if (url.endsWith("/status")) {
      result = polling ?? {
        run: { run_id: "a1b2c3d4e5f6", status: "done",
          results: [
            { index: 4, state: "TIMING_CANDIDATE_ONLY",
              original_audio_url: "/api/dub/jobs/project/s2st/files/a1b2c3d4e5f6/source-004.wav",
              russian_audio_url: "/api/dub/jobs/project/s2st/files/a1b2c3d4e5f6/ru-004.wav",
              preview_video_url: "/api/dub/jobs/project/s2st/files/a1b2c3d4e5f6/preview-004.mp4" },
            { index: 19, state: "REVIEW_REQUIRED",
              reasons: ["extreme_duration_expansion"],
              russian_audio_url: "/api/dub/jobs/project/s2st/files/a1b2c3d4e5f6/ru-019.wav" },
          ],
        },
      };
    }
    return { ok: true, json: async () => result };
  };
  const controller = initS2stLab({ $, fetchFn, clock });
  return {
    $, controller, calls, timers,
    async expand(jid = "project") {
      controller.open(jid);
      assert.equal(calls.length, 0);
      $("s2stLabPanel").open = true;
      $("s2stLabPanel").listeners.toggle();
      await new Promise(setImmediate);
    },
    select(index, checked = true) {
      $("s2stLabCandidates").listeners.change({
        target: {
          closest: () => ({ dataset: { s2stIndex: String(index) }, checked }),
        },
      });
    },
  };
}

test("lab is lazy and does not automatically approve or generate Qwen replacements", async () => {
  const h = harness();
  assert.equal(S2ST_PAGE_SIZE, 50);
  assert.equal(S2ST_MAX_SELECTION, 6);
  await h.expand();
  assert.equal(h.calls.length, 1);
  assert.match(h.calls[0].url, /\/s2st\?page=0$/);
  assert.equal(h.$("s2stLabStart").disabled, true);
  assert.match(h.$("s2stLabCandidates").innerHTML, /36\.18/);
  assert.match(h.$("s2stLabCandidates").innerHTML, /audio controls/);
  assert.match(h.$("s2stLabCandidates").innerHTML, /source\/4\?source_token=/);
  assert.match(h.$("s2stLabCandidates").innerHTML, /Long interval: split first/);
  assert.equal(h.$("s2stLabStatus").textContent.includes("original video is unchanged"), true);
  h.controller.close();
});

test("selected research speech requires a distinct manual confirmation", async () => {
  const h = harness();
  await h.expand();
  h.select(4);
  assert.equal(h.$("s2stLabStart").disabled, true);
  h.$("s2stLabReviewed").checked = true;
  h.$("s2stLabReviewed").listeners.change();
  assert.equal(h.$("s2stLabStart").disabled, false);
  await h.$("s2stLabStart").listeners.click();
  const startCall = h.calls.find((call) => call.url.endsWith("/start"));
  assert.ok(startCall);
  assert.deepEqual(JSON.parse(startCall.options.body), {
    indices: [4], source_token: version, speech_review_confirmed: true,
  });
  assert.equal(h.$("s2stLabStart").disabled, true);
  assert.equal(h.timers.length, 1);
  await h.timers[0]();
  assert.match(h.$("s2stLabResults").innerHTML, /Two-track MP4/);
  assert.match(h.$("s2stLabResults").innerHTML, /Review required/);
  assert.doesNotMatch(h.$("s2stLabResults").innerHTML, /input.mp4/);
  assert.equal(h.$("s2stLabStatus").textContent.includes("run complete"), true);
  h.controller.close();
});

test("changing selected cues clears approval; unselectable interval stays excluded", async () => {
  const h = harness();
  await h.expand();
  h.select(4);
  h.$("s2stLabReviewed").checked = true;
  h.$("s2stLabReviewed").listeners.change();
  assert.equal(h.$("s2stLabStart").disabled, false);
  h.select(5);
  assert.equal(h.$("s2stLabReviewed").checked, false);
  assert.equal(h.$("s2stLabStart").disabled, true);
  h.select(21);
  assert.equal(h.$("s2stLabCandidates").innerHTML.includes('data-s2st-index="21"'), true);
  assert.equal(h.$("s2stLabCandidates").innerHTML.includes("disabled"), true);
  h.select(5, false);
  h.controller.close();
});

test("model not configured only displays original review without a run", async () => {
  const h = harness({ info: {
    source_token: version, page: 0, page_size: 50, total_cues: 1,
    model_available: false, cues: candidates.slice(0, 1), run: null,
  } });
  await h.expand();
  h.select(4);
  h.$("s2stLabReviewed").checked = true;
  h.$("s2stLabReviewed").listeners.change();
  assert.equal(h.$("s2stLabStart").disabled, true);
  assert.match(h.$("s2stLabStatus").textContent, /not installed/);
  h.controller.close();
});

test("escaping protects speaker labels and does not render unsafe result links", () => {
  const html = speechRowsHtml([
    { index: 9, start: 1, end: 2, speaker: '<img src=x onerror="alert(1)">', selectable: true },
  ]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  const result = s2stResultsHtml([
    { index: 3, state: "TIMING_CANDIDATE_ONLY",
      russian_audio_url: 'javascript:alert(1)', reasons: ["<b>bad</b>"] },
  ]);
  assert.doesNotMatch(result, /javascript:/);
  assert.match(result, /&lt;b&gt;/);
});

test("closing the lab makes a pending poll unable to repaint an old job", async () => {
  const h = harness();
  await h.expand();
  h.select(4);
  h.$("s2stLabReviewed").checked = true;
  h.$("s2stLabReviewed").listeners.change();
  await h.$("s2stLabStart").listeners.click();
  const oldPoll = h.timers[0];
  h.controller.close();
  await oldPoll();
  assert.equal(h.$("s2stLabResults").innerHTML, "");
});

test("markup exposes a single embedded research section in Overdub", () => {
  const html = readFileSync(new URL("../../static/index.html", import.meta.url), "utf8");
  for (const id of [
    "s2stLabPanel", "s2stLabStatus", "s2stLabCandidates", "s2stLabReviewed",
    "s2stLabStart", "s2stLabResults", "s2stLabPage",
  ]) assert.match(html, new RegExp(`id="${id}"`));
});
