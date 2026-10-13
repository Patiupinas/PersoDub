// A save that waits a moment for the last of a run of changes (a drag, a few
// presses of Bigger) and then goes once. What it waits with is the project the
// change was made on: opening another project meanwhile must not send this
// change there, nor lose it.

/**
 * @param {(id: string, body: any) => void} send  the save itself
 * @param {number} [ms]  how long a change waits for the next one
 * @returns {{ schedule: (id: string, body: any) => void, flush: () => void }}
 *   schedule: hold `body` for project `id`; a change waiting for another
 *   project goes out first. flush: send what is waiting, now.
 */
export function pendingSave(send, ms = 350) {
  let timer = null;
  let waiting = null;
  function flush() {
    clearTimeout(timer);
    timer = null;
    const w = waiting;
    waiting = null;
    if (w) send(w.id, w.body);
  }
  function schedule(id, body) {
    if (waiting && waiting.id !== id) flush();
    clearTimeout(timer);
    waiting = { id, body };
    timer = setTimeout(flush, ms);
  }
  return { schedule, flush };
}
