import { describe, expect, it } from "vitest";
import { buildTree } from "./tree";
import { note } from "./testClient";

describe("summary sidebar", () => {
  it("orders nested paths lexically and preserves stable UUID keys", () => {
    const a = note("33333333-3333-4333-8333-333333333333", "", "ideas/a.md");
    const z = note("44444444-4444-4444-8444-444444444444", "", "ideas/z.md");
    const root = note(undefined, "", "A.md");
    const tree = buildTree([z, root, a]);
    expect(tree.map((node) => node.name)).toEqual(["A.md", "ideas"]);
    expect(tree[1].kind === "folder" && tree[1].children.map((node) => node.name)).toEqual(["a.md", "z.md"]);
    expect(tree).toEqual(buildTree([a, z, root]));
    expect(tree[0].key).toBe(`note:${root.vault_id}:${root.id}`);
    expect(buildTree([])).toEqual([]);
  });
  it("places read-only sources in the same folders as notes", () => {
    const plan = note(undefined, "", "papers/plan.md");
    const pdf = { id: "55555555-5555-4555-8555-555555555555", relative_path: "papers/study.pdf", kind: "pdf" as const, size_bytes: 10 };
    const code = { id: "66666666-6666-4666-8666-666666666666", relative_path: "timer.py", kind: "code" as const, size_bytes: 5 };
    const tree = buildTree([plan], [pdf, code]);
    expect(tree.map((node) => [node.kind, node.name])).toEqual([["folder", "papers"], ["source", "timer.py"]]);
    const papers = tree[0].kind === "folder" ? tree[0].children : [];
    expect(papers.map((node) => [node.kind, node.name])).toEqual([["note", "plan.md"], ["source", "study.pdf"]]);
    expect(papers[1].key).toBe(`source:${pdf.id}`);
  });
});
