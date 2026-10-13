import { readFileSync } from "node:fs";
import { join } from "node:path";

// One codebase, two builds, one repository. Both editions read their updates
// from the public repository, and open the page's GitHub links, Help
// documents and release notes there. What the edition decides is where a dub
// runs when nothing is chosen: this computer for the open-source edition (the
// default), the Perso API for the production edition, the company's build
// (app/setup.py; orchestrator.js startEngines hands it to the backend).
//
// The packager picks the edition with PERSODUB_EDITION when the payload is
// collected (scripts/collect-payload.mjs writes it into the payload's EDITION
// file), so a packaged app carries its edition and the environment it runs in
// cannot change it. A run with no payload (npm start) reads PERSODUB_EDITION
// from its own environment.
//
// package.json's build.publish entry stays only so electron-builder writes
// latest.yml and app-update.yml; the feed itself is set at run time from the
// edition (updater.js resolveFeed).
export const EDITIONS = {
  opensource: "stronghamjji/PersoDub",
  production: "stronghamjji/PersoDub",
};
const DEFAULT_EDITION = "opensource";

// The build's edition. An unknown name stops the build, so a typo never ships
// an app that updates from the wrong repository; unset or empty is the default.
export function buildEdition(env) {
  const name = env.PERSODUB_EDITION;
  if (!name) return DEFAULT_EDITION;
  if (!Object.hasOwn(EDITIONS, name)) {
    throw new Error(`PERSODUB_EDITION="${name}" is not an edition. Use one of: ${Object.keys(EDITIONS).join(", ")}.`);
  }
  return name;
}

// The running app's edition: the payload's EDITION file when there is one,
// otherwise the environment. An unknown name is the default, since a running
// app has no build to stop.
export function readEdition({ payloadDir, env }) {
  let name = env.PERSODUB_EDITION;
  if (payloadDir) {
    try { name = readFileSync(join(payloadDir, "EDITION"), "utf8").trim(); } catch { /* no EDITION file: the environment's */ }
  }
  return Object.hasOwn(EDITIONS, name) ? name : DEFAULT_EDITION;
}

// electron-updater's feed for an edition's GitHub Releases.
export function editionFeed(edition) {
  const [owner, repo] = EDITIONS[edition].split("/");
  return { provider: "github", owner, repo };
}
