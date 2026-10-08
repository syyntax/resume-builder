/** Building blocks shared by the résumé and cover letter editors. */

import { DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS as DndCSS } from "@dnd-kit/utilities";
import { AlertTriangle, Check, GripVertical, Loader2, Sparkles, X } from "lucide-react";
import { type ReactNode, type TextareaHTMLAttributes, useEffect, useRef, useState } from "react";

import { ApiError, api, csrfHeaders, errorMessage } from "../api/client";
import type { ResumeWarning } from "../api/types";
import { Button, cn, inputClass } from "../components/ui";
import { wordDiff } from "./diff";

// ---- autosave ------------------------------------------------------------------------------------------------

export type SaveState = "saved" | "pending" | "saving" | "error";

/**
 * Saves `value` a moment after it stops changing (EDT-5). `onSaved` gets the server's answer and the value that
 * was sent, so the caller can merge what the server computed (warnings, coverage) into newer local edits. If
 * the page closes with changes pending, they're sent with `keepalive` so nothing is lost.
 */
export function useAutosave<T, R>({ value, edits, url, body, onSaved, delay = 800 }: {
  value: T;
  /** Bumped by every change of yours (history.edits). Merging the server's result back in doesn't bump it,
   * so that doesn't trigger another save. */
  edits: number;
  url: string;
  body: (value: T) => unknown;
  onSaved: (result: R, sent: T) => void;
  delay?: number;
}): { state: SaveState; error: string | null; issues: { path?: string; message: string }[] } {
  const [state, setState] = useState<SaveState>("saved");
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<{ path?: string; message: string }[]>([]);
  const latest = useRef({ value, edits });
  latest.current = { value, edits };
  const saved = useRef(edits); // the edit count the server has
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;
  const bodyRef = useRef(body);
  bodyRef.current = body;

  useEffect(() => {
    if (edits === saved.current) return;
    setState("pending");
    const timer = window.setTimeout(() => {
      const { value: sent, edits: at } = latest.current;
      setState("saving");
      api<R>("PUT", url, { json: bodyRef.current(sent) })
        .then((result) => {
          saved.current = Math.max(saved.current, at);
          setError(null);
          setIssues([]);
          setState(saved.current === latest.current.edits ? "saved" : "pending");
          onSavedRef.current(result, sent);
        })
        .catch((e: unknown) => {
          setState("error");
          setError(errorMessage(e));
          setIssues(e instanceof ApiError ? e.errors : []);
        });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [edits, url, delay]);

  useEffect(() => {
    const flush = () => {
      if (latest.current.edits === saved.current) return;
      // keepalive lets the request finish after the page is gone (bodies up to 64 KB)
      void fetch(url, { method: "PUT", keepalive: true, credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...csrfHeaders() }, body: JSON.stringify(bodyRef.current(latest.current.value)) });
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush(); // leaving the page within the app
    };
  }, [url]);

  return { state, error, issues };
}

export function SaveIndicator({ state, error }: { state: SaveState; error: string | null }) {
  const text = state === "saving" ? "Saving…" : state === "pending" ? "Unsaved changes" : state === "error" ? `Not saved: ${error}` : "All changes saved";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", state === "error" ? "text-red-600 dark:text-red-400" : "text-slate-500")} aria-live="polite">
      {state === "saving" && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {state === "saved" && <Check className="size-3.5" aria-hidden />}
      {text}
    </span>
  );
}

// ---- text display ------------------------------------------------------------------------------------------------

export function Diff({ before, after }: { before: string; after: string }) {
  return (
    <span className="leading-relaxed">
      {wordDiff(before, after).map((part, i) =>
        part.kind === "same" ? <span key={i}>{part.text}</span>
          : part.kind === "add" ? <ins key={i} className="rounded bg-emerald-100 text-emerald-900 no-underline dark:bg-emerald-900/50 dark:text-emerald-100">{part.text}</ins>
            : <del key={i} className="rounded bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200">{part.text}</del>,
      )}
    </span>
  );
}

export function Warnings({ warnings, className }: { warnings: ResumeWarning[]; className?: string }) {
  if (!warnings.length) return null;
  return (
    <ul className={cn("space-y-0.5 text-xs text-amber-800 dark:text-amber-300", className)}>
      {warnings.map((w, i) => (
        <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />{w.message}</li>
      ))}
    </ul>
  );
}

export function AutoTextArea({ value, onChange, className, label, ...props }: { value: string; onChange: (value: string) => void; className?: string; label: string } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  return (
    <textarea aria-label={label} value={value} rows={1} onChange={(e) => onChange(e.target.value)}
      className={cn(inputClass, "field-sizing-content min-h-9 resize-y py-1.5 leading-relaxed", className)} {...props} />
  );
}

// ---- popover --------------------------------------------------------------------------------------------------

export function Popover({ trigger, children, align = "right", label }: { trigger: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; align?: "left" | "right"; label: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={box} className="relative inline-block">
      {trigger(open, () => setOpen((o) => !o))}
      {open && (
        <div role="dialog" aria-label={label} className={cn("absolute z-30 mt-1 w-80 rounded-xl border border-slate-200 bg-white p-3 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900", align === "right" ? "right-0" : "left-0")}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

// ---- refine -------------------------------------------------------------------------------------------------------

export interface QuickAction {
  label: string;
  instruction: string;
}

/** The ✨ menu: quick actions, keywords to work in (when given), and a free-text instruction (EDT-4). */
export function RefineMenu({ quick, keywords = [], onRefine, busy, label = "Refine with AI" }: {
  quick: QuickAction[]; keywords?: string[]; onRefine: (instruction: string) => void; busy?: boolean; label?: string;
}) {
  const [custom, setCustom] = useState("");
  return (
    <Popover label={label} trigger={(open, toggle) => (
      <button type="button" onClick={toggle} aria-expanded={open} title={label} aria-label={label} disabled={busy}
        className="rounded p-1 text-brand-600 hover:bg-brand-50 disabled:opacity-50 dark:text-brand-300 dark:hover:bg-brand-900/40">
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />}
      </button>
    )}>
      {(close) => (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {quick.map((q) => (
              <Button key={q.label} variant="secondary" size="sm" onClick={() => { close(); onRefine(q.instruction); }}>{q.label}</Button>
            ))}
          </div>
          {keywords.length > 0 && (
            <div>
              <p className="mb-1 text-xs text-slate-500">Emphasize a keyword</p>
              <div className="flex flex-wrap gap-1">
                {keywords.map((k) => (
                  <button key={k} type="button" onClick={() => { close(); onRefine(`Emphasize "${k}", but only if this text's sources support it. If they don't, leave it unchanged and say so.`); }}
                    className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700 hover:bg-brand-50 hover:text-brand-800 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-brand-900/40">{k}</button>
                ))}
              </div>
            </div>
          )}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) { close(); onRefine(custom.trim()); setCustom(""); } }}>
            <input className={cn(inputClass, "py-1.5")} placeholder="Or say how to change it…" value={custom} maxLength={1000}
              onChange={(e) => setCustom(e.target.value)} aria-label="Instruction" />
            <Button type="submit" size="sm" disabled={!custom.trim()}>Go</Button>
          </form>
          <p className="text-xs text-slate-500">You'll see the suggestion before anything changes.</p>
        </div>
      )}
    </Popover>
  );
}

/** A proposed rewrite, shown as a diff with Accept and Discard. */
export function Suggestion({ before, after, warnings = [], onAccept, onDiscard, note }: { before: string; after: string; warnings?: ResumeWarning[]; onAccept: () => void; onDiscard: () => void; note?: string }) {
  return (
    <div className="mt-2 rounded-lg border border-brand-200 bg-brand-50/60 p-3 text-sm dark:border-brand-800 dark:bg-brand-900/20">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-brand-700 dark:text-brand-300"><Sparkles className="size-3.5" aria-hidden /> Suggestion</p>
      <p className="text-slate-800 dark:text-slate-200"><Diff before={before} after={after} /></p>
      <Warnings warnings={warnings} className="mt-1" />
      {note && <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{note}</p>}
      <div className="mt-2 flex gap-2">
        <Button size="sm" icon={<Check className="size-4" aria-hidden />} onClick={onAccept}>Accept</Button>
        <Button size="sm" variant="ghost" icon={<X className="size-4" aria-hidden />} onClick={onDiscard}>Discard</Button>
      </div>
    </div>
  );
}

// ---- drag and drop --------------------------------------------------------------------------------------------------

export interface Handle {
  attributes: ReturnType<typeof useSortable>["attributes"];
  listeners: ReturnType<typeof useSortable>["listeners"];
  setActivatorNodeRef: (element: HTMLElement | null) => void;
}

function SortableRow({ id, children }: { id: string; children: (handle: Handle) => ReactNode }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <div ref={setNodeRef} style={{ transform: DndCSS.Translate.toString(transform), transition }} className={cn(isDragging && "relative z-10 opacity-80")}>
      {children({ attributes, listeners, setActivatorNodeRef })}
    </div>
  );
}

export function SortableList<T>({ items, idOf, onMove, children }: { items: T[]; idOf: (item: T) => string; onMove: (from: number, to: number) => void; children: (item: T, index: number, handle: Handle) => ReactNode }) {
  const ids = items.map(idOf);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) onMove(ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
  };
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {items.map((item, i) => <SortableRow key={ids[i]} id={ids[i]!}>{(handle) => children(item, i, handle)}</SortableRow>)}
      </SortableContext>
    </DndContext>
  );
}

export function DragHandle({ handle, label }: { handle: Handle; label: string }) {
  return (
    <button type="button" ref={handle.setActivatorNodeRef} {...handle.attributes} {...handle.listeners} aria-label={`Drag to reorder ${label}`}
      className="mt-1.5 cursor-grab touch-none rounded p-0.5 text-slate-400 hover:text-slate-600 active:cursor-grabbing">
      <GripVertical className="size-4" aria-hidden />
    </button>
  );
}

export function move<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const copy = [...list];
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item as T);
  return copy;
}
