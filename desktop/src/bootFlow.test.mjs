import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

// Boot looks for an old settings file in the default kit folder, which
// config.js works out from the home folder as it loads. So everything boot can
// reach points into a throwaway folder before bootFlow.js is imported: the
// kit, the home folder (HOME on macOS and Linux, USERPROFILE on Windows) and
// Windows' local app data.
const base = mkdtempSync(join(tmpdir(), "odboot-"));
for (const name of ["HOME", "USERPROFILE", "LOCALAPPDATA"]) process.env[name] = base;
process.env.PERSODUB_KIT_DIR = join(base, "kit");
delete process.env.PERSODUB_FAKE;   // the fake engines skip the install entirely
const { createBoot } = await import("./bootFlow.js");

test("the install screen is handed the version, as every other screen is", async () => {
  // A first install: a bundled payload and an empty kit folder.
  const appDir = join(base, "app");
  mkdirSync(join(appDir, "resources", "payload", "app-repo"), { recursive: true });
  writeFileSync(join(appDir, "resources", "payload", "KIT_VERSION"), "9.9.9+test");
  const loads = [];
  const stop = new Error("stop before the install copies or downloads anything");
  const win = {
    loadFile: async (path, { query }) => {
      loads.push({ path, query });
      if (path.endsWith("installing.html")) throw stop;
    },
  };
  const app = { getVersion: () => "1.2.3", getPath: () => join(base, "userData") };
  const boot = createBoot({
    app, ctx: {}, appDir, shellLog: () => {}, countUsage: () => {}, sendReport: () => {},
    flushReports: async () => {}, startUpdater: () => {},
  });
  await assert.rejects(boot(win), (err) => err === stop);
  const installing = loads.find((l) => l.path.endsWith("installing.html"));
  assert.ok(installing, `boot showed ${loads.map((l) => l.path).join(", ")}`);
  assert.equal(installing.query.v, "1.2.3");
  assert.equal(installing.query.mode, "install");
  assert.ok(Number(installing.query.bytes) > 0);
});
