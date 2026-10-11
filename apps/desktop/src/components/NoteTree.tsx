import type { SourceSummaryResponse } from "../core/types";
import type { TreeNode } from "../workspace/tree";
import { Icon } from "./Icon";

export function NoteTree({ nodes, selected, disabled, onSelect, onOpenSource }: {
  nodes: TreeNode[];
  selected: string | undefined;
  disabled: boolean;
  onSelect: (id: string) => void;
  onOpenSource?: (source: SourceSummaryResponse) => void;
}) {
  return <ul className="note-tree">
    {nodes.map((node) => <li key={node.key}>
      {node.kind === "folder" ? <details open>
        <summary className="folder-row"><Icon name="folder" size={14} /><span>{node.name}</span></summary>
        <NoteTree nodes={node.children} selected={selected} disabled={disabled} onSelect={onSelect} onOpenSource={onOpenSource} />
      </details> : node.kind === "source" ? <button
        className={`note-row source-row ${selected === node.source.id ? "is-selected" : ""}`}
        aria-current={selected === node.source.id ? "page" : undefined}
        title={`${node.source.relative_path} · read-only ${node.source.kind === "pdf" ? "PDF" : node.source.kind}`}
        onClick={() => onOpenSource?.(node.source)}
      ><Icon name={node.source.kind} size={14} /><span>{node.name}</span></button> : <button
        className={`note-row ${selected === node.note.id ? "is-selected" : ""}`}
        disabled={disabled} aria-current={selected === node.note.id ? "page" : undefined}
        title={node.note.relative_path} onClick={() => onSelect(node.note.id)}
      ><Icon name="note" size={14} /><span>{node.name}</span></button>}
    </li>)}
  </ul>;
}
