// Run with: node --test ui/src/keptDrafts.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readKept, keepDraft, dropKept, draftMark } from "./keptDrafts.mjs";

function storage(initial = {}) {
  const m = new Map(Object.entries(initial));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

const DRAFT = { downloadId: "0a1b2c3d", name: "street-food.mp4", duration: 52.6, videoUrl: "/v",
                onTimeline: true, ranges: [[0, 20], [31.6, 52.6]], ratio: "9:16" };

test("a kept draft is its video, its name, its length, its cuts and its shape", () => {
  const s = storage();
  assert.deepEqual(readKept(s), []);
  const kept = keepDraft(s, DRAFT);
  assert.deepEqual(kept, [{ downloadId: "0a1b2c3d", name: "street-food.mp4", duration: 52.6,
                            ranges: [[0, 20], [31.6, 52.6]], ratio: "9:16" }]);
  // Read back the same from storage, as the next launch reads it.
  assert.deepEqual(readKept(s), kept);
});

test("keeping the same draft again moves it to the front with its new cuts; another is added", () => {
  const s = storage();
  keepDraft(s, DRAFT);
  keepDraft(s, { ...DRAFT, downloadId: "ffffffff", name: "b.mp4", ranges: [[0, 52.6]] });
  const kept = keepDraft(s, { ...DRAFT, ranges: [[0, 10]] });
  assert.deepEqual(kept.map((k) => k.downloadId), ["0a1b2c3d", "ffffffff"]);
  assert.deepEqual(kept[0].ranges, [[0, 10]]);
});

test("a dubbed or deleted draft is let go, and the others stay", () => {
  const s = storage();
  keepDraft(s, DRAFT);
  keepDraft(s, { ...DRAFT, downloadId: "ffffffff" });
  assert.deepEqual(dropKept(s, "0a1b2c3d").map((k) => k.downloadId), ["ffffffff"]);
  assert.deepEqual(readKept(s).map((k) => k.downloadId), ["ffffffff"]);
});

test("what cannot be a draft is not kept, and damaged storage reads as nothing", () => {
  const s = storage();
  assert.deepEqual(keepDraft(s, { name: "no video yet" }), []);
  assert.deepEqual(keepDraft(s, { ...DRAFT, downloadId: "../../etc" }), []);
  assert.deepEqual(readKept(storage({ "persodub.drafts": "{not json" })), []);
  assert.deepEqual(readKept(storage({ "persodub.drafts": '{"a":1}' })), []);
  // Cuts that make no sense come back as the whole video.
  const odd = readKept(storage({ "persodub.drafts":
    JSON.stringify([{ downloadId: "0a1b2c3d", name: "x", duration: 10, ranges: "all" }]) }));
  assert.deepEqual(odd[0].ranges, [[0, 10]]);
  assert.equal(odd[0].ratio, "original");
});

test("a draft's mark changes with its cuts and its canvas, and with nothing else", () => {
  const mark = draftMark(DRAFT);
  assert.equal(draftMark({ ...DRAFT, name: "other.mp4", videoUrl: "/x" }), mark);
  assert.notEqual(draftMark({ ...DRAFT, ranges: [[0, 1]] }), mark);
  assert.notEqual(draftMark({ ...DRAFT, ratio: "1:1" }), mark);
  assert.equal(draftMark(null), "");
});

test("only the newest twelve are kept", () => {
  const s = storage();
  for (let i = 0; i < 15; i++) keepDraft(s, { ...DRAFT, downloadId: i.toString(16).padStart(8, "0") });
  const kept = readKept(s);
  assert.equal(kept.length, 12);
  assert.equal(kept[0].downloadId, "0000000e");
});
