import test from "node:test";
import assert from "node:assert/strict";
import {
  getDraft, setDraft, clearDraft, setRanges, normalizeRanges,
  keptSeconds, isWhole, onDraftChange,
} from "./draft.mjs";

const video = { downloadId: "d1", name: "a.mp4", duration: 10, videoUrl: "/v" };

test("a new draft keeps the whole video and is on the timeline at once", () => {
  clearDraft();
  const d = setDraft(video);
  assert.deepEqual(d.ranges, [[0, 10]]);
  assert.equal(d.onTimeline, true);
  assert.equal(isWhole(), true);
  assert.equal(keptSeconds(), 10);
});

test("a new draft tells the listeners", () => {
  clearDraft();
  const seen = [];
  const off = onDraftChange((d) => seen.push(d && d.onTimeline));
  setDraft(video);
  off();
  setDraft(video);
  assert.deepEqual(seen, [true]);
});

test("kept parts are sorted, clamped, joined, and slivers dropped", () => {
  assert.deepEqual(normalizeRanges([[4.8, 12], [0, 2.4], [2.4, 2.45], [5, 6]], 10), [[0, 2.4], [4.8, 10]]);
  assert.deepEqual(normalizeRanges([[3, 1]], 10), [[1, 3]]);
});

test("cutting the middle out leaves two parts and fewer seconds", () => {
  setDraft(video);
  setRanges([[0, 2.4], [4.8, 10]]);
  assert.equal(isWhole(), false);
  assert.ok(Math.abs(keptSeconds() - 7.6) < 1e-9);
});

test("no draft: nothing to change, nothing kept", () => {
  clearDraft();
  setRanges([[0, 1]]);
  assert.equal(getDraft(), null);
  assert.equal(keptSeconds(), 0);
});

test("a kept draft comes back on the canvas it was left on; a new one starts on the original", () => {
  assert.equal(setDraft({ downloadId: "d1", name: "a.mp4", duration: 10, videoUrl: "/v" }).ratio, "original");
  assert.equal(setDraft({ downloadId: "d1", name: "a.mp4", duration: 10, videoUrl: "/v", ratio: "9:16" }).ratio, "9:16");
  clearDraft();
});
