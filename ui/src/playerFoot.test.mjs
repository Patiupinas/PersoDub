// The player row under the running dub's video and the Erase tab's.
//
// Run with: node --test ui/src/playerFoot.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { initPlayerFoot, clockLine } from "./playerFoot.mjs";

function el() {
  const listeners = {};
  const attrs = {};
  return {
    textContent: "", innerHTML: "", title: "",
    setAttribute: (k, v) => { attrs[k] = v; },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    addEventListener: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
    fire: (ev) => { for (const fn of listeners[ev] || []) fn(); },
  };
}

function harness({ src = "/v.mp4" } = {}) {
  const video = el();
  Object.assign(video, { paused: true, ended: false, currentTime: 0, duration: NaN, log: [] });
  if (src) video.setAttribute("src", src);
  video.play = () => { video.log.push("play"); video.paused = false; video.fire("play"); return Promise.resolve(); };
  video.pause = () => { video.log.push("pause"); video.paused = true; video.fire("pause"); };
  const stage = { asked: 0, requestFullscreen: () => { stage.asked += 1; return Promise.resolve(); } };
  const doc = { fullscreenElement: null, left: 0,
                exitFullscreen: () => { doc.left += 1; return Promise.resolve(); } };
  const time = el(), play = el(), fullscreen = el();
  initPlayerFoot({ video, time, play, fullscreen, stage, doc });
  return { video, time, play, fullscreen, stage, doc };
}

test("the clock reads zeros until the video knows its length", () => {
  assert.equal(clockLine({ currentTime: 0, duration: NaN }), "00:00:00.0 / 00:00:00.0");
  assert.equal(clockLine({ currentTime: 3.12, duration: 10.04 }), "00:00:03.1 / 00:00:10.0");
});

test("the button plays, then pauses, and says which it will do", () => {
  const h = harness();
  assert.equal(h.play.getAttribute("aria-label"), "Play");
  h.play.fire("click");
  assert.deepEqual(h.video.log, ["play"]);
  assert.equal(h.play.getAttribute("aria-label"), "Pause");
  h.play.fire("click");
  assert.deepEqual(h.video.log, ["play", "pause"]);
  assert.equal(h.play.title, "Play");
});

test("a player with no video in it does not try to play", () => {
  const h = harness({ src: "" });
  h.play.fire("click");
  assert.deepEqual(h.video.log, []);
});

test("the clock follows the video", () => {
  const h = harness();
  h.video.duration = 10;
  h.video.currentTime = 2.5;
  h.video.fire("timeupdate");
  assert.equal(h.time.textContent, "00:00:02.5 / 00:00:10.0");
});

test("full screen takes the stage, and the same button leaves it", () => {
  const h = harness();
  h.fullscreen.fire("click");
  assert.equal(h.stage.asked, 1);
  h.doc.fullscreenElement = h.stage;
  h.fullscreen.fire("click");
  assert.equal(h.doc.left, 1);
  assert.equal(h.stage.asked, 1);
});
