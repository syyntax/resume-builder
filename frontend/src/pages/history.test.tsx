import { describe, expect, it } from "vitest";

import type { Application, MergeItem } from "../api/types";
import { previewFileName } from "../components/AccountSecurity";
import { initialSelections } from "../components/merge";
import { filterApplications } from "./ApplicationsPages";

const app = (id: string, company: string | null, title: string | null, createdAt: string, coverage: number | null, master = "Engineering") =>
  ({ id, job: { company, title }, master: { label: master }, createdAt, coverageScore: coverage, status: "done" }) as unknown as Application;

const apps = [
  app("a", "Globex", "Staff Engineer", "2026-10-01T00:00:00Z", 0.6),
  app("b", "acme", "Platform Lead", "2026-10-03T00:00:00Z", 0.9, "Leadership"),
  app("c", null, "SRE", "2026-10-02T00:00:00Z", null),
];

describe("application history", () => {
  it("searches company, role and master, and sorts", () => {
    expect(filterApplications(apps, "", "newest").map((a) => a.id)).toEqual(["b", "c", "a"]);
    expect(filterApplications(apps, "", "oldest").map((a) => a.id)).toEqual(["a", "c", "b"]);
    expect(filterApplications(apps, "", "company").map((a) => a.id)).toEqual(["b", "a", "c"]);  // case-insensitive; unknown last
    expect(filterApplications(apps, "", "role").map((a) => a.id)).toEqual(["b", "c", "a"]);
    expect(filterApplications(apps, "", "coverage").map((a) => a.id)).toEqual(["b", "a", "c"]);
    expect(filterApplications(apps, "leader", "newest").map((a) => a.id)).toEqual(["b"]);
    expect(filterApplications(apps, "staff globex", "newest").map((a) => a.id)).toEqual(["a"]);
    expect(filterApplications(apps, "nothing", "newest")).toEqual([]);
  });
});

describe("file name preview", () => {
  it("follows the pattern the way the server does", () => {
    expect(previewFileName("{name}_{company}_{role}_{doc}")).toBe("Jordan-Rivera_Globex_Staff-Platform-Engineer_Resume.pdf");
    expect(previewFileName("{last}, {first} - {doc}")).toBe("Rivera, Jordan - Resume.pdf");
    expect(previewFileName("{nothing}")).toBe("Resume.pdf");
    expect(previewFileName("../{doc}?")).toBe("Resume.pdf");
  });
});

describe("merging an import", () => {
  it("starts with every new item and every distinct new bullet picked", () => {
    const items = [
      { key: "work:0", section: "work", title: "Engineer", detail: "Acme", status: "match", bullets: ["New thing", "Reworded old thing"], similarTo: [null, "Old thing"] },
      { key: "work:1", section: "work", title: "Engineer", detail: "Initech", status: "new", bullets: ["x"], similarTo: [] },
      { key: "skills:0", section: "skills", title: "Go", detail: "", status: "same", bullets: [], similarTo: [] },
      { key: "work:2", section: "work", title: "Lead", detail: "Hooli", status: "match", bullets: ["Similar"], similarTo: ["Same"] },
    ] as MergeItem[];
    expect(initialSelections(items)).toEqual({ "work:0": [0], "work:1": null });
  });
});
