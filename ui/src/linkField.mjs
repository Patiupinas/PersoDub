// What counts as a link, and the one sentence every link field says to
// something that is not one (the Import block's, ui/src/importBlock.mjs).
const LINK_RE = /^https?:\/\/\S+$/;
/** What every link field says to something that is not a link. */
export const NOT_A_LINK = "That is not a link. Paste one that starts with https://";
export const isLink = (text) => LINK_RE.test(String(text || "").trim());
