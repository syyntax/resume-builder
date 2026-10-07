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
