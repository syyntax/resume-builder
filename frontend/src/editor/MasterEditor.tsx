/**
 * The structured master résumé editor (MST-4): every section as forms, with drag-and-drop ordering, pin
 * and hide toggles, tags, priorities and bullet variants. It edits a document from `toEditable` and calls
 * `onChange` with an update function; the page owns undo history and saving. Import review passes `flags`
 * so the fields they point at are highlighted, and `activeFlagKey` to scroll to one.
 */

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS as DndCSS } from "@dnd-kit/utilities";
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Eye,
  EyeOff,
  Flag,
  GripVertical,
  Pin,
  PinOff,
  Plus,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { ImportFlag } from "../api/types";
import { Badge, Button, cn } from "../components/ui";
import {
  KEY,
  type Json,
  type JsonObject,
  type Path,
  findById,
  getIn,
  insertAt,
  isObject,
  keyOf,
  listAt,
  moveItem,
  newKey,
  pathToString,
  removeAt,
  setIn,
} from "./doc";
import { AutoTextArea, Field } from "./fields";
import {
  BASICS_FIELDS,
  CUSTOM_ITEM,
  CUSTOM_SECTION,
  type FieldSpec,
  LOCATION_FIELDS,
  PREFERENCE_FIELDS,
  PROFILE_FIELDS,
  SECTIONS,
  type SectionSpec,
} from "./sections";

type Update = (doc: Json) => Json;

interface EditorContextValue {
  doc: Json;
  change: (update: Update, group?: string) => void;
  issues: Map<string, string>;
  flags: ImportFlag[];
  skills: { id: string; name: string }[];
  expanded: Set<string>;
  setOpen: (key: string, open: boolean) => void;
  focusKey: string | null;
  setFocusKey: (key: string | null) => void;
  /** Section headings: h2 when the editor is the page, h3 under a page's own h2 (import review). */
  heading: "h2" | "h3";
}

const EditorContext = createContext<EditorContextValue | null>(null);

function useEditor(): EditorContextValue {
  const value = useContext(EditorContext);
  if (!value) throw new Error("useEditor outside MasterEditor");
  return value;
}

const COMMON_FIELDS: FieldSpec[] = [
  { key: "tags", label: "Tags", kind: "list", hint: "Topics for relevance matching, e.g. leadership." },
  {
    key: "priority", label: "Priority", kind: "select",
    options: [5, 4, 3, 2, 1].map((n) => ({ value: n, label: `${n}${n === 5 ? " (prefer)" : n === 1 ? " (avoid)" : n === 3 ? " (normal)" : ""}` })),
  },
];

const str = (value: Json | undefined) => (typeof value === "string" ? value : "");

/** Every id at or below `node`: an item's own flags plus those on its bullets and sub-items. */
function idsWithin(node: Json): string[] {
  const out: string[] = [];
  const walk = (value: Json) => {
    if (Array.isArray(value)) value.forEach(walk);
    else if (isObject(value)) {
      if (typeof value.id === "string") out.push(value.id);
      Object.values(value).forEach(walk);
    }
  };
  walk(node);
  return out;
}

function issueUnder(issues: Map<string, string>, path: Path): boolean {
  const prefix = pathToString(path);
  for (const key of issues.keys()) {
    if (key === prefix || key.startsWith(`${prefix}.`) || key.startsWith(`${prefix}[`)) return true;
  }
  return false;
}

// ---- drag and drop ----------------------------------------------------------------------------------------

interface HandleProps {
  attributes: ReturnType<typeof useSortable>["attributes"];
  listeners: ReturnType<typeof useSortable>["listeners"];
  setActivatorNodeRef: (element: HTMLElement | null) => void;
}

function SortableItem({ id, children }: { id: string; children: (handle: HandleProps) => ReactNode }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <div ref={setNodeRef} style={{ transform: DndCSS.Translate.toString(transform), transition }} className={cn(isDragging && "relative z-10 opacity-80")}>
      {children({ attributes, listeners, setActivatorNodeRef })}
    </div>
  );
}

function DragHandle({ handle, label }: { handle: HandleProps; label: string }) {
  return (
    <button type="button" ref={handle.setActivatorNodeRef} {...handle.attributes} {...handle.listeners} aria-label={`Drag to reorder ${label}`}
      className="cursor-grab touch-none rounded p-1 text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing dark:hover:bg-slate-800">
      <GripVertical className="size-4" aria-hidden />
    </button>
  );
}

function SortableList({ path, children }: { path: Path; children: (item: Json, index: number, handle: HandleProps) => ReactNode }) {
  const { doc, change } = useEditor();
  const items = listAt(doc, path);
  const ids = items.map(keyOf);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    change((d) => moveItem(d, path, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  };
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {items.map((item, index) => (
          <SortableItem key={ids[index]} id={ids[index] ?? String(index)}>
            {(handle) => children(item, index, handle)}
          </SortableItem>
        ))}
      </SortableContext>
    </DndContext>
  );
}

// ---- small controls --------------------------------------------------------------------------------------

function IconToggle({ on, onIcon, offIcon, label, onChange }: { on: boolean; onIcon: ReactNode; offIcon: ReactNode; label: string; onChange: (on: boolean) => void }) {
  return (
    <button type="button" aria-pressed={on} title={label} aria-label={label} onClick={() => onChange(!on)}
      className={cn("rounded p-1 transition-colors", on ? "text-brand-600 dark:text-brand-300" : "text-slate-500 dark:text-slate-400 hover:text-slate-600 dark:hover:text-slate-300")}>
      {on ? onIcon : offIcon}
    </button>
  );
}

function IconButton({ label, onClick, children, disabled, tone }: { label: string; onClick: () => void; children: ReactNode; disabled?: boolean; tone?: "danger" }) {
  return (
    <button type="button" title={label} aria-label={label} onClick={onClick} disabled={disabled}
      className={cn("rounded p-1 text-slate-500 dark:text-slate-400 transition-colors disabled:opacity-30",
        tone === "danger" ? "hover:text-red-600" : "hover:text-slate-700 dark:hover:text-slate-200")}>
      {children}
    </button>
  );
}

function useFieldProps(path: Path, targetId: string | undefined) {
  const { doc, change, issues, flags, skills } = useEditor();
  return (spec: FieldSpec, fieldPath: Path = [...path, spec.key], fieldName = spec.key) => ({
    spec,
    value: getIn(doc, fieldPath),
    onChange: (value: Json | undefined) => change((d) => setIn(d, fieldPath, value), pathToString(fieldPath)),
    error: issues.get(pathToString(fieldPath)) ?? null,
    flagged: Boolean(targetId) && flags.some((f) => f.targetId === targetId && f.field === fieldName),
    target: targetId ? `${targetId}:${fieldName}` : undefined,
    skills,
  });
}

// ---- bullets -------------------------------------------------------------------------------------------------

function Variants({ path }: { path: Path }) {
  const { doc, change } = useEditor();
  const variants = listAt(doc, path);
  return (
    <div className="sm:col-span-2">
      <p className="mb-1 text-xs font-medium text-slate-600 dark:text-slate-400">Alternative phrasings</p>
      <div className="space-y-2">
        {variants.map((variant, i) => (
          <div key={keyOf(variant) || i} className="flex items-start gap-2">
            <AutoTextArea aria-label={`Variant ${i + 1}`} value={str(isObject(variant) ? variant.text : undefined)}
              onChange={(v) => change((d) => setIn(d, [...path, i, "text"], v), pathToString([...path, i, "text"]))} />
            <IconButton label="Delete variant" tone="danger" onClick={() => change((d) => removeAt(d, path, i))}>
              <Trash2 className="size-4" aria-hidden />
            </IconButton>
          </div>
        ))}
      </div>
      <Button className="mt-2" variant="ghost" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
        onClick={() => change((d) => insertAt(d, path, { text: "" }))}>
        Add phrasing
      </Button>
    </div>
  );
}

function BulletRow({ path, index, count, item, handle }: { path: Path; index: number; count: number; item: Json; handle: HandleProps }) {
  const { change, issues, flags, focusKey } = useEditor();
  const [details, setDetails] = useState(false);
  const bullet = isObject(item) ? item : {};
  const own = [...path, index];
  const id = typeof bullet.id === "string" ? bullet.id : undefined;
  const flagged = Boolean(id) && flags.some((f) => f.targetId === id);
  const fieldProps = useFieldProps(own, id);
  const textPath = [...own, "text"];
  const error = issues.get(pathToString(textPath)) ?? issues.get(pathToString(own));
  const listPath = path;
  return (
    <div data-item-target={id} className={cn("group rounded-lg py-1", bullet.hidden === true && "opacity-60")}>
      <div className="flex items-start gap-1">
        <DragHandle handle={handle} label="bullet" />
        <div className={cn("min-w-0 flex-1 rounded-lg", flagged && "ring-2 ring-amber-400 ring-offset-1 dark:ring-offset-slate-900")}>
          <AutoTextArea aria-label={`Bullet ${index + 1}`} value={str(bullet.text)} autoFocus={focusKey === keyOf(item)}
            placeholder="Led …, cutting … by …" aria-invalid={Boolean(error) || undefined}
            onChange={(v) => change((d) => setIn(d, textPath, v), pathToString(textPath))} />
        </div>
        <div className="flex shrink-0 items-center pt-1">
          <IconToggle on={bullet.pin === true} label={bullet.pin ? "Unpin bullet" : "Pin bullet (always include)"}
            onIcon={<Pin className="size-4" aria-hidden />} offIcon={<PinOff className="size-4" aria-hidden />}
            onChange={(on) => change((d) => setIn(d, [...own, "pin"], on || undefined))} />
          <IconToggle on={bullet.hidden === true} label={bullet.hidden ? "Show bullet" : "Hide bullet (never include)"}
            onIcon={<EyeOff className="size-4" aria-hidden />} offIcon={<Eye className="size-4" aria-hidden />}
            onChange={(on) => change((d) => setIn(d, [...own, "hidden"], on || undefined))} />
          <IconToggle on={details} label="Bullet details" onIcon={<SlidersHorizontal className="size-4" aria-hidden />}
            offIcon={<SlidersHorizontal className="size-4" aria-hidden />} onChange={setDetails} />
          <IconButton label="Move bullet up" disabled={index === 0} onClick={() => change((d) => moveItem(d, listPath, index, index - 1))}>
            <ArrowUp className="size-4" aria-hidden />
          </IconButton>
          <IconButton label="Move bullet down" disabled={index === count - 1} onClick={() => change((d) => moveItem(d, listPath, index, index + 1))}>
            <ArrowDown className="size-4" aria-hidden />
          </IconButton>
          <IconButton label="Delete bullet" tone="danger" onClick={() => change((d) => removeAt(d, listPath, index))}>
            <Trash2 className="size-4" aria-hidden />
          </IconButton>
        </div>
      </div>
      {error && <p className="ml-8 mt-1 text-xs text-red-600 dark:text-red-400">{error}</p>}
      {details && (
        <div className="mt-2 ml-8 grid gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-2 dark:bg-slate-800/50">
          {COMMON_FIELDS.map((spec) => <Field key={spec.key} {...fieldProps(spec)} />)}
          <Field {...fieldProps({ key: "skills", label: "Skills shown", kind: "skills", wide: true })} />
          <Variants path={[...own, "variants"]} />
          {id && <p className="text-xs text-slate-500 dark:text-slate-400 sm:col-span-2">ID: <code>{id}</code></p>}
        </div>
      )}
    </div>
  );
}

function Bullets({ path }: { path: Path }) {
  const { doc, change, setFocusKey } = useEditor();
  const count = listAt(doc, path).length;
  return (
    <div className="sm:col-span-2">
      <p className="mb-1 text-xs font-medium text-slate-600 dark:text-slate-400">Bullets ({count})</p>
      <SortableList path={path}>
        {(item, index, handle) => <BulletRow path={path} index={index} count={count} item={item} handle={handle} />}
      </SortableList>
      <Button className="mt-1" variant="ghost" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
        onClick={() => {
          const bullet = { [KEY]: newKey(), text: "" };
          change((d) => insertAt(d, path, bullet));
          setFocusKey(bullet[KEY]);
        }}>
        Add bullet
      </Button>
    </div>
  );
}

// ---- items and sections ---------------------------------------------------------------------------------

function ItemCard({ spec, listPath, index, count, item, handle }: { spec: SectionSpec; listPath: Path; index: number; count: number; item: Json; handle: HandleProps }) {
  const { change, issues, flags, expanded, setOpen } = useEditor();
  const obj = isObject(item) ? item : {};
  const path = [...listPath, index];
  const key = keyOf(item);
  const open = expanded.has(key);
  const id = typeof obj.id === "string" ? obj.id : undefined;
  const fieldProps = useFieldProps(path, id);
  const within = new Set(idsWithin(item));
  const flagCount = flags.filter((f) => f.targetId && within.has(f.targetId)).length;
  const hasIssue = issueUnder(issues, path);
  const detail = spec.detail?.(obj);

  return (
    <div data-item-target={id}
      className={cn("rounded-xl border bg-white dark:bg-slate-900", hasIssue ? "border-red-300 dark:border-red-800" : "border-slate-200 dark:border-slate-800",
        obj.hidden === true && "opacity-70")}>
      <div className="flex items-center gap-1 px-2 py-1.5">
        <DragHandle handle={handle} label={spec.item} />
        <button type="button" onClick={() => setOpen(key, !open)} aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 rounded px-1 py-1 text-left hover:bg-slate-50 dark:hover:bg-slate-800/60">
          <ChevronRight className={cn("size-4 shrink-0 text-slate-400 transition-transform", open && "rotate-90")} aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">{spec.title(obj)}</span>
            {detail && <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{detail}</span>}
          </span>
          {flagCount > 0 && <Badge tone="amber"><Flag className="mr-1 size-3" aria-hidden />{flagCount}</Badge>}
          {hasIssue && <Badge tone="red">Fix</Badge>}
          {obj.pin === true && <Badge tone="brand">Pinned</Badge>}
          {obj.hidden === true && <Badge>Hidden</Badge>}
        </button>
        {spec.common && (
          <>
            <IconToggle on={obj.pin === true} label={obj.pin ? `Unpin ${spec.item}` : `Pin ${spec.item} (always include)`}
              onIcon={<Pin className="size-4" aria-hidden />} offIcon={<PinOff className="size-4" aria-hidden />}
              onChange={(on) => change((d) => setIn(d, [...path, "pin"], on || undefined))} />
            <IconToggle on={obj.hidden === true} label={obj.hidden ? `Show ${spec.item}` : `Hide ${spec.item} (never include)`}
              onIcon={<EyeOff className="size-4" aria-hidden />} offIcon={<Eye className="size-4" aria-hidden />}
              onChange={(on) => change((d) => setIn(d, [...path, "hidden"], on || undefined))} />
          </>
        )}
        <IconButton label={`Move ${spec.item} up`} disabled={index === 0} onClick={() => change((d) => moveItem(d, listPath, index, index - 1))}>
          <ArrowUp className="size-4" aria-hidden />
        </IconButton>
        <IconButton label={`Move ${spec.item} down`} disabled={index === count - 1} onClick={() => change((d) => moveItem(d, listPath, index, index + 1))}>
          <ArrowDown className="size-4" aria-hidden />
        </IconButton>
        <IconButton label={`Delete ${spec.item}`} tone="danger" onClick={() => change((d) => removeAt(d, listPath, index))}>
          <Trash2 className="size-4" aria-hidden />
        </IconButton>
      </div>
      {open && (
        <div className="grid gap-3 border-t border-slate-100 px-4 py-4 sm:grid-cols-2 dark:border-slate-800">
          {spec.fields.map((field) => <Field key={field.key} {...fieldProps(field)} />)}
          {spec.common && spec !== CUSTOM_SECTION && COMMON_FIELDS.map((field) => <Field key={field.key} {...fieldProps(field)} />)}
          {spec.bullets && <Bullets path={[...path, "highlights"]} />}
          {spec === CUSTOM_SECTION && (
            <div className="sm:col-span-2">
              <ItemList spec={CUSTOM_ITEM} path={[...path, "items"]} />
            </div>
          )}
          {id && <p className="text-xs text-slate-500 dark:text-slate-400 sm:col-span-2">ID: <code>{id}</code></p>}
        </div>
      )}
    </div>
  );
}

function ItemList({ spec, path }: { spec: SectionSpec; path: Path }) {
  const { doc, change, setOpen } = useEditor();
  const items = listAt(doc, path);
  return (
    <div className="space-y-2">
      <SortableList path={path}>
        {(item, index, handle) => <ItemCard spec={spec} listPath={path} index={index} count={items.length} item={item} handle={handle} />}
      </SortableList>
      <Button variant="secondary" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
        onClick={() => {
          const item: JsonObject = { [KEY]: newKey(), ...spec.blank() };
          change((d) => insertAt(d, path, item));
          setOpen(item[KEY] as string, true);
        }}>
        Add {spec.item}
      </Button>
    </div>
  );
}

function SectionFrame({ id, title, count, actions, children }: { id: string; title: string; count?: number; actions?: ReactNode; children: ReactNode }) {
  const Heading = useEditor().heading;
  return (
    <section id={`ed-${id}`} className="scroll-mt-24 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2 dark:border-slate-800">
        <Heading className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {title} {count !== undefined && <span className="font-normal text-slate-500 dark:text-slate-400">({count})</span>}
        </Heading>
        {actions && <div className="flex items-center gap-1">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

function ListSection({ spec }: { spec: SectionSpec }) {
  const { doc, setOpen } = useEditor();
  const items = listAt(doc, [spec.key]);
  const keys = items.map(keyOf);
  return (
    <SectionFrame id={spec.key} title={spec.label} count={items.length}
      actions={items.length > 0 && (
        <>
          <Button variant="ghost" size="sm" onClick={() => keys.forEach((k) => setOpen(k, true))}>Expand all</Button>
          <Button variant="ghost" size="sm" onClick={() => keys.forEach((k) => setOpen(k, false))}>Collapse all</Button>
        </>
      )}>
      <ItemList spec={spec} path={[spec.key]} />
    </SectionFrame>
  );
}

function BasicsSection() {
  const { doc, change } = useEditor();
  const fieldProps = useFieldProps(["basics"], "basics");
  const profiles = listAt(doc, ["basics", "profiles"]);
  return (
    <SectionFrame id="basics" title="Contact details">
      <div className="grid gap-3 sm:grid-cols-2">
        {BASICS_FIELDS.map((field) => <Field key={field.key} {...fieldProps(field)} />)}
        {LOCATION_FIELDS.map((field) => (
          <Field key={field.key} {...fieldProps(field, ["basics", "location", field.key], `location.${field.key}`)} />
        ))}
        <Field {...fieldProps({ key: "remote", label: "Open to remote work", kind: "checkbox" }, ["basics", "location", "remote"], "location.remote")} />
      </div>
      <div className="space-y-2">
        <p className="text-xs font-medium text-slate-600 dark:text-slate-400">Profiles</p>
        {profiles.map((profile, i) => (
          <div key={keyOf(profile) || i} className="flex items-end gap-2">
            <div className="grid flex-1 gap-2 sm:grid-cols-3">
              {PROFILE_FIELDS.map((field) => (
                <Field key={field.key} {...fieldProps(field, ["basics", "profiles", i, field.key], `profiles.${field.key}`)} />
              ))}
            </div>
            <IconButton label="Delete profile" tone="danger" onClick={() => change((d) => removeAt(d, ["basics", "profiles"], i))}>
              <Trash2 className="size-4" aria-hidden />
            </IconButton>
          </div>
        ))}
        <Button variant="ghost" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
          onClick={() => change((d) => insertAt(d, ["basics", "profiles"], { network: "" }))}>
          Add profile
        </Button>
      </div>
    </SectionFrame>
  );
}

function PreferencesSection() {
  const fieldProps = useFieldProps(["preferences"], undefined);
  return (
    <SectionFrame id="preferences" title="Tailoring preferences">
      <div className="grid gap-3 sm:grid-cols-2">
        {PREFERENCE_FIELDS.map((field) => <Field key={field.key} {...fieldProps(field)} />)}
      </div>
    </SectionFrame>
  );
}

// ---- the editor ---------------------------------------------------------------------------------------------

export const SECTION_ORDER: SectionSpec[] = [...SECTIONS, CUSTOM_SECTION];

export interface MasterEditorProps {
  value: Json;
  onChange: (update: Update, group?: string) => void;
  /** Validation errors from the server, by path ("work[2].startDate"). */
  issues?: Map<string, string>;
  /** Unresolved import flags to highlight. */
  flags?: ImportFlag[];
  /** Scroll to and focus this flag's field. */
  activeFlag?: ImportFlag | null;
  /** Show the section index beside the form (the full-page editor). */
  withNav?: boolean;
}

export function MasterEditor({ value, onChange, issues = new Map(), flags = [], activeFlag = null, withNav = false }: MasterEditorProps) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [shown, setShown] = useState<Set<string>>(() => new Set());
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const setOpen = useCallback((key: string, open: boolean) => {
    setExpanded((current) => {
      if (current.has(key) === open) return current;
      const next = new Set(current);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const change = onChange;

  const skills = useMemo(() => listAt(value, ["skills"]).flatMap((s) =>
    isObject(s) && typeof s.name === "string" ? [{ id: typeof s.id === "string" ? s.id : s.name, name: s.name }] : []), [value]);

  // Open (and scroll to) whatever the active flag points at.
  useEffect(() => {
    if (!activeFlag) return;
    const target = activeFlag.targetId;
    let selector: string | null = null;
    let section: string | undefined;
    if (target) {
      const path = target === "basics" ? ["basics"] : findById(value, target);
      section = path ? String(path[0]) : undefined;
      if (path) {
        for (let i = 1; i <= path.length; i += 1) {
          if (typeof path[i - 1] === "number") {
            const key = keyOf(getIn(value, path.slice(0, i)) ?? null);
            if (key) setOpen(key, true);
          }
        }
      }
      const escaped = CSS_ESCAPE(target);
      selector = activeFlag.field ? `[data-field-target="${escaped}:${CSS_ESCAPE(activeFlag.field)}"]` : `[data-item-target="${escaped}"]`;
    } else if (activeFlag.path) {
      section = activeFlag.path.split(/[.[]/)[0];
      selector = `#ed-${section}`;
    }
    if (section) setShown((current) => (current.has(section) ? current : new Set(current).add(section)));
    const timer = window.setTimeout(() => {
      const element = (selector && document.querySelector<HTMLElement>(selector)) || (target && document.querySelector<HTMLElement>(`[data-item-target="${CSS_ESCAPE(target)}"]`));
      if (!element) return;
      element.scrollIntoView?.({ block: "center", behavior: "smooth" });
      element.querySelector<HTMLElement>("input, textarea, select")?.focus({ preventScroll: true });
    }, 60);
    return () => window.clearTimeout(timer);
  }, [activeFlag?.key]); // when a different flag becomes active, not on every edit

  // Open items that have validation errors, so the errors are visible.
  useEffect(() => {
    for (const path of issues.keys()) {
      const parts = path.match(/^([A-Za-z]+)\[(\d+)\]/);
      if (!parts) continue;
      const item = getIn(value, [parts[1]!, Number(parts[2])]);
      if (item) setOpen(keyOf(item), true);
    }
  }, [issues]); // when new errors arrive

  const context: EditorContextValue = { doc: value, change, issues, flags, skills, expanded, setOpen, focusKey, setFocusKey, heading: withNav ? "h2" : "h3" };
  const visible = SECTION_ORDER.filter((s) => listAt(value, [s.key]).length > 0 || shown.has(s.key));
  const hidden = SECTION_ORDER.filter((s) => !visible.includes(s));

  const body = (
    <div className="min-w-0 flex-1 space-y-8">
      <BasicsSection />
      {visible.map((spec) => <ListSection key={spec.key} spec={spec} />)}
      {hidden.length > 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-3 dark:border-slate-700">
          <p className="mb-2 text-xs font-medium text-slate-600 dark:text-slate-400">Add a section</p>
          <div className="flex flex-wrap gap-2">
            {hidden.map((spec) => (
              <Button key={spec.key} variant="secondary" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
                onClick={() => {
                  const item: JsonObject = { [KEY]: newKey(), ...spec.blank() };
                  setShown((current) => new Set(current).add(spec.key));
                  change((d) => insertAt(d, [spec.key], item));
                  setOpen(item[KEY] as string, true);
                }}>
                {spec.label}
              </Button>
            ))}
          </div>
        </div>
      )}
      <PreferencesSection />
    </div>
  );

  return (
    <EditorContext.Provider value={context}>
      {withNav ? (
        <div className="flex gap-8">
          <nav aria-label="Sections" className="sticky top-6 hidden h-fit w-44 shrink-0 space-y-0.5 text-sm lg:block">
            {[{ key: "basics", label: "Contact details" }, ...visible, { key: "preferences", label: "Preferences" }].map((s) => (
              <a key={s.key} href={`#ed-${s.key}`} className="flex justify-between rounded-md px-2 py-1 text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100">
                {s.label}
                {s.key !== "basics" && s.key !== "preferences" && <span className="tabular-nums text-slate-500 dark:text-slate-400">{listAt(value, [s.key]).length}</span>}
              </a>
            ))}
          </nav>
          {body}
        </div>
      ) : body}
    </EditorContext.Provider>
  );
}

const CSS_ESCAPE = (value: string) => (window.CSS?.escape ? window.CSS.escape(value) : value.replace(/["\\]/g, "\\$&"));

export type { Update as EditorUpdate };
