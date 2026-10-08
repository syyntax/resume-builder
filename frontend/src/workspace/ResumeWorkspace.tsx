/**
 * The résumé tab of the workspace (DESIGN.md §12.2, EDT-1…EDT-6): an editor beside the live PDF.
 * Sections, items and bullets can be reordered, removed and re-added from the master; bullets are edited
 * inline with their provenance, warnings, and AI refine. Everything autosaves; ⌘Z undoes.
 */

import { BookOpen, Info, Plus, Redo2, RotateCcw, Sparkles, Trash2, Undo2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { ApplicationDetail, JobAnalysis, RefineResult, ResumeBullet, ResumeItem, ResumeSection, TailoredResume } from "../api/types";
import { Alert, Badge, Button, cn, inputClass } from "../components/ui";
import { useHistory, useUndoShortcuts } from "../editor/history";
import { formatPartialDate, formatUsd } from "../lib/format";
import { DesignDisclosure, FitBanner, PdfPreview, useFit } from "./preview";
import {
  type Candidate, type MasterIndex, WITH_BULLETS, addBullet, applyChange, candidates, indexMaster, itemTitle,
  mentions, mergeSaved, moveBullet, moveItem, moveSection, newBulletId, removeBullet, removeItem, removeSection, removeSkill,
  renameSection, setBlock, setBullet, setItemBullets, sourceTexts,
} from "./resumeOps";
import {
  AutoTextArea, Diff, DragHandle, Popover, type QuickAction, RefineMenu, SaveIndicator, SortableList, Suggestion, Warnings, useAutosave,
} from "./shared";

type Json = Record<string, unknown>;

const BULLET_ACTIONS: QuickAction[] = [
  { label: "Rephrase", instruction: "Rephrase this bullet so it reads better, keeping every fact." },
  { label: "Shorten", instruction: "Make this bullet shorter, keeping the most important result." },
  { label: "Lead with impact", instruction: "Rewrite so the result comes first." },
];
const ITEM_ACTIONS: QuickAction[] = [
  { label: "Rewrite for this job", instruction: "Pick and rewrite this role's best bullets for this job." },
  { label: "Fewer, stronger", instruction: "Keep only the strongest bullets, rewritten tightly." },
];
const DOC_ACTIONS: QuickAction[] = [
  { label: "More leadership", instruction: "Make the résumé more leadership-focused." },
  { label: "More technical", instruction: "Make the résumé more technically specific." },
  { label: "Tighter", instruction: "Tighten every bullet without losing results." },
];

interface Props {
  application: ApplicationDetail;
  master: Json;
}

export function ResumeWorkspace({ application, master }: Props) {
  const history = useHistory<TailoredResume>(application.resume as unknown as TailoredResume);
  useUndoShortcuts(history);
  const [revision, setRevision] = useState(0);
  const save = useAutosave<TailoredResume, { document: TailoredResume }>({
    value: history.value, edits: history.edits, url: `/api/applications/${application.id}/resume`, body: (document) => ({ document }),
    onSaved: (result) => {
      history.replace((local) => mergeSaved(local, result.document));
      setRevision((r) => r + 1);
    },
  });
  const doc = history.value;
  // Fit to page saves on the server: take its result as the new starting point (undo is the banner's Undo)
  const fit = useFit<TailoredResume>(application, "resume", (fitted) => { history.reset(fitted); setRevision((r) => r + 1); });
  const index = useMemo(() => indexMaster(master), [master]);
  const analysis = application.analysis as unknown as JobAnalysis | null;
  const [suggestions, setSuggestions] = useState<Record<string, RefineResult["changes"][number]>>({});
  const [itemSuggestions, setItemSuggestions] = useState<Record<string, ResumeBullet[]>>({});
  const [docSuggestion, setDocSuggestion] = useState<RefineResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [drawer, setDrawer] = useState<{ open: boolean; keyword: string | null }>({ open: false, keyword: null });

  const refine = async (scope: "bullet" | "item" | "headline" | "summary" | "document", targetId: string | null, instruction: string) => {
    setBusy(`${scope}:${targetId ?? ""}`);
    setMessage(null);
    try {
      const result = await api<RefineResult>("POST", `/api/applications/${application.id}/resume/refine`, { json: { scope, targetId, instruction } });
      const notes = result.notes.map((n) => n.text).join(" ");
      if (scope === "document") {
        setDocSuggestion(result);
      } else {
        setSuggestions((s) => ({ ...s, ...Object.fromEntries(result.changes.map((c) => [c.targetId, c])) }));
        setItemSuggestions((s) => ({ ...s, ...Object.fromEntries(result.items.map((i) => [i.itemId, i.bullets as unknown as ResumeBullet[]])) }));
        if (!result.changes.length && !result.items.length) setMessage({ tone: "info", text: notes || "No change was suggested." });
      }
      if (notes && scope !== "document") setMessage({ tone: "info", text: `${notes} (${formatUsd(result.costUsd)})` });
    } catch (e) {
      setMessage({ tone: "error", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  };

  const update = (change: (d: TailoredResume) => TailoredResume, group?: string) => history.set(change, group);
  const dismiss = (key: string) => setSuggestions(({ [key]: _, ...rest }) => rest);
  const warnings = doc.analysis?.warnings?.length ?? 0;
  // Keywords to offer in each bullet's refine menu: the missing ones first, then by importance
  const keywords = useMemo(() => {
    const missing = new Set(doc.analysis?.coverage?.missing ?? []);
    return [...(analysis?.keywords ?? [])]
      .sort((a, b) => Number(missing.has(b.term)) - Number(missing.has(a.term)) || b.importance - a.importance)
      .slice(0, 6).map((k) => k.term);
  }, [analysis, doc.analysis?.coverage?.missing]);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
      <div className="min-w-0 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" icon={<Undo2 className="size-4" aria-hidden />} disabled={!history.canUndo} onClick={history.undo} title="Undo (⌘Z)"><span className="sr-only">Undo</span></Button>
            <Button variant="ghost" size="sm" icon={<Redo2 className="size-4" aria-hidden />} disabled={!history.canRedo} onClick={history.redo} title="Redo (⇧⌘Z)"><span className="sr-only">Redo</span></Button>
            <SaveIndicator state={save.state} error={save.error} />
          </div>
          <div className="flex items-center gap-2">
            {warnings > 0 && <Badge tone="amber">{warnings} to check</Badge>}
            <Button variant="secondary" size="sm" icon={<BookOpen className="size-4" aria-hidden />} onClick={() => setDrawer({ open: true, keyword: null })}>Add from master</Button>
          </div>
        </div>
        <FitBanner fit={fit} onAddMore={() => setDrawer({ open: true, keyword: null })} />
        {save.issues.length > 0 && <Alert tone="error" title="Some edits couldn't be saved">{save.issues.map((i) => `${i.path ?? ""} ${i.message}`).join("; ")}</Alert>}
        {message && <Alert tone={message.tone}>{message.text}</Alert>}

        <DocumentRefine busy={busy === "document:"} suggestion={docSuggestion} onRefine={(i) => void refine("document", null, i)}
          onAccept={(change) => {
            update((d) => applyChange(d, change));
            setDocSuggestion((s) => (s ? { ...s, changes: s.changes.filter((c) => c !== change) } : s));
          }}
          onAcceptAll={() => {
            if (!docSuggestion) return;
            update((d) => docSuggestion.changes.reduce(applyChange, d));
            setDocSuggestion(null);
          }}
          onDiscard={() => setDocSuggestion(null)} />

        {(["headline", "summary"] as const).map((key) => (
          <BlockEditor key={key} label={key === "headline" ? "Headline" : "Summary"} block={doc[key]} index={index}
            suggestion={suggestions[key]} busy={busy === `${key}:${key}`}
            onChange={(text) => update((d) => setBlock(d, key, { text }), key)}
            onRefine={(i) => void refine(key, key, i)}
            onAccept={() => { const s = suggestions[key]; if (s) update((d) => applyChange(d, s)); dismiss(key); }}
            onDiscard={() => dismiss(key)} />
        ))}

        <SortableList items={doc.sections} idOf={(s) => `${s.type}:${s.sourceId ?? s.title}`} onMove={(from, to) => update((d) => moveSection(d, from, to))}>
          {(section, si, handle) => (
            <section className="mb-4 rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
              <header className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-800">
                <DragHandle handle={handle} label="section" />
                <input aria-label="Section title" value={section.title} maxLength={60}
                  onChange={(e) => update((d) => renameSection(d, si, e.target.value), `title:${si}`)}
                  className="min-w-0 flex-1 rounded bg-transparent px-1 text-xs font-semibold tracking-wider text-slate-600 uppercase outline-none focus:bg-slate-50 dark:text-slate-300 dark:focus:bg-slate-800" />
                <button type="button" title="Remove section" aria-label={`Remove ${section.title}`} onClick={() => update((d) => removeSection(d, si))}
                  className="rounded p-1 text-slate-400 hover:text-red-600"><Trash2 className="size-4" aria-hidden /></button>
              </header>
              <div className="space-y-3 p-3">
                <SectionBody section={section} si={si} doc={doc} index={index} update={update} busy={busy} keywords={keywords}
                  suggestions={suggestions} itemSuggestions={itemSuggestions}
                  onRefine={(scope, id, i) => void refine(scope, id, i)}
                  onAcceptChange={(id) => { const s = suggestions[id]; if (s) update((d) => applyChange(d, s)); dismiss(id); }}
                  onDiscardChange={dismiss}
                  onAcceptItem={(itemId) => { const bullets = itemSuggestions[itemId]; if (bullets) update((d) => setItemBullets(d, itemId, bullets)); setItemSuggestions(({ [itemId]: _, ...rest }) => rest); }}
                  onDiscardItem={(itemId) => setItemSuggestions(({ [itemId]: _, ...rest }) => rest)} />
              </div>
            </section>
          )}
        </SortableList>
      </div>

      <aside className="space-y-4 xl:sticky xl:top-4 xl:max-h-[calc(100dvh-2rem)] xl:overflow-auto">
        <PdfPreview application={application} doc="resume" revision={revision} pageLimit={application.options.pageLimit}
          onFit={() => void fit.fit()} fitting={fit.busy === "fit"} fitDisabled={save.state !== "saved"} />
        <DesignDisclosure application={application} />
        <Coverage resume={doc} onPick={(keyword) => setDrawer({ open: true, keyword })} />
      </aside>

      {drawer.open && (
        <AddFromMaster doc={doc} index={index} analysis={analysis} keyword={drawer.keyword}
          onAdd={(c) => update((d) => c.apply(d))} onClose={() => setDrawer({ open: false, keyword: null })} />
      )}
    </div>
  );
}

// ---- pieces ------------------------------------------------------------------------------------------------------------

function DocumentRefine({ busy, suggestion, onRefine, onAccept, onAcceptAll, onDiscard }: {
  busy: boolean; suggestion: RefineResult | null; onRefine: (instruction: string) => void;
  onAccept: (change: RefineResult["changes"][number]) => void; onAcceptAll: () => void; onDiscard: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-3 dark:border-brand-900 dark:bg-brand-900/10">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) onRefine(text.trim()); }}>
        <Sparkles className="size-4 text-brand-600" aria-hidden />
        <input className={cn(inputClass, "min-w-48 flex-1 py-1.5")} placeholder="Ask for a change across the résumé, e.g. “more leadership-focused”"
          value={text} maxLength={1000} onChange={(e) => setText(e.target.value)} aria-label="Change across the résumé" />
        <Button type="submit" size="sm" loading={busy} disabled={!text.trim()}>Suggest</Button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {DOC_ACTIONS.map((a) => <Button key={a.label} variant="ghost" size="sm" disabled={busy} onClick={() => onRefine(a.instruction)}>{a.label}</Button>)}
      </div>
      {suggestion && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{suggestion.changes.length} suggested {suggestion.changes.length === 1 ? "change" : "changes"} · {formatUsd(suggestion.costUsd)}</p>
            <div className="flex gap-2">
              {suggestion.changes.length > 0 && <Button size="sm" onClick={onAcceptAll}>Accept all</Button>}
              <Button size="sm" variant="ghost" onClick={onDiscard}>Discard</Button>
            </div>
          </div>
          {suggestion.notes.map((n, i) => <p key={i} className="text-xs text-slate-600 dark:text-slate-400">{n.text}</p>)}
          <ul className="max-h-96 space-y-2 overflow-auto">
            {suggestion.changes.map((c) => (
              <li key={c.targetId} className="rounded-lg bg-white p-2 text-sm dark:bg-slate-900">
                <Diff before={c.before} after={c.after} />
                <Warnings warnings={c.warnings as { code: string; message: string }[]} className="mt-1" />
                <div className="mt-1 flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => onAccept(c)}>Accept</Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Provenance({ index, sourceIds, text, aiText, onRevertAi, onRevertMaster }: {
  index: MasterIndex; sourceIds: string[]; text: string; aiText?: string | null; onRevertAi?: () => void; onRevertMaster?: () => void;
}) {
  const sources = sourceTexts(index, sourceIds);
  return (
    <Popover label="Where this came from" trigger={(open, toggle) => (
      <button type="button" onClick={toggle} aria-expanded={open} title="Where this came from" aria-label="Where this came from"
        className="rounded p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"><Info className="size-4" aria-hidden /></button>
    )}>
      {(close) => (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-slate-500 uppercase">From your master résumé</p>
          {sources.length ? sources.map((s, i) => <p key={i} className="text-slate-700 dark:text-slate-300">{s}</p>)
            : <p className="text-slate-500">Nothing: you wrote this line.</p>}
          {sources[0] && sources[0] !== text && (
            <>
              <p className="text-xs font-semibold text-slate-500 uppercase">What changed</p>
              <p><Diff before={sources[0]} after={text} /></p>
            </>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            {onRevertAi && aiText && aiText !== text && <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" aria-hidden />} onClick={() => { onRevertAi(); close(); }}>Revert to AI draft</Button>}
            {onRevertMaster && sources[0] && sources[0] !== text && <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" aria-hidden />} onClick={() => { onRevertMaster(); close(); }}>Revert to master</Button>}
          </div>
        </div>
      )}
    </Popover>
  );
}

function BlockEditor({ label, block, index, suggestion, busy, onChange, onRefine, onAccept, onDiscard }: {
  label: string; block: TailoredResume["headline"]; index: MasterIndex; suggestion?: RefineResult["changes"][number]; busy: boolean;
  onChange: (text: string) => void; onRefine: (instruction: string) => void; onAccept: () => void; onDiscard: () => void;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-semibold tracking-wider text-slate-600 uppercase dark:text-slate-300">{label}</p>
        <div className="flex items-center">
          <Provenance index={index} sourceIds={block.sourceIds} text={block.text} aiText={block.aiText}
            onRevertAi={block.aiText ? () => onChange(block.aiText!) : undefined} />
          <RefineMenu quick={[{ label: "Shorter", instruction: `Make the ${label.toLowerCase()} shorter.` }, { label: "Sharper", instruction: `Make the ${label.toLowerCase()} more specific to this job.` }]}
            busy={busy} onRefine={onRefine} />
        </div>
      </div>
      <AutoTextArea label={label} value={block.text} onChange={onChange} maxLength={label === "Headline" ? 300 : 2000} />
      {suggestion && <Suggestion before={suggestion.before} after={suggestion.after} warnings={suggestion.warnings as { code: string; message: string }[]} onAccept={onAccept} onDiscard={onDiscard} />}
    </div>
  );
}

interface SectionBodyProps {
  section: ResumeSection;
  si: number;
  doc: TailoredResume;
  index: MasterIndex;
  update: (change: (d: TailoredResume) => TailoredResume, group?: string) => void;
  busy: string | null;
  keywords: string[];
  suggestions: Record<string, RefineResult["changes"][number]>;
  itemSuggestions: Record<string, ResumeBullet[]>;
  onRefine: (scope: "bullet" | "item", targetId: string, instruction: string) => void;
  onAcceptChange: (id: string) => void;
  onDiscardChange: (id: string) => void;
  onAcceptItem: (itemId: string) => void;
  onDiscardItem: (itemId: string) => void;
}

function dates(item: ResumeItem): string {
  const start = typeof item.startDate === "string" ? item.startDate : "";
  const end = typeof item.endDate === "string" ? item.endDate : null;
  return start ? `${formatPartialDate(start)} – ${formatPartialDate(end)}` : "";
}

function SectionBody(props: SectionBodyProps) {
  const { section, si, update } = props;
  if (section.type === "skills") {
    return (
      <div className="space-y-2">
        {(section.groups ?? []).map((group, gi) => (
          <div key={group.name} className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="mr-1 font-medium text-slate-800 dark:text-slate-200">{group.name}</span>
            {group.items.map((s) => (
              <span key={s.skillId} className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                {s.display}
                <button type="button" aria-label={`Remove ${s.display}`} onClick={() => update((d) => removeSkill(d, si, gi, s.skillId))}
                  className="text-slate-400 hover:text-red-600"><X className="size-3" aria-hidden /></button>
              </span>
            ))}
          </div>
        ))}
      </div>
    );
  }
  const items = section.items ?? [];
  return (
    <SortableList items={items} idOf={(i) => i.sourceId} onMove={(from, to) => update((d) => moveItem(d, si, from, to))}>
      {(item, ii, handle) => <ItemCard {...props} item={item} ii={ii} handle={handle} />}
    </SortableList>
  );
}

function ItemCard({ section, si, item, ii, handle, index, update, busy, keywords, suggestions, itemSuggestions, onRefine, onAcceptChange, onDiscardChange, onAcceptItem, onDiscardItem }:
  SectionBodyProps & { item: ResumeItem; ii: number; handle: Parameters<typeof DragHandle>[0]["handle"] }) {
  const { title, detail } = itemTitle(item);
  const withBullets = WITH_BULLETS.has(section.type);
  const bullets = item.bullets ?? [];
  const pendingItem = itemSuggestions[item.sourceId];
  return (
    <div className="rounded-lg border border-slate-100 p-2 dark:border-slate-800">
      <div className="flex items-start gap-1">
        <DragHandle handle={handle} label={title} />
        <div className="min-w-0 flex-1 py-1">
          <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{title}{detail && <span className="font-normal text-slate-500"> · {detail}</span>}</p>
          {dates(item) && <p className="text-xs text-slate-500">{dates(item)}</p>}
        </div>
        {withBullets && <RefineMenu quick={ITEM_ACTIONS} busy={busy === `item:${item.sourceId}`} label="Rewrite this role's bullets" onRefine={(i) => onRefine("item", item.sourceId, i)} />}
        <button type="button" title="Remove from this résumé" aria-label={`Remove ${title}`} onClick={() => update((d) => removeItem(d, si, ii))}
          className="rounded p-1 text-slate-400 hover:text-red-600"><Trash2 className="size-4" aria-hidden /></button>
      </div>
      {pendingItem && (
        <div className="mt-2 rounded-lg border border-brand-200 bg-brand-50/60 p-3 text-sm dark:border-brand-800 dark:bg-brand-900/20">
          <p className="mb-1 text-xs font-semibold text-brand-700 dark:text-brand-300">Suggested bullets</p>
          <ul className="list-disc space-y-1 pl-5">{pendingItem.map((b) => <li key={b.id}>{b.text}</li>)}</ul>
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => onAcceptItem(item.sourceId)}>Use these</Button>
            <Button size="sm" variant="ghost" onClick={() => onDiscardItem(item.sourceId)}>Discard</Button>
          </div>
        </div>
      )}
      {withBullets && (
        <div className="mt-1 space-y-1 pl-5">
          <SortableList items={bullets} idOf={(b) => b.id} onMove={(from, to) => update((d) => moveBullet(d, item.sourceId, from, to))}>
            {(bullet, _bi, bulletHandle) => (
              <div className="group">
                <div className="flex items-start gap-1">
                  <DragHandle handle={bulletHandle} label="bullet" />
                  <AutoTextArea label="Bullet" value={bullet.text} maxLength={1000}
                    className={cn(bullet.warnings.length > 0 && "border-amber-400 dark:border-amber-600")}
                    onChange={(text) => update((d) => setBullet(d, bullet.id, { text }), `bullet:${bullet.id}`)} />
                  <Provenance index={index} sourceIds={bullet.sourceIds} text={bullet.text} aiText={bullet.aiText}
                    onRevertAi={bullet.aiText ? () => update((d) => setBullet(d, bullet.id, { text: bullet.aiText! })) : undefined}
                    onRevertMaster={bullet.sourceIds[0] ? () => update((d) => setBullet(d, bullet.id, { text: sourceTexts(index, [bullet.sourceIds[0]!])[0] ?? bullet.text })) : undefined} />
                  <RefineMenu quick={BULLET_ACTIONS} keywords={keywords} busy={busy === `bullet:${bullet.id}`} onRefine={(i) => onRefine("bullet", bullet.id, i)} />
                  <button type="button" title="Remove bullet" aria-label="Remove bullet" onClick={() => update((d) => removeBullet(d, bullet.id))}
                    className="mt-1 rounded p-1 text-slate-400 hover:text-red-600"><X className="size-4" aria-hidden /></button>
                </div>
                <Warnings warnings={bullet.warnings} className="ml-6 mt-1" />
                {suggestions[bullet.id] && (
                  <div className="ml-6">
                    <Suggestion before={suggestions[bullet.id]!.before} after={suggestions[bullet.id]!.after}
                      warnings={suggestions[bullet.id]!.warnings as { code: string; message: string }[]}
                      onAccept={() => onAcceptChange(bullet.id)} onDiscard={() => onDiscardChange(bullet.id)} />
                  </div>
                )}
              </div>
            )}
          </SortableList>
          <Button variant="ghost" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
            onClick={() => update((d) => addBullet(d, item.sourceId, { id: newBulletId(), text: "", sourceIds: [], relevance: 3, keywords: [], origin: "user", aiText: null, edited: true, warnings: [] }))}>
            Add your own line
          </Button>
        </div>
      )}
    </div>
  );
}

function Coverage({ resume, onPick }: { resume: TailoredResume; onPick: (keyword: string) => void }) {
  const coverage = resume.analysis?.coverage;
  if (!coverage || coverage.score === null) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Keyword coverage</p>
        <p className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-white">{Math.round(coverage.score * 100)}%</p>
      </div>
      <div className="mt-3 space-y-2 text-xs">
        {coverage.matched.length > 0 && (
          <p className="flex flex-wrap gap-1">{coverage.matched.map((k) => <Badge key={k} tone="green">{k}</Badge>)}</p>
        )}
        {coverage.available.length > 0 && (
          <div>
            <p className="mb-1 text-slate-600 dark:text-slate-400">In your master, not on this résumé (click to add):</p>
            <p className="flex flex-wrap gap-1">
              {coverage.available.map((k) => (
                <button key={k.term} type="button" onClick={() => onPick(k.term)}
                  className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-800 hover:bg-amber-100 dark:bg-amber-950 dark:text-amber-300">{k.term}</button>
              ))}
            </p>
          </div>
        )}
        {coverage.gaps.length > 0 && (
          <p className="text-slate-600 dark:text-slate-400">Gaps, not claimed: {coverage.gaps.join(", ")}</p>
        )}
      </div>
    </div>
  );
}

function AddFromMaster({ doc, index, analysis, keyword, onAdd, onClose }: {
  doc: TailoredResume; index: MasterIndex; analysis: JobAnalysis | null; keyword: string | null; onAdd: (c: Candidate) => void; onClose: () => void;
}) {
  const [filter, setFilter] = useState(keyword ?? "");
  const all = useMemo(() => candidates(doc, index, analysis), [doc, index, analysis]);
  const names = filter ? [filter, ...((analysis?.keywords ?? []).find((k) => k.term === filter)?.aliases ?? [])] : [];
  const shown = filter ? all.filter((c) => names.some((n) => mentions(c.text, n)) || c.label.toLowerCase().includes(filter.toLowerCase())) : all;
  return (
    <div role="dialog" aria-label="Add from master" className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <p className="font-semibold text-slate-900 dark:text-slate-100">Add from your master résumé</p>
        <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><X className="size-5" aria-hidden /></button>
      </div>
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <input className={cn(inputClass, "py-1.5")} placeholder="Filter, e.g. a keyword" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter" />
        <p className="mt-1 text-xs text-slate-500">Most relevant to this job first.</p>
      </div>
      <ul className="flex-1 divide-y divide-slate-100 overflow-auto dark:divide-slate-800">
        {shown.length === 0 && <li className="px-4 py-6 text-sm text-slate-500">Nothing left to add{filter ? " for that filter" : ""}.</li>}
        {shown.map((c) => (
          <li key={c.key} className="flex items-start gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-slate-800 dark:text-slate-200">{c.label}</p>
              <p className="text-xs text-slate-500">{c.kind === "bullet" ? `Bullet · ${c.detail}` : c.kind === "skill" ? `Skill · ${c.detail}` : c.detail}
                {c.score > 0 && <span className="ml-1 text-emerald-700 dark:text-emerald-400">· matches the posting</span>}</p>
            </div>
            <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => onAdd(c)}>Add</Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
