import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApplicationDetail, FitResult, Theme } from "../api/types";
import { FitBanner, useFit } from "./preview";

const theme: Theme = { accent: "#1F3A5F", fonts: "inter", density: "balanced", paper: "letter", margins: "normal",
  dateFormat: "MMM YYYY", contactIcons: true };
const compact: Theme = { ...theme, density: "compact" };
const application = { id: "apl_1", template: "meridian", theme, resume: { v: "before" } } as unknown as ApplicationDetail;

const fitted: FitResult = { fits: true, pages: 1, room: false, changes: ["Compact density", "Removed 1 less relevant bullet"],
  removed: ["Ran the on-call rotation."], document: { v: "after" }, template: "meridian", theme: compact, revisionId: "rev_1", costUsd: 0 };

afterEach(() => vi.unstubAllGlobals());

function json(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
}

describe("fit to page", () => {
  it("applies the fitted document and design, and undoes both", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(url);
      return url.endsWith("/restore") ? json({ kind: "resume", document: { v: "before" }, template: "meridian", theme }) : json(fitted);
    }));
    const client = new QueryClient();
    client.setQueryData(["application", "apl_1"], application);
    const applied: unknown[] = [];
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useFit(application, "resume", (doc) => applied.push(doc)), { wrapper });

    await act(() => result.current.fit());
    expect(calls).toEqual(["/api/applications/apl_1/resume/fit"]);
    expect(applied).toEqual([{ v: "after" }]);
    expect(client.getQueryData<ApplicationDetail>(["application", "apl_1"])).toMatchObject({ theme: compact, resume: { v: "after" } });

    await act(() => result.current.undo());
    expect(calls.at(-1)).toBe("/api/applications/apl_1/revisions/rev_1/restore");
    expect(applied.at(-1)).toEqual({ v: "before" });
    expect(client.getQueryData<ApplicationDetail>(["application", "apl_1"])).toMatchObject({ theme, resume: { v: "before" } });
    expect(result.current.result).toBeNull();
  });

  it("says what changed, what was left out, and offers undo", async () => {
    const undo = vi.fn();
    const user = userEvent.setup();
    const fit = { result: fitted, busy: null, error: null, fit: vi.fn(), undo, dismiss: vi.fn() };
    render(<FitBanner fit={fit} />);
    expect(screen.getByText("Fitted to 1 page")).toBeInTheDocument();
    expect(screen.getByText(/Compact density · Removed 1 less relevant bullet/)).toBeInTheDocument();
    expect(screen.getByText("Ran the on-call rotation.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(undo).toHaveBeenCalled();
  });

  it("explains when it can't fit, and offers more when there's room", async () => {
    const stuck = { ...fitted, fits: false, pages: 2, changes: [], removed: [], revisionId: null };
    const { rerender } = render(<FitBanner fit={{ result: stuck, busy: null, error: null, fit: vi.fn(), undo: vi.fn(), dismiss: vi.fn() }} />);
    expect(screen.getByText("Still 2 pages")).toBeInTheDocument();
    const addMore = vi.fn();
    const roomy = { ...stuck, fits: true, pages: 1, room: true };
    rerender(<FitBanner fit={{ result: roomy, busy: null, error: null, fit: vi.fn(), undo: vi.fn(), dismiss: vi.fn() }} onAddMore={addMore} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Add from master" }));
    expect(addMore).toHaveBeenCalled();
  });
});
