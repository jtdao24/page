import type { NoteSummaryResponse } from "../core/types";

export interface FolderNode {
  kind: "folder";
  /** Stable key: the folder's path within the vault. */
  key: string;
  name: string;
  path: string;
  children: TreeNode[];
}

export interface NoteNode {
  kind: "note";
  /** Stable key: the vault and note UUIDs. */
  key: string;
  name: string;
  note: NoteSummaryResponse;
}

export type TreeNode = FolderNode | NoteNode;

function compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * Build nested folders from note summaries only. Ordering is lexical by
 * code unit (folders and notes interleaved by name), then by UUID, so it
 * does not depend on the list order or the user's locale.
 */
export function buildTree(notes: readonly NoteSummaryResponse[]): TreeNode[] {
  const root: FolderNode = { kind: "folder", key: "", name: "", path: "", children: [] };
  const folders = new Map<string, FolderNode>([["", root]]);
  for (const note of notes) {
    const parts = note.relative_path.split("/");
    let parent = root;
    for (const part of parts.slice(0, -1)) {
      const path = parent.path ? `${parent.path}/${part}` : part;
      let folder = folders.get(path);
      if (folder === undefined) {
        folder = { kind: "folder", key: `folder:${path}`, name: part, path, children: [] };
        folders.set(path, folder);
        parent.children.push(folder);
      }
      parent = folder;
    }
    parent.children.push({
      kind: "note",
      key: `note:${note.vault_id}:${note.id}`,
      name: parts[parts.length - 1],
      note,
    });
  }
  const sort = (nodes: TreeNode[]) => {
    nodes.sort(
      (left, right) =>
        compare(left.name, right.name) ||
        compare(left.kind, right.kind) ||
        compare(left.key, right.key),
    );
    for (const node of nodes) if (node.kind === "folder") sort(node.children);
  };
  sort(root.children);
  return root.children;
}
