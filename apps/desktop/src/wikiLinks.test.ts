import { describe, expect, it } from "vitest";
import type { NoteSummary } from "./types";
import { extractWikiLinks, resolveTitle } from "./wikiLinks";

const notes: NoteSummary[] = [
  { id: "Alpha.md", title: "Alpha", path: "Alpha.md" },
  { id: "projects/Alpha.md", title: "Alpha", path: "projects/Alpha.md" },
  { id: "Beta.md", title: "Beta", path: "Beta.md" },
];

describe("wiki link parsing", () => {
  it("extracts titles and aliases outside code", () => {
    const text = "See [[Beta|the note]] and `[[Beta]]`\n```\n[[Alpha]]\n```\n";
    const links = extractWikiLinks(text, notes);
    expect(links).toHaveLength(1);
    expect(links[0]?.title).toBe("Beta");
    expect(links[0]?.displayText).toBe("the note");
    expect(links[0]?.targetId).toBe("Beta.md");
  });

  it("resolves duplicates and leaves missing titles unresolved", () => {
    expect(resolveTitle("Missing", notes)).toBeNull();
    expect(resolveTitle("Alpha", notes)).toBe("Alpha.md");
    expect(resolveTitle("projects/Alpha", notes)).toBe("projects/Alpha.md");
  });
});
