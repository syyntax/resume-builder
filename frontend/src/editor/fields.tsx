import { X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, type TextareaHTMLAttributes, useId, useState } from "react";

import { cn, inputClass } from "../components/ui";
import type { Json } from "./doc";
import type { FieldSpec } from "./sections";

const DATE = /^\d{4}(-\d{1,2}(-\d{1,2})?)?$/;

export function dateProblem(value: string): string | null {
  if (!value || DATE.test(value.trim())) return null;
  if (/^(present|current|now)$/i.test(value.trim())) return null;
  return "Use YYYY, YYYY-MM or YYYY-MM-DD";
}

interface FieldShellProps {
  label: string;
  id: string;
  error?: string | null;
  hint?: string;
  flagged?: boolean;
  wide?: boolean;
  required?: boolean;
  target?: string;
  children: ReactNode;
}

/** Label, input, and the error or hint below it. `flagged` marks a field an import flag points at. */
export function FieldShell({ label, id, error, hint, flagged, wide, required, target, children }: FieldShellProps) {
  return (
    <div className={cn(wide && "sm:col-span-2", "min-w-0")} data-field-target={target}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
        {required && <span className="text-red-500" aria-hidden> *</span>}
      </label>
      <div className={cn("rounded-lg", flagged && "ring-2 ring-amber-400 ring-offset-1 dark:ring-offset-slate-900")}>{children}</div>
      {(error || hint) && (
        <p className={cn("mt-1 text-xs", error ? "text-red-600 dark:text-red-400" : "text-slate-500 dark:text-slate-400")}>{error ?? hint}</p>
      )}
    </div>
  );
}

const compact = cn(inputClass, "py-1.5");

export function AutoTextArea({ value, onChange, className, ...props }: { value: string; onChange: (value: string) => void; className?: string } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  return (
    <textarea
      value={value}
      rows={1}
      onChange={(e) => onChange(e.target.value)}
      className={cn(compact, "field-sizing-content min-h-9 resize-y", className)}
      {...props}
    />
  );
}

/** Chips for a list of short strings: Enter or comma adds, Backspace on an empty input removes the last. */
export function ChipInput({ id, values, onChange, placeholder, suggestions, describe }: {
  id: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  suggestions?: { value: string; label: string }[];
  describe?: (value: string) => string;
}) {
  const [draft, setDraft] = useState("");
  const listId = useId();
  const add = (raw: string) => {
    const value = raw.trim();
    if (!value) return;
    const match = suggestions?.find((s) => s.label.toLowerCase() === value.toLowerCase() || s.value === value);
    const next = match?.value ?? value;
    if (!values.includes(next)) onChange([...values, next]);
    setDraft("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(draft);
    } else if (event.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div className={cn(compact, "flex min-h-9 flex-wrap items-center gap-1.5 py-1")}>
      {values.map((value) => (
        <span key={value} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {describe ? describe(value) : value}
          <button type="button" className="rounded text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-white" aria-label={`Remove ${describe ? describe(value) : value}`}
            onClick={() => onChange(values.filter((v) => v !== value))}>
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        list={suggestions ? listId : undefined}
        placeholder={values.length ? undefined : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => add(draft)}
        className="min-w-24 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
      />
      {suggestions && (
        <datalist id={listId}>
          {suggestions.filter((s) => !values.includes(s.value)).map((s) => <option key={s.value} value={s.label} />)}
        </datalist>
      )}
    </div>
  );
}

export interface FieldProps {
  spec: FieldSpec;
  value: Json | undefined;
  onChange: (value: Json | undefined) => void;
  error?: string | null;
  flagged?: boolean;
  target?: string;
  skills?: { id: string; name: string }[];
}

/** One field of an item, rendered by its kind. Clearing a field removes it from the document. */
export function Field({ spec, value, onChange, error, flagged, target, skills = [] }: FieldProps) {
  const id = useId();
  const text = typeof value === "string" ? value : typeof value === "number" ? String(value) : "";
  const shell = (control: ReactNode, problem?: string | null) => (
    <FieldShell label={spec.label} id={id} error={error ?? problem} hint={spec.hint} flagged={flagged} wide={spec.wide}
      required={spec.required} target={target}>
      {control}
    </FieldShell>
  );

  switch (spec.kind) {
    case "textarea":
      return shell(<AutoTextArea id={id} value={text} onChange={(v) => onChange(v)} placeholder={spec.placeholder} className="min-h-16" />);
    case "date":
    case "enddate":
      return shell(
        <input id={id} value={text} inputMode="numeric" placeholder={spec.placeholder} className={compact}
          onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(error ?? dateProblem(text)) || undefined} />,
        dateProblem(text),
      );
    case "number":
      return shell(
        <input id={id} type="number" min={0} value={text} className={compact}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />,
      );
    case "select":
      return shell(
        <select id={id} className={compact} value={text}
          onChange={(e) => {
            const option = spec.options?.find((o) => String(o.value) === e.target.value);
            onChange(option ? option.value : undefined);
          }}>
          <option value="">Default</option>
          {spec.options?.map((o) => <option key={o.value} value={String(o.value)}>{o.label}</option>)}
        </select>,
      );
    case "checkbox":
      return (
        <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700 dark:text-slate-300" data-field-target={target}>
          <input type="checkbox" className="size-4 rounded border-slate-300 text-brand-600" checked={value === true}
            onChange={(e) => onChange(e.target.checked || undefined)} />
          {spec.label}
        </label>
      );
    case "list":
    case "skills": {
      const values = Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
      const byId = new Map(skills.map((s) => [s.id, s.name]));
      return shell(
        <ChipInput id={id} values={values} onChange={(v) => onChange(v)}
          placeholder={spec.kind === "skills" ? "Type a skill and press Enter" : "Type and press Enter"}
          suggestions={spec.kind === "skills" ? skills.map((s) => ({ value: s.id, label: s.name })) : undefined}
          describe={spec.kind === "skills" ? (v) => byId.get(v) ?? v : undefined} />,
      );
    }
    default:
      return shell(
        <input id={id} type={spec.kind === "email" ? "email" : spec.kind === "url" ? "url" : "text"} value={text}
          placeholder={spec.placeholder} className={compact} onChange={(e) => onChange(e.target.value)} />,
      );
  }
}
