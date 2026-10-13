// The page zoom (Cmd/Ctrl with + and -) is remembered by Chromium for each
// place a page comes from, across launches. One stray Cmd-plus left a window
// at 110% for good, with nothing on screen saying why everything was bigger.
// So every launch starts at 100%: the first time a place is loaded, its zoom is
// put back. Zooming still works, and lasts until the app is closed -- a page
// that loads again from the same place keeps what the person chose.

/** @returns {(webContents: {getURL: () => string, setZoomLevel: (z: number) => void}) => void} */
export function zoomResetter() {
  const seen = new Set();
  return (webContents) => {
    let place = "";
    try { place = new URL(webContents.getURL()).origin; } catch { /* no address: one place */ }
    if (seen.has(place)) return;
    seen.add(place);
    webContents.setZoomLevel(0);
  };
}
