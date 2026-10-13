// A stand-in browser, just enough for static/index.html's inline scripts to
// run from top to bottom in Node (ui/src/boot.test.mjs). It is not a DOM: it
// knows the markup's elements by id but not how they nest, and has no layout
// and no selector engine. It is faithful where the page's start-up code takes
// its turns:
//
//   - document.getElementById answers only for an id the real markup has, or
//     one the page has since written into an innerHTML/outerHTML string, and
//     null for any other: the way a browser answers a mistyped id.
//   - an element starts with its markup attributes (hidden, disabled,
//     checked, value, class, data-*), a <select> with its <option>s, and an
//     element with nothing but words inside with those words.
//   - every id asked for is recorded, so a test can check each one.
//
// The members modelled are the ones the page's code uses. Anything else
// answers with ANY -- callable, indexable, 0 or "" as a value, never a
// promise -- so a line that only touches the browser in passing runs on,
// rather than stopping at a gap in this file. Those names are kept in
// `unknown`: the first place to look when the page starts reaching for more.
//
// fetch never answers: what the page does at load is what it does before the
// server has said a word. Timers run for real but never keep Node alive, and
// restore() clears them with the globals, so nothing the page started can
// outlive the test. Observers never fire.
//
// Lives outside ui/src on purpose: the CI glob (ui/src/*.test.mjs) and the
// app's /js/<name>.mjs route (flat ui/src only) both pass it by.

/** Callable, indexable, 0 or "" as a value, and never a promise. */
export const ANY = new Proxy(function any() {}, {
  get: (target, key) => (key === "then" ? undefined
    : key === Symbol.toPrimitive ? (hint) => (hint === "number" ? 0 : "")
    : key === Symbol.iterator ? () => [][Symbol.iterator]()
    : key === "length" ? 0
    : ANY),
  apply: () => ANY,
  construct: () => ANY,
  set: () => true,
});

const ATTRS = String.raw`((?:\s+[^\s"'>\/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>\x60]+))?)*)\s*\/?>`;
const START_TAG = new RegExp(String.raw`<([a-zA-Z][\w-]*)` + ATTRS, "g");
const OPTION = new RegExp(String.raw`<option` + ATTRS + "([^<]*)", "gi");
const ATTR = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

const decode = (s) => s.replace(/&(#x[\da-f]+|#\d+|\w+);/gi, (m, e) => (e[0] !== "#" ? ENTITIES[e] ?? m
  : String.fromCodePoint(/x/i.test(e[1]) ? parseInt(e.slice(2), 16) : Number(e.slice(1)))));

function attrsOf(source) {
  const attrs = new Map();
  for (const a of source.matchAll(ATTR)) attrs.set(a[1].toLowerCase(), decode(a[2] ?? a[3] ?? a[4] ?? ""));
  return attrs;
}

/**
 * Every element with an id in `html`, by id: its tag, its attributes, the words
 * inside it when there is nothing else inside it, and a <select>'s inner markup.
 * Scripts, styles and comments are not markup and are passed over.
 */
export function elementsWithIds(html) {
  const text = html.replace(/<!--[\s\S]*?-->|<(script|style)\b[\s\S]*?<\/\1\s*>/gi, "");
  const found = new Map();
  for (const m of text.matchAll(START_TAG)) {
    const attrs = attrsOf(m[2]);
    if (!attrs.get("id")) continue;
    const tag = m[1].toLowerCase();
    const rest = text.slice(m.index + m[0].length);
    const leaf = rest.match(new RegExp(String.raw`^([^<]*)</${tag}\s*>`, "i"));
    const inner = tag === "select" ? rest.slice(0, rest.search(/<\/select\s*>/i)) : "";
    found.set(attrs.get("id"), { tag, attrs, text: leaf ? decode(leaf[1]) : "", inner });
  }
  return found;
}

const BOOLEAN_ATTRS = ["hidden", "disabled", "checked", "open", "selected"];
const STRING_ATTRS = ["id", "title", "type", "name", "href", "src", "placeholder", "role", "target",
  "download", "min", "max", "step"];
const dataAttr = (key) => "data-" + key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
const NO_RECT = Object.freeze({ x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 });

/**
 * Put the stand-in browser on globalThis, built from the page's own markup.
 *
 * @param {string} html  static/index.html as it ships
 * @returns {{ lookedUp: string[], missed: string[], markupIds: Set<string>,
 *   createdIds: Set<string>, errors: unknown[], unknown: Set<string>, restore: () => void }}
 *   lookedUp: every id asked for, in order (getElementById, and #id in a selector);
 *   missed: the ids getElementById answered null for, at the moment they were asked;
 *   createdIds: ids that arrived in markup strings the page wrote itself;
 *   errors: what event listeners threw (a browser reports those and carries on);
 *   unknown: "element.member" names nothing here models.
 */
export function installStubDom(html) {
  const markup = elementsWithIds(html);
  const live = new Map();       // id -> its element, once handed out or written by the page
  const gone = new Set();       // markup ids whose element has left the page
  const report = { lookedUp: [], missed: [], markupIds: new Set(markup.keys()), createdIds: new Set(),
                   errors: [], unknown: new Set() };

  const fromInfo = (m) => makeElement(m.tag, new Map(m.attrs), m.text, m.inner);

  function byId(id) {
    report.lookedUp.push(String(id));
    if (!live.has(id) && markup.has(id) && !gone.has(id)) live.set(id, fromInfo(markup.get(id)));
    if (!live.has(id)) report.missed.push(String(id));
    return live.get(id) ?? null;
  }

  // Markup the page writes itself: the ids in it are on the page from now on.
  function adopt(source) {
    for (const [id, m] of elementsWithIds(String(source))) {
      report.createdIds.add(id);
      gone.delete(id);
      live.set(id, fromInfo(m));
    }
  }

  // The #ids a selector names count as lookups. Only a lone #id is answered;
  // anything else gets one blank element (or none, from querySelectorAll).
  function select(selector, all) {
    const lone = String(selector).trim().match(/^#([\w-]+)$/);
    if (lone) {
      const el = byId(lone[1]);
      return all ? (el ? [el] : []) : el;
    }
    for (const [, id] of String(selector).matchAll(/#([\w-]+)/g)) report.lookedUp.push(id);
    return all ? [] : makeElement("div");
  }

  // addEventListener and friends. A listener that throws is reported, and
  // the others still run -- the browser's way, not a throw at the dispatcher.
  function listenable(getSelf) {
    const listeners = new Map();
    const off = (type, fn) => listeners.set(type, (listeners.get(type) ?? []).filter((l) => l.fn !== fn));
    return {
      addEventListener(type, fn, opts) {
        if (!fn) return;
        const list = listeners.get(type) ?? [];
        if (!list.some((l) => l.fn === fn)) list.push({ fn, once: !!opts?.once });
        listeners.set(type, list);
        opts?.signal?.addEventListener?.("abort", () => off(type, fn));
      },
      removeEventListener: off,
      dispatchEvent(event) {
        const self = getSelf();
        for (const key of ["target", "currentTarget"]) {
          if (!event[key]) Object.defineProperty(event, key, { value: self, configurable: true });
        }
        for (const l of [...(listeners.get(event.type) ?? [])]) {
          if (l.once) off(event.type, l.fn);
          try {
            if (typeof l.fn === "function") l.fn.call(self, event); else l.fn.handleEvent(event);
          } catch (err) {
            report.errors.push(err);
          }
        }
        return !event.defaultPrevented;
      },
    };
  }

  // Members the target lacks answer `fallback(key)`; the ones nothing answers are noted.
  function stand(name, target, fallback = () => ANY) {
    return new Proxy(target, {
      get(t, key) {
        if (key in t || typeof key === "symbol" || key === "then") return Reflect.get(t, key);
        const value = fallback(key);
        if (value === ANY || value === undefined) report.unknown.add(`${name}.${key}`);
        return value;
      },
    });
  }

  function makeElement(tag, attrs = new Map(), text = "", inner = "") {
    let self = null;
    let parent;                   // undefined: somewhere in the markup; null: off the page
    let written = "";             // the last innerHTML the page wrote
    const css = { setProperty(name, value) { css[name] = String(value); } };
    const classes = () => (attrs.get("class") ?? "").split(/\s+/).filter(Boolean);
    const setClasses = (list) => attrs.set("class", [...new Set(list)].join(" "));
    const classList = {
      add: (...names) => setClasses([...classes(), ...names]),
      remove: (...names) => setClasses(classes().filter((c) => !names.includes(c))),
      toggle(name, force) {
        const on = force === undefined ? !classes().includes(name) : !!force;
        if (on) classList.add(name); else classList.remove(name);
        return on;
      },
      contains: (name) => classes().includes(name),
    };
    const dataset = new Proxy({}, {
      get: (t, key) => (typeof key === "string" ? attrs.get(dataAttr(key)) : undefined),
      set: (t, key, value) => { attrs.set(dataAttr(key), String(value)); return true; },
      deleteProperty: (t, key) => { attrs.delete(dataAttr(key)); return true; },
      has: (t, key) => attrs.has(dataAttr(key)),
    });

    // A <select>'s options and which one is picked: the one marked selected,
    // else the first -- and none once told a value it does not have.
    let options = [];
    let picked = -1;
    const setOptions = (list) => {
      options = list;
      const marked = options.findIndex((o) => o.hasAttribute("selected"));
      picked = marked >= 0 ? marked : options.length ? 0 : -1;
    };
    const optionsIn = (source) => [...String(source).matchAll(OPTION)]
      .map((m) => makeElement("option", attrsOf(m[1]), decode(m[2]).trim()));

    // Elements put in are only re-parented (a moved element stays on the page);
    // words are kept as this element's own, and options join a <select>'s.
    function insert(nodes, atStart) {
      const added = nodes.filter((node) => node?.nodeType === 1);
      for (const node of added) node._moveTo(self);
      for (const node of nodes) {
        if (node?.nodeType !== 1) text += node?.nodeType === 3 ? node.textContent : String(node ?? "");
      }
      const newOptions = added.filter((n) => n.tagName === "OPTION");
      if (newOptions.length) {
        const wasPicked = picked >= 0;
        options = atStart ? [...newOptions, ...options] : [...options, ...newOptions];
        if (!wasPicked) setOptions(options);
      }
      return nodes[nodes.length - 1];
    }
    function empty() {
      text = "";
      written = "";
      if (tag === "select") setOptions([]);
    }

    const el = {
      nodeType: 1,
      tagName: tag.toUpperCase(),
      ...listenable(() => self),
      click: () => self.dispatchEvent(new Event("click", { bubbles: true, cancelable: true })),
      focus() {}, blur() {}, select() {}, scrollIntoView() {}, scrollTo() {},
      setPointerCapture() {}, releasePointerCapture() {}, hasPointerCapture: () => false,
      getAttribute: (name) => attrs.get(name.toLowerCase()) ?? null,
      setAttribute: (name, value) => { attrs.set(name.toLowerCase(), String(value)); },
      removeAttribute: (name) => { attrs.delete(name.toLowerCase()); },
      hasAttribute: (name) => attrs.has(name.toLowerCase()),
      classList,
      get className() { return attrs.get("class") ?? ""; },
      set className(value) { attrs.set("class", String(value)); },
      dataset,
      style: new Proxy(css, { get: (t, key) => (typeof key === "symbol" ? t[key] : t[key] ?? "") }),
      get textContent() { return text; },
      set textContent(value) { empty(); text = String(value ?? ""); },
      get innerHTML() { return written; },
      set innerHTML(value) {
        empty();
        written = String(value);
        text = decode(written.replace(/<[^>]*>/g, ""));
        adopt(written);
        if (tag === "select") setOptions(optionsIn(written));
      },
      set outerHTML(value) { self.remove(); adopt(value); },
      appendChild: (node) => insert([node], false),
      append: (...nodes) => { insert(nodes, false); },
      prepend: (...nodes) => { insert(nodes, true); },
      replaceChildren: (...nodes) => { empty(); insert(nodes, false); },
      // Off the page: getElementById no longer finds it.
      remove() {
        el._moveTo(null);
        const id = attrs.get("id");
        if (id && live.get(id) === self) { live.delete(id); gone.add(id); }
      },
      // Moved, not removed: a moved element is still on the page.
      _moveTo(next) {
        parent = next;
        const id = attrs.get("id");
        if (next && id && gone.has(id) && !live.has(id)) { gone.delete(id); live.set(id, self); }
      },
      get parentElement() { return parent === undefined ? (parent = makeElement("div")) : parent; },
      querySelector: (selector) => select(selector, false),
      querySelectorAll: (selector) => select(selector, true),
      closest: () => makeElement("div"),
      contains: (node) => node === self,
      getBoundingClientRect: () => NO_RECT,
      offsetWidth: 0, offsetHeight: 0, offsetLeft: 0, offsetTop: 0,
      clientWidth: 0, clientHeight: 0, scrollWidth: 0, scrollHeight: 0, scrollLeft: 0, scrollTop: 0,
      isConnected: true,
      get value() {
        if (tag === "select") return options[picked]?.value ?? "";
        if (tag === "option") return attrs.get("value") ?? text;
        return attrs.get("value") ?? (tag === "textarea" ? text : "");
      },
      set value(value) {
        if (tag === "select") picked = options.findIndex((o) => o.value === String(value));
        else attrs.set("value", String(value ?? ""));
      },
      get text() { return el.textContent; },
      get options() { return options; },
      get selectedOptions() { return picked >= 0 ? [options[picked]] : []; },
      get files() { return []; },
    };
    for (const name of BOOLEAN_ATTRS) {
      Object.defineProperty(el, name, {
        get: () => attrs.has(name),
        set: (on) => { if (on) attrs.set(name, ""); else attrs.delete(name); },
      });
    }
    for (const name of STRING_ATTRS) {
      Object.defineProperty(el, name, {
        get: () => attrs.get(name) ?? "",
        set: (value) => { attrs.set(name, String(value)); },
      });
    }
    if (tag === "video" || tag === "audio") {
      Object.assign(el, { paused: true, ended: false, currentTime: 0, duration: NaN, videoWidth: 0,
                          videoHeight: 0, muted: false, play: async () => {}, pause() {}, load() {},
                          requestFullscreen: async () => {} });
    }
    if (tag === "canvas") el.getContext = () => ANY;
    if (tag === "select") setOptions(optionsIn(inner));
    const id = attrs.get("id");
    self = stand(id ? `${tag}#${id}` : tag, el);
    return self;
  }

  const body = makeElement("body");
  const document = stand("document", {
    ...listenable(() => document),
    body,
    activeElement: body,
    fullscreenElement: null,
    exitFullscreen: async () => {},
    getElementById: byId,
    querySelector: (selector) => select(selector, false),
    querySelectorAll: (selector) => select(selector, true),
    createElement: (tag) => makeElement(String(tag).toLowerCase()),
    createTextNode: (data) => ({ nodeType: 3, textContent: String(data) }),
  });

  const storage = new Map();
  const localStorage = {
    getItem: (key) => (storage.has(String(key)) ? storage.get(String(key)) : null),
    setItem: (key, value) => { storage.set(String(key), String(value)); },
    removeItem: (key) => { storage.delete(String(key)); },
  };

  // Timers run, but never hold Node open; restore() clears every one still set.
  const real = { setTimeout, setInterval, clearTimeout, clearInterval };
  const timers = new Set();
  const held = (timer) => { timer?.unref?.(); timers.add(timer); return timer; };
  class Watcher { observe() {} unobserve() {} disconnect() {} }

  // A member a browser window lacks is undefined, not ANY -- persodubShell
  // above all, since this is a plain browser, not the desktop app. The rest
  // (setTimeout, localStorage, ...) are the globals below, as in a browser.
  const window = stand("window", {
    ...listenable(() => window),
    innerWidth: 1440,
    innerHeight: 900,
    open: () => null,
    getSelection: () => ANY,
  }, (key) => globalThis[key]);

  const globals = {
    window,
    document,
    localStorage,
    navigator: {
      userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
      platform: "MacIntel",
    },
    fetch: () => new Promise(() => {}),
    getComputedStyle: () => new Proxy({}, { get: (t, key) => (typeof key === "symbol" ? t[key] : "") }),
    requestAnimationFrame: (fn) => held(real.setTimeout(() => fn(performance.now()), 16)),
    setTimeout: (fn, ms, ...args) => held(real.setTimeout(fn, ms, ...args)),
    setInterval: (fn, ms, ...args) => held(real.setInterval(fn, ms, ...args)),
    clearTimeout: (timer) => real.clearTimeout(timer),
    clearInterval: (timer) => real.clearInterval(timer),
    MutationObserver: Watcher,
    ResizeObserver: Watcher,
    Image: class { constructor() { return makeElement("img"); } },
  };
  const saved = Object.keys(globals).map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]);
  for (const [name, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true, enumerable: true });
  }

  return {
    ...report,
    restore() {
      for (const timer of timers) real.clearTimeout(timer);
      for (const [name, descriptor] of saved) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
    },
  };
}
