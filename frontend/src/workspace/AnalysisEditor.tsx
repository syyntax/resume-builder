/**
 * The job analysis, editable (JOB-4): keyword importance, must-includes, added keywords and the themes to lead
 * with. In review-first mode (JOB-5) it's shown before the résumé is written; afterwards, regenerating uses it.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Check, Plus, RotateCcw, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { api, errorMessage } from "../api/client";
import type { ApplicationDetail, JobAnalysis } from "../api/types";
import { Dialog } from "../components/Dialog";
import { AnalysisPanel } from "../components/resume";
import { Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, cn, inputClass } from "../components/ui";

interface KeywordRow {
  term: string;
  importance: 1 | 2 | 3;
  mustInclude: boolean;
}

export function AnalysisEditor({ application, mode }: { application: ApplicationDetail; mode: "review" | "done" }) {
  const queryClient = useQueryClient();
  const analysis = application.analysis as unknown as JobAnalysis;
  const [rows, setRows] = useState<KeywordRow[]>(analysis.keywords.map((k) => ({ term: k.term, importance: k.importance, mustInclude: k.mustInclude })));
  const [emphasis, setEmphasis] = useState<string[]>(analysis.suggestedEmphasis);
  const [newTerm, setNewTerm] = useState("");
  const [newTheme, setNewTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [withLetter, setWithLetter] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["application", application.id] });

  const saveAnalysis = async () => {
    await api("PUT", `/api/applications/${application.id}/analysis`, { json: { keywords: rows, suggestedEmphasis: emphasis } });
  };
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const setRow = (i: number, patch: Partial<KeywordRow>) => {
    setSaved(false);
    setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Card>
        <CardHeader title={mode === "review" ? "Review the analysis before the résumé is written" : "Job analysis"}
          description="Promote what matters most, mark must-include keywords, and choose the themes to lead with. Only keywords your master résumé supports can appear." />
        <CardBody className="space-y-4">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="pb-2 font-medium">Keyword</th><th className="pb-2 font-medium">Importance</th><th className="pb-2 font-medium">Must include</th><th /></tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((row, i) => (
                <tr key={row.term}>
                  <td className="py-1.5 pr-2 text-slate-900 dark:text-slate-100">{row.term}</td>
                  <td className="py-1.5 pr-2">
                    <select aria-label={`Importance of ${row.term}`} className={cn(inputClass, "w-32 py-1")} value={row.importance}
                      onChange={(e) => setRow(i, { importance: Number(e.target.value) as 1 | 2 | 3 })}>
                      <option value={3}>Central</option><option value={2}>Wanted</option><option value={1}>Minor</option>
                    </select>
                  </td>
                  <td className="py-1.5 pr-2"><input type="checkbox" aria-label={`Must include ${row.term}`} className="size-4" checked={row.mustInclude} onChange={(e) => setRow(i, { mustInclude: e.target.checked })} /></td>
                  <td className="py-1.5 text-right">
                    <button type="button" aria-label={`Remove ${row.term}`} className="rounded p-1 text-slate-400 hover:text-red-600"
                      onClick={() => { setSaved(false); setRows((r) => r.filter((_, j) => j !== i)); }}><X className="size-4" aria-hidden /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = newTerm.trim(); if (t && !rows.some((r) => r.term.toLowerCase() === t.toLowerCase())) { setRows((r) => [...r, { term: t, importance: 2, mustInclude: false }]); setSaved(false); } setNewTerm(""); }}>
            <input className={cn(inputClass, "py-1.5")} placeholder="Add a keyword the posting cares about" value={newTerm} maxLength={80} onChange={(e) => setNewTerm(e.target.value)} aria-label="New keyword" />
            <Button type="submit" variant="secondary" size="sm" icon={<Plus className="size-3.5" aria-hidden />}>Add</Button>
          </form>
          <div>
            <p className="mb-1.5 text-sm font-medium text-slate-700 dark:text-slate-300">Themes to emphasize</p>
            <div className="flex flex-wrap gap-1.5">
              {emphasis.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-xs text-brand-800 dark:bg-brand-900/50 dark:text-brand-200">
                  {t}<button type="button" aria-label={`Remove ${t}`} onClick={() => { setEmphasis((e) => e.filter((x) => x !== t)); setSaved(false); }}><X className="size-3" aria-hidden /></button>
                </span>
              ))}
            </div>
            <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = newTheme.trim(); if (t && emphasis.length < 10 && !emphasis.includes(t)) { setEmphasis((x) => [...x, t]); setSaved(false); } setNewTheme(""); }}>
              <input className={cn(inputClass, "py-1.5")} placeholder="e.g. Developer platforms" value={newTheme} maxLength={200} onChange={(e) => setNewTheme(e.target.value)} aria-label="New theme" />
              <Button type="submit" variant="secondary" size="sm" icon={<Plus className="size-3.5" aria-hidden />}>Add</Button>
            </form>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          <div className="flex flex-wrap items-center gap-2">
            {mode === "review" ? (
              <Button icon={<Sparkles className="size-4" aria-hidden />} loading={busy}
                onClick={() => void run(async () => { await saveAnalysis(); await api("POST", `/api/applications/${application.id}/continue`); })}>
                Write my résumé
              </Button>
            ) : (
              <>
                <Button variant="secondary" icon={<Check className="size-4" aria-hidden />} loading={busy}
                  onClick={() => void run(async () => { await saveAnalysis(); setSaved(true); })}>Save</Button>
                <Button icon={<RotateCcw className="size-4" aria-hidden />} disabled={busy} onClick={() => setConfirm(true)}>Regenerate résumé</Button>
                {saved && <Badge tone="green">Saved</Badge>}
                {application.analysisEdited && <span className="text-xs text-slate-500">You've edited this analysis.</span>}
              </>
            )}
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Fit" />
        <CardBody><AnalysisPanel analysis={analysis} /></CardBody>
      </Card>
      <Dialog open={confirm} tone="danger" title="Regenerate the résumé?" confirmLabel="Regenerate" busy={busy}
        description="A new résumé is written from this analysis. It replaces the current résumé, including your edits."
        onClose={() => setConfirm(false)}
        onConfirm={() => void run(async () => { await saveAnalysis(); await api("POST", `/api/applications/${application.id}/regenerate`, { json: { letter: withLetter } }); setConfirm(false); })}>
        <Checkbox label="Write a new cover letter too" checked={withLetter} onChange={(e) => setWithLetter(e.target.checked)} />
      </Dialog>
    </div>
  );
}
