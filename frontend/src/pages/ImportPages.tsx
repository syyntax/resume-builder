import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardPaste,
  FileSearch,
  FileUp,
  Info,
  Plus,
  Redo2,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  X,
} from "lucide-react";
import { type DragEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { AiSettings, Import, ImportDetail, ImportFlag, ImportPreview, ImportStatus, Issue, MasterSave } from "../api/types";
import { aiSettingsKey, useApiKeyStatus } from "../components/AiSettingsCard";
import { Dialog } from "../components/Dialog";
import { ImportStatusBadge, importsKey } from "../components/imports";
import { IssueList } from "../components/masters";
import { Alert, Badge, Button, Card, CardBody, CardHeader, PageHeader, Spinner, TextArea, TextField, cn } from "../components/ui";
import { MasterEditor } from "../editor/MasterEditor";
import { type Json, fromEditable, insertAt, toEditable } from "../editor/doc";
import { useHistory, useUndoShortcuts } from "../editor/history";
import { formatUsd, modelLabel } from "../lib/format";
import { mastersKey } from "./MastersPages";
import { TabButton, UnsavedChangesGuard, errorIssues, issuesMap, withoutIssue } from "./MasterEditPage";
import { NotFoundPage } from "./NotFoundPage";

const PdfViewer = lazy(() => import("../preview/PdfViewer"));

const ACTIVE: ImportStatus[] = ["queued", "transcribing", "checking"];
const MAX_FILE_BYTES = 5 * 1024 * 1024;

// ---- start an import ---------------------------------------------------------------------------------------

function FileDrop({ onFile, busy }: { onFile: (file: File) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const accept = (file: File | undefined) => {
    if (!file) return;
    setProblem(null);
    if (file.size > MAX_FILE_BYTES) setProblem("That file is larger than 5 MB.");
    else if (!/\.(pdf|docx)$/i.test(file.name)) setProblem("Choose a PDF or Word (.docx) file. For anything else, paste the text instead.");
    else onFile(file);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    accept(e.dataTransfer.files[0]);
  };
  return (
    <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
      className={cn("flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
        dragging ? "border-brand-400 bg-brand-50 dark:border-brand-500 dark:bg-brand-900/30" : "border-slate-300 dark:border-slate-700")}>
      <FileUp className="mb-3 size-8 text-slate-400" aria-hidden />
      <p className="font-medium text-slate-800 dark:text-slate-200">Drop your résumé here</p>
      <p className="mt-1 text-sm text-slate-500">PDF (including scans and LinkedIn's "Save to PDF") or Word .docx · up to 5 MB and 10 pages</p>
      <input ref={input} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="sr-only" aria-label="Choose a résumé file" onChange={(e) => { accept(e.target.files?.[0]); e.target.value = ""; }} />
      <Button className="mt-4" variant="secondary" icon={<Upload className="size-4" aria-hidden />} loading={busy} onClick={() => input.current?.click()}>
        Choose file
      </Button>
      {problem && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{problem}</p>}
    </div>
  );
}

export function ImportStartPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const keyStatus = useApiKeyStatus();
  const settings = useQuery({ queryKey: aiSettingsKey, queryFn: () => api<AiSettings>("GET", "/api/account/ai-settings") });
  const [tab, setTab] = useState<"file" | "text">("file");
  const [text, setText] = useState("");
  const started = (created: Import) => {
    void queryClient.invalidateQueries({ queryKey: importsKey });
    navigate(`/imports/${created.id}`);
  };
  const upload = useMutation({
    mutationFn: (file: File) => api<Import>("POST", `/api/imports?filename=${encodeURIComponent(file.name)}`, {
      body: file, headers: { "Content-Type": file.type || "application/octet-stream" },
    }),
    onSuccess: started,
  });
  const paste = useMutation({
    mutationFn: () => api<Import>("POST", "/api/imports/text", { json: { text } }),
    onSuccess: started,
  });
  const noKey = keyStatus.data && !keyStatus.data.using;
  const error = upload.error ?? paste.error;

  return (
    <>
      <Link to="/masters" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> Master résumés
      </Link>
      <PageHeader title="Import a résumé" description="Claude transcribes your existing résumé into a master résumé, word for word. You review it before it's saved." />
      {noKey && (
        <Alert tone="warning" title="Add your Anthropic API key first" className="mb-6">
          Imports run on your own key. <Link to="/account#ai" className="font-medium underline underline-offset-2">Add it in Account → AI</Link>.
        </Alert>
      )}
      <Card>
        <CardHeader
          title={
            <div role="tablist" aria-label="Import from" className="inline-flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
              <TabButton active={tab === "file"} onClick={() => setTab("file")} icon={<FileUp className="size-4" aria-hidden />}>Upload a file</TabButton>
              <TabButton active={tab === "text"} onClick={() => setTab("text")} icon={<ClipboardPaste className="size-4" aria-hidden />}>Paste text</TabButton>
            </div>
          }
        />
        <CardBody className="space-y-4">
          {tab === "file" ? (
            <FileDrop busy={upload.isPending} onFile={(file) => upload.mutate(file)} />
          ) : (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); paste.mutate(); }}>
              <TextArea label="Résumé text" rows={16} minLength={100} maxLength={50000} required value={text}
                onChange={(e) => setText(e.target.value)} placeholder="Paste your whole résumé: contact details, experience, education, skills…" />
              <Button type="submit" icon={<Sparkles className="size-4" aria-hidden />} loading={paste.isPending} disabled={text.trim().length < 100 || Boolean(noKey)}>
                Import text
              </Button>
            </form>
          )}
          {error && <Alert tone="error">{errorMessage(error)}</Alert>}
          <p className="text-xs text-slate-500">
            {settings.data ? `Uses ${modelLabel(settings.data.model)} on your API key; ` : ""}a typical import costs about $0.10–0.40.
            The original file is kept with the master résumé (you can delete it later).
          </p>
        </CardBody>
      </Card>
    </>
  );
}

// ---- progress ---------------------------------------------------------------------------------------------------

function useImport(id: string) {
  const queryClient = useQueryClient();
  const key = useMemo(() => ["import", id], [id]);
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<ImportDetail>("GET", `/api/imports/${id}`),
    retry: false,
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 5000 : false),
  });
  const active = query.data ? ACTIVE.includes(query.data.status) : false;
  useEffect(() => {
    if (!active) return;
    const source = new EventSource(`/api/imports/${id}/events`);
    const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
    source.addEventListener("status", (e: MessageEvent<string>) => {
      const data = JSON.parse(e.data) as { status: ImportStatus };
      queryClient.setQueryData<ImportDetail>(key, (old) => (old ? { ...old, status: data.status } : old));
    });
    source.addEventListener("done", () => { refresh(); source.close(); void queryClient.invalidateQueries({ queryKey: importsKey }); });
    source.addEventListener("error", () => { refresh(); source.close(); });
    return () => source.close();
  }, [id, active, queryClient, key]);
  return query;
}

const STEPS: { status: ImportStatus; label: string }[] = [
  { status: "queued", label: "Uploaded and read" },
  { status: "transcribing", label: "Transcribing with Claude" },
  { status: "checking", label: "Checking every field against the original" },
];

function ImportProgress({ status }: { status: ImportStatus }) {
  const current = STEPS.findIndex((s) => s.status === status);
  return (
    <Card className="mb-6">
      <CardBody>
        <ol className="space-y-3">
          {STEPS.map((step, i) => {
            const state = i < current ? "done" : i === current ? "active" : "todo";
            return (
              <li key={step.status} className="flex items-center gap-3 text-sm">
                <span className={cn("grid size-6 place-items-center rounded-full text-xs font-semibold",
                  state === "done" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200"
                    : state === "active" ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500 dark:bg-slate-800")}>
                  {state === "active" ? <Spinner className="size-3.5 text-white" /> : state === "done" ? <Check className="size-3.5" aria-label="Done" /> : i + 1}
                </span>
                <span className={state === "todo" ? "text-slate-500" : "font-medium text-slate-900 dark:text-slate-100"}>{step.label}</span>
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-sm text-slate-500">This usually takes under a minute. You can leave this page and come back.</p>
      </CardBody>
    </Card>
  );
}

// ---- review ---------------------------------------------------------------------------------------------------------

function SourcePane({ detail }: { detail: ImportDetail }) {
  const preview = useQuery({
    queryKey: ["import", detail.id, "preview"],
    queryFn: () => api<ImportPreview>("GET", `/api/imports/${detail.id}/preview`),
    enabled: detail.sourceKind !== "pdf",
  });
  if (detail.sourceKind === "pdf") {
    return (
      <Suspense fallback={<Spinner />}>
        <PdfViewer url={`/api/imports/${detail.id}/source`} />
      </Suspense>
    );
  }
  if (preview.isPending) return <Spinner />;
  if (preview.isError) return <Alert tone="error">{errorMessage(preview.error)}</Alert>;
  if (preview.data.html) {
    const doc = `<!doctype html><meta charset="utf-8"><style>body{font:14px/1.55 system-ui,sans-serif;color:#0f172a;margin:24px;}
h1,h2,h3{font-size:15px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.04em}p{margin:4px 0}ul{margin:4px 0;padding-left:20px}
table{border-collapse:collapse}td,th{border:1px solid #e2e8f0;padding:4px 8px;vertical-align:top}a{color:#24528a}</style>${preview.data.html}`;
    return <iframe title="Original document" sandbox="" srcDoc={doc} className="h-[75vh] w-full rounded-lg bg-white ring-1 ring-slate-200 dark:ring-slate-700" />;
  }
  return <pre className="rounded-lg bg-white p-4 font-sans text-sm whitespace-pre-wrap ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">{preview.data.text}</pre>;
}

const FLAG_ICON = { note: AlertTriangle, fidelity: FileSearch, inferredSkill: Plus } as const;

function FlagNavigator({ flags, resolved, index, onIndex, onResolve, onAddSkill }: {
  flags: ImportFlag[];
  resolved: Record<string, "accepted" | "dismissed">;
  index: number;
  onIndex: (index: number) => void;
  onResolve: (flag: ImportFlag, state: "accepted" | "dismissed" | null) => void;
  onAddSkill: (flag: ImportFlag) => void;
}) {
  const open = flags.filter((f) => !resolved[f.key]).length;
  const flag = flags[index];
  if (!flag) {
    return <Alert tone="success" title="Nothing to check">Claude didn't flag anything, and every field matched the original. Look it over, then save it.</Alert>;
  }
  const state = resolved[flag.key];
  const Icon = flag.severity === "info" && flag.kind === "note" ? Info : FLAG_ICON[flag.kind];
  const kindLabel = flag.kind === "note" ? (flag.severity === "warning" ? "Check this" : "Note") : flag.kind === "fidelity" ? "Differs from the original" : "Possible skill";
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 dark:border-amber-900 dark:bg-amber-950/30">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
          Flag {index + 1} of {flags.length} · <span className="text-slate-600 dark:text-slate-400">{open} to review</span>
        </p>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" icon={<ChevronLeft className="size-4" aria-hidden />} disabled={index === 0} onClick={() => onIndex(index - 1)}>Previous</Button>
          <Button variant="ghost" size="sm" disabled={index === flags.length - 1} onClick={() => onIndex(index + 1)}>
            Next <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
      </div>
      <div className="mt-3 flex gap-3">
        <Icon className={cn("mt-0.5 size-5 shrink-0", flag.severity === "warning" ? "text-amber-600" : "text-sky-600")} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">{kindLabel}{flag.path ? ` · ${flag.path}` : ""}</p>
          <p className="mt-0.5 text-sm text-slate-800 dark:text-slate-200">{flag.message}</p>
          {flag.skill?.evidence && <p className="mt-1 text-xs text-slate-500">Mentioned in: “{flag.skill.evidence}”</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {state ? (
              <>
                <Badge tone={state === "accepted" ? "green" : "neutral"}>{state === "accepted" ? "Resolved" : "Dismissed"}</Badge>
                <Button variant="ghost" size="sm" icon={<RotateCcw className="size-3.5" aria-hidden />} onClick={() => onResolve(flag, null)}>Reopen</Button>
              </>
            ) : flag.kind === "inferredSkill" ? (
              <>
                <Button size="sm" icon={<Plus className="size-4" aria-hidden />} onClick={() => onAddSkill(flag)}>Add to skills</Button>
                <Button variant="secondary" size="sm" icon={<X className="size-4" aria-hidden />} onClick={() => onResolve(flag, "dismissed")}>Not a skill</Button>
              </>
            ) : (
              <>
                <Button size="sm" icon={<Check className="size-4" aria-hidden />} onClick={() => onResolve(flag, "accepted")}>
                  {flag.kind === "fidelity" ? "It's right" : "Done"}
                </Button>
                <Button variant="secondary" size="sm" icon={<X className="size-4" aria-hidden />} onClick={() => onResolve(flag, "dismissed")}>Dismiss</Button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewScreen({ detail }: { detail: ImportDetail }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const initial = useMemo(() => toEditable((detail.document ?? {}) as Json), [detail.document]);
  const history = useHistory<Json>(initial);
  useUndoShortcuts(history);
  const [resolved, setResolved] = useState<Record<string, "accepted" | "dismissed">>(detail.resolved ?? {});
  const [index, setIndex] = useState(0);
  const [label, setLabel] = useState(() => {
    const meta = (detail.document as { meta?: { label?: string } } | null)?.meta;
    return meta?.label ?? "Imported résumé";
  });
  const [issues, setIssues] = useState<Issue[]>([]);
  const [discarding, setDiscarding] = useState(false);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [accepted, setAccepted] = useState(false);
  const flags = detail.flags;
  const openFlags = useMemo(() => flags.filter((f) => !resolved[f.key]), [flags, resolved]);
  const active = flags[index] ?? null;

  // Autosave the review (edits and flag decisions) a moment after the last change.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setSaveState("saving");
    const timer = window.setTimeout(() => {
      api("PUT", `/api/imports/${detail.id}/review`, { json: { document: fromEditable(history.value), resolved } })
        .then(() => setSaveState("saved"))
        .catch(() => setSaveState("error"));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [history.value, resolved, detail.id]);

  const resolve = (flag: ImportFlag, state: "accepted" | "dismissed" | null) => {
    setResolved((current) => {
      const next = { ...current };
      if (state) next[flag.key] = state;
      else delete next[flag.key];
      return next;
    });
    if (state) {
      const after = flags.findIndex((f, i) => i > index && !resolved[f.key] && f.key !== flag.key);
      if (after !== -1) setIndex(after);
    }
  };

  const accept = useMutation({
    mutationFn: () => api<MasterSave>("POST", `/api/imports/${detail.id}/accept`, { json: { label: label.trim(), document: fromEditable(history.value) } }),
    onSuccess: (saved) => {
      setAccepted(true);
      void queryClient.invalidateQueries({ queryKey: mastersKey });
      void queryClient.invalidateQueries({ queryKey: importsKey });
      navigate(`/masters/${saved.master.id}`, { replace: true });
    },
    onError: (error) => setIssues(errorIssues(error)),
  });
  const discard = useMutation({
    mutationFn: () => api<void>("DELETE", `/api/imports/${detail.id}`),
    onSuccess: () => {
      setAccepted(true);
      void queryClient.invalidateQueries({ queryKey: importsKey });
      navigate("/masters", { replace: true });
    },
  });
  const issueMap = useMemo(() => issuesMap(issues), [issues]);
  const fidelity = detail.fidelity;

  return (
    <>
      <PageHeader
        title={<>Review import <span className="font-normal text-slate-500">· {detail.sourceName}</span></>}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {fidelity?.available ? (
              <span title="Share of transcribed fields found word for word in the original">
                Fidelity {Math.round((fidelity.score ?? 0) * 100)}% ({fidelity.passed} of {fidelity.checked} fields match the original)
              </span>
            ) : (
              <span>Fidelity check unavailable {detail.sourceKind === "pdf" && !detail.hasTextLayer ? "(scanned document)" : ""}</span>
            )}
            <span>· {modelLabel(detail.model)} · {formatUsd(detail.costUsd)}</span>
            <span className="text-slate-400" aria-live="polite">· {saveState === "saving" ? "Saving…" : saveState === "error" ? "Couldn't save your review" : "Review saved"}</span>
          </span>
        }
        actions={
          <>
            <Button variant="ghost" size="sm" icon={<Undo2 className="size-4" aria-hidden />} disabled={!history.canUndo} onClick={history.undo} title="Undo (⌘Z)"><span className="sr-only">Undo</span></Button>
            <Button variant="ghost" size="sm" icon={<Redo2 className="size-4" aria-hidden />} disabled={!history.canRedo} onClick={history.redo} title="Redo (⇧⌘Z)"><span className="sr-only">Redo</span></Button>
            <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setDiscarding(true)}>Discard</Button>
          </>
        }
      />

      <div className="mb-6 grid gap-4 xl:grid-cols-[1fr_24rem]">
        <FlagNavigator flags={flags} resolved={resolved} index={Math.min(index, Math.max(0, flags.length - 1))} onIndex={setIndex}
          onResolve={resolve}
          onAddSkill={(flag) => {
            history.set((d) => insertAt(d, ["skills"], { name: flag.skill?.name ?? "", ...(flag.skill?.category ? { category: flag.skill.category } : {}) }));
            resolve(flag, "accepted");
          }} />
        <form className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
          onSubmit={(e) => { e.preventDefault(); setIssues([]); accept.mutate(); }}>
          <TextField label="Name for the new master résumé" value={label} maxLength={100} required onChange={(e) => setLabel(e.target.value)} />
          <Button type="submit" className="w-full" icon={<Save className="size-4" aria-hidden />} loading={accept.isPending} disabled={!label.trim()}>
            Save as new master résumé
          </Button>
          {openFlags.length > 0 && <p className="text-xs text-slate-500">{openFlags.length} flag{openFlags.length === 1 ? "" : "s"} not reviewed yet. You can still save, and edit later.</p>}
          {accept.isError && !issues.length && <Alert tone="error">{errorMessage(accept.error)}</Alert>}
        </form>
      </div>
      {issues.length > 0 && <div className="mb-6"><IssueList issues={issues} tone="error" /></div>}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:overflow-auto">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Original</h2>
          <SourcePane detail={detail} />
        </div>
        <div className="min-w-0">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Transcription <span className="font-normal text-slate-500">(edit anything)</span></h2>
          <MasterEditor value={history.value} issues={issueMap} flags={openFlags} activeFlag={active} onChange={(update, group) => {
            history.set(update, group);
            setIssues((current) => withoutIssue(current, group));
          }} />
        </div>
      </div>

      <Dialog open={discarding} tone="danger" title="Discard this import?" confirmLabel="Discard" busy={discard.isPending}
        description="The transcription and the uploaded file are deleted. Nothing is saved as a master résumé."
        onClose={() => setDiscarding(false)} onConfirm={() => discard.mutate()} />
      <UnsavedChangesGuard dirty={saveState !== "saved" && !accepted} />
    </>
  );
}

export function ImportReviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const detail = useImport(id);
  const retry = useMutation({
    mutationFn: () => api<Import>("POST", `/api/imports/${id}/retry`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["import", id] }),
  });
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", `/api/imports/${id}`),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: importsKey }); navigate("/masters", { replace: true }); },
  });

  if (detail.isPending) return <Spinner />;
  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isError) return <Alert tone="error">{errorMessage(detail.error)}</Alert>;
  const d = detail.data;
  const back = (
    <Link to="/masters" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
      <ArrowLeft className="size-4" aria-hidden /> Master résumés
    </Link>
  );

  if (d.status === "ready") return <>{back}<ReviewScreen key={d.id} detail={d} /></>;
  return (
    <>
      {back}
      <PageHeader title={<span className="flex flex-wrap items-center gap-3">Import · {d.sourceName} <ImportStatusBadge status={d.status} /></span>} />
      {ACTIVE.includes(d.status) && <ImportProgress status={d.status} />}
      {d.status === "failed" && (
        <Alert tone="error" title="The import failed" className="mb-6">
          <p>{String(d.error?.message ?? "Something went wrong.")}</p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="secondary" icon={<RotateCcw className="size-4" aria-hidden />} loading={retry.isPending} onClick={() => retry.mutate()}>Retry</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" aria-hidden />} loading={remove.isPending} onClick={() => remove.mutate()}>Discard</Button>
          </div>
          {retry.isError && <p className="mt-2">{errorMessage(retry.error)}</p>}
        </Alert>
      )}
      {d.status === "accepted" && (
        <Alert tone="success" title="Saved as a master résumé" className="mb-6">
          {d.resultMasterId ? <Link to={`/masters/${d.resultMasterId}`} className="font-medium underline underline-offset-2">Open the master résumé</Link> : "The master résumé was deleted since."}
        </Alert>
      )}
      {d.costUsd > 0 && <p className="text-xs text-slate-500">Estimated cost so far: {formatUsd(d.costUsd)}</p>}
    </>
  );
}
