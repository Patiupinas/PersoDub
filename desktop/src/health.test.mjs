import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { getFreePort } from "./freePort.js";
import { waitForHealth } from "./health.js";

function serveJson(port, handler) {
  const srv = createServer((req, res) => {
    const body = handler();
    res.writeHead(body === null ? 503 : 200, { "content-type": "application/json" });
    res.end(JSON.stringify(body ?? {}));
  });
  return new Promise((resolve) => srv.listen(port, "127.0.0.1", () => resolve(srv)));
}

test("resolves once predicate is satisfied", async () => {
  const port = await getFreePort();
  let calls = 0;
  const srv = await serveJson(port, () => (++calls >= 3 ? { model_loaded: true } : { model_loaded: false }));
  const body = await waitForHealth(`http://127.0.0.1:${port}/health`, {
    timeoutMs: 5000, intervalMs: 50, predicate: (b) => b.model_loaded === true,
  });
  assert.equal(body.model_loaded, true);
  srv.close();
});

test("rejects after timeout when server never becomes healthy", async () => {
  const port = await getFreePort();
  await assert.rejects(
    waitForHealth(`http://127.0.0.1:${port}/health`, { timeoutMs: 300, intervalMs: 50 }),
    (err) => err.message.includes(String(port)),
  );
});

test("a process that has exited ends the wait at once, not at the timeout", async () => {
  const port = await getFreePort();
  const t0 = Date.now();
  await assert.rejects(
    waitForHealth(`http://127.0.0.1:${port}/health`, { timeoutMs: 60000, intervalMs: 50, alive: () => false }),
    (err) => err.exited === true,
  );
  assert.ok(Date.now() - t0 < 2000, `took ${Date.now() - t0} ms`);
});

test("a busy answer restarts the silence clock; silence alone runs it out", async () => {
  const port = await getFreePort();
  const started = Date.now();
  // "loading" for 1.2 s, then ready: longer than the 400 ms silence limit.
  const srv = await serveJson(port, () => ({ status: Date.now() - started > 1200 ? "ok" : "loading" }));
  try {
    const body = await waitForHealth(`http://127.0.0.1:${port}/health`, {
      timeoutMs: 400, intervalMs: 50, maxMs: 10000,
      predicate: (b) => b.status === "ok", busy: (b) => b.status === "loading",
    });
    assert.equal(body.status, "ok");
    // Without `busy` an answer that is not the one wanted is silence, and the limit holds.
    await assert.rejects(waitForHealth(`http://127.0.0.1:${port}/health`, {
      timeoutMs: 400, intervalMs: 50, predicate: (b) => b.status === "never",
    }), /timed out/);
  } finally {
    srv.close();
  }
});

test("busy answers stop counting at maxMs", async () => {
  const port = await getFreePort();
  const srv = await serveJson(port, () => ({ status: "loading" }));
  try {
    const t0 = Date.now();
    await assert.rejects(waitForHealth(`http://127.0.0.1:${port}/health`, {
      timeoutMs: 300, intervalMs: 50, maxMs: 1000,
      predicate: (b) => b.status === "ok", busy: (b) => b.status === "loading",
    }), /timed out/);
    assert.ok(Date.now() - t0 < 3000, `took ${Date.now() - t0} ms`);
  } finally {
    srv.close();
  }
});
