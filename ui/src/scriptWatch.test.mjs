import test from "node:test";
import assert from "node:assert/strict";
import { scriptChecker } from "./scriptWatch.mjs";

// The server's stamp, as the next look will find it, and the table's own.
function setup({ drawn = "100", active = true } = {}) {
  const s = { server: drawn, drawn, active, refreshed: [], asked: 0 };
  globalThis.fetch = async (url) => {
    s.asked += 1;
    assert.equal(url, "/api/dub/jobs/j1/script/stamp");
    return { ok: true, json: async () => ({ stamp: s.server }) };
  };
  s.look = scriptChecker({
    getJobId: () => "j1",
    getStamp: () => s.drawn,
    refresh: async (id) => { s.refreshed.push(id); s.drawn = s.server; },
    active: () => s.active,
  });
  return s;
}

test("a script changed from outside is drawn again once its stamp holds still", async () => {
  const s = setup();
  await s.look();
  assert.deepEqual(s.refreshed, []);           // nothing changed
  s.server = "200";                            // the agent remade a voice
  await s.look();
  assert.deepEqual(s.refreshed, []);           // still moving, maybe
  await s.look();
  assert.deepEqual(s.refreshed, ["j1"]);       // the same twice: drawn again
  await s.look();
  await s.look();
  assert.deepEqual(s.refreshed, ["j1"]);       // and only once
});

test("a stamp that keeps moving is waited out", async () => {
  const s = setup();
  for (const t of ["200", "300", "400"]) { s.server = t; await s.look(); }
  assert.deepEqual(s.refreshed, []);
  await s.look();
  assert.deepEqual(s.refreshed, ["j1"]);
});

test("nothing is asked while the table is busy, being typed in or not on screen", async () => {
  const s = setup({ active: false });
  s.server = "200";
  await s.look();
  await s.look();
  assert.equal(s.asked, 0);
  assert.deepEqual(s.refreshed, []);
});

test("a script with no stamp (a read-only Perso mirror) is never asked about", async () => {
  const s = setup({ drawn: null });
  await s.look();
  assert.equal(s.asked, 0);
});
