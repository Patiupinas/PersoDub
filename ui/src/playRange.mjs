// Plays only [start, end] of a video and stops there. Shared: the trim bar
// previews the chosen part with it, and the finished screen plays one line.
// One range at a time per video -- a second press replaces the first press's
// stop-listener instead of racing it.
// The map is this module's own, so every file that imports these shares it.
const rangeStoppers = new WeakMap();
export function playRange(video, start, end) {
  const previous = rangeStoppers.get(video);
  if (previous) video.removeEventListener("timeupdate", previous);
  const stop = () => {
    if (video.currentTime < end) return;
    video.pause();
    video.removeEventListener("timeupdate", stop);
    rangeStoppers.delete(video);
  };
  rangeStoppers.set(video, stop);
  video.addEventListener("timeupdate", stop);
  video.currentTime = start;
  return video.play();
}

// The other half of playRange: forget a range that was never played to its end
// (the dialog closed, a new file was dropped, the viewer took the controls
// back). Without this the old stop-listener stays armed and pauses the next,
// unrelated playback at the abandoned range's end.
export function cancelRange(video) {
  const stop = rangeStoppers.get(video);
  if (stop) {
    video.removeEventListener("timeupdate", stop);
    rangeStoppers.delete(video);
  }
  video.pause();
}
