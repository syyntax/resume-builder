import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Copy, Download, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { AiSettings, Application, ApplicationStatus, Preferences } from "../api/types";
import { aiSettingsKey, useApiKeyStatus } from "../components/AiSettingsCard";
import { Dialog } from "../components/Dialog";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyState, PageHeader, Spinner, TextArea, TextField, cn, linkButtonClass,
} from "../components/ui";
import { modelLabel, timeAgo } from "../lib/format";
import { useMasters } from "./MastersPages";

export const applicationsKey = ["applications"] as const;
export const ACTIVE: ApplicationStatus[] = ["queued", "analyzing", "tailoring", "validating", "writing", "auditing"];

export function roleName(a: Application): string {
  if (a.job.title && a.job.company) return `${a.job.title} at ${a.job.company}`;
  return a.job.title ?? a.job.company ?? "Untitled application";
}

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  if (status === "done") return <Badge tone="green">Ready</Badge>;
  if (status === "failed") return <Badge tone="red">Failed</Badge>;
  if (status === "review") return <Badge tone="amber">Review the analysis</Badge>;
  return <Badge tone="brand">{status === "queued" ? "Queued" : "Generating…"}</Badge>;
}

// ---- new application --------------------------------------------------------------------------------

export function NewApplicationPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const masters = useMasters();
  const keyStatus = useApiKeyStatus();
  const settings = useQuery({ queryKey: aiSettingsKey, queryFn: () => api<AiSettings>("GET", "/api/account/ai-settings") });
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api<Preferences>("GET", "/api/account/preferences") });
  const [form, setForm] = useState({ masterId: "", text: "", company: "", title: "", url: "", pageLimit: "1",
    tone: "confident", instructions: "", letter: null as boolean | null, notes: "", recipient: "", review: false });
  const masterId = form.masterId || masters.data?.[0]?.id || "";
  const letter = form.letter ?? prefs.data?.coverLetter ?? true;

  const create = useMutation({
    mutationFn: () =>
      api<Application>("POST", "/api/applications", {
        json: {
          masterId,
          job: { text: form.text, company: form.company || null, title: form.title || null, url: form.url || null },
          options: { pageLimit: form.pageLimit === "auto" ? "auto" : Number(form.pageLimit), tone: form.tone,
            instructions: form.instructions || null, reviewAnalysis: form.review },
          coverLetter: { generate: letter, notes: form.notes, recipient: { name: form.recipient } },
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
      <Link to="/applications" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200">
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
            <div className="sm:col-span-3">
              <Checkbox label="Let me review the job analysis before the résumé is written" checked={form.review}
                onChange={(e) => setForm({ ...form, review: e.target.checked })} />
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Cover letter" description="Written with the résumé. More options, like tone and length, are in its tab afterwards." />
          <CardBody className="space-y-4">
            <Checkbox label="Write a cover letter too" checked={letter} onChange={(e) => setForm({ ...form, letter: e.target.checked })} />
            {letter && (
              <div className="grid gap-4 sm:grid-cols-3">
                <TextField label="Recipient (optional)" value={form.recipient} maxLength={200} placeholder="e.g. Priya Shah"
                  hint="Leave empty for “Dear Hiring Team,”" onChange={(e) => setForm({ ...form, recipient: e.target.value })} />
                <TextArea className="sm:col-span-2" label="Why this company? (optional)" rows={3} maxLength={3000} value={form.notes}
                  placeholder="What draws you to them: a product you use, their mission, someone you met. Without notes, that paragraph is flagged for you to personalize."
                  onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
            )}
          </CardBody>
        </Card>
        {create.isError && !error?.errors.length && <Alert tone="error">{errorMessage(create.error)}</Alert>}
        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" icon={<Sparkles className="size-4" aria-hidden />} loading={create.isPending}
            disabled={Boolean(noKey) || Boolean(noMaster) || !masterId}>
            Tailor my résumé
          </Button>
          {settings.data && (
            <span className="text-sm text-slate-500 dark:text-slate-400">
              Uses {modelLabel(settings.data.model)}. A typical run costs about $0.30–0.60 on your key.
            </span>
          )}
        </div>
      </form>
    </>
  );
}

// ---- list -----------------------------------------------------------------------------------------------

type Sort = "newest" | "oldest" | "company" | "role" | "coverage";
const SORTS: { value: Sort; label: string }[] = [
  { value: "newest", label: "Newest first" }, { value: "oldest", label: "Oldest first" },
  { value: "company", label: "Company A–Z" }, { value: "role", label: "Role A–Z" }, { value: "coverage", label: "Best keyword coverage" },
];

/** Search and sort the history (HIS-2): by company, role, master and date; coverage and dates sort. */
export function filterApplications(apps: Application[], query: string, sort: Sort): Application[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = (a: Application) => [a.job.company, a.job.title, a.master.label].filter(Boolean).join(" ").toLowerCase();
  const found = apps.filter((a) => words.every((w) => text(a).includes(w)));
  const by = (key: (a: Application) => string) => (x: Application, y: Application) => key(x).localeCompare(key(y), undefined, { sensitivity: "base" });
  const sorters: Record<Sort, (x: Application, y: Application) => number> = {
    newest: (x, y) => y.createdAt.localeCompare(x.createdAt),
    oldest: (x, y) => x.createdAt.localeCompare(y.createdAt),
    company: by((a) => a.job.company ?? "\uffff"),
    role: by((a) => a.job.title ?? "\uffff"),
    coverage: (x, y) => (y.coverageScore ?? -1) - (x.coverageScore ?? -1),
  };
  return [...found].sort(sorters[sort]);
}

export function ApplicationsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const apps = useQuery({
    queryKey: applicationsKey,
    queryFn: () => api<Application[]>("GET", "/api/applications"),
    refetchInterval: (query) => (query.state.data?.some((a) => ACTIVE.includes(a.status)) ? 3000 : false),
  });
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [deleting, setDeleting] = useState<Application | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: applicationsKey });
  const duplicate = useMutation({
    mutationFn: (id: string) => api<Application>("POST", `/api/applications/${id}/duplicate`),
    onSuccess: (copy) => { void refresh(); navigate(`/applications/${copy.id}`); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>("DELETE", `/api/applications/${id}`),
    onSuccess: () => { setDeleting(null); void refresh(); },
  });
  const shown = apps.data ? filterApplications(apps.data, query, sort) : [];
  const field = "rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <>
      <PageHeader title="Applications" description="One tailored résumé, and cover letter, per job."
        actions={<Link to="/applications/new" className={linkButtonClass("primary", "sm")}><Plus className="size-4" aria-hidden /> New application</Link>} />
      {apps.isPending ? <Spinner /> : apps.isError ? <Alert tone="error">{errorMessage(apps.error)}</Alert> : apps.data.length === 0 ? (
        <Card>
          <EmptyState icon={<Briefcase className="size-6" aria-hidden />} title="No applications yet">
            <p>Paste a job posting to get a résumé tailored to it.</p>
            <Link to="/applications/new" className={`${linkButtonClass("primary", "sm")} mt-4`}>New application</Link>
          </EmptyState>
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <div className="relative min-w-56 flex-1">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-slate-400" aria-hidden />
              <input type="search" aria-label="Search applications" placeholder="Search by company, role or master" value={query}
                onChange={(e) => setQuery(e.target.value)} className={cn(field, "w-full pl-8")} />
            </div>
            <select aria-label="Sort applications" className={field} value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              {SORTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          {(duplicate.isError || remove.isError) && <Alert tone="error" className="mb-4">{errorMessage(duplicate.error ?? remove.error)}</Alert>}
          <Card>
            {shown.length === 0 && <p className="px-5 py-6 text-sm text-slate-500 dark:text-slate-400">No applications match “{query}”.</p>}
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {shown.map((a) => (
                <li key={a.id} className="flex items-center gap-2 pr-3 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <Link to={`/applications/${a.id}`} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1 px-5 py-4">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-slate-900 dark:text-slate-100">{roleName(a)}</p>
                      <p className="text-sm text-slate-500 dark:text-slate-400">from {a.master.label ?? "a deleted master"} · {timeAgo(a.createdAt)}</p>
                    </div>
                    {a.coverageScore !== null && <span className="text-sm text-slate-600 tabular-nums dark:text-slate-400">{Math.round(a.coverageScore * 100)}% keywords</span>}
                    <StatusBadge status={a.status} />
                  </Link>
                  {a.status === "done" && (
                    <a href={`/api/applications/${a.id}/export?doc=resume&format=pdf`} title="Download the résumé (PDF)" aria-label={`Download the résumé for ${roleName(a)}`}
                      className="rounded p-1.5 text-slate-500 dark:text-slate-400 hover:bg-slate-200 hover:text-slate-800 dark:hover:bg-slate-700 dark:hover:text-slate-200"><Download className="size-4" aria-hidden /></a>
                  )}
                  {!ACTIVE.includes(a.status) && (
                    <>
                      <button type="button" title="Duplicate" aria-label={`Duplicate ${roleName(a)}`} disabled={duplicate.isPending} onClick={() => duplicate.mutate(a.id)}
                        className="rounded p-1.5 text-slate-500 dark:text-slate-400 hover:bg-slate-200 hover:text-slate-800 dark:hover:bg-slate-700 dark:hover:text-slate-200"><Copy className="size-4" aria-hidden /></button>
                      <button type="button" title="Delete" aria-label={`Delete ${roleName(a)}`} onClick={() => setDeleting(a)}
                        className="rounded p-1.5 text-slate-500 dark:text-slate-400 hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-950"><Trash2 className="size-4" aria-hidden /></button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
      <Dialog open={deleting !== null} tone="danger" title="Delete this application?" confirmLabel="Delete" busy={remove.isPending}
        description={deleting ? `${roleName(deleting)}: the posting, analysis, résumé and cover letter are deleted. Its usage still counts toward this month.` : ""}
        onClose={() => setDeleting(null)} onConfirm={() => deleting && remove.mutate(deleting.id)} />
    </>
  );
}
