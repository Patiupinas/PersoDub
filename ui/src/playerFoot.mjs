// The row under a video in the center panel: the clock on the left, play in
// the middle, full screen on the right. The finished job's player has one of
// its own, tied to the script and the timeline; this is the same row for the
// two videos that have neither -- the original while a dub runs, and the one
// the Erase tab draws its box on.
import { fmtClockTenths } from "./format.mjs";
import { lucide } from "./icons.mjs";
import { t } from "./i18n.mjs";

const PLAY = lucide("play", 12.8, true);
const PAUSE = lucide("pause", 12.8, true);

/** "00:00:03.1 / 00:00:10.0", and zeros for a video that has no length yet. */
export function clockLine(video) {
  const total = Number.isFinite(video.duration) ? video.duration : 0;
  return `${fmtClockTenths(video.currentTime || 0)} / ${fmtClockTenths(total)}`;
}

/**
 * Wire one player row to its video.
 *
 * @param {object} deps
 * @param {any} deps.video       the <video> the row plays
 * @param {any} deps.time        where the clock is written
 * @param {any} deps.play        the play / pause button
 * @param {any} deps.fullscreen  the full screen button
 * @param {any} deps.stage       what goes full screen: the picture and
 *        whatever is drawn over it
 * @param {any} [deps.doc]       the document, for leaving full screen
 */
export function initPlayerFoot({ video, time, play, fullscreen, stage,
                                 doc = globalThis.document }) {
  function paint() {
    const playing = !video.paused && !video.ended;
    play.innerHTML = playing ? PAUSE : PLAY;
    const label = playing ? t("Pause") : t("Play");
    play.setAttribute("aria-label", label);
    play.title = label;
    // Nothing to play until there is a video.
    play.disabled = !video.getAttribute("src");
    time.textContent = clockLine(video);
  }

  play.addEventListener("click", () => {
    if (!video.getAttribute("src")) return;
    if (video.paused || video.ended) video.play().catch(() => {});
    else video.pause();
  });
  fullscreen.addEventListener("click", () => {
    if (doc.fullscreenElement) doc.exitFullscreen().catch(() => {});
    else stage.requestFullscreen().catch(() => {});
  });
  for (const e of ["play", "playing", "pause", "ended", "emptied", "loadstart",
                   "timeupdate", "loadedmetadata", "seeked"]) {
    video.addEventListener(e, paint);
  }
  paint();
  return { paint };
}
