import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Braces, ListTree, Redo2, Save, Undo2 } from "lucide-react";
import { type ReactNode, Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link, useBlocker, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { Issue, MasterDetail, MasterSave } from "../api/types";
import { Dialog } from "../components/Dialog";
import { IssueList } from "../components/masters";
import { Alert, Button, Spinner, cn } from "../components/ui";
import { MasterEditor } from "../editor/MasterEditor";
import { type Json, fromEditable, toEditable } from "../editor/doc";
import { useHistory, useUndoShortcuts } from "../editor/history";
import { mastersKey } from "./MastersPages";
import { NotFoundPage } from "./NotFoundPage";

const JsonEditor = lazy(() => import("../editor/JsonEditor"));

export function issuesMap(issues: Issue[]): Map<string, string> {
  return new Map(issues.map((issue) => [issue.path, issue.message]));
}

/** Editing a field clears the server error reported for it (edits are grouped by field path). */
export function withoutIssue(issues: Issue[], group: string | undefined): Issue[] {
  return group && issues.some((issue) => issue.path === group) ? issues.filter((issue) => issue.path !== group) : issues;
}

export function errorIssues(error: unknown): Issue[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  return error.errors.map((e) => ({ path: e.path ?? e.field ?? "(document)", message: e.message }));
}

/** Warn before leaving with unsaved changes: in-app navigation (a dialog) and closing the tab. */
export function UnsavedChangesGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty);
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);
  return (
    <Dialog open={blocker.state === "blocked"} tone="danger" title="Leave without saving?" confirmLabel="Leave"
      cancelLabel="Keep editing" description="Your changes haven't been saved." onClose={() => blocker.reset?.()}
      onConfirm={() => blocker.proceed?.()} />
  );
}

export function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}
      className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white")}>
      {icon}
      {children}
    </button>
  );
}

function EditorScreen({ master, onSaved }: { master: MasterDetail; onSaved: (saved: MasterSave) => void }) {
  const initial = useMemo(() => toEditable((master.content ?? {}) as Json), [master.content]);
  const history = useHistory<Json>(initial);
  const [baseline, setBaseline] = useState<Json>(initial); // the document as last loaded or saved
  const [tab, setTab] = useState<"form" | "json">("form");
  const [jsonText, setJsonText] = useState("");
  const [jsonBase, setJsonBase] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  useUndoShortcuts(history, tab === "form");

  const dirty = history.value !== baseline || (tab === "json" && jsonText !== jsonBase);
  const issueMap = useMemo(() => issuesMap(issues), [issues]);

  const showJson = () => {
    const text = `${JSON.stringify(fromEditable(history.value), null, 2)}\n`;
    setJsonText(text);
    setJsonBase(text);
    setJsonError(null);
    setTab("json");
  };

  const parseJson = (): Json | null => {
    try {
      const parsed = JSON.parse(jsonText) as Json;
      setJsonError(null);
      return parsed;
    } catch (error) {
      setJsonError(`This isn't valid JSON: ${(error as Error).message}`);
      return null;
    }
  };

  const showForm = () => {
    if (jsonText !== jsonBase) {
      const parsed = parseJson();
      if (parsed === null) return;
      history.set(() => toEditable(parsed));
    }
    setTab("form");
  };

  const save = async () => {
    let body: string;
    if (tab === "json") {
      const parsed = parseJson();
      if (parsed === null) return;
      body = JSON.stringify(parsed);
    } else {
      body = JSON.stringify(fromEditable(history.value));
    }
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await api<MasterSave>("PUT", `/api/master-resumes/${master.id}`, { body, headers: { "Content-Type": "application/json" } });
      setIssues([]);
      setBaseline(history.value);
      setJsonBase(jsonText);
      onSaved(saved);
    } catch (error) {
      const found = errorIssues(error);
      setIssues(found);
      setSaveError(found.length ? "Fix the problems listed below, then save again." : errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="sticky top-0 z-10 -mx-4 mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/95 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8 dark:border-slate-800 dark:bg-slate-950/95">
        <div role="tablist" aria-label="Editor view" className="inline-flex rounded-lg bg-slate-200/70 p-1 dark:bg-slate-800">
          <TabButton active={tab === "form"} onClick={showForm} icon={<ListTree className="size-4" aria-hidden />}>Form</TabButton>
          <TabButton active={tab === "json"} onClick={showJson} icon={<Braces className="size-4" aria-hidden />}>JSON</TabButton>
        </div>
        <div className="flex items-center gap-2">
          {tab === "form" && (
            <>
              <Button variant="ghost" size="sm" icon={<Undo2 className="size-4" aria-hidden />} disabled={!history.canUndo} onClick={history.undo} title="Undo (⌘Z)">
                <span className="sr-only">Undo</span>
              </Button>
              <Button variant="ghost" size="sm" icon={<Redo2 className="size-4" aria-hidden />} disabled={!history.canRedo} onClick={history.redo} title="Redo (⇧⌘Z)">
                <span className="sr-only">Redo</span>
              </Button>
            </>
          )}
          <span className="text-sm text-slate-500" aria-live="polite">{dirty ? "Unsaved changes" : "No changes"}</span>
          <Button size="sm" icon={<Save className="size-4" aria-hidden />} loading={saving} disabled={!dirty} onClick={() => void save()}>
            Save new version
          </Button>
        </div>
      </div>

      {jsonError && <Alert tone="error" className="mb-4">{jsonError}</Alert>}
      {saveError && <Alert tone="error" className="mb-4" title="Not saved">{saveError}</Alert>}
      {issues.length > 0 && <div className="mb-6"><IssueList issues={issues} tone="error" /></div>}

      {tab === "form" ? (
        <MasterEditor value={history.value} issues={issueMap} withNav onChange={(update, group) => {
          history.set(update, group);
          setIssues((current) => withoutIssue(current, group));
        }} />
      ) : (
        <Suspense fallback={<Spinner />}>
          <p className="mb-3 text-sm text-slate-500">
            Edit the raw JSON. It's checked against the master résumé schema as you type; hover a field for its description.
          </p>
          <JsonEditor value={jsonText} onChange={setJsonText} />
        </Suspense>
      )}
      <UnsavedChangesGuard dirty={dirty && !saving} />
    </>
  );
}

export function MasterEditPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["master", id], queryFn: () => api<MasterDetail>("GET", `/api/master-resumes/${id}`), retry: false });
  const [lastSave, setLastSave] = useState<MasterSave | null>(null);

  if (detail.isPending) return <Spinner />;
  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isError) return <Alert tone="error">{errorMessage(detail.error)}</Alert>;
  const master = detail.data;

  return (
    <>
      <Link to={`/masters/${id}`} className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> {master.label}
      </Link>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Edit master résumé</h1>
      <p className="mb-6 text-sm text-slate-500">
        Saving creates version {(master.currentVersion?.versionNumber ?? 0) + 1}. Earlier versions, and applications made from them, stay as they are.
      </p>
      {lastSave && (
        <Alert tone={lastSave.createdNewVersion ? "success" : "info"} className="mb-6"
          title={lastSave.createdNewVersion ? `Saved as version ${lastSave.version.versionNumber}` : "Nothing changed"}>
          {lastSave.createdNewVersion ? "Keep editing, or go back to the overview." : "The document matches the current version."}
        </Alert>
      )}
      <EditorScreen key={master.currentVersion?.id ?? "none"} master={master} onSaved={(saved) => {
        setLastSave(saved);
        void queryClient.invalidateQueries({ queryKey: ["master", id] });
        void queryClient.invalidateQueries({ queryKey: mastersKey });
      }} />
    </>
  );
}
