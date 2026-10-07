import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Check, Download, FileJson, Lightbulb, Plus, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { AiSettings, Application, ApplicationDetail, ApplicationStatus, JobAnalysis, TailoredResume } from "../api/types";
import { aiSettingsKey, useApiKeyStatus } from "../components/AiSettingsCard";
import { Dialog } from "../components/Dialog";
import { AnalysisPanel, ResumePreview } from "../components/resume";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, EmptyState, PageHeader, Spinner, TextArea, TextField, cn, linkButtonClass,
} from "../components/ui";
import { formatDateTime, formatUsd, modelLabel, timeAgo } from "../lib/format";
import { useMasters } from "./MastersPages";
import { NotFoundPage } from "./NotFoundPage";

export const applicationsKey = ["applications"] as const;
const ACTIVE: ApplicationStatus[] = ["queued", "analyzing", "tailoring", "validating"];

function roleName(a: Application): string {
  if (a.job.title && a.job.company) return `${a.job.title} at ${a.job.company}`;
  return a.job.title ?? a.job.company ?? "Untitled application";
}

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  if (status === "done") return <Badge tone="green">Ready</Badge>;
  if (status === "failed") return <Badge tone="red">Failed</Badge>;
  return <Badge tone="brand">{status === "queued" ? "Queued" : "Generating…"}</Badge>;
}

// ---- new application --------------------------------------------------------------------------------

export function NewApplicationPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const masters = useMasters();
  const keyStatus = useApiKeyStatus();
  const settings = useQuery({ queryKey: aiSettingsKey, queryFn: () => api<AiSettings>("GET", "/api/account/ai-settings") });
  const [form, setForm] = useState({ masterId: "", text: "", company: "", title: "", url: "", pageLimit: "1",
    tone: "confident", instructions: "" });
  const masterId = form.masterId || masters.data?.[0]?.id || "";

  const create = useMutation({
    mutationFn: () =>
      api<Application>("POST", "/api/applications", {
        json: {
          masterId,
          job: { text: form.text, company: form.company || null, title: form.title || null, url: form.url || null },
          options: { pageLimit: form.pageLimit === "auto" ? "auto" : Number(form.pageLimit), tone: form.tone,
            instructions: form.instructions || null },
        },
      }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: applicationsKey });
      navigate(`/applications/${created.id}`);
    },
  });

  const noKey = keyStatus.data && !keyStatus.data.using;
  const noMaster = masters.data && masters.data.length === 0;
  const error = create.error instanceof ApiError ? create.error : null;
  const select = "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <>
      <Link to="/applications" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> Applications
      </Link>
      <PageHeader title="New application" description="Paste a job posting. You'll get a tailored résumé in about a minute." />
      {noKey && (
        <Alert tone="warning" title="Add your Anthropic API key first" className="mb-6">
          Tailoring runs on your own key. <Link to="/account#ai" className="font-medium underline underline-offset-2">Add it in Account → AI</Link>.
        </Alert>
      )}
      {noMaster && (
        <Alert tone="warning" title="Upload a master résumé first" className="mb-6">
          Tailoring picks from your master résumé. <Link to="/masters" className="font-medium underline underline-offset-2">Upload one</Link>.
        </Alert>
      )}
      <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Card>
          <CardHeader title="Job posting" />
          <CardBody className="space-y-4">
            <TextArea label="Posting text" required minLength={40} maxLength={50000} rows={14} value={form.text}
              placeholder="Paste the full job posting: title, company, responsibilities and requirements."
              onChange={(e) => setForm({ ...form, text: e.target.value })}
              error={error?.fieldError("job.text") ? "Paste at least a few sentences of the posting." : undefined} />
            <div className="grid gap-4 sm:grid-cols-3">
              <TextField label="Job title (optional)" value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} hint="Detected from the posting if empty." />
              <TextField label="Company (optional)" value={form.company} maxLength={200} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              <TextField label="Posting URL (optional)" type="url" value={form.url} maxLength={2048} onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Options" />
          <CardBody className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="master" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Master résumé</label>
              <select id="master" className={select} value={masterId} onChange={(e) => setForm({ ...form, masterId: e.target.value })}>
                {masters.data?.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="length" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Length</label>
              <select id="length" className={select} value={form.pageLimit} onChange={(e) => setForm({ ...form, pageLimit: e.target.value })}>
                <option value="1">One page</option><option value="2">Two pages</option><option value="auto">Automatic</option>
              </select>
            </div>
            <div>
              <label htmlFor="tone" className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">Tone</label>
              <select id="tone" className={select} value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })}>
                <option value="confident">Confident</option><option value="neutral">Neutral</option><option value="conservative">Conservative</option>
              </select>
            </div>
            <TextArea className="sm:col-span-3" label="Instructions (optional)" rows={2} maxLength={2000} value={form.instructions}
              placeholder="For example: emphasize incident response leadership."
              onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
          </CardBody>
        </Card>
        {create.isError && !error?.errors.length && <Alert tone="error">{errorMessage(create.error)}</Alert>}
        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" icon={<Sparkles className="size-4" aria-hidden />} loading={create.isPending}
            disabled={Boolean(noKey) || Boolean(noMaster) || !masterId}>
            Tailor my résumé
          </Button>
          {settings.data && (
            <span className="text-sm text-slate-500">
              Uses {modelLabel(settings.data.model)}. A typical run costs about $0.30–0.60 on your key.
            </span>
          )}
        </div>
      </form>
    </>
  );
}

// ---- list -----------------------------------------------------------------------------------------------

export function ApplicationsPage() {
  const apps = useQuery({
    queryKey: applicationsKey,
    queryFn: () => api<Application[]>("GET", "/api/applications"),
    refetchInterval: (query) => (query.state.data?.some((a) => ACTIVE.includes(a.status)) ? 3000 : false),
  });
  return (
    <>
      <PageHeader title="Applications" description="One tailored résumé per job."
        actions={<Link to="/applications/new" className={linkButtonClass("primary", "sm")}><Plus className="size-4" aria-hidden /> New application</Link>} />
      {apps.isPending ? <Spinner /> : apps.isError ? <Alert tone="error">{errorMessage(apps.error)}</Alert> : apps.data.length === 0 ? (
        <Card>
          <EmptyState icon={<Briefcase className="size-6" aria-hidden />} title="No applications yet">
            <p>Paste a job posting to get a résumé tailored to it.</p>
            <Link to="/applications/new" className={`${linkButtonClass("primary", "sm")} mt-4`}>New application</Link>
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {apps.data.map((a) => (
              <li key={a.id}>
                <Link to={`/applications/${a.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-900 dark:text-slate-100">{roleName(a)}</p>
                    <p className="text-sm text-slate-500">from {a.master.label ?? "a deleted master"} · {timeAgo(a.createdAt)}</p>
                  </div>
                  {a.coverageScore !== null && <span className="text-sm text-slate-600 tabular-nums dark:text-slate-400">{Math.round(a.coverageScore * 100)}% keywords</span>}
                  <StatusBadge status={a.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

// ---- detail ---------------------------------------------------------------------------------------------

const steps: { status: ApplicationStatus; label: string }[] = [
  { status: "analyzing", label: "Analyzing the posting" },
  { status: "tailoring", label: "Tailoring your résumé" },
  { status: "validating", label: "Checking every claim" },
];

function Progress({ status }: { status: ApplicationStatus }) {
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
                  state === "done" ? "bg-emerald-600 text-white" : state === "active" ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-500 dark:bg-slate-800")}>
                  {state === "active" ? <Spinner className="size-3.5 text-white" /> : state === "done" ? <Check className="size-3.5" aria-label="Done" /> : i + 1}
                </span>
                <span className={state === "todo" ? "text-slate-500" : "font-medium text-slate-900 dark:text-slate-100"}>{step.label}</span>
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-sm text-slate-500">{status === "queued" ? "Waiting to start…" : "This usually takes about a minute. You can leave this page."}</p>
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

export function ApplicationDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const detail = useApplication(id);
  const [deleting, setDeleting] = useState(false);
  const retry = useMutation({
    mutationFn: () => api<Application>("POST", `/api/applications/${id}/retry`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["application", id] }),
  });
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", `/api/applications/${id}`),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: applicationsKey }); navigate("/applications", { replace: true }); },
  });

  if (detail.isPending) return <Spinner />;
  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isError) return <Alert tone="error">{errorMessage(detail.error)}</Alert>;
  const a = detail.data;
  const analysis = a.analysis as JobAnalysis | null;
  const resume = a.resume as TailoredResume | null;
  const running = ACTIVE.includes(a.status);
  const report = resume?.analysis;
  const flagged = report ? report.warnings.length : 0;

  return (
    <>
      <Link to="/applications" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> Applications
      </Link>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">{roleName(a)} <StatusBadge status={a.status} /></span>}
        description={`From ${a.master.label ?? "a deleted master"} (v${a.master.versionNumber}) · ${modelLabel(a.model)} · created ${formatDateTime(a.createdAt)}`}
        actions={
          <>
            {resume && (
              <>
                <a href={`/api/applications/${id}/export?format=md`} className={linkButtonClass("secondary", "sm")}><Download className="size-4" aria-hidden /> Markdown</a>
                <a href={`/api/applications/${id}/export?format=json`} className={linkButtonClass("ghost", "sm")}><FileJson className="size-4" aria-hidden /> JSON</a>
              </>
            )}
            {!running && <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setDeleting(true)}><span className="sr-only">Delete application</span></Button>}
          </>
        }
      />

      {running && <Progress status={a.status} />}
      {a.status === "failed" && (
        <Alert tone="error" title="Generation failed" className="mb-6">
          <p>{String(a.error?.message ?? "Something went wrong.")} {errorHelp(a.error?.code as string | undefined)}</p>
          <Button className="mt-3" size="sm" variant="secondary" icon={<RotateCcw className="size-4" aria-hidden />} loading={retry.isPending} onClick={() => retry.mutate()}>Retry</Button>
          {retry.isError && <p className="mt-2">{errorMessage(retry.error)}</p>}
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-6">
          {resume ? (
            <>
              {flagged > 0 && (
                <Alert tone="warning" title={`${flagged} ${flagged === 1 ? "line needs" : "lines need"} a check`}>
                  Highlighted lines mention a number or term that their source in your master résumé doesn't. Hover the warning icon for details.
                </Alert>
              )}
              <ResumePreview resume={resume} />
              <p className="text-xs text-slate-500">This preview shows content and structure. Styled PDF and Word exports with your chosen template arrive in a later release.</p>
            </>
          ) : running ? (
            <Card><CardBody className="py-16 text-center text-sm text-slate-500">Your tailored résumé will appear here.</CardBody></Card>
          ) : null}
        </div>

        <aside className="space-y-6">
          {report?.coverage.score !== undefined && report.coverage.score !== null && (
            <Card>
              <CardHeader title="Keyword coverage" />
              <CardBody className="space-y-3">
                <p className="text-3xl font-semibold tabular-nums text-slate-900 dark:text-white">{Math.round(report.coverage.score * 100)}%</p>
                <p className="text-sm text-slate-500">of the posting's weighted keywords appear on the résumé.</p>
                {report.coverage.available.length > 0 && (
                  <p className="text-sm text-slate-600 dark:text-slate-400">
                    In your master but not used: {report.coverage.available.map((x) => x.term).join(", ")}.
                  </p>
                )}
                {report.coverage.gaps.length > 0 && (
                  <p className="text-sm text-slate-600 dark:text-slate-400">Gaps (not claimed): {report.coverage.gaps.join(", ")}.</p>
                )}
              </CardBody>
            </Card>
          )}
          {report && report.notes.length > 0 && (
            <Card>
              <CardHeader title="Notes for you" />
              <CardBody>
                <ul className="space-y-2 text-sm">
                  {report.notes.map((n, i) => (
                    <li key={i} className="flex gap-2">
                      <Lightbulb className={cn("mt-0.5 size-4 shrink-0", n.type === "gap" ? "text-red-500" : "text-amber-500")} aria-hidden />
                      <span className="text-slate-700 dark:text-slate-300">{n.text}</span>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
          {analysis && (
            <Card>
              <CardHeader title="Job analysis" />
              <CardBody><AnalysisPanel analysis={analysis} coverage={report?.coverage} /></CardBody>
            </Card>
          )}
          <p className="text-xs text-slate-500">Estimated cost: {formatUsd(a.costUsd)}</p>
        </aside>
      </div>

      <Dialog open={deleting} tone="danger" title="Delete this application?" confirmLabel="Delete" busy={remove.isPending}
        description="The posting, analysis and tailored résumé are deleted. Its usage still counts toward this month's cap."
        onClose={() => setDeleting(false)} onConfirm={() => remove.mutate()}>
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </>
  );
}
