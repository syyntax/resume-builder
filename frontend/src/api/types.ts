import type { components } from "./schema";

type S = components["schemas"];

export type Me = S["MeOut"];
export type User = S["UserOut"];
export type Session = S["SessionOut"];
export type RegistrationInfo = S["RegistrationInfoOut"];
export type TokenCheck = S["TokenCheckOut"];
export type Issue = S["IssueOut"];
export type MasterSummary = S["MasterSummary"];
export type Validation = S["ValidationOut"];
export type Master = S["MasterOut"];
export type MasterDetail = S["MasterDetailOut"];
export type MasterSave = S["MasterSaveOut"];
export type VersionMeta = S["VersionMeta"];
export type Invite = S["InviteOut"];
export type Link = S["LinkOut"];
export type SystemSettings = S["SystemSettingsOut"];
export type AuditEntry = S["AuditEntryOut"];
export type RegistrationMode = SystemSettings["registrationMode"];

/** Loose shape of a normalized master résumé document, for the read-only overview. */
export interface MasterDocument {
  meta?: { label?: string };
  basics: {
    name: string;
    label?: string;
    email?: string;
    phone?: string;
    url?: string;
    location?: { city?: string; region?: string; countryCode?: string; remote?: boolean };
    profiles?: { network?: string; username?: string; url?: string }[];
  };
  headlines?: { id: string; text: string; tags?: string[] }[];
  summaries?: { id: string; text: string; tags?: string[] }[];
  work?: {
    id: string;
    company: string;
    position: string;
    location?: string;
    startDate?: string;
    endDate?: string | null;
    highlights?: Bullet[];
  }[];
  projects?: { id: string; name: string; description?: string; highlights?: Bullet[] }[];
  education?: { id: string; institution: string; studyType?: string; area?: string; endDate?: string | null }[];
  certifications?: { id: string; name: string; issuer?: string; date?: string }[];
  skills?: { id: string; name: string; category?: string; aliases?: string[] }[];
  customSections?: { id: string; title: string; items?: { id: string; title: string; subtitle?: string }[] }[];
}

export interface Bullet {
  id: string;
  text: string;
  tags?: string[];
  pin?: boolean;
  hidden?: boolean;
  priority?: number;
  variants?: { text: string }[];
}

export type ApiKeyStatus = S["ApiKeyStatusOut"];
export type AiSettings = S["AiSettingsOut"];
export type Usage = S["UsageOut"];
export type Application = S["ApplicationOut"];
export type ApplicationDetail = S["ApplicationDetailOut"];
export type ApplicationStatus = Application["status"];
export type AdminUser = S["AdminUserOut"];
export type AdminAiSettings = S["AdminAiSettingsOut"];
export type UserUsage = S["UserUsageOut"];
export type SourceFile = S["SourceFileOut"];
export type Import = S["ImportOut"];
export type ImportDetail = S["ImportDetailOut"];
export type ImportFlag = S["ImportFlagOut"];
export type ImportPreview = S["ImportPreviewOut"];
export type ImportStatus = Import["status"];
export type Theme = S["Theme"];
export type TemplateCatalog = S["TemplatesOut"];
export type Design = S["DesignOut"];

/** Shape of the stored job analysis (backend app/ai/schemas.py JobAnalysis). */
export interface JobAnalysis {
  company: string | null;
  title: string | null;
  seniority: string;
  location: string | null;
  employmentType: string | null;
  roleSummary: string;
  requirements: { id: string; text: string; kind: "required" | "preferred"; category: string; keywords: string[] }[];
  responsibilities: string[];
  keywords: { term: string; aliases: string[]; importance: 1 | 2 | 3; category: string; mustInclude: boolean }[];
  companySignals: string[];
  match: { requirementId: string; status: "met" | "partial" | "missing"; evidenceIds: string[]; note: string }[];
  fit: { rating: "strong" | "moderate" | "weak"; rationale: string };
  suggestedEmphasis: string[];
}

export interface ResumeWarning {
  targetId?: string;
  code: string;
  message: string;
}

export interface ResumeBullet {
  id: string;
  text: string;
  sourceIds: string[];
  relevance: number;
  keywords: string[];
  origin: "ai" | "master" | "user";
  /** The AI's wording, for "Revert to AI draft". */
  aiText?: string | null;
  edited?: boolean;
  warnings: ResumeWarning[];
}

export interface ResumeItem {
  sourceId: string;
  [field: string]: unknown;
  bullets?: ResumeBullet[];
}

export interface ResumeSection {
  type: string;
  title: string;
  sourceId?: string;
  items?: ResumeItem[];
  groups?: { name: string; items: { skillId: string; display: string }[] }[];
}

/** Shape of a TailoredResume document (DESIGN.md §7.3). */
export interface TailoredResume {
  meta: { model: string; generatedAt: string; job: { company: string | null; title: string | null } };
  basics: MasterDocument["basics"];
  headline: SourcedBlock;
  summary: SourcedBlock;
  sections: ResumeSection[];
  analysis: {
    coverage: {
      score: number | null;
      matched: string[];
      missing: string[];
      gaps: string[];
      available: { term: string; ids: string[] }[];
    };
    warnings: ResumeWarning[];
    notices: ResumeWarning[];
    notes: { type: "gap" | "suggestion"; text: string }[];
    audit?: AuditReport;
  };
}

export interface SourcedBlock {
  text: string;
  sourceIds: string[];
  aiText?: string;
  edited?: boolean;
}

export interface AuditReport {
  status: "done" | "running" | "unavailable";
  checkedAt?: string;
  checked?: number;
  message?: string;
}

export type ParagraphRole = "opening" | "evidence" | "motivation" | "closing";

export interface LetterParagraph {
  id: string;
  role: ParagraphRole;
  text: string;
  sourceIds: string[];
  jobRefs: string[];
  companySources: ("posting" | "notes")[];
  aiText?: string | null;
  edited?: boolean;
  flags: string[];
  warnings: ResumeWarning[];
}

/** Shape of a CoverLetter document (DESIGN.md §7.4). */
export interface CoverLetter {
  meta?: { generatedAt: string; model: string };
  options: LetterOptions;
  sender: MasterDocument["basics"];
  date: string;
  recipient: { name?: string; title?: string; company?: string; address?: string[] };
  subject: string;
  salutation: string;
  paragraphs: LetterParagraph[];
  closing: string;
  signature: string;
  analysis: { wordCount: number; warnings: ResumeWarning[]; notes?: { type: string; text: string }[]; audit?: AuditReport };
}

export type LetterOptions = S["CoverLetterOptions"];
export type RefineResult = S["RefineOut"];
export type LetterRefineResult = S["LetterRefineOut"];
export type LetterStatus = ApplicationDetail["coverLetterStatus"];
