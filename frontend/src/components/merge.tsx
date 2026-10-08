/** Merging an import into an existing master (IMP-6): what's new, what it adds to items already there, and
 * what's already in the master. Nothing is added until it's picked; nothing already there changes. */

import { GitMerge } from "lucide-react";
import { useMemo, useState } from "react";

import type { MergeItem, MergePlan } from "../api/types";
import { Badge, Button, Card, CardBody, CardHeader, cn } from "./ui";

const SECTION_LABELS: Record<string, string> = {
  work: "Experience", projects: "Projects", education: "Education", certifications: "Certifications", awards: "Awards",
  publications: "Publications", volunteer: "Volunteering", languages: "Languages", customSections: "Other sections",
  skills: "Skills", headlines: "Headlines", summaries: "Summaries",
};

export type Selections = Record<string, number[] | null>;

/** What's picked to start with: every new item, and every new bullet that isn't much like one already there. */
export function initialSelections(items: MergeItem[]): Selections {
  const picks: Selections = {};
  for (const item of items) {
    if (item.status === "new") picks[item.key] = null;
    if (item.status === "match") {
      const indexes = item.bullets.map((_, i) => i).filter((i) => !(item.similarTo ?? [])[i]);
      if (indexes.length) picks[item.key] = indexes;
    }
  }
  return picks;
}

export function MergeReview({ plan, masterLabel, busy, onMerge, onCancel }: {
  plan: MergePlan; masterLabel: string; busy: boolean; onMerge: (selections: Selections) => void; onCancel: () => void;
}) {
  const [picks, setPicks] = useState<Selections>(() => initialSelections(plan.items));
  const offered = plan.items.filter((i) => i.status !== "same");
  const same = plan.items.length - offered.length;
  const sections = useMemo(() => {
    const groups = new Map<string, MergeItem[]>();
    for (const item of offered) groups.set(item.section, [...(groups.get(item.section) ?? []), item]);
    return [...groups.entries()];
  }, [offered]);
  const itemCount = Object.entries(picks).filter(([key, v]) => v === null && plan.items.find((i) => i.key === key)?.status === "new").length;
  const bulletCount = Object.values(picks).reduce((n, v) => n + (v ? v.length : 0), 0);

  const toggleItem = (item: MergeItem, on: boolean) => setPicks(({ [item.key]: _, ...rest }) => (on ? { ...rest, [item.key]: null } : rest));
  const toggleBullet = (item: MergeItem, index: number, on: boolean) => setPicks((current) => {
    const now = new Set(current[item.key] ?? []);
    if (on) now.add(index);
    else now.delete(index);
    const { [item.key]: _, ...rest } = current;
    return now.size ? { ...rest, [item.key]: [...now].sort((a, b) => a - b) } : rest;
  });

  return (
    <Card>
      <CardHeader title={`Add to “${masterLabel}”`}
        description={`Pick what to add. Nothing already in it changes.${same ? ` ${same} item${same === 1 ? " is" : "s are"} already there and not shown.` : ""}`} />
      <CardBody className="space-y-5">
        {offered.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">Everything in this import is already in that master résumé.</p>}
        {sections.map(([section, items]) => (
          <section key={section}>
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 dark:text-slate-400 uppercase">{SECTION_LABELS[section] ?? section}</h3>
            <ul className="space-y-2">
              {items.map((item) => (
                <li key={item.key} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  {item.status === "new" ? (
                    <label className="flex cursor-pointer items-start gap-2 text-sm">
                      <input type="checkbox" className="mt-0.5 size-4" checked={picks[item.key] === null} onChange={(e) => toggleItem(item, e.target.checked)} />
                      <span className="min-w-0">
                        <span className="font-medium text-slate-900 dark:text-slate-100">{item.title || "(untitled)"}</span>
                        {item.detail && <span className="text-slate-500 dark:text-slate-400"> · {item.detail}</span>} <Badge tone="brand">New</Badge>
                        {item.bullets.length > 0 && (
                          <ul className="mt-1 list-disc pl-5 text-slate-600 dark:text-slate-400">{item.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
                        )}
                      </span>
                    </label>
                  ) : (
                    <div className="text-sm">
                      <p><span className="font-medium text-slate-900 dark:text-slate-100">{item.title}</span>
                        {item.detail && <span className="text-slate-500 dark:text-slate-400"> · {item.detail}</span>} <Badge>Already there</Badge></p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Bullets it doesn't have yet:</p>
                      <ul className="mt-1 space-y-1">
                        {item.bullets.map((bullet, i) => {
                          const similar = (item.similarTo ?? [])[i];
                          return (
                            <li key={bullet}>
                              <label className="flex cursor-pointer items-start gap-2">
                                <input type="checkbox" className="mt-0.5 size-4" checked={(picks[item.key] ?? []).includes(i)}
                                  onChange={(e) => toggleBullet(item, i, e.target.checked)} />
                                <span className={cn("min-w-0", similar && "text-slate-600 dark:text-slate-400")}>
                                  {bullet}
                                  {similar && <span className="mt-0.5 block text-xs text-amber-800 dark:text-amber-300">Much like one it has: “{similar}”</span>}
                                </span>
                              </label>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
        <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
          <Button icon={<GitMerge className="size-4" aria-hidden />} loading={busy} disabled={itemCount + bulletCount === 0} onClick={() => onMerge(picks)}>
            Add {itemCount} item{itemCount === 1 ? "" : "s"} and {bulletCount} bullet{bulletCount === 1 ? "" : "s"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <span className="text-xs text-slate-500 dark:text-slate-400">This saves a new version of the master résumé, with this file attached.</span>
        </div>
      </CardBody>
    </Card>
  );
}
