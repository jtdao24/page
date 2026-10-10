export interface NoteSummary {
  id: string;
  title: string;
  path: string;
}

export interface Note extends NoteSummary {
  content: string;
}

export interface Backlink {
  source_id: string;
  source_title: string;
  excerpt: string;
  target_title: string;
}

export interface GraphNode {
  id: string;
  title: string;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ExtractedWikiLink {
  title: string;
  displayText: string | null;
  raw: string;
  start: number;
  end: number;
  targetId: string | null;
}
