import { describe, expect, it } from "vitest";
import { filterNotes, PREVIEW_NOTES } from "./library";

describe("Library", () => {
  it("finds notes by title, path, and excerpt and combines the collection filter", () => {
    expect(filterNotes(PREVIEW_NOTES, "  NOTICING  ", "All collections", false)[0].id).toBe("preview-1");
    expect(filterNotes(PREVIEW_NOTES, "unexpected threads", "Ideas", false)[0].id).toBe("preview-6");
    expect(filterNotes(PREVIEW_NOTES, "unexpected threads", "Reading", false)).toEqual([]);
    expect(filterNotes(PREVIEW_NOTES, "projects/", "All collections", false)).toHaveLength(2);
  });

  it("sorts recent notes without changing the source library", () => {
    const notes = [...PREVIEW_NOTES].reverse();
    expect(filterNotes(notes, "", "All collections", true)[0].id).toBe("preview-1");
    expect(notes[0].id).toBe("preview-8");
  });

  it("includes root-level notes in the Notes collection", () => {
    const rootNote = { ...PREVIEW_NOTES[0], path: "note.md" };
    expect(filterNotes([...PREVIEW_NOTES.slice(1), rootNote], "", "Notes", false)).toEqual([rootNote]);
  });
});
