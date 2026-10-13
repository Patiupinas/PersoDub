// Run with: node --test desktop/src/zoomReset.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { zoomResetter } from "./zoomReset.js";

const page = (url) => ({ url, zooms: [], getURL() { return this.url; },
                         setZoomLevel(z) { this.zooms.push(z); } });

test("each page the window loads starts at 100%, once", () => {
  const reset = zoomResetter();
  const wc = page("file:///app/screens/loading.html?v=1");
  reset(wc);
  assert.deepEqual(wc.zooms, [0], "the loading screen");

  // The app page: another place, with its own remembered zoom.
  wc.url = "http://127.0.0.1:5001/";
  reset(wc);
  assert.deepEqual(wc.zooms, [0, 0]);

  // Zoomed during the session, then the page loads again (a reload, an
  // update notice): the zoom the person chose is left alone.
  reset(wc);
  wc.url = "http://127.0.0.1:5001/?again=1";
  reset(wc);
  assert.deepEqual(wc.zooms, [0, 0]);
});

test("an address that cannot be read is still put back to 100%", () => {
  const reset = zoomResetter();
  const wc = page("");
  reset(wc);
  assert.deepEqual(wc.zooms, [0]);
});

test("the window resets its zoom when a page finishes loading", () => {
  // The window is made in windowFactory.js (main.js only calls it).
  const code = readFileSync(fileURLToPath(new URL("./windowFactory.js", import.meta.url)), "utf8");
  assert.match(code, /import \{ zoomResetter \} from "\.\/zoomReset\.js";/);
  const at = code.indexOf('win.webContents.on("did-finish-load"');
  assert.ok(at >= 0);
  assert.match(code.slice(at, code.indexOf("});", at)), /resetZoom\(win\.webContents\);/);
});
