import type { TreeNode } from "../workspace/tree";
import { Icon } from "./Icon";

export function NoteTree({ nodes, selected, disabled, onSelect }: {
  nodes: TreeNode[];
  selected: string | undefined;
  disabled: boolean;
  onSelect: (id: string) => void;
}) {
  return <ul className="note-tree">
    {nodes.map((node) => <li key={node.key}>
      {node.kind === "folder" ? <details open>
        <summary className="folder-row"><Icon name="folder" size={14} /><span>{node.name}</span></summary>
        <NoteTree nodes={node.children} selected={selected} disabled={disabled} onSelect={onSelect} />
      </details> : <button
        className={`note-row ${selected === node.note.id ? "is-selected" : ""}`}
        disabled={disabled} aria-current={selected === node.note.id ? "page" : undefined}
        title={node.note.relative_path} onClick={() => onSelect(node.note.id)}
      ><Icon name="note" size={14} /><span>{node.name}</span></button>}
    </li>)}
  </ul>;
}
