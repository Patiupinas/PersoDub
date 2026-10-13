// The translators a dubbing that ChatGPT stopped (its limit, or its sign-in
// gone) can carry on with: one button each on the popup, and Resume does the
// rest (POST /api/dub/jobs/{id}/resume with the translator). Nothing switches
// by itself (owner, 2026-10-03). Pure: the page hands in what GET /api/engines
// and GET /api/models said.
import { gb } from "./modelsUi.mjs";
import { t } from "./i18n.mjs";

const NAMES = { chatgpt: "ChatGPT", hunyuan: "Hunyuan", gemma: "Gemma", gemini: "Gemini" };
// Best first, the order the owner named them.
const OFFERED = ["hunyuan", "gemma", "gemini"];

/** A translator's name for the screen, or "" for one this file does not know. */
export function translatorName(id) {
  return NAMES[id] || "";
}

/**
 * @param {string} failed   the job's own translator, never offered back
 * @param {object} engines  GET /api/engines: {hunyuan_available, gemma_available, gemini_available, ...}
 * @param {object[]} rows   GET /api/models rows: {id, state, bytes}
 * @returns {{id: string, label: string}[]}  a translator that runs now says
 *   only its name; a local one not downloaded yet says its size too, and the
 *   resume's 409 then opens the download dialog. One whose model is here but
 *   cannot run right now (its runtime is down), and Gemini without a key,
 *   are left out.
 */
export function translatorChoices(failed, engines, rows) {
  const row = (id) => (rows || []).find((r) => r.id === id);
  const runtime = row("ollama-runtime");
  const out = [];
  for (const id of OFFERED) {
    const name = NAMES[id];
    if (id === failed) continue;
    if (engines && engines[`${id}_available`]) {
      out.push({ id, label: t("Continue with {name}", { name }) });
      continue;
    }
    const model = row(id);
    if (!model || model.state === "ready") continue;
    // The download dialog asks for the runtime too when it is not here yet.
    const bytes = model.bytes + (runtime && runtime.state !== "ready" ? runtime.bytes : 0);
    out.push({ id, label: t("Continue with {name} ({size} GB)", { name, size: gb(bytes) }) });
  }
  return out;
}

/** "Resets Oct 24, 1:07 PM." out of a ChatGPT limit notice (app/pipeline.py
 * raise_notice), in the page's language, or "" when OpenAI named no time. The
 * notice's message is English on purpose, so this reads it the same in both. */
export function resetsSentence(message) {
  const m = /Resets ([^.]+)\./.exec(message || "");
  return m ? t("Resets {time}.", { time: m[1] }) : "";
}
