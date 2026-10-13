// The failure card's Try again, run in the page itself: ui/src/app.mjs on the
// stand-in browser of ui/testlib/stubDom.mjs, opening on a dub that failed.
// The server answers Try again with the 409 a start gets when models are
// missing (a local dub whose model was removed since). That answer reached
// the screen as "[object Object]" under the button (2026-10-10); it is the
// download dialog Resume opens, and Try again goes on once the model is in.
//
// One page per process: app.mjs runs once, at the import below.
//
// Run with: node --test ui/src/failCard.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { installStubDom } from "../testlib/stubDom.mjs";

const json = (status, body) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" } });
const VOICE = { id: "qwen3-tts", role: "tts", name: "Qwen3-TTS", bytes: 4.5e9, hint: "", state: "not_downloaded" };

const page = installStubDom(readFileSync(new URL("../../static/index.html", import.meta.url), "utf8"));
const posted = [];
globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  if (opts.method === "POST") posted.push(u);
  if (u === "/api/dub/jobs/j1") {
    return json(200, { id: "j1", kind: "dub", status: "error", dub_mode: "local", error: "It stopped.", logs: [] });
  }
  if (u === "/api/dub/jobs/j1/retry") {
    return posted.length === 1
      ? json(409, { detail: { missing: [{ ...VOICE, kind: "model" }], total_bytes: VOICE.bytes, free_bytes: 1e11 } })
      : json(200, { job_id: "j2", status: "running" });
  }
  if (u === "/api/models") return json(200, { models: [VOICE], platform: "mac" });
  if (u === "/api/models/qwen3-tts/download") { VOICE.state = "ready"; return json(200, {}); }
  return new Promise(() => {});   // the rest of the server has not answered yet
};
// The page opens on the dub it was left on: this one.
localStorage.setItem("persodub.layout.lastJobId", "j1");
await import("./app.mjs");
await sleep(300);
const $ = (id) => document.getElementById(id);

test("Try again short of a model opens the download dialog, then tries again", async () => {
  assert.equal(document.body.dataset.screen, "failed");
  $("doneRetry").click();
  await sleep(100);
  assert.equal($("doneRetryError").textContent, "");
  assert.ok($("modelsNeededOverlay").classList.contains("open"), "the download dialog is open");

  $("mnDownload").click();
  await sleep(300);
  assert.deepEqual(posted, ["/api/dub/jobs/j1/retry", "/api/models/qwen3-tts/download", "/api/dub/jobs/j1/retry"]);
});

test.after(() => page.restore());
