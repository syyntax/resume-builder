/**
 * The raw JSON tab of the master editor: Monaco with the master résumé JSON Schema for validation and
 * autocomplete. Loaded lazily (it's large), bundled locally (no CDN), with its workers served from 'self'.
 */

import "monaco-editor/features/register.all";

import { Editor, loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import { jsonDefaults } from "monaco-editor/languages/features/json/register";
import JsonWorker from "monaco-editor/language/json/json.worker?worker";
import { useEffect, useState } from "react";

self.MonacoEnvironment = {
  getWorker: (_id: string, label: string) => (label === "json" ? new JsonWorker() : new EditorWorker()),
};
loader.config({ monaco });

const SCHEMA_URI = "https://resume-tailor.local/schema/master-resume.schema.json";
let schemaLoaded: Promise<void> | null = null;

function loadSchema(): Promise<void> {
  schemaLoaded ??= fetch("/schema/master-resume.schema.json", { credentials: "same-origin" })
    .then((response) => (response.ok ? response.json() : null))
    .then((schema: unknown) => {
      jsonDefaults.setDiagnosticsOptions({
        validate: true,
        allowComments: false,
        enableSchemaRequest: false,
        schemaValidation: "error", // the server rejects these, so don't present them as mere warnings
        schemas: schema ? [{ uri: SCHEMA_URI, fileMatch: ["*"], schema }] : [],
      });
    })
    .catch(() => undefined);
  return schemaLoaded;
}

function useDarkMode(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const onChange = () => setDark(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return dark;
}

export default function JsonEditor({ value, onChange, height = "70vh" }: { value: string; onChange: (value: string) => void; height?: string }) {
  const dark = useDarkMode();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    void loadSchema().then(() => setReady(true));
  }, []);
  if (!ready) return <div style={{ height }} className="animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />;
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
      <Editor
        height={height}
        language="json"
        path="master-resume.json"
        value={value}
        theme={dark ? "vs-dark" : "vs"}
        onChange={(text) => onChange(text ?? "")}
        options={{
          minimap: { enabled: false },
          fontSize: 13,
          tabSize: 2,
          wordWrap: "on",
          scrollBeyondLastLine: false,
          automaticLayout: true,
          formatOnPaste: true,
        }}
      />
    </div>
  );
}
