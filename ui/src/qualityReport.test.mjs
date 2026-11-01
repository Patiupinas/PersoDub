// Finished media quality report: read-only, cached per job, and source-aware.
import test from "node:test";
import assert from "node:assert/strict";
import { initQualityReport, qualityIssueText, qualitySummary } from "./qualityReport.mjs";

const baseReport = {
  schema_version: 1, status: "review_required", output_file: "dubbed.mp4",
  declared_audio_mode: "replace", expected_audio_mode: "replace", actual_audio_streams: 1,
  issues: [
    { code: "speech_audio_clipped", count: 1, total_cut_seconds: 1.461 },
    { code: "timing_slot_overruns", count: 5, total_excess_seconds: 3.14 },
  ],
  human_review_remaining: ["Russian accent and pronunciation"],
};

function makeElement(id) {
  return {
    id, hidden: false, open: false, textContent: "", innerHTML: "",
    disabled: false, listeners: {},
    addEventListener(event, handler) { this.listeners[event] = handler; },
  };
}

function harness({ fetchFn = null } = {}) {
  const elements = new Map();
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };
  const calls = [];
  const fetcher = fetchFn || (async (url) => {
    calls.push(url);
    return { ok: true, json: async () => baseReport };
  });
  return { $, calls, view: initQualityReport({ $, fetchFn: fetcher }) };
}

function job(id = "j1") {
  return { id, status: "done", dub_mode: "local", kind: "dub" };
}

test("quality opens once per job, describes objective defects without perceptual PASS", async () => {
  const h = harness();
  await h.view.show(job());
  assert.equal(h.$("qualityAudit").hidden, false);
  assert.equal(h.$("qualityAudit").open, false);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0], "/api/dub/jobs/j1/quality");
  assert.match(h.$("qualityAuditStatus").textContent, /2 issue/);
  assert.match(h.$("qualityAuditScope").textContent, /replace.*1 audio/);
  assert.match(h.$("qualityAuditIssues").innerHTML, /1\.461/);
  assert.match(h.$("qualityAuditIssues").innerHTML, /3\.14/);
  assert.match(h.$("qualityAuditHuman").textContent, /Russian accent/);
  await h.view.show(job());
  assert.equal(h.calls.length, 1, "polling does not rerun acoustic diagnostics");
  await h.$("qualityAuditRefresh").listeners.click();
  assert.equal(h.calls.length, 2, "explicit recheck refreshes diagnostics");
});

test("a separate Overdub file gets its own quality report and stays unverified by ear", async () => {
  const calls = [];
  const h = harness({ fetchFn: async (url) => {
    calls.push(url);
    return {
      ok: true, json: async () => url.includes("?file=") ? {
        ...baseReport, status: "not_perceptually_verified", issues: [],
        output_file: "finished-overdub-2.mp4", declared_audio_mode: "overdub",
        expected_audio_mode: "overdub", actual_audio_streams: 2,
      } : baseReport,
    };
  } });
  await h.view.show(job());
  await h.view.showOverdub("j1", "finished-overdub-2.mp4");
  assert.equal(h.$("qualityAudit").open, true);
  assert.equal(
    calls[1],
    "/api/dub/jobs/j1/quality?file=finished-overdub-2.mp4",
  );
  assert.match(h.$("qualityAuditStatus").textContent, /listening not verified/);
  assert.match(h.$("qualityAuditScope").textContent, /2 audio streams/);
  assert.equal(h.$("qualityAuditIssues").innerHTML, "");
  await h.view.show(job());
  assert.equal(calls.length, 2, "polling does not revert the reviewed export selection");
});

test("changing jobs discards a late report for the prior job", async () => {
  const answers = [];
  const h = harness({ fetchFn: (url) => new Promise((resolve) => {
    answers.push({ url, resolve });
  }) });
  const old = h.view.show(job("old"));
  const next = h.view.show(job("new"));
  answers[1].resolve({ ok: true, json: async () => ({
    ...baseReport, issues: [], status: "not_perceptually_verified",
  }) });
  await next;
  answers[0].resolve({ ok: true, json: async () => baseReport });
  await old;
  assert.match(h.$("qualityAuditStatus").textContent, /No automated issues/);
  assert.equal(h.$("qualityAuditIssues").innerHTML, "");
  h.view.show({ id: "in-progress", status: "running" });
  assert.equal(h.$("qualityAudit").hidden, true);
});

test("API failure stays visible and offers recheck", async () => {
  const h = harness({ fetchFn: async () => ({
    ok: false, json: async () => ({ detail: "File unavailable" }),
  }) });
  await h.view.show(job());
  assert.match(h.$("qualityAuditStatus").textContent, /unavailable/);
  assert.match(h.$("qualityAuditScope").textContent, /File unavailable/);
  assert.equal(h.$("qualityAuditRefresh").disabled, false);
  assert.equal(h.view.showOverdub("wrong", "finished-overdub.mp4"), undefined);
  assert.equal(h.view.showOverdub("j1", "../input.mp4"), undefined);
});

test("issue strings are escaped before DOM insertion", () => {
  const h = harness();
  assert.match(qualityIssueText({ code: "speaker_reference_too_short", speaker: "S1", audio_seconds: 0.9 }), /0\.9/);
  assert.match(qualitySummary({ status: "not_perceptually_verified", issues: [] }), /not verified/);
  assert.equal(h.$("qualityAudit").hidden, false);
});
