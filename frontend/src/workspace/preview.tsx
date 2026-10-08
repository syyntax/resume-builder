/** The live PDF preview (TPL-1) and the design panel, shared by the résumé and cover letter tabs. */

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";

import { ApiError, api, errorMessage } from "../api/client";
import type { ApplicationDetail, Theme } from "../api/types";
import { DesignPanel } from "../components/design";
import { Spinner, cn } from "../components/ui";

const PdfViewer = lazy(() => import("../preview/PdfViewer"));

/** Template and theme, saved a moment after the last change; the cached application then updates, and with it
 * the preview URL. */
function useDesign(application: ApplicationDetail) {
  const queryClient = useQueryClient();
  const [design, setDesign] = useState({ template: application.template, theme: application.theme });
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
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

/** The document as a PDF, re-rendered whenever `revision` changes (after each save) or the design changes. */
export function PdfPreview({ application, doc, revision, pageLimit }: { application: ApplicationDetail; doc: "resume" | "cover-letter"; revision: number; pageLimit: unknown }) {
  const [pages, setPages] = useState<number | null>(null);
  const design = `${application.template}:${JSON.stringify(application.theme)}`;
  const url = `/api/applications/${application.id}/preview.pdf?doc=${doc}&d=${encodeURIComponent(design)}&r=${revision}`;
  const note = pages !== null ? pageNote(pages, pageLimit, application.theme) : null;
  return (
    <div className="rounded-xl bg-slate-200/60 p-3 dark:bg-slate-800/60">
      <p className={cn("mb-2 min-h-5 text-xs", note && !note.ok ? "text-amber-700 dark:text-amber-400" : "text-slate-500")} aria-live="polite">
        {note ? note.text : "Rendering…"}
      </p>
      <Suspense fallback={<Spinner />}>
        <PdfViewer url={url} onLoad={setPages} />
      </Suspense>
      <p className="mt-2 text-xs text-slate-500">This is the PDF exactly as it downloads.</p>
    </div>
  );
}
