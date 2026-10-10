export interface ContextNote {
  id: string;
  title: string;
  path: string;
  excerpt: string;
  chunks: number;
  updated_at: string;
}

export const PREVIEW_NOTES: ContextNote[] = [
  { id: "preview-1", title: "The art of noticing", path: "Ideas/The art of noticing.md", excerpt: "Good ideas often begin with a small observation. Make room for the things that catch your attention: a sentence, a question, a pattern you haven’t seen before.", chunks: 4, updated_at: "2026-09-28T12:00:00Z" },
  { id: "preview-2", title: "Building something meaningful", path: "Projects/Building something meaningful.md", excerpt: "Start with the problem, stay curious about the people, and let the details follow. A collection of notes on turning an idea into something useful.", chunks: 6, updated_at: "2026-09-27T12:00:00Z" },
  { id: "preview-3", title: "A field guide to good questions", path: "Ideas/A field guide to good questions.md", excerpt: "What are we assuming? What would change our minds? Keep the questions that open a door rather than close a conversation.", chunks: 3, updated_at: "2026-09-26T12:00:00Z" },
  { id: "preview-4", title: "Design, slowly", path: "Reading/Design slowly.md", excerpt: "Thoughts on making thoughtful things. On restraint, rhythm, and the space between what a product does and how it feels.", chunks: 5, updated_at: "2026-09-25T12:00:00Z" },
  { id: "preview-5", title: "Notes from the margins", path: "Reading/Notes from the margins.md", excerpt: "The sentences worth returning to, and the thoughts they left behind. Reading is a conversation; these are the parts I want to remember.", chunks: 2, updated_at: "2026-09-24T12:00:00Z" },
  { id: "preview-6", title: "Creative connections", path: "Ideas/Creative connections.md", excerpt: "An idea becomes more interesting when it meets another. Look for the unexpected threads running through what you already know.", chunks: 4, updated_at: "2026-09-23T12:00:00Z" },
  { id: "preview-7", title: "The next chapter", path: "Projects/The next chapter.md", excerpt: "A place for the possibilities that aren’t projects yet. Things to learn, places to explore, and experiments that might be worth trying.", chunks: 3, updated_at: "2026-09-22T12:00:00Z" },
  { id: "preview-8", title: "Small things, well made", path: "Reading/Small things well made.md", excerpt: "Collecting examples of care: a considered interaction, a beautiful explanation, a tool that gets out of the way.", chunks: 2, updated_at: "2026-09-21T12:00:00Z" },
];

export function collectionOf(note: ContextNote): string {
  return note.path.includes("/") ? note.path.split("/")[0] : "Notes";
}

export function filterNotes(notes: ContextNote[], query: string, collection: string, recent: boolean) {
  const search = query.trim().toLocaleLowerCase();
  const matching = notes.filter((note) => (collection === "All collections" || collectionOf(note) === collection)
    && `${note.title} ${note.path} ${note.excerpt}`.toLocaleLowerCase().includes(search));
  return recent ? [...matching].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 20) : matching;
}
