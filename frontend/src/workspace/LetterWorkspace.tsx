/**
 * The cover letter tab (DESIGN.md §12.3, CVL-1…CVL-7): options and generation, then a paragraph editor beside
 * the letter's PDF. Paragraphs can be edited, reordered, refined one at a time or all together, and compared with
 * the AI draft. Everything autosaves.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Download, Flag, Info, Plus, Redo2, RotateCcw, Sparkles, Trash2, Undo2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { api, errorMessage } from "../api/client";
import type { ApplicationDetail, CoverLetter, LetterOptions, LetterParagraph, LetterRefineResult, ParagraphRole } from "../api/types";
import { Dialog } from "../components/Dialog";
import { Alert, Badge, Button, Card, CardBody, CardHeader, Spinner, TextArea, TextField, cn, inputClass, linkButtonClass } from "../components/ui";
import { useHistory, useUndoShortcuts } from "../editor/history";
import { formatUsd } from "../lib/format";
import { DesignDisclosure, PdfPreview } from "./preview";
import { indexMaster, sourceTexts } from "./resumeOps";
import { AutoTextArea, Diff, DragHandle, Popover, type QuickAction, RefineMenu, SaveIndicator, SortableList, Suggestion, Warnings, move, useAutosave } from "./shared";

type Json = Record<string, unknown>;
const ROLES: { value: ParagraphRole; label: string }[] = [
  { value: "opening", label: "Opening" }, { value: "evidence", label: "Evidence" },
  { value: "motivation", label: "Why this company" }, { value: "closing", label: "Closing" },
];
const PARAGRAPH_ACTIONS: QuickAction[] = [
  { label: "Shorter", instruction: "Make this paragraph shorter." },
  { label: "Warmer", instruction: "Make this paragraph warmer, without flattery." },
  { label: "More specific", instruction: "Make this paragraph more specific, using the cited accomplishments." },
];
const DEFAULT_OPTIONS: LetterOptions = { generate: true, recipient: { name: "", title: "", company: "", address: [] }, tone: "confident",
  length: "standard", notes: "", highlights: "", referral: "" };

export function LetterWorkspace({ application, master }: { application: ApplicationDetail; master: Json }) {
  const queryClient = useQueryClient();
  const status = application.coverLetterStatus;
  const [rewriting, setRewriting] = useState(false);

  // While the letter is being written, check back every couple of seconds.
  useEffect(() => {
    if (status !== "generating") return;
    const timer = window.setInterval(() => void queryClient.invalidateQueries({ queryKey: ["application", application.id] }), 2000);
    return () => window.clearInterval(timer);
  }, [status, application.id, queryClient]);

  if (status === "generating") {
    return <Card><CardBody className="flex items-center gap-3 py-10 text-sm text-slate-600 dark:text-slate-400"><Spinner /> Writing your cover letter… This takes about half a minute.</CardBody></Card>;
  }
  const saved = (application.options.coverLetter as LetterOptions | undefined) ?? DEFAULT_OPTIONS;
  if (status !== "ready" || !application.coverLetter || rewriting) {
    return (
      <div className="max-w-3xl space-y-4">
        {status === "failed" && <Alert tone="error" title="The cover letter couldn't be written">{String(application.coverLetterError?.message ?? "")} Change anything below and try again.</Alert>}
        {rewriting && <Alert tone="warning">Writing a new letter replaces your edits to the current one.</Alert>}
        <LetterOptionsForm application={application} initial={{ ...DEFAULT_OPTIONS, ...saved }} onCancel={rewriting ? () => setRewriting(false) : undefined}
          onStarted={() => setRewriting(false)} />
      </div>
    );
  }
  // A new letter (a new generation time) starts a fresh editor.
  return <LetterEditor key={(application.coverLetter as unknown as CoverLetter).meta?.generatedAt ?? application.id} application={application} master={master} onRewrite={() => setRewriting(true)} />;
}

function LetterOptionsForm({ application, initial, onCancel, onStarted }: { application: ApplicationDetail; initial: LetterOptions; onCancel?: () => void; onStarted: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recipient = form.recipient;
  const set = (patch: Partial<LetterOptions>) => setForm((f) => ({ ...f, ...patch }));
  const setRecipient = (patch: Partial<LetterOptions["recipient"]>) => setForm((f) => ({ ...f, recipient: { ...f.recipient, ...patch } }));
  const select = cn(inputClass, "py-1.5");
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("POST", `/api/applications/${application.id}/cover-letter`, { json: form });
      onStarted();
      await queryClient.invalidateQueries({ queryKey: ["application", application.id] });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Cover letter" description="Grounded in your master résumé and the posting. Statements about the company come only from the posting and your notes." />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <TextField label="Recipient name (optional)" value={recipient.name} maxLength={200} onChange={(e) => setRecipient({ name: e.target.value })} hint="Leave empty for “Dear Hiring Team,”" />
          <TextField label="Their title" value={recipient.title} maxLength={200} onChange={(e) => setRecipient({ title: e.target.value })} />
          <TextField label="Company" value={recipient.company} maxLength={200} placeholder={application.job.company ?? ""} onChange={(e) => setRecipient({ company: e.target.value })} />
        </div>
        <TextArea label="Address (optional, one line each)" rows={2} value={(recipient.address ?? []).join("\n")}
          onChange={(e) => setRecipient({ address: e.target.value.split("\n").slice(0, 5) })} />
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="tone" className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">Tone</label>
            <select id="tone" className={select} value={form.tone} onChange={(e) => set({ tone: e.target.value as LetterOptions["tone"] })}>
              <option value="confident">Confident</option><option value="warm">Warm</option><option value="neutral">Neutral</option><option value="formal">Formal</option>
            </select>
          </div>
          <div>
            <label htmlFor="length" className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">Length</label>
            <select id="length" className={select} value={form.length} onChange={(e) => set({ length: e.target.value as LetterOptions["length"] })}>
              <option value="short">Short (about 200 words)</option><option value="standard">Standard (about 300)</option><option value="detailed">Detailed (about 400)</option>
            </select>
          </div>
        </div>
        <TextArea label="Why this company? (your notes)" rows={3} maxLength={3000} value={form.notes} onChange={(e) => set({ notes: e.target.value })}
          hint="What draws you to them: a product you use, their mission, someone you met. Without notes, the letter flags the paragraph for you to personalize." />
        <TextArea label="Points to highlight (optional)" rows={2} maxLength={1000} value={form.highlights} onChange={(e) => set({ highlights: e.target.value })} />
        <TextField label="Referral or connection (optional)" maxLength={500} value={form.referral} onChange={(e) => set({ referral: e.target.value })} />
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex gap-2">
          <Button icon={<Sparkles className="size-4" aria-hidden />} loading={busy} onClick={() => void submit()}>Write cover letter</Button>
          {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
        </div>
      </CardBody>
    </Card>
  );
}

function mergeSaved(local: CoverLetter, saved: CoverLetter): CoverLetter {
  const byId = new Map(saved.paragraphs.map((p) => [p.id, p]));
  return {
    ...local, analysis: saved.analysis,
    paragraphs: local.paragraphs.map((p) => {
      const s = byId.get(p.id);
      return s && s.text === p.text ? { ...p, warnings: s.warnings, flags: s.flags, edited: s.edited, sourceIds: s.sourceIds } : p;
    }),
  };
}

const newParagraphId = () => `p${Math.random().toString(36).slice(2, 6)}`;

function LetterEditor({ application, master, onRewrite }: { application: ApplicationDetail; master: Json; onRewrite: () => void }) {
  const history = useHistory<CoverLetter>(application.coverLetter as unknown as CoverLetter);
  useUndoShortcuts(history);
  const [revision, setRevision] = useState(0);
  const save = useAutosave<CoverLetter, { document: CoverLetter }>({
    value: history.value, edits: history.edits, url: `/api/applications/${application.id}/cover-letter`, body: (document) => ({ document }),
    onSaved: (result) => {
      history.replace((local) => mergeSaved(local, result.document));
      setRevision((r) => r + 1);
    },
  });
  const letter = history.value;
  const index = useMemo(() => indexMaster(master), [master]);
  const [suggestions, setSuggestions] = useState<Record<string, LetterParagraph>>({});
  const [whole, setWhole] = useState<LetterRefineResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [confirmRewrite, setConfirmRewrite] = useState(false);
  const [instruction, setInstruction] = useState("");
  const update = (change: (l: CoverLetter) => CoverLetter, group?: string) => history.set(change, group);
  const setParagraph = (id: string, patch: Partial<LetterParagraph>, group?: string) =>
    update((l) => ({ ...l, paragraphs: l.paragraphs.map((p) => (p.id === id ? { ...p, ...patch } : p)) }), group);

  const refine = async (targetId: string | null, text: string) => {
    setBusy(targetId ?? "letter");
    setMessage(null);
    try {
      const result = await api<LetterRefineResult>("POST", `/api/applications/${application.id}/cover-letter/refine`, { json: { targetId, instruction: text } });
      if (result.scope === "letter") setWhole(result);
      else setSuggestions((s) => ({ ...s, ...Object.fromEntries((result.paragraphs as unknown as LetterParagraph[]).map((p) => [p.id, p])) }));
      const notes = result.notes.map((n) => n.text).join(" ");
      if (notes) setMessage({ tone: "info", text: `${notes} (${formatUsd(result.costUsd)})` });
    } catch (e) {
      setMessage({ tone: "error", text: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  };

  const recipient = letter.recipient;
  const setRecipient = (patch: Partial<CoverLetter["recipient"]>) => update((l) => ({ ...l, recipient: { ...l.recipient, ...patch } }), "recipient");
  const field = cn(inputClass, "py-1.5");

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" icon={<Undo2 className="size-4" aria-hidden />} disabled={!history.canUndo} onClick={history.undo} title="Undo (⌘Z)"><span className="sr-only">Undo</span></Button>
            <Button variant="ghost" size="sm" icon={<Redo2 className="size-4" aria-hidden />} disabled={!history.canRedo} onClick={history.redo} title="Redo (⇧⌘Z)"><span className="sr-only">Redo</span></Button>
            <SaveIndicator state={save.state} error={save.error} />
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            {letter.analysis.wordCount} words
            <Button variant="secondary" size="sm" icon={<RotateCcw className="size-4" aria-hidden />} onClick={() => setConfirmRewrite(true)}>Write a new letter</Button>
          </div>
        </div>
        {save.issues.length > 0 && <Alert tone="error" title="Some edits couldn't be saved">{save.issues.map((i) => `${i.path ?? ""} ${i.message}`).join("; ")}</Alert>}
        {message && <Alert tone={message.tone}>{message.text}</Alert>}

        <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-3 sm:grid-cols-3 dark:border-slate-800 dark:bg-slate-900">
          <input className={field} aria-label="Recipient name" placeholder="Recipient name" value={recipient.name ?? ""} onChange={(e) => setRecipient({ name: e.target.value })} />
          <input className={field} aria-label="Recipient title" placeholder="Title" value={recipient.title ?? ""} onChange={(e) => setRecipient({ title: e.target.value })} />
          <input className={field} aria-label="Company" placeholder="Company" value={recipient.company ?? ""} onChange={(e) => setRecipient({ company: e.target.value })} />
          <input className={cn(field, "sm:col-span-2")} aria-label="Subject" placeholder="Re: line" value={letter.subject} onChange={(e) => update((l) => ({ ...l, subject: e.target.value }), "subject")} />
          <input className={field} aria-label="Salutation" value={letter.salutation} onChange={(e) => update((l) => ({ ...l, salutation: e.target.value }), "salutation")} />
        </div>

        <form className="flex flex-wrap items-center gap-2 rounded-xl border border-brand-200 bg-brand-50/40 p-3 dark:border-brand-900 dark:bg-brand-900/10"
          onSubmit={(e) => { e.preventDefault(); if (instruction.trim()) void refine(null, instruction.trim()); }}>
          <Sparkles className="size-4 text-brand-600" aria-hidden />
          <input className={cn(field, "min-w-48 flex-1")} placeholder="Ask for a change to the whole letter, e.g. “more formal”" value={instruction} maxLength={1000}
            onChange={(e) => setInstruction(e.target.value)} aria-label="Change to the whole letter" />
          <Button type="submit" size="sm" loading={busy === "letter"} disabled={!instruction.trim()}>Suggest</Button>
        </form>
        {whole && (
          <div className="rounded-xl border border-brand-200 bg-white p-3 dark:border-brand-800 dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-medium">Suggested letter · {formatUsd(whole.costUsd)}</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => { update((l) => ({ ...l, paragraphs: whole.paragraphs as unknown as LetterParagraph[] })); setWhole(null); }}>Use it</Button>
                <Button size="sm" variant="ghost" onClick={() => setWhole(null)}>Discard</Button>
              </div>
            </div>
            {(whole.paragraphs as unknown as LetterParagraph[]).map((p) => (
              <p key={p.id} className="mb-2 text-sm"><Diff before={letter.paragraphs.find((x) => x.id === p.id)?.text ?? ""} after={p.text} /></p>
            ))}
          </div>
        )}

        <SortableList items={letter.paragraphs} idOf={(p) => p.id} onMove={(from, to) => update((l) => ({ ...l, paragraphs: move(l.paragraphs, from, to) }))}>
          {(p, _i, handle) => (
            <div className="mb-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
              <div className="mb-1 flex items-center gap-1">
                <DragHandle handle={handle} label="paragraph" />
                <select aria-label="Paragraph role" className="rounded bg-transparent text-xs font-semibold text-slate-600 uppercase dark:text-slate-300" value={p.role}
                  onChange={(e) => setParagraph(p.id, { role: e.target.value as ParagraphRole })}>
                  {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                {p.flags.includes("PERSONALIZE") && <Badge tone="amber"><Flag className="mr-1 size-3" aria-hidden />Personalize</Badge>}
                <span className="flex-1" />
                <ParagraphSources index={index} paragraph={p} onRevert={p.aiText && p.aiText !== p.text ? () => setParagraph(p.id, { text: p.aiText! }) : undefined} />
                <RefineMenu quick={PARAGRAPH_ACTIONS} busy={busy === p.id} onRefine={(text) => void refine(p.id, text)} />
                <button type="button" aria-label="Delete paragraph" title="Delete paragraph" onClick={() => update((l) => ({ ...l, paragraphs: l.paragraphs.filter((x) => x.id !== p.id) }))}
                  className="rounded p-1 text-slate-400 hover:text-red-600"><Trash2 className="size-4" aria-hidden /></button>
              </div>
              <AutoTextArea label={`Paragraph ${p.role}`} value={p.text} maxLength={3000} className="min-h-24"
                onChange={(text) => setParagraph(p.id, { text }, `p:${p.id}`)} />
              {p.flags.includes("PERSONALIZE") && <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">Add why this company appeals to you: only you know that. The letter didn't guess.</p>}
              <Warnings warnings={p.warnings} className="mt-1" />
              {suggestions[p.id] && (
                <Suggestion before={p.text} after={suggestions[p.id]!.text} onDiscard={() => setSuggestions(({ [p.id]: _, ...rest }) => rest)}
                  onAccept={() => { setParagraph(p.id, { text: suggestions[p.id]!.text, aiText: suggestions[p.id]!.text, sourceIds: suggestions[p.id]!.sourceIds }); setSuggestions(({ [p.id]: _, ...rest }) => rest); }} />
              )}
            </div>
          )}
        </SortableList>
        <Button variant="ghost" size="sm" icon={<Plus className="size-3.5" aria-hidden />}
          onClick={() => update((l) => ({ ...l, paragraphs: [...l.paragraphs, { id: newParagraphId(), role: "evidence", text: "", sourceIds: [], jobRefs: [], companySources: [], aiText: null, edited: true, flags: [], warnings: [] }] }))}>
          Add a paragraph
        </Button>
        <input className={cn(field, "max-w-xs")} aria-label="Closing" value={letter.closing} onChange={(e) => update((l) => ({ ...l, closing: e.target.value }), "closing")} />
      </div>

      <aside className="space-y-4 xl:sticky xl:top-4 xl:max-h-[calc(100dvh-2rem)] xl:overflow-auto">
        <PdfPreview application={application} doc="cover-letter" revision={revision} pageLimit={1} />
        <a href={`/api/applications/${application.id}/export?doc=packet&format=pdf`} className={linkButtonClass("secondary", "sm")}>
          <Download className="size-4" aria-hidden /> Application packet (letter + résumé)
        </a>
        <DesignDisclosure application={application} />
      </aside>

      <Dialog open={confirmRewrite} tone="danger" title="Write a new cover letter?" confirmLabel="Continue"
        description="A new letter replaces this one, including your edits. You'll choose the options first."
        onClose={() => setConfirmRewrite(false)} onConfirm={() => { setConfirmRewrite(false); onRewrite(); }} />
    </div>
  );
}

function ParagraphSources({ index, paragraph, onRevert }: { index: ReturnType<typeof indexMaster>; paragraph: LetterParagraph; onRevert?: () => void }) {
  const sources = sourceTexts(index, paragraph.sourceIds);
  return (
    <Popover label="Where this came from" trigger={(open, toggle) => (
      <button type="button" onClick={toggle} aria-expanded={open} title="Where this came from" aria-label="Where this came from"
        className="rounded p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"><Info className="size-4" aria-hidden /></button>
    )}>
      {(close) => (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-slate-500 uppercase">Draws on</p>
          {sources.length ? sources.map((s, i) => <p key={i} className="text-slate-700 dark:text-slate-300">{s}</p>) : <p className="text-slate-500">No résumé items.</p>}
          {paragraph.companySources.length > 0 && <p className="text-xs text-slate-500">Company details from: {paragraph.companySources.map((c) => (c === "notes" ? "your notes" : "the posting")).join(" and ")}</p>}
          {paragraph.aiText && paragraph.aiText !== paragraph.text && (
            <>
              <p className="text-xs font-semibold text-slate-500 uppercase">Your changes to the AI draft</p>
              <p><Diff before={paragraph.aiText} after={paragraph.text} /></p>
              {onRevert && <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" aria-hidden />} onClick={() => { onRevert(); close(); }}>Revert to AI draft</Button>}
            </>
          )}
        </div>
      )}
    </Popover>
  );
}
