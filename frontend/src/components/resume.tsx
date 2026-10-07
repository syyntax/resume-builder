import { AlertTriangle, Check, CircleDashed, X } from "lucide-react";
import type { ReactNode } from "react";

import type { JobAnalysis, ResumeBullet, ResumeItem, ResumeSection, TailoredResume } from "../api/types";
import { formatPartialDate } from "../lib/format";
import { Badge, cn } from "./ui";

const str = (value: unknown): string => (typeof value === "string" ? value : "");

function dates(item: ResumeItem): string {
  const start = str(item.startDate);
  if (!start) return item.endDate ? formatPartialDate(str(item.endDate)) : str(item.date) ? formatPartialDate(str(item.date)) : "";
  return `${formatPartialDate(start)} – ${formatPartialDate(item.endDate ? str(item.endDate) : null)}`;
}

function Bullet({ bullet }: { bullet: ResumeBullet }) {
  const flagged = bullet.warnings.length > 0;
  return (
    <li className="relative pl-3.5">
      <span className="absolute top-[0.6em] left-0 size-1.5 rounded-[1px] bg-[#1F3A5F]" aria-hidden />
      <span className={cn(flagged && "rounded bg-amber-100/70 decoration-amber-500")}>{bullet.text}</span>
      {flagged && (
        <span className="ml-1.5 inline-flex align-middle" title={bullet.warnings.map((w) => w.message).join("\n")}>
          <AlertTriangle className="size-3.5 text-amber-600" aria-label={bullet.warnings.map((w) => w.message).join(" ")} />
        </span>
      )}
    </li>
  );
}

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="mt-5 mb-2 flex items-center gap-3 text-[11px] font-bold tracking-[0.16em] text-[#1F3A5F] uppercase">
      {children}
      <span className="h-px flex-1 bg-slate-200" />
    </h3>
  );
}

function Section({ section }: { section: ResumeSection }) {
  if (section.type === "skills") {
    return (
      <section>
        <SectionHeading>{section.title}</SectionHeading>
        <dl className="grid grid-cols-[9rem_1fr] gap-x-4 gap-y-1">
          {section.groups?.map((g) => (
            <div key={g.name} className="contents">
              <dt className="font-semibold text-slate-900">{g.name}</dt>
              <dd>{g.items.map((i) => i.display).join(", ")}</dd>
            </div>
          ))}
        </dl>
      </section>
    );
  }
  return (
    <section>
      <SectionHeading>{section.title}</SectionHeading>
      <div className="space-y-3">
        {section.items?.map((item) => {
          const title = str(item.position) || str(item.name) || str(item.title) || str(item.language)
            || [str(item.studyType), str(item.area)].filter(Boolean).join(" ") || str(item.institution);
          const org = str(item.company) || str(item.issuer) || (title !== str(item.institution) ? str(item.institution) : "")
            || str(item.organization) || str(item.subtitle) || str(item.fluency) || str(item.description);
          return (
            <div key={item.sourceId}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                <p className="font-semibold text-slate-900">
                  {title}
                  {org && <span className="font-medium text-[#1F3A5F]"> · {org}</span>}
                </p>
                <span className="text-xs text-slate-500 tabular-nums">{dates(item)}</span>
              </div>
              {item.bullets && item.bullets.length > 0 && (
                <ul className="mt-1 space-y-0.5">{item.bullets.map((b) => <Bullet key={b.id} bullet={b} />)}</ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** A document-style preview of a TailoredResume. The final PDF templates arrive in a later milestone. */
export function ResumePreview({ resume }: { resume: TailoredResume }) {
  const b = resume.basics;
  const place = [b.location?.city, b.location?.region].filter(Boolean).join(", ");
  const contact = [b.email, b.phone, place, ...(b.profiles ?? []).map((p) => p.url?.replace(/^https?:\/\//, ""))].filter(Boolean);
  return (
    <article className="rounded-lg bg-white px-8 py-8 text-[13px] leading-relaxed text-slate-800 shadow-sm ring-1 ring-slate-200 sm:px-10 dark:ring-slate-700">
      <div className="-mx-8 -mt-8 mb-6 h-1.5 rounded-t-lg bg-[#1F3A5F] sm:-mx-10" aria-hidden />
      <h2 className="text-[26px] leading-tight font-bold tracking-tight text-[#1F3A5F]">{b.name}</h2>
      <p className="mt-0.5 text-[15px] font-medium text-slate-600">{resume.headline.text}</p>
      <p className="mt-2 text-xs text-slate-600">{contact.join("  ·  ")}</p>
      {resume.summary.text && (
        <section>
          <SectionHeading>Summary</SectionHeading>
          <p>{resume.summary.text}</p>
        </section>
      )}
      {resume.sections.map((section, i) => <Section key={`${section.type}-${i}`} section={section} />)}
    </article>
  );
}

// ---- analysis ----------------------------------------------------------------------------------------

const statusIcon = {
  met: <Check className="size-4 text-emerald-600" aria-label="Met" />,
  partial: <CircleDashed className="size-4 text-amber-600" aria-label="Partly met" />,
  missing: <X className="size-4 text-red-600" aria-label="Missing" />,
};

export function AnalysisPanel({ analysis, coverage }: { analysis: JobAnalysis; coverage?: TailoredResume["analysis"]["coverage"] }) {
  const matches = new Map(analysis.match.map((m) => [m.requirementId, m]));
  const matched = new Set(coverage?.matched ?? []);
  const gaps = new Set(coverage?.gaps ?? []);
  return (
    <div className="space-y-5 text-sm">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={analysis.fit.rating === "strong" ? "green" : analysis.fit.rating === "moderate" ? "amber" : "red"}>
            {analysis.fit.rating === "strong" ? "Strong fit" : analysis.fit.rating === "moderate" ? "Moderate fit" : "Weak fit"}
          </Badge>
          {analysis.seniority !== "unknown" && <Badge>{analysis.seniority}</Badge>}
          {analysis.location && <Badge>{analysis.location}</Badge>}
        </div>
        <p className="mt-2 text-slate-700 dark:text-slate-300">{analysis.roleSummary}</p>
        <p className="mt-2 text-slate-500">{analysis.fit.rationale}</p>
      </div>
      <div>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-slate-500 uppercase">Requirements</h3>
        <ul className="space-y-1.5">
          {analysis.requirements.map((r) => {
            const m = matches.get(r.id);
            return (
              <li key={r.id} className="flex gap-2">
                <span className="mt-0.5 shrink-0">{m ? statusIcon[m.status] : null}</span>
                <span className="min-w-0">
                  <span className="text-slate-800 dark:text-slate-200">{r.text}</span>
                  {r.kind === "preferred" && <span className="ml-1.5 text-xs text-slate-500">(preferred)</span>}
                  {m?.note && <span className="block text-xs text-slate-500">{m.note}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
      <div>
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-slate-500 uppercase">Keywords</h3>
        <div className="flex flex-wrap gap-1.5">
          {[...analysis.keywords].sort((a, b) => b.importance - a.importance).map((k) => (
            <span key={k.term} title={k.aliases.length ? `Also: ${k.aliases.join(", ")}` : undefined}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
                matched.has(k.term) ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                  : gaps.has(k.term) ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  : coverage ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300"
                  : "border-slate-200 text-slate-700 dark:border-slate-700 dark:text-slate-300",
                k.importance === 3 && "font-semibold",
              )}>
              {matched.has(k.term) ? <Check className="size-3" aria-hidden /> : gaps.has(k.term) ? <X className="size-3" aria-hidden /> : null}
              {k.term}
            </span>
          ))}
        </div>
        {coverage && (
          <p className="mt-2 text-xs text-slate-500">
            <span className="text-emerald-700 dark:text-emerald-400">Green</span>: on the résumé.{" "}
            <span className="text-amber-700 dark:text-amber-400">Amber</span>: in your master résumé but not used.{" "}
            <span className="text-red-700 dark:text-red-400">Red</span>: not in your master résumé (a gap, so it isn't claimed).
          </p>
        )}
      </div>
    </div>
  );
}
