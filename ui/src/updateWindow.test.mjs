// What the update icon and the "Version update" window show for each state
// the shell announces -- including an older shell that sends no date or notes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { updateLive, updateIconView, updateWindowView, noteLines, releaseDay } from "./updateWindow.mjs";

const DOWNLOADING = { version: "0.7.1", phase: "downloading", pct: 42 };
const READY = { version: "0.7.1", phase: "ready", pct: 100,
  releaseDate: "2026-09-30T12:00:00.000Z", releaseNotes: "<ul><li>ElevenLabs voices.</li><li>Erase box fits</li></ul>" };

test("the icon is grey with no update and lit while one downloads or waits", () => {
  assert.deepEqual(updateIconView(null), { live: false, title: "Updates" });
  assert.deepEqual(updateIconView(undefined), { live: false, title: "Updates" });
  assert.equal(updateIconView(DOWNLOADING).live, true);
  assert.equal(updateIconView(READY).live, true);
  assert.equal(updateLive({ version: "0.7.1", phase: "something-else" }), false);
  assert.equal(updateLive({ phase: "ready" }), false, "no version, nothing to offer");
});

test("with no update the window says so and shows the running version's list", () => {
  const v = updateWindowView(null, { current: "0.7.0", currentNotes: ["One", "Two"] });
  assert.equal(v.title, "PersoDub is up to date");
  assert.equal(v.current, "Current version: 0.7.0");
  assert.equal(v.next, "");
  assert.equal(v.button, null);
  assert.deepEqual(v.notes, ["One", "Two"]);
  assert.equal(v.notesLink, null);
});

test("a from-source run's 0.0.0 is not shown as a version", () => {
  assert.equal(updateWindowView(null, { current: "0.0.0" }).current, "");
});

test("while downloading the button is the percent and cannot be pressed", () => {
  const v = updateWindowView(DOWNLOADING, { current: "0.7.0" });
  assert.equal(v.title, "You can update to the latest version");
  assert.deepEqual(v.button, { label: "Downloading 42%", disabled: true });
});

test("when ready: restart button, version, day, and the notes as lines", () => {
  const v = updateWindowView(READY, { current: "0.7.0" });
  assert.deepEqual(v.button, { label: "Restart to update", disabled: false });
  assert.equal(v.next, "New version: 0.7.1");
  assert.equal(v.released, "Released on 2026-09-30");
  assert.deepEqual(v.notes, ["ElevenLabs voices.", "Erase box fits"]);
  assert.equal(v.notesLink, null);
});

test("an older shell (no date, no notes) gets no date and a link to the release", () => {
  // The releases page is the repository the build points at (app.mjs REPO_URL).
  const releases = "https://example.test/owner/PersoDub/releases";
  const v = updateWindowView({ version: "0.7.1", phase: "ready", pct: 100 }, { current: "0.7.0", releases });
  assert.equal(v.next, "New version: 0.7.1");
  assert.equal(v.released, "");
  assert.deepEqual(v.notes, []);
  assert.equal(v.notesLink, "https://example.test/owner/PersoDub/releases/tag/v0.7.1");
});

test("a running dub is named only when an update is on offer", () => {
  assert.equal(updateWindowView(READY, { dubRunning: true }).running, "Dubbing is running. Restarting stops it.");
  assert.equal(updateWindowView(READY, { dubRunning: false }).running, "");
  assert.equal(updateWindowView(null, { dubRunning: true }).running, "");
});

test("release notes: HTML is stripped to text, never kept as markup", () => {
  assert.deepEqual(noteLines('<p>Fixes &amp; more</p><img src=x onerror="alert(1)"><script>x</script>', "1"),
    ["Fixes & more"]);
  // The column's own heading is not repeated as the first line.
  assert.deepEqual(noteLines("<h2>What&#39;s new</h2><p>A<br>B</p>", "1"), ["A", "B"]);
  assert.deepEqual(noteLines("&lt;b&gt; stays text", "1"), ["<b> stays text"]);
});

test("release notes: plain markdown lines lose their bullets and bold marks", () => {
  assert.deepEqual(noteLines("## New\n- **Voices.** ElevenLabs\n* Two\n\n", "1"), ["New", "Voices. ElevenLabs", "Two"]);
});

test("release notes: a list picks this version's note, or joins them all", () => {
  const list = [{ version: "0.7.1", note: "<p>Mine</p>" }, { version: "0.7.0", note: "Older" }];
  assert.deepEqual(noteLines(list, "0.7.1"), ["Mine"]);
  assert.deepEqual(noteLines(list, "9.9.9"), ["Mine", "Older"]);
  assert.deepEqual(noteLines([{ version: "0.7.1", note: null }], "0.7.1"), []);
});

test("release notes: nothing gives no lines", () => {
  assert.deepEqual(noteLines(null, "1"), []);
  assert.deepEqual(noteLines("", "1"), []);
  assert.deepEqual(noteLines(undefined, "1"), []);
});

test("release day reads an ISO date and gives up on anything else", () => {
  assert.equal(releaseDay("2026-09-30T12:00:00.000Z"), "2026-09-30");
  assert.equal(releaseDay("not a date"), "");
  assert.equal(releaseDay(undefined), "");
});
