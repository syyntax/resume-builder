import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { ImportFlag } from "../api/types";
import { MasterEditor } from "./MasterEditor";
import { type Json, KEY, findById, fromEditable, getIn, insertAt, moveItem, parsePath, pathToString, removeAt, setIn, toEditable } from "./doc";
import { useHistory } from "./history";

const master = {
  meta: { schemaVersion: "1.0", label: "Engineering" },
  basics: { name: "Jordan Rivera", email: "jordan@example.com", location: { city: "Denver" } },
  work: [
    {
      id: "acme", company: "Acme", position: "Engineer", startDate: "2021-03", custom: "kept",
      highlights: [{ id: "acme.b1", text: "Led the migration." }, "Plain string bullet."],
    },
    { id: "initech", company: "Initech", position: "Developer", highlights: [] },
  ],
  skills: [{ id: "go", name: "Go", category: "Languages" }],
} as unknown as Json;

describe("editable documents", () => {
  it("adds hidden keys, turns string bullets into objects, and strips keys again", () => {
    const editable = toEditable(master);
    const work = getIn(editable, ["work"]) as Record<string, Json>[];
    expect(typeof work[0]?.[KEY]).toBe("string");
    expect(getIn(editable, ["work", 0, "highlights", 1, "text"])).toBe("Plain string bullet.");
    const back = fromEditable(editable) as typeof master;
    expect(JSON.stringify(back)).not.toContain(KEY);
    expect(getIn(back, ["work", 0, "custom"])).toBe("kept"); // unknown fields pass through
    expect(getIn(back, ["work", 0, "highlights", 1])).toEqual({ text: "Plain string bullet." });
  });

  it("sets, clears, inserts, moves and removes immutably", () => {
    const doc = toEditable(master);
    const renamed = setIn(doc, ["basics", "name"], "Sam");
    expect(getIn(renamed, ["basics", "name"])).toBe("Sam");
    expect(getIn(doc, ["basics", "name"])).toBe("Jordan Rivera");
    expect(getIn(setIn(doc, ["basics", "email"], ""), ["basics", "email"])).toBeUndefined(); // cleared = removed
    expect(getIn(setIn(doc, ["preferences", "tone"], "neutral"), ["preferences", "tone"])).toBe("neutral"); // created

    const added = insertAt(doc, ["work", 1, "highlights"], { text: "New" });
    expect(getIn(added, ["work", 1, "highlights", 0, "text"])).toBe("New");
    const moved = moveItem(doc, ["work"], 0, 1);
    expect(getIn(moved, ["work", 0, "company"])).toBe("Initech");
    expect(getIn(removeAt(doc, ["work"], 0), ["work", 0, "company"])).toBe("Initech");
    expect(findById(doc, "acme.b1")).toEqual(["work", 0, "highlights", 0]);
  });

  it("round-trips API paths", () => {
    expect(parsePath("work[2].highlights[0].text")).toEqual(["work", 2, "highlights", 0, "text"]);
    expect(pathToString(["work", 2, "highlights", 0, "text"])).toBe("work[2].highlights[0].text");
  });
});

describe("history", () => {
  it("groups typing in one field into a single undo step", () => {
    const { result } = renderHook(() => useHistory(0));
    act(() => result.current.set((v) => v + 1, "a"));
    act(() => result.current.set((v) => v + 1, "a"));
    act(() => result.current.set((v) => v + 10, "b"));
    expect(result.current.value).toBe(12);
    act(() => result.current.undo());
    expect(result.current.value).toBe(2);
    act(() => result.current.undo());
    expect(result.current.value).toBe(0);
    expect(result.current.canUndo).toBe(false);
    act(() => result.current.redo());
    expect(result.current.value).toBe(2);
  });
});

function Harness({ flags = [], issues, active = null, onValue }: { flags?: ImportFlag[]; issues?: Map<string, string>; active?: ImportFlag | null; onValue?: (doc: Json) => void }) {
  const history = useHistory<Json>(toEditable(master));
  const [, rerender] = useState(0);
  onValue?.(history.value);
  return (
    <>
      <button type="button" onClick={() => { history.undo(); rerender((n) => n + 1); }}>test-undo</button>
      <MasterEditor value={history.value} onChange={history.set} flags={flags} issues={issues} activeFlag={active} />
    </>
  );
}

describe("MasterEditor", () => {
  it("edits fields, toggles pins, reorders and adds bullets", async () => {
    const user = userEvent.setup();
    let latest: Json = null;
    render(<Harness onValue={(doc) => { latest = doc; }} />);

    await user.clear(screen.getByLabelText(/Full name/));
    await user.type(screen.getByLabelText(/Full name/), "Sam Lee");
    expect(getIn(latest, ["basics", "name"])).toBe("Sam Lee");

    await user.click(screen.getAllByRole("button", { name: "Pin role (always include)" })[0]!);
    expect(getIn(latest, ["work", 0, "pin"])).toBe(true);

    await user.click(screen.getAllByRole("button", { name: "Move role down" })[0]!);
    expect(getIn(latest, ["work", 0, "company"])).toBe("Initech");

    // Open Acme (now second) and add a bullet; the new bullet gets focus.
    await user.click(screen.getByRole("button", { name: /Engineer · Acme/ }));
    await user.click(screen.getByRole("button", { name: "Add bullet" }));
    expect(getIn(latest, ["work", 1, "highlights"])).toHaveLength(3);
    await user.keyboard("Cut costs by 30%.");
    expect(getIn(latest, ["work", 1, "highlights", 2, "text"])).toBe("Cut costs by 30%.");

    await user.click(screen.getByRole("button", { name: "test-undo" }));
    expect(getIn(latest, ["work", 1, "highlights", 2, "text"])).toBe("");
  });

  it("shows server errors and import flags where they point", async () => {
    const flags: ImportFlag[] = [
      { key: "note-0", kind: "note", severity: "warning", message: "End date unclear", targetId: "acme", field: "endDate", path: "work[0].endDate" },
      { key: "fid", kind: "fidelity", severity: "warning", message: "Not in the original", targetId: "acme.b1", field: "text", path: "work[0].highlights[0]" },
    ];
    render(<Harness flags={flags} issues={new Map([["work[1].startDate", 'expected YYYY, YYYY-MM, or YYYY-MM-DD, got "spring"']])} active={flags[0]} />);
    const acme = screen.getByRole("button", { name: /Engineer · Acme/ });
    expect(within(acme).getByText("2")).toBeInTheDocument(); // two flags inside this role
    // The active flag opens its item; the item with a server error opens too.
    expect(await screen.findByDisplayValue("Led the migration.")).toBeInTheDocument();
    expect(screen.getByText(/got "spring"/)).toBeInTheDocument();
    const endField = document.querySelector('[data-field-target="acme:endDate"]');
    expect(endField?.querySelector(".ring-amber-400")).not.toBeNull();
  });

  it("adds a section that was empty", async () => {
    const user = userEvent.setup();
    let latest: Json = null;
    render(<Harness onValue={(doc) => { latest = doc; }} />);
    await user.click(screen.getByRole("button", { name: "Certifications" }));
    fireEvent.change(screen.getAllByLabelText(/^Name/).at(-1)!, { target: { value: "CKA" } });
    expect(getIn(latest, ["certifications", 0, "name"])).toBe("CKA");
  });
});
