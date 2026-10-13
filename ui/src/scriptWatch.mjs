// The script pane, drawn again when its job changed somewhere else: the Dub
// Agent remade a voice, or another window rewrote a line. The table only
// redrew after its own presses, so an agent's remake left the old words,
// "Words changed" and "Remake voices (1)" on screen until a reload, and that
// button would have sent a finished line again (night test 2026-10-01).
//
// One look asks the server for the script's stamp (when its words, voices or
// video last changed) and compares it with the stamp the table was drawn
// from. The table's own presses draw it again themselves, so they never look
// like a change from outside. A stamp still moving (a video being rebuilt) is
// waited out: it is acted on once two looks in a row agree.
//
// active() says whether now is a time to draw again: the finished screen is
// up, nobody is typing in a line and the table is not busy with its own work.
export function scriptChecker({ getJobId, getStamp, refresh, active }) {
  let last = null;
  return async function look() {
    const jobId = getJobId();
    if (!jobId || getStamp() == null || !active()) { last = null; return; }
    const got = await fetch(`/api/dub/jobs/${jobId}/script/stamp`)
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const stamp = got && got.stamp;
    if (!stamp || getJobId() !== jobId) return;
    const settled = stamp === last;
    last = stamp;
    if (settled && stamp !== getStamp() && active()) await refresh(jobId);
  };
}
