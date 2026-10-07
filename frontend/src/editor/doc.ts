/**
 * The master résumé as the editor holds it: plain JSON, plus a hidden `_key` on every object in an array
 * so list items keep a stable identity (for React keys and drag-and-drop) while they're edited, moved,
 * or not yet saved (new items have no `id` until the server assigns one). `toEditable` adds keys and
 * `fromEditable` strips them; everything else, including fields the editor doesn't know, passes through.
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type Path = (string | number)[];

export const KEY = "_key";
let counter = 0;

export function newKey(): string {
  counter += 1;
  return `k${counter.toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

/** Hand-written JSON may have plain-string bullets; the editor always works with objects. */
export function toEditable(value: Json, parentKey = ""): Json {
  if (Array.isArray(value)) {
    return value.map((item): Json => {
      if (parentKey === "highlights" && typeof item === "string") return { [KEY]: newKey(), text: item };
      const converted = toEditable(item, "");
      return isObject(converted) ? { [KEY]: newKey(), ...converted } : converted;
    });
  }
  if (isObject(value)) {
    const out: JsonObject = {};
    for (const [k, v] of Object.entries(value)) out[k] = toEditable(v, k);
    return out;
  }
  return value;
}

export function fromEditable(value: Json): Json {
  if (Array.isArray(value)) return value.map(fromEditable);
  if (isObject(value)) {
    const out: JsonObject = {};
    for (const [k, v] of Object.entries(value)) if (k !== KEY) out[k] = fromEditable(v);
    return out;
  }
  return value;
}

export function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function keyOf(item: Json): string {
  return isObject(item) && typeof item[KEY] === "string" ? item[KEY] : "";
}

// ---- paths -------------------------------------------------------------------------------------------

export function getIn(doc: Json, path: Path): Json | undefined {
  let node: Json | undefined = doc;
  for (const part of path) {
    if (Array.isArray(node) && typeof part === "number") node = node[part];
    else if (isObject(node) && typeof part === "string") node = node[part];
    else return undefined;
  }
  return node;
}

function isEmpty(value: Json | undefined): boolean {
  return value === undefined || value === "" || (Array.isArray(value) && value.length === 0);
}

/**
 * A copy of `doc` with `value` at `path`. Empty values (undefined, "", []) remove the key, so clearing a
 * field means "not set" rather than an empty string the schema would reject. Missing objects are created.
 */
export function setIn(doc: Json, path: Path, value: Json | undefined): Json {
  if (path.length === 0) return value ?? null;
  const [head, ...rest] = path;
  if (Array.isArray(doc) && typeof head === "number") {
    const copy = [...doc];
    copy[head] = setIn(doc[head] ?? {}, rest, value);
    return copy;
  }
  const base = isObject(doc) ? doc : {};
  const key = String(head);
  const next = rest.length ? setIn(base[key] ?? (typeof rest[0] === "number" ? [] : {}), rest, value) : value;
  const copy = { ...base };
  if (rest.length === 0 && isEmpty(next)) delete copy[key];
  else copy[key] = next as Json;
  return copy;
}

export function listAt(doc: Json, path: Path): Json[] {
  const value = getIn(doc, path);
  return Array.isArray(value) ? value : [];
}

export function insertAt(doc: Json, path: Path, item: Json, index?: number): Json {
  const list = [...listAt(doc, path)];
  const withKey = isObject(item) ? { [KEY]: newKey(), ...item } : item;
  list.splice(index ?? list.length, 0, withKey);
  return setIn(doc, path, list);
}

export function removeAt(doc: Json, path: Path, index: number): Json {
  const list = listAt(doc, path).filter((_, i) => i !== index);
  return setIn(doc, path, list);
}

export function moveItem(doc: Json, path: Path, from: number, to: number): Json {
  const list = [...listAt(doc, path)];
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return doc;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item as Json);
  return setIn(doc, path, list);
}

// ---- path strings, as the API reports them ("work[2].highlights[0].text") ---------------------------------------

export function pathToString(path: Path): string {
  return path.reduce<string>((out, part) => (typeof part === "number" ? `${out}[${part}]` : out ? `${out}.${part}` : part), "");
}

export function parsePath(text: string): Path {
  const out: Path = [];
  for (const match of text.matchAll(/([^.[\]]+)|\[(\d+)\]/g)) {
    out.push(match[2] !== undefined ? Number(match[2]) : (match[1] as string));
  }
  return out;
}

/** The path of the object whose `id` is `id` (the first match, depth-first), or null. */
export function findById(doc: Json, id: string, path: Path = []): Path | null {
  if (isObject(doc)) {
    if (doc.id === id) return path;
    for (const [k, v] of Object.entries(doc)) {
      const found = findById(v, id, [...path, k]);
      if (found) return found;
    }
  } else if (Array.isArray(doc)) {
    for (let i = 0; i < doc.length; i += 1) {
      const found = findById(doc[i] as Json, id, [...path, i]);
      if (found) return found;
    }
  }
  return null;
}
