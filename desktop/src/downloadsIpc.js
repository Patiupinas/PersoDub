import { existsSync, mkdirSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { revealAllowed } from "./revealPolicy.js";
import { uniqueName } from "./downloadPath.js";

/**
 * Where a finished job's files are saved, and showing one of them. Registers
 * the page's two channels at once; the session's will-download listener is
 * returned for the caller to attach once the app is ready, since the session
 * does not exist before then.
 */
export function registerDownloadIpc({ app, ipcMain, shell, ctx, shellLog }) {
  // Filled by the screen when it renders a finished job, read back synchronously
  // inside will-download (which cannot await a fetch).
  const jobFolders = new Map();
  ipcMain.on("shell:remember-job", (_e, job) => {
    if (job && job.id && job.project && job.day) {
      jobFolders.set(job.id, { project: job.project, day: job.day });
    }
  });

  // "Saved to Downloads · Show". The page knows where the app wrote a file and
  // asks for it to be shown; this decides whether it may be. Only the two
  // folders this app writes into (revealPolicy.js) -- a reveal that took any
  // path the page named would be a way to point the user at any file on the
  // disk. A refusal is logged and answered quietly: the page's own line has
  // already said where the file went.
  ipcMain.handle("shell:reveal", (_e, target) => {
    const folders = [app.getPath("downloads"), ctx.bootedKitDir].filter(Boolean);
    if (!revealAllowed(target, folders)) {
      shellLog(`PERSODUB_REVEAL refused: ${String(target).slice(0, 200)}`);
      return { ok: false };
    }
    shell.showItemInFolder(target);
    return { ok: true };
  });

  // The app server names the file (dub_en.mp4); the folder comes from the job's
  // date and project, so three episodes do not collapse into "dub_en (1).mp4".
  // Nothing here is fatal: on any failure Electron picks the path the way it
  // always did -- which is also what happens when the UI runs in a plain
  // browser and never sent us the job.
  function willDownload(_event, item, webContents) {
    // The window saves silently, so without a word back the page has nothing to
    // show and the user, seeing nothing happen, clicks Download again. Attached
    // before the naming below so a download we did not rename still reports.
    item.once("done", (_e, state) => {
      const path = item.getSavePath();
      if (webContents && !webContents.isDestroyed()) {
        webContents.send("shell:download-done", {
          state,
          path,
          filename: basename(path),
          folder: dirname(path),
        });
      }
    });
    try {
      const jid = new URL(item.getURL()).pathname.split("/")[4];
      const folder = jid && jobFolders.get(jid);
      if (!folder) return;
      const dir = join(app.getPath("downloads"), folder.day, folder.project);
      mkdirSync(dir, { recursive: true });
      const name = uniqueName(item.getFilename(), (n) => existsSync(join(dir, n)));
      if (name) item.setSavePath(join(dir, name));
    } catch {
      /* fall through to Electron's default naming */
    }
  }

  return { willDownload };
}
