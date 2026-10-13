// What a caught value says, as text. Most are Errors, but a rejection can carry
// a plain string (or anything else), and an Error with an empty message says
// nothing -- so the value itself, as text, stands in for the message.
export function errorText(err) {
  return String((err && err.message) || err);
}
