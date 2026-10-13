// The page as one text: static/index.html with its script, ui/src/app.mjs, put
// back inside the module block that loads it, and each of its stylesheets
// (static/css) put back inside a <style> block where the page links it -- the
// way the file read when all of them were written there.
//
// For the tests that read the page as text (indexHtml, races, escapeKey). They
// pin a line of markup, a rule of the stylesheet and a line of the script
// alike, and slice between marks that can sit in any of them. Lifting the
// script and the stylesheets into files of their own changed where those lines
// live, not what they say, so the tests read the page through this and assert
// what they did.
//
// The parts of the script lifted on into modules of their own (LIFTED) come
// after the page, a module block each: a test that pins something as absent
// from the page -- no confirm(), no "Proofread" -- still looks everywhere the
// page's code went. A test about one of them reads that module itself.
//
// Lives outside ui/src on purpose, like stubDom.mjs: the CI glob
// (ui/src/*.test.mjs) and the app's /js/<name>.mjs route both pass it by.
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

// The block static/index.html loads its script with.
const SCRIPT_LOADER = /<script type="module">\nimport \{\} from "\/js\/app\.mjs";\n<\/script>/;
// A stylesheet of the page's own, as app/main.py serves it.
const STYLESHEET = /<link rel="stylesheet" href="\/css\/([a-z0-9-]+\.css)">/g;
// Lifted out of the page's script unchanged (2026-10-10).
const LIFTED = ["subtitleOverlay", "donePlayer", "playRange", "keyWindow", "chatgptSignIn",
                "confirmDialogs", "whatsNew"];

/** static/index.html with ui/src/app.mjs and static/css/*.css written back in, and LIFTED after it. */
export function readPage() {
  const page = read("../../static/index.html");
  if (!SCRIPT_LOADER.test(page)) {
    throw new Error("static/index.html no longer loads ui/src/app.mjs from the block readPage() looks for");
  }
  // Functions, not strings: the script is full of "$(" and a replacement
  // string would read "$&" and "$'" in it as patterns.
  return page
    .replace(STYLESHEET, (link, name) => `<style>\n${read(`../../static/css/${name}`)}</style>`)
    .replace(SCRIPT_LOADER, () => `<script type="module">\n${read("../src/app.mjs")}</script>`)
    + LIFTED.map((name) => `<script type="module">\n${read(`../src/${name}.mjs`)}</script>\n`).join("");
}
