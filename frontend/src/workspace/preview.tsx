/** The live PDF preview (TPL-1) and the design panel, shared by the résumé and cover letter tabs. */

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Minimize2, RotateCcw, Wand2 } from "lucide-react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";

import { ApiError, api, errorMessage } from "../api/client";
import type { ApplicationDetail, FitResult, RestoreResult, Theme } from "../api/types";
import { DesignPanel } from "../components/design";
import { Alert, Button, Spinner, cn } from "../components/ui";
import { formatUsd } from "../lib/format";

const PdfViewer = lazy(() => import("../preview/PdfViewer"));

/** Template and theme, saved a moment after the last change; the cached application then updates, and with it
 * the preview URL. */
function useDesign(application: ApplicationDetail) {
  const queryClient = useQueryClient();
  const [design, setDesign] = useState({ template: application.template, theme: application.theme });
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // Fit to page and its undo change the design on the server: follow them
  useEffect(() => setDesign({ template: application.template, theme: application.theme }), [application.template, application.theme]);
  const change = (template: string, theme: Theme) => {
    setDesign({ template, theme });
    setError(null);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api("PUT", `/api/applications/${application.id}/design`, { json: { template, theme } })
        .then(() => queryClient.setQueryData<ApplicationDetail>(["application", application.id], (old) => (old ? { ...old, template, theme } : old)))
        .catch((e: unknown) => {
          const detail = e instanceof ApiError ? e.errors[0]?.message ?? e.message : errorMessage(e);
          setError(detail.replace(/^Value error, /, ""));
        });
    }, 400);
  };
  return { design, change, error };
}

export function DesignDisclosure({ application }: { application: ApplicationDetail }) {
  const { design, change, error } = useDesign(application);
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold text-slate-900 dark:text-slate-100">
        Design <span className="flex items-center gap-2 font-normal text-slate-500">{design.template[0]!.toUpperCase() + design.template.slice(1)}
          <span className="inline-block size-3 rounded-full" style={{ backgroundColor: design.theme.accent }} />
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden /></span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-4 py-4 dark:border-slate-800">
          <DesignPanel template={design.template} theme={design.theme} error={error} onChange={change} />
        </div>
      )}
    </div>
  );
}

export function pageNote(pages: number, limit: unknown, theme: Theme): { ok: boolean; text: string } {
  const label = `${pages} ${pages === 1 ? "page" : "pages"}`;
  if (typeof limit !== "number") return { ok: true, text: label };
  if (pages <= limit) return { ok: true, text: `${label} · fits the ${limit}-page target` };
  const tries = [theme.density !== "compact" && "Compact density", theme.margins !== "narrow" && "Narrow margins"].filter(Boolean);
  const hint = tries.length ? `Try ${tries.join(" or ")}.` : "Remove less relevant bullets, or allow a longer résumé.";
  return { ok: false, text: `${label} · over the ${limit}-page target. ${hint}` };
}

/** The document as a PDF, re-rendered whenever `revision` changes (after each save) or the design changes. With
 * `onFit`, a document over its page target offers to fit itself. */
export function PdfPreview({ application, doc, revision, pageLimit, onFit, fitting, fitDisabled }: {
  application: ApplicationDetail; doc: "resume" | "cover-letter"; revision: number; pageLimit: unknown;
  onFit?: () => void; fitting?: boolean; fitDisabled?: boolean;
}) {
  const [pages, setPages] = useState<number | null>(null);
  const design = `${application.template}:${JSON.stringify(application.theme)}`;
  const url = `/api/applications/${application.id}/preview.pdf?doc=${doc}&d=${encodeURIComponent(design)}&r=${revision}`;
  const note = pages !== null ? pageNote(pages, pageLimit, application.theme) : null;
  const target = typeof pageLimit === "number" ? pageLimit : null;
  return (
    <div className="rounded-xl bg-slate-200/60 p-3 dark:bg-slate-800/60">
      <div className="mb-2 flex min-h-5 items-start justify-between gap-2">
        <p className={cn("text-xs", note && !note.ok ? "text-amber-700 dark:text-amber-400" : "text-slate-500")} aria-live="polite">
          {note ? note.text : "Rendering…"}
        </p>
        {onFit && note && !note.ok && target !== null && (
          <Button size="sm" variant="secondary" className="shrink-0" icon={<Minimize2 className="size-3.5" aria-hidden />}
            loading={fitting} disabled={fitDisabled} onClick={onFit}>
            Fit to {target} {target === 1 ? "page" : "pages"}
          </Button>
        )}
      </div>
      <Suspense fallback={<Spinner />}>
        <PdfViewer url={url} onLoad={setPages} />
      </Suspense>
      <p className="mt-2 text-xs text-slate-500">This is the PDF exactly as it downloads.</p>
    </div>
  );
}


/** Fit to page (TPL-4) and its one-step undo. `apply` puts the server's document into the editor. */
export function useFit<T>(application: ApplicationDetail, kind: "resume" | "cover-letter", apply: (document: T) => void) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<FitResult | null>(null);
  const [busy, setBusy] = useState<"fit" | "undo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const field = kind === "resume" ? "resume" : "coverLetter";
  const sync = (template: string, theme: Theme, document: unknown) =>
    queryClient.setQueryData<ApplicationDetail>(["application", application.id], (old) =>
      old ? { ...old, template, theme, [field]: document } : old);
  const run = async (what: "fit" | "undo", action: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };
  const fit = () => run("fit", async () => {
    const out = await api<FitResult>("POST", `/api/applications/${application.id}/${kind}/fit`, kind === "resume" ? { json: {} } : {});
    setResult(out);
    if (out.changes.length) {
      apply(out.document as unknown as T);
      sync(out.template, out.theme, out.document);
    }
  });
  const undo = () => run("undo", async () => {
    if (!result?.revisionId) return;
    const out = await api<RestoreResult>("POST", `/api/applications/${application.id}/revisions/${result.revisionId}/restore`);
    apply(out.document as unknown as T);
    sync(out.template, out.theme, out.document);
    setResult(null);
  });
  return { result, busy, error, fit, undo, dismiss: () => { setResult(null); setError(null); } };
}

/** What fit to page did, with Undo; or why it couldn't, or that there's room for more. */
export function FitBanner({ fit, onAddMore }: { fit: ReturnType<typeof useFit<unknown>>; onAddMore?: () => void }) {
  const { result, error, busy } = fit;
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!result) return null;
  const pages = `${result.pages} ${result.pages === 1 ? "page" : "pages"}`;
  if (!result.changes.length) {
    if (result.fits && result.room && onAddMore) {
      return (
        <Alert tone="info" title="It fits, with room to spare">
          <p>The last page is less than 60% full.</p>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => { fit.dismiss(); onAddMore(); }}>Add from master</Button>
            <Button size="sm" variant="ghost" onClick={fit.dismiss}>Dismiss</Button>
          </div>
        </Alert>
      );
    }
    if (result.fits) return null;
    return (
      <Alert tone="warning" title={`Still ${pages}`}>
        <p>It can't fit without cutting more than fit to page will: it never removes pinned, edited or your own bullets, or
          takes a recent role below its minimum. Remove something yourself, or allow a longer résumé.</p>
        <Button className="mt-2" size="sm" variant="ghost" onClick={fit.dismiss}>Dismiss</Button>
      </Alert>
    );
  }
  return (
    <Alert tone={result.fits ? "success" : "warning"} title={result.fits ? `Fitted to ${pages}` : `Shortened, but still ${pages}`}>
      <p className="flex items-center gap-1.5"><Wand2 className="size-3.5" aria-hidden />{result.changes.join(" · ")}
        {result.costUsd > 0 && <span className="text-xs opacity-80">({formatUsd(result.costUsd)})</span>}</p>
      {result.removed.length > 0 && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer">Left out</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">{result.removed.map((text) => <li key={text}>{text}</li>)}</ul>
        </details>
      )}
      <div className="mt-2 flex gap-2">
        <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" aria-hidden />} loading={busy === "undo"} onClick={() => void fit.undo()}>Undo</Button>
        <Button size="sm" variant="ghost" onClick={fit.dismiss}>Keep</Button>
      </div>
    </Alert>
  );
}
