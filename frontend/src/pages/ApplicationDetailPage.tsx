/**
 * One application: progress while it generates, then the workspace (résumé, cover letter, job analysis).
 * Loaded on demand: the editors bring in drag-and-drop and PDF.js.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, Download, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { Application, ApplicationDetail, ApplicationStatus, TailoredResume } from "../api/types";
import { Dialog } from "../components/Dialog";
import { Alert, Button, Card, CardBody, PageHeader, Spinner, cn } from "../components/ui";
import { formatDateTime, formatUsd, modelLabel } from "../lib/format";
import { AnalysisEditor } from "../workspace/AnalysisEditor";
import { LetterWorkspace } from "../workspace/LetterWorkspace";
import { ResumeWorkspace } from "../workspace/ResumeWorkspace";
import { Popover } from "../workspace/shared";
import { ACTIVE, StatusBadge, applicationsKey, roleName } from "./ApplicationsPages";
import { NotFoundPage } from "./NotFoundPage";

const STEPS: { status: ApplicationStatus; label: string }[] = [
  { status: "analyzing", label: "Analyzing the posting" },
  { status: "tailoring", label: "Tailoring your résumé" },
  { status: "validating", label: "Checking facts" },
  { status: "writing", label: "Writing the cover letter" },
  { status: "auditing", label: "Auditing every claim" },
];

function Progress({ status, letter }: { status: ApplicationStatus; letter: boolean }) {
  const steps = STEPS.filter((s) => letter || s.status !== "writing");
  const current = steps.findIndex((s) => s.status === status);
  return (
    <Card className="mb-6">
      <CardBody>
        <ol className="flex flex-col gap-3 sm:flex-row sm:gap-6" aria-label="Progress">
          {steps.map((step, i) => {
            const state = status === "queued" ? "todo" : i < current ? "done" : i === current ? "active" : "todo";
            return (
              <li key={step.status} className="flex items-center gap-2 text-sm">
                <span className={cn("grid size-6 place-items-center rounded-full text-xs font-semibold",
                  state === "done" ? "bg-emerald-600 text-white" : state === "active" ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-500 dark:text-slate-400 dark:bg-slate-800")}>
                  {state === "active" ? <Spinner className="size-3.5 text-white" /> : state === "done" ? <Check className="size-3.5" aria-label="Done" /> : i + 1}
                </span>
                <span className={state === "todo" ? "text-slate-500 dark:text-slate-400" : "font-medium text-slate-900 dark:text-slate-100"}>{step.label}</span>
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">{status === "queued" ? "Waiting to start…" : "This usually takes about a minute. You can leave this page."}</p>
      </CardBody>
    </Card>
  );
}

/** Live progress over SSE, with polling as a fallback. */
function useApplication(id: string) {
  const queryClient = useQueryClient();
  const key = ["application", id];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<ApplicationDetail>("GET", `/api/applications/${id}`),
    retry: false,
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 5000 : false),
  });
  const active = query.data ? ACTIVE.includes(query.data.status) : false;
  useEffect(() => {
    if (!active) return;
    const source = new EventSource(`/api/applications/${id}/events`);
    const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
    const onStatus = (e: MessageEvent<string>) => {
      const data = JSON.parse(e.data) as { status: ApplicationStatus };
      queryClient.setQueryData<ApplicationDetail>(key, (old) => (old ? { ...old, status: data.status } : old));
    };
    source.addEventListener("status", onStatus);
    source.addEventListener("analysis", refresh);
    source.addEventListener("done", () => { refresh(); source.close(); void queryClient.invalidateQueries({ queryKey: applicationsKey }); });
    source.addEventListener("error", () => { refresh(); source.close(); });
    source.addEventListener("review", () => { refresh(); source.close(); });
    return () => source.close();
  }, [id, active, queryClient]); // key is derived from id
  return query;
}

function errorHelp(code: string | undefined) {
  if (code === "no_api_key" || code === "key_rejected" || code === "key_unreadable" || code === "out_of_credit" || code === "model_unavailable") {
    return <Link to="/account#ai" className="font-medium underline underline-offset-2">Open Account → AI</Link>;
  }
  if (code === "cap_reached") return <Link to="/account#ai" className="font-medium underline underline-offset-2">Review your spending cap</Link>;
  return null;
}

// ---- the workspace -------------------------------------------------------------------------------------------

type Tab = "resume" | "letter" | "analysis";

function ExportMenu({ id, hasLetter }: { id: string; hasLetter: boolean }) {
  const link = (doc: string, format: string, label: string, enabled = true) => enabled
    ? <a key={doc + format} href={`/api/applications/${id}/export?doc=${doc}&format=${format}`} className="block rounded px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800">{label}</a>
    : <span key={doc + format} className="block px-2 py-1.5 text-slate-400">{label}</span>;
  return (
    <Popover label="Export" trigger={(open, toggle) => (
      <Button size="sm" icon={<Download className="size-4" aria-hidden />} aria-expanded={open} onClick={toggle}>Export</Button>
    )}>
      {() => (
        <div className="grid grid-cols-2 gap-x-4 text-sm">
          <div>
            <p className="px-2 pb-1 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">Résumé</p>
            {link("resume", "pdf", "PDF")}{link("resume", "docx", "Word")}{link("resume", "txt", "Plain text")}
            {link("resume", "md", "Markdown")}{link("resume", "json", "JSON")}
          </div>
          <div>
            <p className="px-2 pb-1 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">Cover letter</p>
            {link("cover-letter", "pdf", "PDF", hasLetter)}{link("cover-letter", "docx", "Word", hasLetter)}
            {link("cover-letter", "txt", "Plain text", hasLetter)}{link("cover-letter", "md", "Markdown", hasLetter)}
            {link("cover-letter", "json", "JSON", hasLetter)}
          </div>
          <div className="col-span-2 mt-2 border-t border-slate-100 pt-2 dark:border-slate-800">
            {link("packet", "pdf", "Application packet (PDF): letter, then résumé", hasLetter)}
          </div>
        </div>
      )}
    </Popover>
  );
}

function useMasterVersion(application: ApplicationDetail | undefined) {
  return useQuery({
    queryKey: ["masterVersion", application?.master.versionId],
    queryFn: () => api<{ content: Record<string, unknown> }>("GET", `/api/master-resumes/${application!.master.id}/versions/${application!.master.versionId}`),
    enabled: Boolean(application?.master.id) && application?.status === "done",
    staleTime: Infinity,
  });
}

export function ApplicationDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const detail = useApplication(id);
  const masterVersion = useMasterVersion(detail.data);
  const [deleting, setDeleting] = useState(false);
  const [tab, setTab] = useState<Tab>("resume");
  const retry = useMutation({
    mutationFn: () => api<Application>("POST", `/api/applications/${id}/retry`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["application", id] }),
  });
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", `/api/applications/${id}`),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: applicationsKey }); navigate("/applications", { replace: true }); },
  });
  const duplicate = useMutation({
    mutationFn: () => api<Application>("POST", `/api/applications/${id}/duplicate`),
    onSuccess: (copy) => { void queryClient.invalidateQueries({ queryKey: applicationsKey }); navigate(`/applications/${copy.id}`); },
  });

  if (detail.isPending) return <Spinner />;
  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isError) return <Alert tone="error">{errorMessage(detail.error)}</Alert>;
  const a = detail.data;
  const resume = a.resume as TailoredResume | null;
  const running = ACTIVE.includes(a.status);
  const master = masterVersion.data?.content;

  return (
    <>
      <Link to="/applications" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> Applications
      </Link>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">{roleName(a)} <StatusBadge status={a.status} /></span>}
        description={`From ${a.master.label ?? "a deleted master"} (v${a.master.versionNumber}) · ${modelLabel(a.model)} · ${formatUsd(a.costUsd)} so far · created ${formatDateTime(a.createdAt)}`}
        actions={
          <>
            {resume && <ExportMenu id={id} hasLetter={a.coverLetterStatus === "ready"} />}
            {!running && a.status !== "review" && (
              <Button variant="ghost" size="sm" icon={<Copy className="size-4" aria-hidden />} loading={duplicate.isPending} onClick={() => duplicate.mutate()} title="Duplicate to try a variant">
                <span className="sr-only">Duplicate</span>
              </Button>
            )}
            {!running && <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setDeleting(true)}><span className="sr-only">Delete application</span></Button>}
          </>
        }
      />

      {running && <Progress status={a.status} letter={Boolean((a.options.coverLetter as { generate?: boolean } | undefined)?.generate)} />}
      {a.status === "failed" && (
        <Alert tone="error" title="Generation failed" className="mb-6">
          <p>{String(a.error?.message ?? "Something went wrong.")} {errorHelp(a.error?.code as string | undefined)}</p>
          <Button className="mt-3" size="sm" variant="secondary" icon={<RotateCcw className="size-4" aria-hidden />} loading={retry.isPending} onClick={() => retry.mutate()}>Retry</Button>
          {retry.isError && <p className="mt-2">{errorMessage(retry.error)}</p>}
        </Alert>
      )}
      {a.status === "review" && a.analysis && <AnalysisEditor application={a} mode="review" />}

      {a.status === "done" && resume && (
        <>
          <div role="tablist" aria-label="Application" className="mb-5 inline-flex rounded-lg bg-slate-200/70 p-1 dark:bg-slate-800">
            {([["resume", "Résumé"], ["letter", "Cover letter"], ["analysis", "Job analysis"]] as const).map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                className={cn("rounded-md px-3 py-1.5 text-sm font-medium", tab === key ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-600 dark:text-slate-400")}>
                {label}{key === "letter" && a.coverLetterStatus === "generating" && " …"}
              </button>
            ))}
          </div>
          {!master ? <Spinner /> : tab === "resume" ? (
            <ResumeWorkspace key={String((resume as { meta?: { generatedAt?: string } }).meta?.generatedAt)} application={a} master={master} />
          ) : tab === "letter" ? (
            <LetterWorkspace application={a} master={master} />
          ) : (
            <AnalysisEditor application={a} mode="done" />
          )}
        </>
      )}

      <Dialog open={deleting} tone="danger" title="Delete this application?" confirmLabel="Delete" busy={remove.isPending}
        description="The posting, analysis, résumé and cover letter are deleted. Its usage still counts toward this month's cap."
        onClose={() => setDeleting(false)} onConfirm={() => remove.mutate()}>
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </>
  );
}
