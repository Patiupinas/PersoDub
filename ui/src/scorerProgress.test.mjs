// Scorer counters are display-only and never treated as a completion state.
import test from "node:test";
import assert from "node:assert/strict";
import { scorerProgressText } from "./scorerProgress.mjs";

test("live pronunciation scoring is shown with bounded counters", () => {
  const current = { status: "running", scorer_progress: {
    phase: "asr", done: 63, total: 128, reused: 16,
  } };
  assert.match(scorerProgressText(current), /63\/128/);
  assert.equal(scorerProgressText({ ...current, status: "done" }), "");
  assert.equal(scorerProgressText({ ...current, scorer_progress: {
    phase: "asr", done: 129, total: 128, reused: 0,
  } }), "");
  assert.equal(scorerProgressText({ ...current, scorer_progress: {
    phase: "asr", done: 3, total: 128, reused: 5,
  } }), "");
  assert.equal(scorerProgressText({ status: "running" }), "");
  assert.equal(scorerProgressText({ ...current, scorer_progress: {
    phase: "unknown", done: 3, total: 128, reused: 0,
  } }), "");
});
