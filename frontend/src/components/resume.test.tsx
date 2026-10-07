import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { JobAnalysis, TailoredResume } from "../api/types";
import { AnalysisPanel, ResumePreview } from "./resume";

const resume: TailoredResume = {
  meta: { model: "claude-opus-5-5", generatedAt: "2026-10-06T00:00:00Z", job: { company: "Globex", title: "SRE" } },
  basics: { name: "Jordan Rivera", email: "jordan@example.com", location: { city: "Denver", region: "CO" } },
  headline: { text: "Senior Platform Engineer", sourceIds: ["h-platform"] },
  summary: { text: "Platform engineer with 9 years of experience.", sourceIds: ["s-platform"] },
  sections: [
    {
      type: "experience",
      title: "Experience",
      items: [{
        sourceId: "acme", company: "Acme Payments", position: "Senior Software Engineer", startDate: "2021-03", endDate: null,
        bullets: [
          { id: "tb-1", text: "Migrated 40 services to Kubernetes.", sourceIds: ["acme-b1"], relevance: 5, keywords: [], origin: "ai", warnings: [] },
          { id: "tb-2", text: "Cut latency 50%.", sourceIds: ["acme-b1"], relevance: 4, keywords: [], origin: "ai",
            warnings: [{ code: "NUMBER_NOT_IN_SOURCE", message: "Mentions 50, which its sources don't." }] },
        ],
      }],
    },
    { type: "skills", title: "Skills", groups: [{ name: "Cloud", items: [{ skillId: "k8s", display: "Kubernetes" }] }] },
  ],
  analysis: { coverage: { score: 0.5, matched: ["Kubernetes"], missing: ["GCP"], gaps: ["GCP"], available: [] }, warnings: [], notices: [], notes: [] },
};

describe("ResumePreview", () => {
  it("renders facts, bullets and flags lines that need a check", () => {
    render(<ResumePreview resume={resume} />);
    expect(screen.getByRole("heading", { name: "Jordan Rivera" })).toBeInTheDocument();
    expect(screen.getByText("Senior Platform Engineer")).toBeInTheDocument();
    expect(screen.getByText("Migrated 40 services to Kubernetes.")).toBeInTheDocument();
    expect(screen.getByLabelText("Mentions 50, which its sources don't.")).toBeInTheDocument();
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
  });
});

describe("AnalysisPanel", () => {
  it("marks requirement matches and keyword coverage", () => {
    const analysis: JobAnalysis = {
      company: "Globex", title: "SRE", seniority: "senior", location: null, employmentType: null, roleSummary: "Own reliability.",
      requirements: [
        { id: "r1", text: "Kubernetes in production", kind: "required", category: "skill", keywords: ["Kubernetes"] },
        { id: "r2", text: "GCP", kind: "preferred", category: "skill", keywords: ["GCP"] },
      ],
      responsibilities: [], companySignals: [], suggestedEmphasis: [],
      keywords: [
        { term: "Kubernetes", aliases: [], importance: 3, category: "technology", mustInclude: false },
        { term: "GCP", aliases: [], importance: 2, category: "technology", mustInclude: false },
      ],
      match: [
        { requirementId: "r1", status: "met", evidenceIds: ["acme-b1"], note: "Shown at Acme." },
        { requirementId: "r2", status: "missing", evidenceIds: [], note: "Not in the master." },
      ],
      fit: { rating: "strong", rationale: "Good match." },
    };
    render(<AnalysisPanel analysis={analysis} coverage={resume.analysis.coverage} />);
    expect(screen.getByText("Strong fit")).toBeInTheDocument();
    expect(screen.getByLabelText("Met")).toBeInTheDocument();
    expect(screen.getByLabelText("Missing")).toBeInTheDocument();
    expect(screen.getByText("(preferred)")).toBeInTheDocument();
  });
});
