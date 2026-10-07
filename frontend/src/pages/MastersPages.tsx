import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Braces, Download, FileText, FileUp, Paperclip, Pencil, SquarePen, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { Master, MasterDetail, MasterDocument, MasterSave, SourceFile, Validation, VersionMeta } from "../api/types";
import { Dialog } from "../components/Dialog";
import { ImportStatusBadge, useImports } from "../components/imports";
import { IssueList, JsonDropZone, MasterOverview, SummaryStats } from "../components/masters";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  PageHeader,
  Spinner,
  TextField,
  linkButtonClass,
} from "../components/ui";
import { formatDateTime, timeAgo } from "../lib/format";
import { NotFoundPage } from "./NotFoundPage";

export const mastersKey = ["masters"] as const;

export function useMasters() {
  return useQuery({ queryKey: mastersKey, queryFn: () => api<Master[]>("GET", "/api/master-resumes") });
}

const sendJson = (text: string) => ({ body: text, headers: { "Content-Type": "application/json" } });

interface Picked {
  name: string;
  text: string;
  result: Validation;
}

/** Validate a picked file and show the outcome; `onSave` gets the raw text once it's valid. */
function UploadPanel({ onSave, saving, saveLabel, error }: { onSave: (picked: Picked, label: string) => void; saving: boolean; saveLabel: string; error: unknown }) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const [label, setLabel] = useState("");
  const validate = useMutation({
    mutationFn: async ({ name, text }: { name: string; text: string }) => ({
      name,
      text,
      result: await api<Validation>("POST", "/api/master-resumes/validate", sendJson(text)),
    }),
    onSuccess: (value) => {
      setPicked(value);
      setLabel(value.result.summary?.label ?? value.name.replace(/\.json$/i, ""));
    },
  });

  if (!picked) {
    return (
      <div className="space-y-3">
        <JsonDropZone busy={validate.isPending} onFile={(name, text) => validate.mutate({ name, text })} />
        {validate.isError && <Alert tone="error">{errorMessage(validate.error)}</Alert>}
      </div>
    );
  }

  const { result } = picked;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          <span className="font-medium text-slate-900 dark:text-slate-100">{picked.name}</span>{" "}
          {result.valid ? <Badge tone="green">Valid</Badge> : <Badge tone="red">Needs fixes</Badge>}
        </p>
        <Button variant="ghost" size="sm" onClick={() => setPicked(null)}>
          Choose a different file
        </Button>
      </div>
      {result.summary && <SummaryStats summary={result.summary} />}
      <IssueList issues={result.errors} tone="error" />
      <IssueList issues={result.warnings} tone="warning" />
      {!result.valid && (
        <p className="text-sm text-slate-500">Fix the problems in your file and choose it again. Paths like <code>work[1].startDate</code> point to the exact field.</p>
      )}
      {result.valid && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            onSave(picked, label);
          }}
        >
          <TextField className="min-w-60 flex-1" label="Name for this master résumé" value={label} maxLength={100}
            onChange={(e) => setLabel(e.target.value)} />
          <Button type="submit" loading={saving}>{saveLabel}</Button>
        </form>
      )}
      {error ? <Alert tone="error">{errorMessage(error)}</Alert> : null}
    </div>
  );
}

// ---- list ---------------------------------------------------------------------------------------------

export function MastersPage() {
  const masters = useMasters();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [uploading, setUploading] = useState(false);

  const create = useMutation({
    mutationFn: ({ text, label }: { text: string; label: string }) =>
      api<MasterSave>("POST", `/api/master-resumes?label=${encodeURIComponent(label.trim() || "Master résumé")}`, sendJson(text)),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: mastersKey });
      navigate(`/masters/${saved.master.id}`);
    },
  });

  const showUpload = uploading || (masters.data?.length ?? 0) === 0;
  return (
    <>
      <PageHeader
        title="Master résumés"
        description="Your complete career history. Applications are tailored from these."
        actions={
          <>
            <a href="/api/schema/master-resume/example" download="master-resume.example.json" className={linkButtonClass("ghost", "sm")}>
              <Download className="size-4" aria-hidden /> Example
            </a>
            <a href="/schema/master-resume.schema.json" target="_blank" rel="noreferrer" className={linkButtonClass("ghost", "sm")}>
              <Braces className="size-4" aria-hidden /> JSON Schema
            </a>
            {!showUpload && (
              <Button variant="secondary" size="sm" icon={<Upload className="size-4" aria-hidden />} onClick={() => setUploading(true)}>
                Upload JSON
              </Button>
            )}
            <Link to="/masters/import" className={linkButtonClass("primary", "sm")}>
              <FileUp className="size-4" aria-hidden /> Import PDF or Word
            </Link>
          </>
        }
      />

      {showUpload && (
        <Card className="mb-6">
          <CardHeader
            title="Upload a master résumé"
            description="We check it, fill in missing IDs, and keep every upload as a version."
            actions={masters.data?.length ? <Button variant="ghost" size="sm" onClick={() => setUploading(false)}>Cancel</Button> : undefined}
          />
          <CardBody>
            <UploadPanel saveLabel="Save master résumé" saving={create.isPending} error={create.error}
              onSave={(picked, label) => create.mutate({ text: picked.text, label })} />
            <p className="mt-4 text-sm text-slate-500">
              Don't have one in JSON? <Link to="/masters/import" className="font-medium text-brand-700 underline underline-offset-2 dark:text-brand-300">Import your PDF or Word résumé</Link> instead,
              or start from the example file.
            </p>
          </CardBody>
        </Card>
      )}

      <PendingImports />

      {masters.isPending ? (
        <Spinner />
      ) : masters.isError ? (
        <Alert tone="error">{errorMessage(masters.error)}</Alert>
      ) : masters.data.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {masters.data.map((m) => (
            <Link key={m.id} to={`/masters/${m.id}`}
              className="group rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-300 hover:shadow dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-700">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-900 group-hover:text-brand-700 dark:text-white dark:group-hover:text-brand-200">{m.label}</p>
                  <p className="truncate text-sm text-slate-500">{m.currentVersion?.summary.name}</p>
                </div>
                <Badge>v{m.currentVersion?.versionNumber ?? 0}</Badge>
              </div>
              {m.currentVersion && (
                <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
                  {m.currentVersion.summary.counts.work ?? 0} roles · {m.currentVersion.summary.counts.bullets ?? 0} bullets ·{" "}
                  {m.currentVersion.summary.counts.skills ?? 0} skills
                </p>
              )}
              <p className="mt-1 text-xs text-slate-500">Updated {timeAgo(m.updatedAt)}</p>
            </Link>
          ))}
        </div>
      ) : (
        !showUpload && (
          <Card>
            <EmptyState icon={<FileText className="size-6" aria-hidden />} title="No master résumés yet" />
          </Card>
        )
      )}
    </>
  );
}

function PendingImports() {
  const imports = useImports();
  const pending = (imports.data ?? []).filter((i) => i.status !== "accepted");
  if (!pending.length) return null;
  return (
    <Card className="mb-6">
      <CardHeader title="Imports" description="Résumés you've uploaded that aren't saved as master résumés yet." />
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {pending.map((i) => (
          <li key={i.id}>
            <Link to={`/imports/${i.id}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50">
              <span className="font-medium text-slate-900 dark:text-slate-100">{i.sourceName}</span>
              <span className="flex items-center gap-3 text-slate-500">
                {timeAgo(i.createdAt)} <ImportStatusBadge status={i.status} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function fileSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ---- detail -------------------------------------------------------------------------------------------

function ChangeSummary({ changes }: { changes: Record<string, unknown> }) {
  const count = (key: string) => (Array.isArray(changes[key]) ? (changes[key] as unknown[]).length : 0);
  const parts = [
    `${count("added")} added`,
    `${count("changed")} changed`,
    `${count("removed")} removed`,
    changes.basicsChanged ? "contact details changed" : null,
  ].filter(Boolean);
  return <>{parts.join(", ")}.</>;
}

export function MasterDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const detailKey = ["master", id] as const;
  const versionsKey = ["master", id, "versions"] as const;
  const detail = useQuery({ queryKey: detailKey, queryFn: () => api<MasterDetail>("GET", `/api/master-resumes/${id}`), retry: false });
  const versions = useQuery({ queryKey: versionsKey, queryFn: () => api<VersionMeta[]>("GET", `/api/master-resumes/${id}/versions`), enabled: detail.isSuccess });

  const [uploading, setUploading] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [lastSave, setLastSave] = useState<MasterSave | null>(null);
  const [deletingFile, setDeletingFile] = useState<{ versionId: string; file: SourceFile } | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["master", id] });
    void queryClient.invalidateQueries({ queryKey: mastersKey });
  };
  const upload = useMutation({
    mutationFn: (text: string) => api<MasterSave>("PUT", `/api/master-resumes/${id}`, sendJson(text)),
    onSuccess: (saved) => {
      setLastSave(saved);
      setUploading(false);
      refresh();
    },
  });
  const rename = useMutation({
    mutationFn: (label: string) => api<Master>("PATCH", `/api/master-resumes/${id}`, { json: { label } }),
    onSuccess: () => {
      setRenaming(null);
      refresh();
    },
  });
  const removeFile = useMutation({
    mutationFn: (versionId: string) => api<void>("DELETE", `/api/master-resumes/${id}/versions/${versionId}/source`),
    onSuccess: () => {
      setDeletingFile(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", `/api/master-resumes/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mastersKey });
      navigate("/masters", { replace: true });
    },
  });

  if (detail.isPending) return <Spinner />;
  if (detail.error instanceof ApiError && detail.error.status === 404) return <NotFoundPage />;
  if (detail.isError) return <Alert tone="error">{errorMessage(detail.error)}</Alert>;

  const master = detail.data;
  const current = master.currentVersion;
  return (
    <>
      <Link to="/masters" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft className="size-4" aria-hidden /> Master résumés
      </Link>
      <PageHeader
        title={master.label}
        description={current ? `Version ${current.versionNumber} · saved ${formatDateTime(current.createdAt)}` : undefined}
        actions={
          <>
            <Button variant="ghost" size="sm" icon={<Pencil className="size-4" aria-hidden />} onClick={() => setRenaming(master.label)}>
              Rename
            </Button>
            {current && (
              <a href={`/api/master-resumes/${id}/versions/${current.id}/normalized`} className={linkButtonClass("secondary", "sm")}>
                <Download className="size-4" aria-hidden /> Download JSON
              </a>
            )}
            <Button variant="secondary" size="sm" icon={<Upload className="size-4" aria-hidden />} onClick={() => setUploading(true)}>
              Upload JSON
            </Button>
            {current && (
              <Link to={`/masters/${id}/edit`} className={linkButtonClass("primary", "sm")}>
                <SquarePen className="size-4" aria-hidden /> Edit
              </Link>
            )}
          </>
        }
      />

      {lastSave && (
        <Alert tone={lastSave.createdNewVersion ? "success" : "info"} className="mb-6"
          title={lastSave.createdNewVersion ? `Saved as version ${lastSave.version.versionNumber}` : "No changes"}>
          {lastSave.createdNewVersion && lastSave.changes ? <ChangeSummary changes={lastSave.changes} /> : "That file matches the current version."}
        </Alert>
      )}

      {uploading && (
        <Card className="mb-6">
          <CardHeader title="Upload a new version" description="Earlier versions are kept, and applications keep using the version they were made from."
            actions={<Button variant="ghost" size="sm" onClick={() => setUploading(false)}>Cancel</Button>} />
          <CardBody>
            <UploadPanel saveLabel="Save new version" saving={upload.isPending} error={upload.error}
              onSave={(picked) => upload.mutate(picked.text)} />
          </CardBody>
        </Card>
      )}

      {current && (
        <div className="space-y-6">
          <SummaryStats summary={current.summary} />
          <IssueList issues={current.warnings} tone="warning" />
          <Card>
            <CardBody className="py-5">
              {master.content && <MasterOverview doc={master.content as unknown as MasterDocument} />}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Versions" description="Every upload is kept. Download any version." />
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {(versions.data ?? []).map((v) => (
                <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="font-medium text-slate-900 dark:text-slate-100">Version {v.versionNumber}</span>
                    {v.id === current.id && <Badge tone="brand">Current</Badge>}
                  </span>
                  <span className="text-slate-500">
                    {formatDateTime(v.createdAt)} · {v.summary.counts.bullets ?? 0} bullets
                  </span>
                  <span className="flex flex-wrap items-center gap-1">
                    {v.sourceFile && (
                      <>
                        <a href={`/api/master-resumes/${id}/versions/${v.id}/source`} className={linkButtonClass("ghost", "sm")}
                          title={`Imported from ${v.sourceFile.name} (${fileSize(v.sourceFile.size)})`}>
                          <Paperclip className="size-4" aria-hidden /> Original
                        </a>
                        <Button variant="ghost" size="sm" icon={<Trash2 className="size-4" aria-hidden />}
                          onClick={() => v.sourceFile && setDeletingFile({ versionId: v.id, file: v.sourceFile })}>
                          <span className="sr-only">Delete the original file</span>
                        </Button>
                      </>
                    )}
                    <a href={`/api/master-resumes/${id}/versions/${v.id}/normalized`} className={linkButtonClass("ghost", "sm")}>
                      <Download className="size-4" aria-hidden /> JSON
                    </a>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Delete this master résumé" description="Removes every version. This can't be undone."
              actions={<Button variant="danger" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setDeleting(true)}>Delete</Button>} />
          </Card>
        </div>
      )}

      <Dialog open={renaming !== null} title="Rename master résumé" confirmLabel="Save" busy={rename.isPending}
        confirmDisabled={!renaming?.trim()} onClose={() => setRenaming(null)} onConfirm={() => renaming && rename.mutate(renaming.trim())}>
        <TextField label="Name" value={renaming ?? ""} maxLength={100} autoFocus onChange={(e) => setRenaming(e.target.value)}
          error={rename.isError ? errorMessage(rename.error) : undefined} />
      </Dialog>
      <Dialog open={deletingFile !== null} tone="danger" title="Delete the original file?" confirmLabel="Delete file"
        busy={removeFile.isPending} onClose={() => setDeletingFile(null)} onConfirm={() => deletingFile && removeFile.mutate(deletingFile.versionId)}
        description={`${deletingFile?.file.name ?? "The file"} is deleted. The master résumé version made from it stays.`}>
        {removeFile.isError && <Alert tone="error">{errorMessage(removeFile.error)}</Alert>}
      </Dialog>
      <Dialog open={deleting} tone="danger" title={`Delete “${master.label}”?`} confirmLabel="Delete" busy={remove.isPending}
        description="All versions will be deleted. Download a copy first if you might need it." onClose={() => setDeleting(false)}
        onConfirm={() => remove.mutate()}>
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </>
  );
}
