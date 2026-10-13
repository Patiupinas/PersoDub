// Which Perso voice models the Dubbing model row offers, and which languages
// each of them can dub into.
//
// Run with: node --test ui/src/persoModels.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { PERSO_MODELS, DEFAULT_MODEL, languagesFor, modelLabel } from "./persoModels.mjs";

const ko = { id: "ko", models: ["NIGHTINGALE", "ORIOLE", "WREN"] };
const gb = { id: "en-GB", models: ["ORIOLE", "NIGHTINGALE"] };
const au = { id: "en-AU", models: ["NIGHTINGALE"] };

test("the row offers Nightingale, Oriole, Wren, in that order, Oriole first selected", () => {
  assert.deepEqual(PERSO_MODELS.map((m) => m.label), ["Nightingale", "Oriole", "Wren"]);
  assert.equal(DEFAULT_MODEL, "ORIOLE");
});

test("a model lists every language that has it, and no other", () => {
  const list = [ko, gb, au];
  assert.deepEqual(languagesFor(list, "NIGHTINGALE").map((l) => l.id), ["ko", "en-GB", "en-AU"]);
  assert.deepEqual(languagesFor(list, "ORIOLE").map((l) => l.id), ["ko", "en-GB"]);
  assert.deepEqual(languagesFor(list, "WREN").map((l) => l.id), ["ko"]);
});

test("an entry that names no models stays under every model", () => {
  // The ten shown until Perso's list answers carry no models.
  assert.deepEqual(languagesFor([{ id: "en" }, au], "WREN").map((l) => l.id), ["en"]);
});

test("a model's name as the screen says it", () => {
  assert.equal(modelLabel("WREN"), "Wren");
  assert.equal(modelLabel("DODO"), "");
  assert.equal(modelLabel(undefined), "");
});
