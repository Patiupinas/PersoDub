// Which build this is, and so which repository the app points at: the
// build's strict check, the running app's lenient read, and the update feed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { EDITIONS, buildEdition, readEdition, editionFeed } from "./edition.js";

// A payload folder, with an EDITION file when `edition` is given.
function payload(edition) {
  const dir = mkdtempSync(join(tmpdir(), "odedition-"));
  if (edition !== undefined) writeFileSync(join(dir, "EDITION"), edition);
  return dir;
}

test("both editions name the public repository", () => {
  assert.deepEqual(EDITIONS, { opensource: "stronghamjji/PersoDub", production: "stronghamjji/PersoDub" });
});

test("the build takes a known edition, and unset or empty is the open-source one", () => {
  assert.equal(buildEdition({ PERSODUB_EDITION: "production" }), "production");
  assert.equal(buildEdition({ PERSODUB_EDITION: "opensource" }), "opensource");
  assert.equal(buildEdition({}), "opensource");
  assert.equal(buildEdition({ PERSODUB_EDITION: "" }), "opensource");
});

test("the build stops on an unknown edition and names the ones it knows", () => {
  assert.throws(() => buildEdition({ PERSODUB_EDITION: "prod" }),
    { message: 'PERSODUB_EDITION="prod" is not an edition. Use one of: opensource, production.' });
  // A name every object answers to is still not an edition.
  for (const name of ["Production", "constructor", "toString"]) {
    assert.throws(() => buildEdition({ PERSODUB_EDITION: name }), /is not an edition/, name);
  }
});

test("the running app follows the payload's EDITION file, whatever the environment says", () => {
  assert.equal(readEdition({ payloadDir: payload("production\n"), env: { PERSODUB_EDITION: "opensource" } }), "production");
  assert.equal(readEdition({ payloadDir: payload("opensource"), env: { PERSODUB_EDITION: "production" } }), "opensource");
});

test("with no EDITION file the running app reads the environment", () => {
  // npm start has no payload; a payload collected before editions has no file.
  assert.equal(readEdition({ payloadDir: null, env: { PERSODUB_EDITION: "production" } }), "production");
  assert.equal(readEdition({ payloadDir: payload(), env: { PERSODUB_EDITION: "production" } }), "production");
  assert.equal(readEdition({ payloadDir: null, env: {} }), "opensource");
});

test("an unknown edition at run time is the open-source one", () => {
  assert.equal(readEdition({ payloadDir: payload("nonsense"), env: { PERSODUB_EDITION: "production" } }), "opensource");
  assert.equal(readEdition({ payloadDir: payload(""), env: { PERSODUB_EDITION: "production" } }), "opensource");
  assert.equal(readEdition({ payloadDir: null, env: { PERSODUB_EDITION: "constructor" } }), "opensource");
});

test("each edition's update feed is its repository's GitHub Releases", () => {
  assert.deepEqual(editionFeed("production"), { provider: "github", owner: "stronghamjji", repo: "PersoDub" });
  assert.deepEqual(editionFeed("opensource"), { provider: "github", owner: "stronghamjji", repo: "PersoDub" });
});
