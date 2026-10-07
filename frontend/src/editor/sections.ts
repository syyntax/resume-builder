/** What the structured master editor shows for each section of a master résumé (DESIGN.md §7.1). */

import { formatPartialDate } from "../lib/format";
import type { Json, JsonObject } from "./doc";

export type FieldKind = "text" | "textarea" | "date" | "enddate" | "url" | "email" | "list" | "skills" | "number" | "select" | "checkbox";

export interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  placeholder?: string;
  hint?: string;
  wide?: boolean;
  options?: { value: string | number; label: string }[];
}

export interface SectionSpec {
  key: string;
  label: string;
  item: string; // singular, for "Add role", "Delete project"
  fields: FieldSpec[];
  bullets?: boolean;
  /** Items carry tags, priority, pin and hide (every list section except custom-section containers). */
  common?: boolean;
  title: (item: JsonObject) => string;
  detail?: (item: JsonObject) => string;
  blank: () => JsonObject;
}

const str = (value: Json | undefined): string => (typeof value === "string" ? value : "");

export function dateRange(item: JsonObject): string {
  const start = str(item.startDate);
  if (!start) return "";
  return `${formatPartialDate(start)} – ${item.endDate ? formatPartialDate(str(item.endDate)) : "present"}`;
}

const join = (...parts: string[]) => parts.filter(Boolean).join(" · ");
const when = (value: Json | undefined) => (str(value) ? formatPartialDate(str(value)) : "");

const START: FieldSpec = { key: "startDate", label: "Start", kind: "date", placeholder: "YYYY-MM" };
const END: FieldSpec = { key: "endDate", label: "End", kind: "enddate", placeholder: "Present", hint: "Empty means current." };
const URL_FIELD: FieldSpec = { key: "url", label: "URL", kind: "url", placeholder: "https://" };

export const SECTIONS: SectionSpec[] = [
  {
    key: "headlines", label: "Headlines", item: "headline", common: true,
    fields: [{ key: "text", label: "Headline", kind: "text", required: true, wide: true, placeholder: "Senior Platform Engineer" }],
    title: (i) => str(i.text) || "New headline", blank: () => ({ text: "" }),
  },
  {
    key: "summaries", label: "Summaries", item: "summary", common: true,
    fields: [{ key: "text", label: "Summary", kind: "textarea", required: true, wide: true }],
    title: (i) => str(i.text).slice(0, 90) || "New summary", blank: () => ({ text: "" }),
  },
  {
    key: "work", label: "Experience", item: "role", common: true, bullets: true,
    fields: [
      { key: "position", label: "Position", kind: "text", required: true },
      { key: "company", label: "Company", kind: "text", required: true },
      { key: "location", label: "Location", kind: "text", placeholder: "Denver, CO" },
      { key: "employmentType", label: "Employment type", kind: "text", placeholder: "Full-time" },
      START, END, URL_FIELD,
      { key: "summary", label: "Summary", kind: "textarea", wide: true, hint: "A sentence about the role, shown above its bullets." },
      { key: "skills", label: "Skills used", kind: "skills", wide: true },
    ],
    title: (i) => join(str(i.position), str(i.company)) || "New role", detail: dateRange,
    blank: () => ({ company: "", position: "", highlights: [] }),
  },
  {
    key: "projects", label: "Projects", item: "project", common: true, bullets: true,
    fields: [
      { key: "name", label: "Name", kind: "text", required: true },
      { key: "entity", label: "Organization", kind: "text" },
      { key: "description", label: "Description", kind: "textarea", wide: true },
      START, END, URL_FIELD,
      { key: "type", label: "Type", kind: "text", placeholder: "Open source" },
      { key: "roles", label: "Roles", kind: "list" },
      { key: "keywords", label: "Keywords", kind: "list" },
      { key: "skills", label: "Skills used", kind: "skills", wide: true },
    ],
    title: (i) => str(i.name) || "New project", detail: dateRange, blank: () => ({ name: "", highlights: [] }),
  },
  {
    key: "education", label: "Education", item: "education entry", common: true, bullets: true,
    fields: [
      { key: "institution", label: "Institution", kind: "text", required: true, wide: true },
      { key: "studyType", label: "Degree", kind: "text", placeholder: "B.S." },
      { key: "area", label: "Field of study", kind: "text", placeholder: "Computer Science" },
      START, END,
      { key: "score", label: "GPA or grade", kind: "text" }, URL_FIELD,
      { key: "courses", label: "Courses", kind: "list" },
      { key: "honors", label: "Honors", kind: "list" },
    ],
    title: (i) => str(i.institution) || "New education entry", detail: (i) => join(str(i.studyType), str(i.area), dateRange(i)),
    blank: () => ({ institution: "" }),
  },
  {
    key: "certifications", label: "Certifications", item: "certification", common: true,
    fields: [
      { key: "name", label: "Name", kind: "text", required: true, wide: true },
      { key: "issuer", label: "Issuer", kind: "text" },
      { key: "credentialId", label: "Credential ID", kind: "text" },
      { key: "date", label: "Issued", kind: "date", placeholder: "YYYY-MM" },
      { key: "expires", label: "Expires", kind: "date", placeholder: "YYYY-MM" }, URL_FIELD,
    ],
    title: (i) => str(i.name) || "New certification", detail: (i) => join(str(i.issuer), when(i.date)),
    blank: () => ({ name: "" }),
  },
  {
    key: "skills", label: "Skills", item: "skill", common: true,
    fields: [
      { key: "name", label: "Name", kind: "text", required: true },
      { key: "category", label: "Category", kind: "text", placeholder: "Cloud & Infrastructure" },
      { key: "level", label: "Level", kind: "text", placeholder: "expert, advanced, intermediate…" },
      { key: "years", label: "Years", kind: "number" },
      { key: "aliases", label: "Aliases", kind: "list", wide: true, hint: "Other names for it, such as K8s for Kubernetes. Tailoring may use these." },
      { key: "keywords", label: "Keywords", kind: "list", wide: true },
    ],
    title: (i) => str(i.name) || "New skill", detail: (i) => str(i.category), blank: () => ({ name: "" }),
  },
  {
    key: "awards", label: "Awards", item: "award", common: true,
    fields: [
      { key: "title", label: "Title", kind: "text", required: true, wide: true },
      { key: "awarder", label: "Awarded by", kind: "text" },
      { key: "date", label: "Date", kind: "date", placeholder: "YYYY-MM" },
      { key: "summary", label: "Summary", kind: "textarea", wide: true },
    ],
    title: (i) => str(i.title) || "New award", detail: (i) => join(str(i.awarder), when(i.date)),
    blank: () => ({ title: "" }),
  },
  {
    key: "publications", label: "Publications", item: "publication", common: true,
    fields: [
      { key: "name", label: "Title", kind: "text", required: true, wide: true },
      { key: "publisher", label: "Publisher", kind: "text" },
      { key: "releaseDate", label: "Date", kind: "date", placeholder: "YYYY-MM" }, URL_FIELD,
      { key: "summary", label: "Summary", kind: "textarea", wide: true },
    ],
    title: (i) => str(i.name) || "New publication", detail: (i) => str(i.publisher), blank: () => ({ name: "" }),
  },
  {
    key: "volunteer", label: "Volunteering", item: "volunteer role", common: true, bullets: true,
    fields: [
      { key: "organization", label: "Organization", kind: "text", required: true },
      { key: "position", label: "Position", kind: "text" },
      START, END, URL_FIELD,
      { key: "summary", label: "Summary", kind: "textarea", wide: true },
    ],
    title: (i) => join(str(i.position), str(i.organization)) || "New volunteer role", detail: dateRange,
    blank: () => ({ organization: "", highlights: [] }),
  },
  {
    key: "languages", label: "Languages", item: "language", common: true,
    fields: [
      { key: "language", label: "Language", kind: "text", required: true },
      { key: "fluency", label: "Fluency", kind: "text", placeholder: "Native, Professional…" },
    ],
    title: (i) => str(i.language) || "New language", detail: (i) => str(i.fluency), blank: () => ({ language: "" }),
  },
  {
    key: "interests", label: "Interests", item: "interest", common: true,
    fields: [
      { key: "name", label: "Interest", kind: "text", required: true },
      { key: "keywords", label: "Keywords", kind: "list" },
    ],
    title: (i) => str(i.name) || "New interest", blank: () => ({ name: "" }),
  },
  {
    key: "references", label: "References", item: "reference", common: true,
    fields: [
      { key: "name", label: "Name", kind: "text", required: true },
      { key: "reference", label: "Reference", kind: "textarea", wide: true },
    ],
    title: (i) => str(i.name) || "New reference", blank: () => ({ name: "" }),
  },
];

export const CUSTOM_SECTION: SectionSpec = {
  key: "customSections", label: "Custom sections", item: "section", common: true,
  fields: [{ key: "title", label: "Section title", kind: "text", required: true, wide: true, placeholder: "Security Clearance" }],
  title: (i) => str(i.title) || "New section", detail: (i) => `${Array.isArray(i.items) ? i.items.length : 0} items`,
  blank: () => ({ title: "", items: [] }),
};

export const CUSTOM_ITEM: SectionSpec = {
  key: "items", label: "Items", item: "item", common: true, bullets: true,
  fields: [
    { key: "title", label: "Title", kind: "text", required: true },
    { key: "subtitle", label: "Subtitle", kind: "text" },
    { key: "date", label: "Date", kind: "date", placeholder: "YYYY-MM" },
    START, END, URL_FIELD,
    { key: "summary", label: "Summary", kind: "textarea", wide: true },
  ],
  title: (i) => str(i.title) || "New item", detail: (i) => join(str(i.subtitle), when(i.date)),
  blank: () => ({ title: "" }),
};

export const BASICS_FIELDS: FieldSpec[] = [
  { key: "name", label: "Full name", kind: "text", required: true },
  { key: "label", label: "Professional title", kind: "text", placeholder: "Senior Platform Engineer" },
  { key: "email", label: "Email", kind: "email" },
  { key: "phone", label: "Phone", kind: "text" },
  { key: "url", label: "Website", kind: "url", placeholder: "https://" },
  { key: "workAuthorization", label: "Work authorization", kind: "text", placeholder: "US citizen" },
];

export const LOCATION_FIELDS: FieldSpec[] = [
  { key: "city", label: "City", kind: "text" },
  { key: "region", label: "State or region", kind: "text" },
  { key: "postalCode", label: "Postal code", kind: "text" },
  { key: "countryCode", label: "Country code", kind: "text", placeholder: "US" },
];

export const PROFILE_FIELDS: FieldSpec[] = [
  { key: "network", label: "Network", kind: "text", placeholder: "LinkedIn" },
  { key: "username", label: "Username", kind: "text" },
  { key: "url", label: "URL", kind: "url", placeholder: "https://" },
];

export const PREFERENCE_FIELDS: FieldSpec[] = [
  { key: "pageLimit", label: "Length", kind: "select", options: [{ value: 1, label: "One page" }, { value: 2, label: "Two pages" }, { value: "auto", label: "Automatic" }] },
  { key: "tone", label: "Tone", kind: "select", options: [{ value: "confident", label: "Confident" }, { value: "neutral", label: "Neutral" }, { value: "conservative", label: "Conservative" }] },
  { key: "recentYears", label: "Recent years", kind: "number", hint: "Older roles collapse into an Earlier Experience line." },
  { key: "minBulletsPerRecentRole", label: "Minimum bullets per recent role", kind: "number" },
  { key: "spelling", label: "Spelling", kind: "text", placeholder: "en-US" },
  { key: "showWorkAuthorization", label: "Show work authorization", kind: "checkbox" },
];
