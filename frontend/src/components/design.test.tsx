import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TemplateCatalog, Theme } from "../api/types";
import { DesignPanel } from "./design";

const theme: Theme = { accent: "#1F3A5F", fonts: "inter", density: "balanced", paper: "letter", margins: "normal",
  dateFormat: "MMM YYYY", contactIcons: true };

const catalog: TemplateCatalog = {
  templates: [
    { key: "meridian", label: "Meridian", description: "Modern", layout: "Single column", ats: "Excellent", available: true },
    { key: "atlas", label: "Atlas", description: "Two columns", layout: "Two columns", ats: "Good", available: false },
  ],
  options: {
    accents: [{ value: "#1F3A5F", label: "Navy" }, { value: "#0F766E", label: "Teal" }],
    fonts: [{ value: "inter", label: "Inter" }, { value: "plex", label: "IBM Plex Sans" }],
    densities: [{ value: "balanced", label: "Balanced" }, { value: "compact", label: "Compact" }],
    papers: [{ value: "letter", label: "US Letter" }, { value: "a4", label: "A4" }],
    margins: [{ value: "normal", label: "Normal" }, { value: "narrow", label: "Narrow" }],
    dateFormats: [{ value: "MMM YYYY", label: "Mar 2021" }, { value: "YYYY", label: "2021" }],
  },
  defaultTemplate: "meridian",
  defaultTheme: theme,
};

afterEach(() => vi.unstubAllGlobals());

function renderPanel(onChange: (template: string, theme: Theme) => void, error?: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(catalog), { headers: { "content-type": "application/json" } })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DesignPanel template="meridian" theme={theme} onChange={onChange} error={error} />
    </QueryClientProvider>,
  );
}

describe("DesignPanel", () => {
  it("offers available templates and changes theme options", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderPanel(onChange);
    expect(await screen.findByRole("button", { name: /Atlas/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Meridian/ })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Teal" }));
    expect(onChange).toHaveBeenLastCalledWith("meridian", { ...theme, accent: "#0F766E" });
    await user.selectOptions(screen.getByLabelText("Paper"), "a4");
    expect(onChange).toHaveBeenLastCalledWith("meridian", { ...theme, paper: "a4" });
    await user.click(screen.getByLabelText("Contact icons"));
    expect(onChange).toHaveBeenLastCalledWith("meridian", { ...theme, contactIcons: false });
  });

  it("shows why a choice was refused", async () => {
    renderPanel(vi.fn(), "this color is too light to read on white; choose a darker one");
    expect(await screen.findByRole("alert")).toHaveTextContent("too light");
  });
});

describe("page notes", () => {
  it("suggests only what hasn't been tried", async () => {
    const { pageNote } = await import("../workspace/preview");
    expect(pageNote(1, 1, theme)).toEqual({ ok: true, text: "1 page · fits the 1-page target" });
    expect(pageNote(2, 1, theme).text).toContain("Try Compact density or Narrow margins.");
    expect(pageNote(2, 1, { ...theme, density: "compact" }).text).toContain("Try Narrow margins.");
    expect(pageNote(2, 1, { ...theme, density: "compact", margins: "narrow" }).text).toContain("Remove less relevant bullets");
    expect(pageNote(3, "auto", theme)).toEqual({ ok: true, text: "3 pages" });
  });
});
