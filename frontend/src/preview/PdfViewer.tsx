/**
 * Renders a PDF's pages to canvases with PDF.js (DESIGN.md §10.4, and the résumé preview in M4). Loaded
 * lazily. WebAssembly decoders stay off so the app's Content-Security-Policy needs no 'wasm-unsafe-eval'.
 */

import { GlobalWorkerOptions, type PDFDocumentProxy, getDocument } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

GlobalWorkerOptions.workerSrc = workerUrl;

function Page({ pdf, number, width }: { pdf: PDFDocumentProxy; number: number; width: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null;
    void pdf.getPage(number).then((page) => {
      if (cancelled || !canvas.current || width <= 0) return;
      const scale = width / page.getViewport({ scale: 1 }).width;
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      const element = canvas.current;
      element.width = Math.floor(viewport.width);
      element.height = Math.floor(viewport.height);
      element.style.width = `${Math.floor(viewport.width / ratio)}px`;
      element.style.height = `${Math.floor(viewport.height / ratio)}px`;
      task = page.render({ canvas: element, viewport });
      task.promise.catch(() => undefined); // cancelled renders reject; that's expected
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, number, width]);
  return <canvas ref={canvas} className="mx-auto block bg-white shadow-sm ring-1 ring-slate-200 dark:ring-slate-700" aria-label={`Page ${number}`} />;
}

export default function PdfViewer({ url }: { url: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof getDocument> | null = null;
    setPdf(null);
    setError(null);
    fetch(url, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.arrayBuffer();
      })
      .then((data) => {
        if (cancelled) return null;
        task = getDocument({ data: new Uint8Array(data), useWasm: false });
        return task.promise;
      })
      .then((doc) => {
        if (doc && !cancelled) setPdf(doc);
      })
      .catch(() => !cancelled && setError("The original document couldn't be displayed."));
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setWidth(Math.round(entry?.contentRect.width ?? 0)));
    });
    observer.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={container} className="space-y-4">
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : !pdf ? (
        <div className="aspect-[8.5/11] animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
      ) : (
        Array.from({ length: pdf.numPages }, (_, i) => <Page key={i} pdf={pdf} number={i + 1} width={width} />)
      )}
    </div>
  );
}
