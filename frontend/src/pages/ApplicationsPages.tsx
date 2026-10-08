import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { AiSettings, Application, ApplicationStatus } from "../api/types";
import { aiSettingsKey, useApiKeyStatus } from "../components/AiSettingsCard";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, EmptyState, PageHeader, Spinner, TextArea, TextField, linkButtonClass,
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
