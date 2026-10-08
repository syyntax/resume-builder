import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { AiSettings, ApiKeyStatus, Usage } from "../api/types";
import { formatUsd, modelLabel, monthLabel, timeAgo } from "../lib/format";
import { Dialog } from "./Dialog";
import { Alert, Badge, Button, Card, CardBody, CardHeader, Spinner, TextField, cn } from "./ui";

export const apiKeyKey = ["account", "api-key"] as const;
export const aiSettingsKey = ["account", "ai-settings"] as const;
export const usageKey = ["account", "usage"] as const;

export function useApiKeyStatus() {
  return useQuery({ queryKey: apiKeyKey, queryFn: () => api<ApiKeyStatus>("GET", "/api/account/api-key") });
}

export function useUsage(month: string | null = null) {
  return useQuery({ queryKey: [...usageKey, month], queryFn: () => api<Usage>("GET", `/api/account/usage${month ? `?month=${month}` : ""}`) });
}

export function SpendBar({ spent, cap }: { spent: number; cap: number | null }) {
  const percent = cap ? Math.min(100, (100 * spent) / cap) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-slate-900 dark:text-slate-100">{formatUsd(spent)}</span>
        <span className="text-slate-500 dark:text-slate-400">{cap ? `of ${formatUsd(cap)} this month` : "no cap"}</span>
      </div>
      {cap ? (
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="meter"
          aria-valuemin={0} aria-valuemax={cap} aria-valuenow={spent} aria-label="Spending this month">
          <div className={cn("h-full rounded-full", percent >= 100 ? "bg-red-500" : percent >= 80 ? "bg-amber-500" : "bg-brand-500")}
            style={{ width: `${percent}%` }} />
        </div>
      ) : null}
    </div>
  );
}

function KeySection() {
  const queryClient = useQueryClient();
  const status = useApiKeyStatus();
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [form, setForm] = useState({ apiKey: "", password: "" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["account"] });

  const save = useMutation({
    mutationFn: () => api<ApiKeyStatus>("PUT", "/api/account/api-key", { json: form }),
    onSuccess: (value) => {
      queryClient.setQueryData(apiKeyKey, value);
      setEditing(false);
      setForm({ apiKey: "", password: "" });
    },
  });
  const test = useMutation({
    mutationFn: () => api<ApiKeyStatus>("POST", "/api/account/api-key/test"),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", "/api/account/api-key", { json: { password: form.password } }),
    onSuccess: () => {
      setRemoving(false);
      setForm({ apiKey: "", password: "" });
      refresh();
    },
  });

  if (status.isPending) return <Spinner />;
  if (status.isError) return <Alert tone="error">{errorMessage(status.error)}</Alert>;
  const key = status.data;
  const error = save.error instanceof ApiError ? save.error : null;

  return (
    <div className="space-y-4">
      {key.hasKey ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <KeyRound className="size-5 text-slate-400" aria-hidden />
            <div>
              <p className="font-mono text-sm text-slate-900 dark:text-slate-100">sk-ant-…{key.hint}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {key.status === "valid" ? "Working" : "Rejected by Anthropic"}
                {key.verifiedAt && ` · checked ${timeAgo(key.verifiedAt)}`}
                {key.lastUsedAt && ` · last used ${timeAgo(key.lastUsedAt)}`}
              </p>
            </div>
            {key.status === "valid" ? <Badge tone="green">Active</Badge> : <Badge tone="red">Invalid</Badge>}
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" icon={<RefreshCw className="size-4" aria-hidden />} loading={test.isPending}
              onClick={() => test.mutate()}>Test</Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Replace</Button>
            <Button variant="ghost" size="sm" icon={<Trash2 className="size-4 text-red-600" aria-hidden />}
              onClick={() => setRemoving(true)}><span className="sr-only">Remove key</span></Button>
          </div>
        </div>
      ) : (
        <Alert tone={key.sharedKeyAvailable ? "info" : "warning"}
          title={key.sharedKeyAvailable ? "Using the shared key" : "Add your API key to start tailoring"}>
          {key.sharedKeyAvailable
            ? "Your admin lets people without a key use the deployment's shared key, within a monthly allowance. Add your own key to use your own account."
            : "Resume Tailor uses your own Anthropic API key, so AI usage is billed to your Anthropic account."}{" "}
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium underline underline-offset-2">
            Get a key <ExternalLink className="size-3" aria-hidden />
          </a>
        </Alert>
      )}
      {test.isError && <Alert tone="error">{errorMessage(test.error)}</Alert>}
      {test.isSuccess && <p className="flex items-center gap-1.5 text-sm text-emerald-700 dark:text-emerald-400"><CheckCircle2 className="size-4" aria-hidden /> Anthropic accepted the key.</p>}

      {(editing || !key.hasKey) && (
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <TextField className="sm:col-span-2" label="Anthropic API key" type="password" autoComplete="off" spellCheck={false}
            placeholder="sk-ant-…" required value={form.apiKey} onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
            error={error?.fieldError("apiKey") ? error.message : undefined}
            hint="We check it with Anthropic, store it encrypted, and never show it again." />
          <TextField label="Your Resume Tailor password" type="password" autoComplete="current-password" required
            value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
            error={error?.fieldError("password") ? "Incorrect password." : undefined} />
          <div className="flex items-end gap-2">
            <Button type="submit" loading={save.isPending}>{key.hasKey ? "Replace key" : "Save key"}</Button>
            {key.hasKey && <Button variant="ghost" onClick={() => { setEditing(false); save.reset(); }}>Cancel</Button>}
          </div>
          {save.isError && !error?.errors.length && <Alert tone="error" className="sm:col-span-2">{errorMessage(save.error)}</Alert>}
        </form>
      )}

      <Dialog open={removing} tone="danger" title="Remove your API key?" confirmLabel="Remove key" busy={remove.isPending}
        confirmDisabled={!form.password} onClose={() => { setRemoving(false); remove.reset(); }} onConfirm={() => remove.mutate()}
        description="AI tailoring stops working until you add a key again (unless your admin allows the shared key).">
        <TextField label="Password" type="password" autoComplete="current-password" value={form.password} autoFocus
          onChange={(e) => setForm({ ...form, password: e.target.value })} />
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </div>
  );
}

function ModelAndCapSection() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: aiSettingsKey, queryFn: () => api<AiSettings>("GET", "/api/account/ai-settings") });
  const [month, setMonth] = useState<string | null>(null);
  const usage = useUsage(month);
  const [cap, setCap] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<AiSettings>("PUT", "/api/account/ai-settings", { json: body }),
    onSuccess: (value) => {
      queryClient.setQueryData(aiSettingsKey, value);
      void queryClient.invalidateQueries({ queryKey: usageKey });
      setCap(null);
    },
  });
  if (settings.isPending) return <Spinner />;
  if (settings.isError) return <Alert tone="error">{errorMessage(settings.error)}</Alert>;
  const s = settings.data;
  const effectiveCap = s.monthlyCapUsd ?? s.defaultCapUsd;

  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <div className="space-y-2">
        <label htmlFor="ai-model" className="block text-sm font-medium text-slate-700 dark:text-slate-300">Model</label>
        <select id="ai-model" value={s.model} disabled={s.allowedModels.length < 2 || update.isPending}
          onChange={(e) => update.mutate({ model: e.target.value })}
          className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900">
          {s.allowedModels.map((m) => <option key={m} value={m}>{modelLabel(m)}{m === s.defaultModel ? " (default)" : ""}</option>)}
        </select>
        <p className="text-xs text-slate-500 dark:text-slate-400">Your admin chooses which models are available.</p>
      </div>
      <div className="space-y-2">
        <form className="flex items-end gap-2" onSubmit={(e) => {
          e.preventDefault();
          if (cap !== null) update.mutate(cap.trim() === "" ? { resetCap: true } : { monthlyCapUsd: Number(cap) });
        }}>
          <TextField className="flex-1" label="Monthly spending cap (USD)" type="number" min={0} step="1"
            value={cap ?? String(effectiveCap)} onChange={(e) => setCap(e.target.value)}
            hint={`0 means no cap. Leave empty for the default ($${s.defaultCapUsd}).`} />
          {cap !== null && <Button type="submit" loading={update.isPending} className="mb-[1.375rem]">Save</Button>}
        </form>
        {update.isError && <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(update.error)}</p>}
      </div>
      {usage.data && (
        <div className="sm:col-span-2 space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">This month</p>
          <SpendBar spent={usage.data.own.spentUsd} cap={usage.data.own.capUsd} />
          {usage.data.shared && (
            <div>
              <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">Shared key allowance</p>
              <SpendBar spent={usage.data.shared.spentUsd} cap={usage.data.shared.capUsd} />
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">Usage by step and by application</p>
            {usage.data.months.length > 0 && (
              <select aria-label="Month" value={usage.data.month} onChange={(e) => setMonth(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900">
                {[...new Set([usage.data.month, ...usage.data.months.map((m) => m.month)])].sort().reverse().map((m) => {
                  const row = usage.data.months.find((x) => x.month === m);
                  return <option key={m} value={m}>{monthLabel(m)}{row ? ` · ${formatUsd(row.costUsd)}` : ""}</option>;
                })}
              </select>
            )}
          </div>
          {usage.data.byStage.length === 0 ? <p className="text-sm text-slate-500 dark:text-slate-400">No AI use in {monthLabel(usage.data.month)}.</p> : (
            <div className="grid gap-4 sm:grid-cols-2">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-slate-500 dark:text-slate-400 uppercase"><tr><th className="py-1 font-medium">Step</th><th className="py-1 font-medium">Calls</th><th className="py-1 text-right font-medium">Tokens</th><th className="py-1 text-right font-medium">Cost</th></tr></thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                  {usage.data.byStage.map((row) => (
                    <tr key={row.stage}><td className="py-1.5">{stageLabel(row.stage)}</td><td className="py-1.5 tabular-nums">{row.calls}</td>
                      <td className="py-1.5 text-right tabular-nums">{(row.inputTokens + row.outputTokens).toLocaleString()}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatUsd(row.costUsd)}</td></tr>
                  ))}
                </tbody>
              </table>
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-slate-500 dark:text-slate-400 uppercase"><tr><th className="py-1 font-medium">For</th><th className="py-1 text-right font-medium">Cost</th></tr></thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                  {usage.data.byItem.map((row) => (
                    <tr key={`${row.kind}:${row.id ?? row.label}`}>
                      <td className="py-1.5">{row.kind === "application" && row.id ? <Link to={`/applications/${row.id}`} className="hover:underline">{row.label}</Link> : row.label}</td>
                      <td className="py-1.5 text-right tabular-nums">{formatUsd(row.costUsd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Estimates from token counts, for your cap. Your actual bill is in the{" "}
            <a className="underline underline-offset-2" href="https://console.anthropic.com/" target="_blank" rel="noreferrer">Anthropic Console</a>.
          </p>
        </div>
      )}
    </div>
  );
}

export function stageLabel(stage: string): string {
  return ({ analyze: "Analyze posting", tailor: "Tailor résumé", tailor_repair: "Tailor (repair pass)", letter: "Cover letter",
    audit: "Claim audit", refine: "Refine", letter_refine: "Refine letter", condense: "Condense letter", import: "Import résumé" } as Record<string, string>)[stage] ?? stage;
}

export function AiSettingsCard() {
  return (
    <Card>
      <span id="ai" className="block scroll-mt-20" />
      <CardHeader title="AI" description="Your Anthropic API key, model and monthly spending cap." />
      <CardBody className="space-y-6">
        <KeySection />
        <div className="border-t border-slate-200 pt-6 dark:border-slate-800">
          <ModelAndCapSection />
        </div>
      </CardBody>
    </Card>
  );
}
