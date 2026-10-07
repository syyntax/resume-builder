import { AlertTriangle, FileJson, Upload, XCircle } from "lucide-react";
import { type DragEvent, type ReactNode, useId, useRef, useState } from "react";

import type { Bullet, Issue, MasterDocument, MasterSummary } from "../api/types";
import { formatPartialDate } from "../lib/format";
import { Badge, Button, cn } from "./ui";

export const MAX_MASTER_BYTES = 1_048_576;

// ---- file picker ----------------------------------------------------------------------------------

export function JsonDropZone({ onFile, busy, label = "Drop a master résumé JSON file here" }: { onFile: (name: string, text: string) => void; busy?: boolean; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const inputId = useId();

  async function accept(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    if (file.size > MAX_MASTER_BYTES) {
      setProblem("That file is larger than 1 MB.");
      return;
    }
    onFile(file.name, await file.text());
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void accept(e.dataTransfer.files[0]);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
        dragging
          ? "border-brand-400 bg-brand-50 dark:border-brand-500 dark:bg-brand-900/30"
          : "border-slate-300 dark:border-slate-700",
      )}
    >
      <FileJson className="mb-3 size-8 text-slate-400" aria-hidden />
      <p className="font-medium text-slate-800 dark:text-slate-200">{label}</p>
      <p className="mt-1 text-sm text-slate-500">JSON Resume files work too. Up to 1 MB.</p>
      <input
        id={inputId}
        ref={input}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        onChange={(e) => {
          void accept(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <Button className="mt-4" variant="secondary" icon={<Upload className="size-4" aria-hidden />} loading={busy}
        onClick={() => input.current?.click()}>
        Choose file
      </Button>
      {problem && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{problem}</p>}
    </div>
  );
}

// ---- validation output -------------------------------------------------------------------------------

export function IssueList({ issues, tone }: { issues: Issue[]; tone: "error" | "warning" }) {
  if (issues.length === 0) return null;
  const Icon = tone === "error" ? XCircle : AlertTriangle;
  return (
    <div
      className={cn(
        "rounded-lg border",
        tone === "error"
          ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
          : "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
      )}
    >
      <p className={cn("flex items-center gap-2 px-4 pt-3 text-sm font-medium",
        tone === "error" ? "text-red-800 dark:text-red-200" : "text-amber-900 dark:text-amber-200")}>
        <Icon className="size-4" aria-hidden />
        {issues.length} {tone === "error" ? (issues.length === 1 ? "problem" : "problems") : issues.length === 1 ? "warning" : "warnings"}
      </p>
      <ul className="max-h-72 divide-y divide-black/5 overflow-auto px-4 py-2 text-sm dark:divide-white/10">
        {issues.map((issue, i) => (
          <li key={`${issue.path}-${i}`} className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:gap-3">
            <code className="shrink-0 font-mono text-xs text-slate-600 sm:w-56 sm:truncate dark:text-slate-400" title={issue.path}>
              {issue.path}
            </code>
            <span className="text-slate-800 dark:text-slate-200">{issue.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const countLabels: [keyof MasterSummary["counts"], string][] = [
  ["work", "Roles"],
  ["bullets", "Bullets"],
  ["projects", "Projects"],
  ["skills", "Skills"],
  ["education", "Education"],
  ["certifications", "Certifications"],
];

export function SummaryStats({ summary }: { summary: MasterSummary }) {
  return (
    <dl className="grid grid-cols-3 gap-3 lg:grid-cols-6">
      {countLabels.map(([key, label]) => (
        <div key={key} className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
          <dt className="text-xs text-slate-500">{label}</dt>
          <dd className="text-lg font-semibold tabular-nums text-slate-900 dark:text-white">{summary.counts[key] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---- read-only overview of a normalized master -------------------------------------------------------

function BulletList({ bullets }: { bullets?: Bullet[] }) {
  if (!bullets?.length) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {bullets.map((b) => (
        <li key={b.id} className={cn("flex gap-2 text-sm", b.hidden && "opacity-50")}>
          <span className="mt-2 size-1.5 shrink-0 rounded-sm bg-brand-500" aria-hidden />
          <span className="min-w-0 flex-1 text-slate-700 dark:text-slate-300">
            {b.text}
            <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
              <code className="rounded bg-slate-100 px-1 text-[11px] text-slate-500 dark:bg-slate-800">{b.id}</code>
              {b.pin && <Badge tone="brand">pinned</Badge>}
              {b.hidden && <Badge>hidden</Badge>}
              {b.variants?.length ? <Badge>{b.variants.length} variant{b.variants.length > 1 ? "s" : ""}</Badge> : null}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-slate-200 pt-5 dark:border-slate-800">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-slate-500 uppercase">{title}</h3>
      {children}
    </section>
  );
}

export function MasterOverview({ doc }: { doc: MasterDocument }) {
  const b = doc.basics;
  const location = [b.location?.city, b.location?.region].filter(Boolean).join(", ");
  const contact = [b.email, b.phone, location, b.location?.remote ? "Remote" : null, ...(b.profiles ?? []).map((p) => p.url)]
    .filter(Boolean)
    .join(" · ");
  const skillGroups = new Map<string, string[]>();
  for (const skill of doc.skills ?? []) {
    const key = skill.category ?? "Other";
    skillGroups.set(key, [...(skillGroups.get(key) ?? []), skill.name]);
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xl font-semibold text-slate-900 dark:text-white">{b.name}</p>
        {contact && <p className="mt-1 text-sm text-slate-500">{contact}</p>}
      </div>

      {(doc.headlines?.length || doc.summaries?.length) ? (
        <Section title="Headlines & summaries">
          <div className="flex flex-wrap gap-2">
            {doc.headlines?.map((h) => <Badge key={h.id} tone="brand">{h.text}</Badge>)}
          </div>
          <div className="mt-3 space-y-3">
            {doc.summaries?.map((s) => (
              <p key={s.id} className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                {s.text} <code className="rounded bg-slate-100 px-1 text-[11px] text-slate-500 dark:bg-slate-800">{s.id}</code>
              </p>
            ))}
          </div>
        </Section>
      ) : null}

      {doc.work?.length ? (
        <Section title="Experience">
          <div className="space-y-5">
            {doc.work.map((w) => (
              <div key={w.id}>
                <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                  <p className="font-medium text-slate-900 dark:text-slate-100">
                    {w.position} <span className="font-normal text-slate-500">· {w.company}</span>
                  </p>
                  <p className="text-sm tabular-nums text-slate-500">
                    {w.startDate ? `${formatPartialDate(w.startDate)} – ${formatPartialDate(w.endDate)}` : "No dates"}
                  </p>
                </div>
                <BulletList bullets={w.highlights} />
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {doc.projects?.length ? (
        <Section title="Projects">
          <div className="space-y-4">
            {doc.projects.map((p) => (
              <div key={p.id}>
                <p className="font-medium text-slate-900 dark:text-slate-100">
                  {p.name} {p.description && <span className="font-normal text-slate-500">· {p.description}</span>}
                </p>
                <BulletList bullets={p.highlights} />
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      {skillGroups.size ? (
        <Section title="Skills">
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[12rem_1fr]">
            {[...skillGroups].map(([group, names]) => (
              <div key={group} className="contents">
                <dt className="font-medium text-slate-700 dark:text-slate-300">{group}</dt>
                <dd className="text-slate-600 dark:text-slate-400">{names.join(", ")}</dd>
              </div>
            ))}
          </dl>
        </Section>
      ) : null}

      {(doc.education?.length || doc.certifications?.length) ? (
        <Section title="Education & certifications">
          <ul className="space-y-1 text-sm text-slate-700 dark:text-slate-300">
            {doc.education?.map((e) => (
              <li key={e.id}>{[e.studyType, e.area].filter(Boolean).join(" ")} · {e.institution}</li>
            ))}
            {doc.certifications?.map((c) => (
              <li key={c.id}>{c.name}{c.issuer ? ` · ${c.issuer}` : ""}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      {doc.customSections?.map((section) => (
        <Section key={section.id} title={section.title}>
          <ul className="space-y-1 text-sm text-slate-700 dark:text-slate-300">
            {section.items?.map((item) => (
              <li key={item.id}>{item.title}{item.subtitle ? ` · ${item.subtitle}` : ""}</li>
            ))}
          </ul>
        </Section>
      ))}
    </div>
  );
}
