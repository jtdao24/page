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
});
