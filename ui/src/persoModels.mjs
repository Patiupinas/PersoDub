// The Perso voice models a Perso API dubbing can be made with: the row
// "Dubbing model" under Advanced options, and the name a finished dubbing
// shows. The model is chosen first and the target languages follow it: each
// entry of Perso's language list (GET /api/languages) names the models that
// language has. The server checks the pair again (app/languages.py model_for).

// The models offered, in the order the row shows them (Perso's own site's).
export const PERSO_MODELS = [
  { id: "NIGHTINGALE", label: "Nightingale" },
  { id: "ORIOLE", label: "Oriole" },
  { id: "WREN", label: "Wren" },
];
// The one selected until another is chosen, as on Perso's site.
export const DEFAULT_MODEL = "ORIOLE";

/** The languages a model can dub into, in the list's own order. An entry that
    names no models (the list has not answered yet) is kept under every model. */
export function languagesFor(list, model) {
  return list.filter((l) => !l.models || l.models.includes(model));
}

/** A model's name as the screen says it ("Oriole"), or "" for one not offered. */
export function modelLabel(id) {
  return (PERSO_MODELS.find((m) => m.id === id) || { label: "" }).label;
}
