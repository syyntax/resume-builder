import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "./AdminPage";

const efforts = { analyze: "medium", tailor: "high", letter: "high", import: "high", refine: "medium", audit: "low", condense: "low" };
const ai = { sharedKeyConfigured: false, allowSharedKey: false, defaultModel: "claude-opus-5-5", allowedModels: ["claude-opus-5-5"],
  knownModels: ["claude-opus-5-5", "claude-sonnet-5-5"], defaultCapUsd: 20, effort: efforts, claimAudit: true };

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("admin settings", () => {
  it("says it saved, and shows what was stored", async () => {
    const puts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { claimAudit: boolean };
        puts.push(body);
        return json({ ...ai, claimAudit: body.claimAudit });
      }
      return json(ai);
    }));
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={["/admin?tab=ai"]}><AdminPage /></MemoryRouter></QueryClientProvider>);
    await user.click(await screen.findByRole("checkbox", { name: /claim audit/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    // Saving used to refetch, remount the form and lose the confirmation.
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /claim audit/i })).not.toBeChecked();
    expect(puts).toHaveLength(1);
  });
});
