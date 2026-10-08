import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApplicationDetail, JobAnalysis, TailoredResume } from "../api/types";
import { wordDiff } from "./diff";
import { candidates, indexMaster, mergeSaved, setBullet } from "./resumeOps";

vi.mock("../preview/PdfViewer", () => ({ default: () => <div data-testid="pdf" /> }));

const master = {
  basics: { name: "Jordan Rivera" },
  work: [{ id: "acme", company: "Acme", position: "Engineer", startDate: "2021-03", highlights: [
    { id: "acme.b1", text: "Led migration of 40 services to Kubernetes." },
    { id: "acme.b2", text: "Ran the on-call rotation." },
    { id: "acme.b3", text: "Built Terraform modules used by 12 teams." },
  ] }],
  projects: [{ id: "tf", name: "tf-guard", highlights: [{ id: "tf.b1", text: "A Terraform linter." }] }],
  skills: [{ id: "k8s", name: "Kubernetes", category: "Cloud" }, { id: "terraform", name: "Terraform", category: "Cloud" }],
};

const analysis = {
  keywords: [{ term: "Terraform", aliases: [], importance: 3, category: "technology", mustInclude: false }],
} as unknown as JobAnalysis;

const resume: TailoredResume = {
  meta: { model: "m", generatedAt: "2026-10-07T00:00:00Z", job: { company: "Globex", title: "SRE" } },
  basics: { name: "Jordan Rivera" },
  headline: { text: "Platform Engineer", sourceIds: [] },
  summary: { text: "Builds platforms.", sourceIds: [] },
  sections: [
    { type: "experience", title: "Experience", items: [{ sourceId: "acme", company: "Acme", position: "Engineer", startDate: "2021-03",
      bullets: [{ id: "tb-1", text: "Led migration of 40 services to Kubernetes.", sourceIds: ["acme.b1"], relevance: 5, keywords: [], origin: "ai",
        aiText: "Led migration of 40 services to Kubernetes.", warnings: [] }] }] },
    { type: "skills", title: "Skills", groups: [{ name: "Cloud", items: [{ skillId: "k8s", display: "Kubernetes" }] }] },
  ],
  analysis: { coverage: { score: 0.5, matched: ["Kubernetes"], missing: ["Terraform"], gaps: [], available: [{ term: "Terraform", ids: ["acme.b3"] }] },
    warnings: [], notices: [], notes: [] },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("word diff", () => {
  it("marks words removed and added", () => {
    const parts = wordDiff("Led migration of 40 services", "Drove migration of 40 payment services");
    expect(parts.filter((p) => p.kind === "del").map((p) => p.text.trim())).toEqual(["Led"]);
    expect(parts.filter((p) => p.kind === "add").map((p) => p.text.trim()).join(" ")).toContain("Drove");
    expect(parts.map((p) => (p.kind === "del" ? "" : p.text)).join("")).toBe("Drove migration of 40 payment services");
  });
});

describe("résumé operations", () => {
  it("lists what's left out of the master, most relevant first", () => {
    const list = candidates(resume, indexMaster(master), analysis);
    expect(list[0]!.label).toBe("Built Terraform modules used by 12 teams."); // matches a central keyword
    expect(list.map((c) => c.kind)).toEqual(expect.arrayContaining(["bullet", "item", "skill"]));
    const withBullet = list[0]!.apply(resume);
    const added = withBullet.sections[0]!.items![0]!.bullets!.at(-1)!;
    expect(added).toMatchObject({ text: "Built Terraform modules used by 12 teams.", sourceIds: ["acme.b3"], origin: "master" });
    const skill = list.find((c) => c.key === "skill:terraform")!.apply(resume);
    expect(skill.sections[1]!.groups![0]!.items.map((i) => i.skillId)).toEqual(["k8s", "terraform"]);
    const project = list.find((c) => c.key === "item:tf")!.apply(resume);
    expect(project.sections.at(-1)).toMatchObject({ type: "projects", items: [{ sourceId: "tf", name: "tf-guard" }] });
  });

  it("merges what the server computed without losing newer typing", () => {
    const typedSince = setBullet(resume, "tb-1", { text: "Something newer" });
    const saved = setBullet(resume, "tb-1", { warnings: [{ code: "X", message: "server warning" }] });
    expect(mergeSaved(typedSince, saved).sections[0]!.items![0]!.bullets![0]!).toMatchObject({ text: "Something newer", warnings: [] });
    expect(mergeSaved(resume, saved).sections[0]!.items![0]!.bullets![0]!.warnings).toEqual([{ code: "X", message: "server warning" }]);
  });
});

describe("ResumeWorkspace", () => {
  it("edits, removes and adds lines, and autosaves", async () => {
    const { ResumeWorkspace } = await import("./ResumeWorkspace");
    const saves: TailoredResume[] = [];
    const refines: { instruction: string; targetId: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/resume/refine")) {
        refines.push(JSON.parse(String(init!.body)) as { instruction: string; targetId: string });
        const { targetId } = refines.at(-1)!;
        const change = { kind: "bullet", targetId, before: "", after: "Moved 40 services to Kubernetes.", sourceIds: ["acme.b1"], warnings: [] };
        return new Response(JSON.stringify({ changes: [change], items: [], notes: [], costUsd: 0.01 }), { headers: { "content-type": "application/json" } });
      }
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { document: TailoredResume };
        saves.push(body.document);
        return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
      }
      return new Response("{}", { headers: { "content-type": "application/json" } });
    }));
    const application = { id: "apl_1", resume, analysis, options: { pageLimit: 1 }, template: "meridian",
      theme: { accent: "#1F3A5F", fonts: "inter", density: "balanced", paper: "letter", margins: "normal", dateFormat: "MMM YYYY", contactIcons: true },
    } as unknown as ApplicationDetail;
    const user = userEvent.setup();
    const { unmount } = render(<QueryClientProvider client={new QueryClient()}><ResumeWorkspace application={application} master={master} /></QueryClientProvider>);

    const bullet = screen.getByRole("textbox", { name: "Bullet" });
    await user.clear(bullet);
    await user.type(bullet, "Drove a migration.");
    await act(() => new Promise((r) => setTimeout(r, 900)));
    expect(saves.at(-1)!.sections[0]!.items![0]!.bullets![0]!.text).toBe("Drove a migration.");
    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    // Merging the server's answer back in isn't an edit, so it doesn't start another save.
    const settled = saves.length;
    await act(() => new Promise((r) => setTimeout(r, 1000)));
    expect(saves.length).toBe(settled);
    expect(screen.getByText("All changes saved")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add from master" }));
    const drawer = screen.getByRole("dialog", { name: "Add from master" });
    const terraform = within(drawer).getByText("Built Terraform modules used by 12 teams.").closest("li")!;
    await user.click(within(terraform).getByRole("button", { name: "Add" }));
    expect(screen.getAllByRole("textbox", { name: "Bullet" })).toHaveLength(2);

    await user.click(screen.getAllByRole("button", { name: "Remove bullet" })[0]!);
    expect(screen.getAllByRole("textbox", { name: "Bullet" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /Undo/ }));
    expect(screen.getAllByRole("textbox", { name: "Bullet" })).toHaveLength(2);

    // Refine: a keyword from the analysis, shown as a suggestion until accepted
    await user.click(screen.getAllByRole("button", { name: "Refine with AI" }).find((b) => b.closest("li, div.group"))!);
    await user.click(within(screen.getByRole("dialog", { name: "Refine with AI" })).getByRole("button", { name: "Terraform" }));
    expect(refines.at(-1)!.instruction).toContain('"Terraform"');
    await user.click(await screen.findByRole("button", { name: "Accept" }));
    expect(screen.getAllByRole("textbox", { name: "Bullet" })[0]).toHaveValue("Moved 40 services to Kubernetes.");

    // Leaving with unsaved changes flushes them rather than dropping them.
    const before = saves.length;
    unmount();
    expect(saves.length).toBe(before + 1);
    expect(saves.at(-1)!.sections[0]!.items![0]!.bullets).toHaveLength(2);
  });
});
