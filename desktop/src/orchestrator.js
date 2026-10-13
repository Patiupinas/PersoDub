import { spawn, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, openSync, fstatSync, mkdirSync, existsSync, rmSync } from "node:fs";
import { basename, join } from "node:path";
import { homedir } from "node:os";
import { parseEnvFile, KIT_ENV } from "./kitEnv.js";
import { getFreePort, getPreferredPort } from "./freePort.js";
import { waitForHealth } from "./health.js";
import { IS_WIN, venvBin, exeName, PATH_SEP } from "./platform.js";
import { readRuntime, writeRuntime, clearRuntime } from "./runtimeFile.js";
import { PACKS, packInstalled } from "./installSpec.js";
import { maskTail } from "./report.js";
import { errorText } from "./errorText.js";

const PIDS_FILE = "pids.json";

// Force-kill a spawned engine and its descendants. POSIX kills the process
// group (the child is a group leader via detached); Windows has no process
// groups, so taskkill /T walks the process tree by PID.
function forceKillTree(pid) {
  if (!Number.isInteger(pid) || pid <= 1) return;
  if (IS_WIN) {
    // windowsHide: taskkill is a console program launched from a GUI process,
    // so without it every kill flashed a console window on screen -- three per
    // launch (stale engines) and three more per quit.
    try { spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore", windowsHide: true }); } catch { /* gone */ }
    return;
  }
  try { process.kill(-pid, "SIGKILL"); } catch { /* group gone */ }
  try { process.kill(pid, "SIGKILL"); } catch { /* already gone */ }
}

// kit.env's PERSODUB_BIN_DIR (kit/bin: ffmpeg, ffprobe) must be visible to the
// backend's subprocesses; GUI apps start with a minimal PATH.
export function applyBinDir(env) {
  if (!env.PERSODUB_BIN_DIR) return env;
  // Windows env names are case-insensitive and the real key is usually "Path",
  // so prepend to whatever spelling already exists rather than a stray "PATH".
  const key = IS_WIN ? (Object.keys(env).find((k) => k.toLowerCase() === "path") || "Path") : "PATH";
  env[key] = `${env.PERSODUB_BIN_DIR}${PATH_SEP}${env[key] || ""}`;
  return env;
}

export async function killStalePids(logDir) {
  const path = join(logDir, PIDS_FILE);
  if (!existsSync(path)) return;
  let pids = [];
  try { pids = JSON.parse(readFileSync(path, "utf8")); } catch { /* corrupt file: just remove */ }
  for (const pid of pids) {
    // A failed spawn records pid null, and kill(-null) === kill(-0) SIGKILLs
    // OUR OWN process group -- the app would kill itself on every launch.
    forceKillTree(pid);
  }
  rmSync(path, { force: true });
}

function substitute(argv, port) {
  return argv.map((a) => a.replaceAll("{port}", String(port)));
}

function launch(argv, { cwd, env, logPath }) {
  const fd = openSync(logPath, "a");
  // POSIX detaches so the engine leads a process group stopChild can signal.
  // Windows must NOT detach: DETACHED_PROCESS strips the console entirely and
  // makes Windows ignore windowsHide, so every console child an engine spawns
  // (ollama's gpu probes, ffmpeg) opened its own visible window. windowsHide
  // alone gives the engine a hidden console the whole tree inherits, and
  // taskkill /T reaps by PID without needing a process group anyway.
  const child = spawn(argv[0], argv.slice(1), { cwd, env, detached: !IS_WIN, windowsHide: true, stdio: ["ignore", fd, fd] });
  // Where this launch's lines begin in a log earlier launches also wrote: a
  // start that fails is told with its own last lines (engineTail).
  child.logPath = logPath;
  child.logFrom = fstatSync(fd).size;
  // A program that is not there never runs, and never exits either: without
  // this it counted as alive, and the unhandled event took the shell down.
  child.on("error", (err) => { child.launchError = err; });
  return child;
}

// This launch's last lines of an engine's log, masked the way a failure
// report is (report.js): the user's home folder and keys never go further.
// Read at boot only, before any dub ran, so no line of dialogue is in it.
function engineTail(child, kitDir, maxLines = 8) {
  try {
    const text = readFileSync(child.logPath).subarray(child.logFrom).toString("utf8");
    return maskTail(text, { home: homedir(), kit: kitDir, maxLines });
  } catch {
    return "";
  }
}

function howItEnded(child) {
  if (child.launchError) return `could not run: ${child.launchError.code || child.launchError.message}`;
  if (child.signalCode) return `killed by ${child.signalCode}`;
  return `exit code ${child.exitCode}`;
}

function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  if (IS_WIN) { forceKillTree(child.pid); return; }
  try { process.kill(-child.pid, "SIGTERM"); } catch { /* group gone */ }
  const killTimer = setTimeout(() => forceKillTree(child.pid), 3000);
  killTimer.unref();
}

// The voice sidecar's launch line. Exported so the path it boots from is
// testable without spawning anything: it must be the engines venv (the voice
// packages merged into it in 0.5.1), never the retired qwen_venv.
export function sidecarArgv(kitDir, port) {
  return [venvBin(join(kitDir, "engines_venv"), "uvicorn"),
          "server:app", "--host", "127.0.0.1", "--port", String(port)];
}

// The address a pack announces in runtime.json, if it has one. A pack that is
// only files (subtitle-eraser: a source tree and a venv the backend runs on
// demand) has none -- and must not withdraw another pack's address when it is
// installed or removed.
export const PACK_RUNTIME_KEY = { engine: "tts_url", "ollama-runtime": "ollama_url" };

// One pack's process: started at boot for every pack already on disk, and
// again by the install-pack IPC the moment a pack finishes downloading -- the
// same function both times, so a pack installed mid-session behaves exactly
// like one that was there at launch. Each process announces where it listens
// through <kit>/runtime.json (runtimeFile.js), which the backend reads at use
// time (app/runtime.py) -- never through the backend's environment, which is
// fixed at its launch. Returns the children it started (for stopPack).
// Whether a pack's process is still up. A process the system killed (out of
// memory, a crash) ends with a signal, not an exit code: exitCode stays null
// and signalCode says which. Counting only exitCode read a killed voice
// engine as alive, so Start dubbing "restarted" it without starting anything
// and the dub stayed refused (2026-09-29).
export const RESTART_EXIT_CODE = 75;

export function packAlive(children) {
  return (children || []).some((c) => c && c.exitCode == null && c.signalCode == null && !c.killed && !c.launchError);
}

// What the page is told about a pack that is not up yet, next to its address
// in runtime.json: "starting" while it comes up, "failed" when it did not,
// gone once it answers. The backend words it (app/runtime.py, GET /api/engines)
// and its preflight refuses a local dub that needs it with that sentence.
export const PACK_STATE_KEY = { engine: "tts_state", "ollama-runtime": "ollama_state" };

export async function startPackProcesses(cfg, packId, { logDir, env, children, record, healthTimeoutMs }) {
  if (packId === "ollama-runtime") {
    // Local translation runs through an Ollama server owned by this app:
    // kit-contained binary and models dir, free port (never fights a user's
    // own Ollama on 11434), killed with the other engines.
    const ollamaBin = join(cfg.kitDir, "ollama", exeName("ollama"));
    if (!existsSync(ollamaBin)) return [];
    const port = await getFreePort();
    writeRuntime(cfg.kitDir, { ollama_state: "starting" });
    const child = launch([ollamaBin, "serve"], {
      cwd: cfg.kitDir,
      env: { ...env, OLLAMA_HOST: `127.0.0.1:${port}`, OLLAMA_MODELS: join(cfg.kitDir, "models", "ollama") },
      logPath: join(logDir, "ollama.log"),
    });
    children.push(child);
    record();
    // Announced only once it answers: right after an on-demand install the
    // page pulls a model within the second, and a server still binding its
    // port turned that first pull into a refused connection.
    await announceWhenUp(`http://127.0.0.1:${port}/api/tags`, (b) => Array.isArray(b.models),
                         () => writeRuntime(cfg.kitDir, { ollama_url: `http://127.0.0.1:${port}` }));
    return [child];
  }
  if (packId === "engine") {
    // Dev and tests: the fake sidecar (cfg.sidecarCmd) stands in for the
    // engine pack, and goes through everything below the same way.
    const fake = cfg.sidecarCmd != null;
    const port = fake && cfg.sidecarPort !== 0 ? cfg.sidecarPort : await getFreePort();
    writeRuntime(cfg.kitDir, { tts_state: "starting" });
    const child = launch(fake ? substitute(cfg.sidecarCmd, port) : sidecarArgv(cfg.kitDir, port), {
      cwd: fake ? process.cwd() : join(cfg.kitDir, "sidecar"), env, logPath: join(logDir, "sidecar.log"),
    });
    children.push(child);
    record();
    // Status ok is enough: the voice model may not be downloaded yet (it is
    // optional, fetched through the in-app catalog), and the sidecar
    // lazy-loads it when the weights appear (vendor/sidecar/server.py) --
    // /synthesize answers 503 until then. Waiting on model_loaded here made
    // every model-less boot a 2-minute timeout and an error screen. A model
    // that IS on disk loads after the port opens, and "loading" is progress.
    await announceWhenUp(`http://127.0.0.1:${port}/health`, (b) => b.status === "ok",
                         () => writeRuntime(cfg.kitDir, { tts_url: `http://127.0.0.1:${port}` }),
                         (b) => b.status === "loading");
    return [child];
  }
  return [];

  // Waits for the process just launched to answer, then announces it. A
  // process that never answers is stopped and forgotten before the error goes
  // up, so a retry does not leave a second copy running. One that exits
  // stops the wait at once: waiting two minutes on a dead engine told nobody
  // anything. Either way the pack is marked failed for the page, and the
  // error carries the engine's own last lines for the log and the report.
  async function announceWhenUp(url, predicate, announce, busy) {
    const child = children[children.length - 1];
    try {
      await waitForHealth(url, {
        timeoutMs: healthTimeoutMs ?? cfg.sidecarHealthTimeoutMs, predicate, busy,
        maxMs: cfg.engineLoadTimeoutMs, alive: () => packAlive([child]),
      });
    } catch (err) {
      if (err.exited) err.message = `${packId} stopped while starting (${howItEnded(child)})`;
      stopChild(child);
      children.pop();
      record();
      writeRuntime(cfg.kitDir, { [PACK_STATE_KEY[packId]]: "failed" });
      const tail = engineTail(child, cfg.kitDir);
      if (tail) err.message += `\nLast lines of ${basename(child.logPath)}:\n${tail}`;
      throw err;
    }
    announce();
    clearRuntime(cfg.kitDir, [PACK_STATE_KEY[packId]]);
  }
}

export async function startEngines(cfg, { logDir, appVersion, locale, edition, preferredBackendPort }) {
  mkdirSync(logDir, { recursive: true });
  await killStalePids(logDir);

  const overrideMode = cfg.sidecarCmd != null && cfg.backendCmd != null;
  let env = process.env;
  let backendCwd = cfg.backendCwd ?? process.cwd();
  if (!overrideMode) {
    const kitEnv = parseEnvFile(readFileSync(join(cfg.kitDir, KIT_ENV), "utf8"));
    env = applyBinDir({ ...process.env, ...kitEnv });
    backendCwd = kitEnv.PERSODUB_APP_REPO_DIR;
  }
  // Tells the backend it is the desktop app rather than a plain server run, and which
  // version it is -- the two facts it reports to Perso (see app/perso_client.py) -- and
  // which edition, which decides where a dub runs by default (app/setup.py). Set here,
  // after the kit env, so a stale kit.env can never override what this build actually is.
  // The computer's language goes the same way: what a language setting of "auto" means to
  // the backend (app/i18n.py), a fact of this computer and not a setting. The edition
  // decides where a dub runs by default (app/setup.py).
  env = { ...env, PERSODUB_CLIENT: "desktop", PERSODUB_APP_VERSION: appVersion ?? "",
          PERSODUB_LOCALE: locale ?? "en", PERSODUB_EDITION: edition ?? "" };

  const children = [];
  const packChildren = new Map();   // pack id -> the processes it owns
  const pids = () => children.map((c) => c.pid);
  const stopAll = () => children.forEach(stopChild);
  const record = () => writeFileSync(join(logDir, PIDS_FILE), JSON.stringify(pids()));
  const packOpts = { logDir, env, children, record };

  const failed = [];   // {pack, message}: packs that did not start, for bootFlow.js to log and report

  try {
    // Addresses (and states) from the last launch must not outlive it: a
    // pack that was removed since would otherwise still be announced.
    clearRuntime(cfg.kitDir, ["ollama_url", "tts_url", ...Object.values(PACK_STATE_KEY)]);
    // Every pack already on this kit's disk starts now; a pack installed
    // later in the session starts through startPack below, the same way.
    // A kit with no engine pack simply has no sidecar yet: the backend
    // answers that the voice engine is not installed, and its preflight
    // asks for the pack before a local dub. Dev and tests start the fake
    // sidecar in the engine pack's place.
    const bootPacks = overrideMode ? ["engine"] : PACKS.filter((p) => packInstalled(cfg.kitDir, p.id)).map((p) => p.id);
    for (const id of bootPacks) {
      try {
        packChildren.set(id, await startPackProcesses(cfg, id, packOpts));
      } catch (err) {
        // One engine that will not start costs only the work that needs it:
        // Perso dubs, erasing, exporting and finished projects need neither,
        // so the window still opens. The page learns it through runtime.json
        // and the retry is the install-pack IPC, which starts it again.
        failed.push({ pack: id, message: errorText(err) });
      }
    }

    // Last launch's port when free (bootFlow.js remembers it), so the page keeps
    // the same origin -- and its localStorage -- from one launch to the next.
    const backendPort = await getPreferredPort(preferredBackendPort);
    const backendArgv = overrideMode
      ? substitute(cfg.backendCmd, backendPort)
      : [venvBin(join(cfg.kitDir, "app_venv"), "uvicorn"),
         "app.main:app", "--host", "127.0.0.1", "--port", String(backendPort)];
    children.push(launch(backendArgv, { cwd: backendCwd, env, logPath: join(logDir, "backend.log") }));
    record();
    await waitForHealth(`http://127.0.0.1:${backendPort}/health`, {
      timeoutMs: cfg.backendHealthTimeoutMs,
    });

    // The install-pack IPC (packIpc.js) starts a pack's process the moment its
    // files are down; remove-pack stops it and withdraws its address.
    const startPack = async (id) => {
      if (overrideMode) return;
      // Started already and still announced: nothing to do. A pack whose
      // start failed earlier left no address behind, so it is tried again.
      const key = PACK_RUNTIME_KEY[id];
      if (packAlive(packChildren.get(id)) && (!key || readRuntime(cfg.kitDir)[key])) return;
      // Not running (never started, or it died after announcing itself): its
      // stale address goes first, so nothing reads it while the new one comes up.
      await startAgain(id);
    };
    const startAgain = async (id) => {
      for (const c of packChildren.get(id) || []) {
        const i = children.indexOf(c);
        if (i >= 0) children.splice(i, 1);
      }
      packChildren.delete(id);
      if (PACK_RUNTIME_KEY[id]) clearRuntime(cfg.kitDir, [PACK_RUNTIME_KEY[id], PACK_STATE_KEY[id]]);
      // A pack started right after its install imports torch cold, on a disk
      // that just wrote gigabytes: the boot's two minutes were not enough on
      // Windows (2026-09-07), and a start that gives up leaves the dub refused.
      packChildren.set(id, await startPackProcesses(cfg, id, { ...packOpts, healthTimeoutMs: 5 * 60 * 1000 }));
      watchRestart(id);
    };
    // The voice engine asks to be started again by exiting with
    // RESTART_EXIT_CODE (vendor/sidecar/server.py POST /restart): the one way
    // it can give back the memory it leaks, about 8-12 GB per 50 lines
    // (2026-10-07). Any other end is left alone, as before: Start dubbing
    // restarts a dead engine when it needs it. A start that fails leaves the
    // pack marked failed in runtime.json, which the page already reads.
    const watchRestart = (id) => {
      for (const c of packChildren.get(id) || []) {
        c.once("exit", (code) => { if (code === RESTART_EXIT_CODE) startAgain(id).catch(() => {}); });
      }
    };
    for (const id of packChildren.keys()) watchRestart(id);
    const stopPack = (id) => {
      for (const c of packChildren.get(id) || []) {
        stopChild(c);
        const i = children.indexOf(c);
        if (i >= 0) children.splice(i, 1);
      }
      packChildren.delete(id);
      record();
      if (PACK_RUNTIME_KEY[id]) clearRuntime(cfg.kitDir, [PACK_RUNTIME_KEY[id], PACK_STATE_KEY[id]]);
    };

    return { url: `http://127.0.0.1:${backendPort}`, port: backendPort, pids: pids(), stopAll,
             startPack, stopPack, failed };
  } catch (err) {
    stopAll();
    err.logDir = logDir;
    throw err;
  }
}
