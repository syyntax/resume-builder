import { useCallback, useEffect, useMemo, useReducer } from "react";

/** Undo and redo for a value. Consecutive edits with the same `group` (typing in one field) within a
 * second become one step, so undo restores the field as it was before you started typing. */

const LIMIT = 200;
const GROUP_MS = 1000;

interface State<T> {
  past: T[];
  present: T;
  future: T[];
  group: string | null;
  at: number;
}

type Action<T> =
  | { type: "set"; update: (value: T) => T; group?: string; now: number }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; value: T };

function reducer<T>(state: State<T>, action: Action<T>): State<T> {
  switch (action.type) {
    case "set": {
      const next = action.update(state.present);
      if (Object.is(next, state.present)) return state;
      const merge = action.group !== undefined && action.group === state.group && action.now - state.at < GROUP_MS;
      return {
        past: merge ? state.past : [...state.past, state.present].slice(-LIMIT),
        present: next,
        future: [],
        group: action.group ?? null,
        at: action.now,
      };
    }
    case "undo": {
      const previous = state.past.at(-1);
      if (previous === undefined) return state;
      return { past: state.past.slice(0, -1), present: previous, future: [state.present, ...state.future], group: null, at: 0 };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (next === undefined) return state;
      return { past: [...state.past, state.present], present: next, future: rest, group: null, at: 0 };
    }
    case "reset":
      return { past: [], present: action.value, future: [], group: null, at: 0 };
  }
}

export interface History<T> {
  value: T;
  set: (update: (value: T) => T, group?: string) => void;
  undo: () => void;
  redo: () => void;
  reset: (value: T) => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useHistory<T>(initial: T): History<T> {
  const [state, dispatch] = useReducer(reducer<T>, { past: [], present: initial, future: [], group: null, at: 0 });
  const set = useCallback((update: (value: T) => T, group?: string) => dispatch({ type: "set", update, group, now: Date.now() }), []);
  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);
  const reset = useCallback((value: T) => dispatch({ type: "reset", value }), []);
  return useMemo(
    () => ({ value: state.present, set, undo, redo, reset, canUndo: state.past.length > 0, canRedo: state.future.length > 0 }),
    [state, set, undo, redo, reset],
  );
}

/** ⌘/Ctrl+Z and ⌘/Ctrl+⇧+Z (or Ctrl+Y) while `enabled`, including in the form's own fields (controlled
 * inputs have unreliable native undo). Fields marked `data-native-undo`, and Monaco, keep their own. */
export function useUndoShortcuts(history: Pick<History<unknown>, "undo" | "redo">, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("[data-native-undo], .monaco-editor")) return;
      const key = event.key.toLowerCase();
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) history.redo();
        else history.undo();
      } else if (key === "y") {
        event.preventDefault();
        history.redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [history, enabled]);
}
