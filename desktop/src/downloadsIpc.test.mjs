// Run with: node --test desktop/src/downloadsIpc.test.mjs
// Electron's download item and the system file window are stand-ins; the
// Downloads folder and the kit are temp folders.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { registerDownloadIpc } from "./downloadsIpc.js";

function setup() {
  const downloads = mkdtempSync(join(tmpdir(), "oddownloads-"));
  const on = {};
  const handle = {};
  const shown = [];
  const logged = [];
  const ctx = { bootedKitDir: null };
  const { willDownload } = registerDownloadIpc({
    app: { getPath: (name) => (name === "downloads" ? downloads : null) },
    ipcMain: { on: (channel, fn) => { on[channel] = fn; }, handle: (channel, fn) => { handle[channel] = fn; } },
    shell: { showItemInFolder: (path) => shown.push(path) },
    ctx, shellLog: (line) => logged.push(line),
  });
  return { downloads, on, handle, shown, logged, ctx, willDownload };
}

// A download as Electron hands it over, saved at `savePath` unless renamed.
function item(url, filename, savePath) {
  return {
    savePath,
    getURL: () => url,
    getFilename: () => filename,
    setSavePath(path) { this.savePath = path; },
    getSavePath() { return this.savePath; },
    once(_event, fn) { this.done = fn; },
  };
}

test("a finished job's file lands in Downloads/<day>/<project> without overwriting, and the page hears where", () => {
  const s = setup();
  s.on["shell:remember-job"]({}, { id: "abc123", project: "Ep 1", day: "2026-10-10" });
  const folder = join(s.downloads, "2026-10-10", "Ep 1");
  mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, "dub_en.mp4"), "an earlier export");
  const dub = item("http://127.0.0.1:5001/api/dub/jobs/abc123/download", "dub_en.mp4", join(s.downloads, "dub_en.mp4"));
  const told = [];
  s.willDownload({}, dub, { isDestroyed: () => false, send: (channel, info) => told.push([channel, info]) });
  assert.equal(dub.getSavePath(), join(folder, "dub_en_001.mp4"));
  dub.done({}, "completed");
  assert.deepEqual(told, [["shell:download-done",
    { state: "completed", path: join(folder, "dub_en_001.mp4"), filename: "dub_en_001.mp4", folder }]]);
});

test("a download the page never described keeps Electron's own name, and still reports", () => {
  const s = setup();
  const plain = item("http://127.0.0.1:5001/api/dub/jobs/ffffff/download", "x.mp4", join(s.downloads, "x.mp4"));
  const told = [];
  s.willDownload({}, plain, { isDestroyed: () => false, send: (_channel, info) => told.push(info.path) });
  assert.equal(plain.getSavePath(), join(s.downloads, "x.mp4"));
  plain.done({}, "cancelled");
  assert.deepEqual(told, [join(s.downloads, "x.mp4")]);
});

test("only a file inside Downloads or the kit is shown; anything else is refused and logged", () => {
  const s = setup();
  s.ctx.bootedKitDir = mkdtempSync(join(tmpdir(), "odkit-"));
  assert.deepEqual(s.handle["shell:reveal"]({}, join(s.downloads, "a.mp4")), { ok: true });
  assert.deepEqual(s.handle["shell:reveal"]({}, join(s.ctx.bootedKitDir, "logs", "x.log")), { ok: true });
  assert.deepEqual(s.handle["shell:reveal"]({}, "/etc/hosts"), { ok: false });
  assert.deepEqual(s.shown, [join(s.downloads, "a.mp4"), join(s.ctx.bootedKitDir, "logs", "x.log")]);
  assert.deepEqual(s.logged, ["PERSODUB_REVEAL refused: /etc/hosts"]);
});
