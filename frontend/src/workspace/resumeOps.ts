/**
 * Pure operations on a tailored résumé, for the workspace editor. The server re-checks everything on save
 * (facts from the master, sources, warnings), so these only need to produce a sensible document.
 */

import type { JobAnalysis, RefineResult, ResumeBullet, ResumeItem, ResumeSection, TailoredResume } from "../api/types";
import { move } from "./shared";

type Json = Record<string, unknown>;

/** Section type → the master résumé section its items come from. */
export const SECTION_SOURCE: Record<string, string> = {
  experience: "work", "earlier-experience": "work", projects: "projects", education: "education",
  certifications: "certifications", awards: "awards", publications: "publications", volunteer: "volunteer",
  languages: "languages",
};
export const SECTION_TITLES: Record<string, string> = {
  experience: "Experience", "earlier-experience": "Earlier Experience", projects: "Projects", skills: "Skills",
  education: "Education", certifications: "Certifications", awards: "Awards", publications: "Publications",
  volunteer: "Volunteering", languages: "Languages",
};
export const WITH_BULLETS = new Set(["experience", "projects"]);
const NOT_FACTS = new Set(["id", "highlights", "tags", "priority", "pin", "hidden", "skills", "variants"]);

// ---- the master, indexed --------------------------------------------------------------------------------------

export interface MasterBullet {
  id: string;
  text: string;
  itemId: string;
  hidden: boolean;
}

export interface MasterIndex {
  items: Map<string, { section: string; item: Json }>;
  bullets: Map<string, MasterBullet>;
  bulletsOf: Map<string, MasterBullet[]>;
  skills: Map<string, Json>;
}

export function indexMaster(master: Json): MasterIndex {
  const index: MasterIndex = { items: new Map(), bullets: new Map(), bulletsOf: new Map(), skills: new Map() };
  for (const section of ["work", "projects", "education", "certifications", "awards", "publications", "volunteer", "languages"]) {
    for (const item of (master[section] as Json[] | undefined) ?? []) {
      const id = String(item.id);
      if (item.hidden) continue;
      index.items.set(id, { section, item });
      const list: MasterBullet[] = [];
      for (const h of (item.highlights as Json[] | undefined) ?? []) {
        if (typeof h !== "object" || h === null || typeof h.id !== "string") continue;
        const bullet = { id: h.id, text: String(h.text ?? ""), itemId: id, hidden: Boolean(h.hidden) };
        index.bullets.set(h.id, bullet);
        if (!bullet.hidden) list.push(bullet);
      }
      index.bulletsOf.set(id, list);
    }
  }
  for (const skill of (master.skills as Json[] | undefined) ?? []) if (!skill.hidden) index.skills.set(String(skill.id), skill);
  return index;
}

export function sourceTexts(index: MasterIndex, ids: string[]): string[] {
  return ids.flatMap((id) => {
    const bullet = index.bullets.get(id);
    if (bullet) return [bullet.text];
    const item = index.items.get(id)?.item;
    return item ? [String(item.position ?? item.name ?? item.title ?? item.institution ?? id)] : [];
  });
}

// ---- small immutable helpers --------------------------------------------------------------------------------------

function edit(doc: TailoredResume, change: (draft: TailoredResume) => void): TailoredResume {
  const draft = structuredClone(doc);
  change(draft);
  return draft;
}

function findBullet(doc: TailoredResume, bulletId: string): { item: ResumeItem; index: number } | null {
  for (const section of doc.sections) {
    for (const item of section.items ?? []) {
      const index = (item.bullets ?? []).findIndex((b) => b.id === bulletId);
      if (index !== -1) return { item, index };
    }
  }
  return null;
}

function findItem(doc: TailoredResume, sourceId: string): ResumeItem | null {
  for (const section of doc.sections) for (const item of section.items ?? []) if (item.sourceId === sourceId) return item;
  return null;
}

export const newBulletId = () => `ub-${Math.random().toString(36).slice(2, 8)}`;

// ---- bullets ---------------------------------------------------------------------------------------------------------

export function setBullet(doc: TailoredResume, bulletId: string, patch: Partial<ResumeBullet>): TailoredResume {
  return edit(doc, (d) => {
    const found = findBullet(d, bulletId);
    if (found) Object.assign(found.item.bullets![found.index]!, patch);
  });
}

export function removeBullet(doc: TailoredResume, bulletId: string): TailoredResume {
  return edit(doc, (d) => {
    const found = findBullet(d, bulletId);
    if (found) found.item.bullets!.splice(found.index, 1);
  });
}

export function moveBullet(doc: TailoredResume, itemId: string, from: number, to: number): TailoredResume {
  return edit(doc, (d) => {
    const item = findItem(d, itemId);
    if (item?.bullets) item.bullets = move(item.bullets, from, to);
  });
}

export function addBullet(doc: TailoredResume, itemId: string, bullet: ResumeBullet): TailoredResume {
  return edit(doc, (d) => {
    const item = findItem(d, itemId);
    if (item) item.bullets = [...(item.bullets ?? []), bullet];
  });
}

export function setItemBullets(doc: TailoredResume, itemId: string, bullets: ResumeBullet[]): TailoredResume {
  return edit(doc, (d) => {
    const item = findItem(d, itemId);
    if (item) item.bullets = bullets;
  });
}

export function setBlock(doc: TailoredResume, key: "headline" | "summary", patch: Partial<TailoredResume["headline"]>): TailoredResume {
  return { ...doc, [key]: { ...doc[key], ...patch } };
}

// ---- items and sections ------------------------------------------------------------------------------------------------

export function removeItem(doc: TailoredResume, sectionIndex: number, itemIndex: number): TailoredResume {
  return edit(doc, (d) => {
    d.sections[sectionIndex]!.items!.splice(itemIndex, 1);
    if (!d.sections[sectionIndex]!.items!.length) d.sections.splice(sectionIndex, 1);
  });
}

export function moveItem(doc: TailoredResume, sectionIndex: number, from: number, to: number): TailoredResume {
  return edit(doc, (d) => {
    const section = d.sections[sectionIndex]!;
    section.items = move(section.items ?? [], from, to);
  });
}

export function moveSection(doc: TailoredResume, from: number, to: number): TailoredResume {
  return { ...doc, sections: move(doc.sections, from, to) };
}

export function removeSection(doc: TailoredResume, index: number): TailoredResume {
  return { ...doc, sections: doc.sections.filter((_, i) => i !== index) };
}

export function renameSection(doc: TailoredResume, index: number, title: string): TailoredResume {
  return edit(doc, (d) => { d.sections[index]!.title = title; });
}

export function removeSkill(doc: TailoredResume, sectionIndex: number, groupIndex: number, skillId: string): TailoredResume {
  return edit(doc, (d) => {
    const groups = d.sections[sectionIndex]!.groups!;
    groups[groupIndex]!.items = groups[groupIndex]!.items.filter((s) => s.skillId !== skillId);
    d.sections[sectionIndex]!.groups = groups.filter((g) => g.items.length);
    if (!d.sections[sectionIndex]!.groups!.length) d.sections.splice(sectionIndex, 1);
  });
}

function factsOf(item: Json): Json {
  return Object.fromEntries(Object.entries(item).filter(([k]) => !NOT_FACTS.has(k)));
}

// ---- add from master (EDT-3) --------------------------------------------------------------------------------------------

export interface Candidate {
  key: string;
  kind: "bullet" | "item" | "skill";
  label: string;
  detail: string;
  score: number;
  text: string;
  apply: (doc: TailoredResume) => TailoredResume;
}

function keywordNames(analysis: JobAnalysis | null): string[][] {
  return (analysis?.keywords ?? []).map((k) => [k.term, ...k.aliases]);
}

export function mentions(text: string, term: string): boolean {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![A-Za-z0-9])${escaped}(?:s|es)?(?![A-Za-z0-9])`, "i").test(text);
}

/** How well some text answers the posting: the importance of the keywords it mentions. */
export function relevance(text: string, analysis: JobAnalysis | null): number {
  return (analysis?.keywords ?? []).reduce((sum, k, i) => sum + (keywordNames(analysis)[i]!.some((n) => mentions(text, n)) ? k.importance : 0), 0);
}

export function candidates(doc: TailoredResume, index: MasterIndex, analysis: JobAnalysis | null): Candidate[] {
  const out: Candidate[] = [];
  const usedSources = new Set(doc.sections.flatMap((s) => (s.items ?? []).flatMap((i) => (i.bullets ?? []).flatMap((b) => b.sourceIds))));
  const usedItems = new Set(doc.sections.flatMap((s) => (s.items ?? []).map((i) => i.sourceId)));
  const usedSkills = new Set(doc.sections.flatMap((s) => (s.groups ?? []).flatMap((g) => g.items.map((i) => i.skillId))));

  // Bullets of included roles and projects that were left out.
  for (const section of doc.sections) {
    if (!WITH_BULLETS.has(section.type)) continue;
    for (const item of section.items ?? []) {
      for (const bullet of index.bulletsOf.get(item.sourceId) ?? []) {
        if (usedSources.has(bullet.id)) continue;
        out.push({
          key: `bullet:${bullet.id}`, kind: "bullet", label: bullet.text,
          detail: String(item.position ?? item.name ?? ""), score: relevance(bullet.text, analysis), text: bullet.text,
          apply: (d) => addBullet(d, item.sourceId, { id: newBulletId(), text: bullet.text, sourceIds: [bullet.id], relevance: 3,
            keywords: [], origin: "master", aiText: null, edited: false, warnings: [] }),
        });
      }
    }
  }

  // Whole items that aren't in the résumé.
  const sectionFor: Record<string, string> = { work: "experience", projects: "projects", education: "education",
    certifications: "certifications", awards: "awards", publications: "publications", volunteer: "volunteer", languages: "languages" };
  for (const [id, { section, item }] of index.items) {
    if (usedItems.has(id)) continue;
    const type = sectionFor[section]!;
    const label = String(item.position ?? item.name ?? item.title ?? item.institution ?? item.organization ?? item.language ?? id);
    const detail = String(item.company ?? item.issuer ?? item.studyType ?? item.awarder ?? item.publisher ?? "");
    const text = [label, detail, ...(index.bulletsOf.get(id) ?? []).map((b) => b.text)].join(" ");
    out.push({
      key: `item:${id}`, kind: "item", label, detail: `${SECTION_TITLES[type]}${detail ? ` · ${detail}` : ""}`,
      score: relevance(text, analysis), text,
      apply: (d) => edit(d, (draft) => {
        const entry: ResumeItem = { sourceId: id, ...factsOf(item) } as ResumeItem;
        if (WITH_BULLETS.has(type)) {
          entry.bullets = (index.bulletsOf.get(id) ?? []).slice(0, 2).map((b) => ({ id: newBulletId(), text: b.text, sourceIds: [b.id],
            relevance: 3, keywords: [], origin: "master", aiText: null, edited: false, warnings: [] }));
        }
        let target = draft.sections.find((s) => s.type === type);
        if (!target) {
          target = { type, title: SECTION_TITLES[type] ?? type, items: [] } as ResumeSection;
          draft.sections.push(target);
        }
        target.items = [...(target.items ?? []), entry];
      }),
    });
  }

  // Skills that aren't listed.
  for (const [id, skill] of index.skills) {
    if (usedSkills.has(id)) continue;
    const name = String(skill.name);
    const category = String(skill.category ?? "Skills");
    out.push({
      key: `skill:${id}`, kind: "skill", label: name, detail: category,
      score: relevance([name, ...((skill.aliases as string[] | undefined) ?? [])].join(" "), analysis), text: name,
      apply: (d) => edit(d, (draft) => {
        let section = draft.sections.find((s) => s.type === "skills");
        if (!section) {
          section = { type: "skills", title: "Skills", groups: [] } as ResumeSection;
          draft.sections.push(section);
        }
        const groups = section.groups ?? [];
        const group = groups.find((g) => g.name === category) ?? groups[groups.push({ name: category, items: [] }) - 1]!;
        group.items.push({ skillId: id, display: name });
        section.groups = groups;
      }),
    });
  }
  return out.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
}

// ---- suggestions and server results ------------------------------------------------------------------------------------

export function applyChange(doc: TailoredResume, change: RefineResult["changes"][number]): TailoredResume {
  if (change.kind === "bullet") {
    return setBullet(doc, change.targetId, { text: change.after, sourceIds: change.sourceIds, aiText: change.after,
      origin: "ai", edited: false, warnings: change.warnings as unknown as ResumeBullet["warnings"] });
  }
  return setBlock(doc, change.kind, { text: change.after, sourceIds: change.sourceIds, aiText: change.after, edited: false });
}

/**
 * Bring in what the server computed on save (warnings, coverage, facts, edited flags) without undoing anything
 * typed since: a bullet's annotations are taken only while its text still matches what was saved.
 */
export function mergeSaved(local: TailoredResume, saved: TailoredResume): TailoredResume {
  const savedBullets = new Map<string, ResumeBullet>();
  const savedItems = new Map<string, ResumeItem>();
  for (const section of saved.sections) {
    for (const item of section.items ?? []) {
      savedItems.set(item.sourceId, item);
      for (const bullet of item.bullets ?? []) savedBullets.set(bullet.id, bullet);
    }
  }
  return {
    ...local,
    analysis: saved.analysis,
    sections: local.sections.map((section) => ({
      ...section,
      items: section.items?.map((item) => {
        const fresh = savedItems.get(item.sourceId);
        return {
          ...item, ...(fresh ? Object.fromEntries(Object.entries(fresh).filter(([k]) => k !== "bullets")) : {}),
          bullets: item.bullets?.map((b) => {
            const s = savedBullets.get(b.id);
            return s && s.text === b.text ? { ...b, warnings: s.warnings, edited: s.edited, origin: s.origin, sourceIds: s.sourceIds } : b;
          }),
        } as ResumeItem;
      }),
    })),
  };
}

export function itemTitle(item: ResumeItem): { title: string; detail: string } {
  const s = (k: string) => (typeof item[k] === "string" ? (item[k] as string) : "");
  if (s("position") && s("company")) return { title: s("position"), detail: s("company") };
  if (s("institution")) return { title: [s("studyType"), s("area")].filter(Boolean).join(" ") || s("institution"), detail: s("studyType") ? s("institution") : "" };
  return { title: s("name") || s("title") || s("organization") || s("language"), detail: s("issuer") || s("description") || s("awarder") || s("publisher") || s("fluency") };
}
