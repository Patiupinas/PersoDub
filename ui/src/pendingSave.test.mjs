// Run with: node --test ui/src/pendingSave.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { pendingSave } from "./pendingSave.mjs";

function harness(t) {
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const timers = new Map();
  let next = 1;
  globalThis.setTimeout = (fn) => { timers.set(next, fn); return next++; };
  globalThis.clearTimeout = (id) => { timers.delete(id); };
  t.after(() => Object.assign(globalThis, real));
  const sent = [];
  const save = pendingSave((id, body) => sent.push([id, body]));
  const tick = () => { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } };
  return { save, sent, tick };
}

test("a run of changes on one project is saved once, with the last of them", (t) => {
  const h = harness(t);
  h.save.schedule("A", { size: 110 });
  h.save.schedule("A", { size: 120 });
  assert.deepEqual(h.sent, []);
  h.tick();
  assert.deepEqual(h.sent, [["A", { size: 120 }]]);
  h.tick();
  assert.equal(h.sent.length, 1);
});

test("a change still waiting when another project is opened goes to the project it was made on", (t) => {
  const h = harness(t);
  const styleA = { preset: "neon" };
  h.save.schedule("A", styleA);
  // Project B is opened and its own style measured and saved before A's
  // moment was up.
  h.save.schedule("B", { preset: "clean" });
  assert.deepEqual(h.sent, [["A", styleA]], "A's change is not dropped, and not sent to B");
  h.tick();
  assert.deepEqual(h.sent, [["A", styleA], ["B", { preset: "clean" }]]);
});

test("flush sends what is waiting now, and nothing twice", (t) => {
  const h = harness(t);
  h.save.flush();
  assert.deepEqual(h.sent, []);
  h.save.schedule("A", 1);
  h.save.flush();
  h.tick();
  assert.deepEqual(h.sent, [["A", 1]]);
});
