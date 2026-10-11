# Knowledge sources: PDFs, code, text and websites

Besides Markdown notes, Page can use other files you keep in the vault folder, and
pages you save from the web. Search, Ask and the MCP server use all of them.

## Files in the vault

Put files anywhere in the vault folder. Page finds them on the next search, ask or
refresh. It never changes them.

| Kind | Extensions | How text is read |
|---|---|---|
| PDF | `.pdf` | Text from each page with [pypdf](https://pypdf.readthedocs.io), marked `[Page n]` |
| Code | `.py .js .jsx .ts .tsx .rs .go .java .kt .swift .c .h .cpp .hpp .cs .rb .php .sh .sql .html .css .json .yaml .yml .toml` | As UTF-8 text |
| Text | `.txt` | As UTF-8 text |

Extensions match in any case (`Scan.PDF` works).

Skipped:
- hidden files and folders;
- symlinks;
- the folders `node_modules`, `__pycache__`, `venv`, `target`, `dist` and `build`;
- files over 25 MB;
- more than 5,000 sources per vault.

Text beyond 2 million characters per file is cut off. Files whose text can't be
read are listed but not searchable. Examples are scanned PDFs with no text layer,
password-protected PDFs, and code that isn't UTF-8.

Sources are read-only documents, not notes:
- In the app they appear in **Files** with their own icons. Clicking one opens a viewer
  with line numbers.
- Search results and Ask citations that point to a source open it at the cited lines.
- A source's ID comes from its path, so a moved file counts as a new document.
- Sources don't take part in wiki links or the graph.

Extracted text is cached in memory, keyed by file size, modification time and inode.
Embeddings are cached with the notes' embeddings, so unchanged files aren't
re-processed.

## Websites

**Add website** in the sidebar asks for an address. Page then:
1. downloads the page once;
2. keeps its readable content as Markdown: headings, paragraphs, lists, links and
   code, without scripts, styles, navigation or forms;
3. saves it as a new note at `web/<host>/<title>.md`, adding `-2`, `-3` … if that
   name is taken.

The note starts with front matter recording the source URL and save date. After that
it's an ordinary note: you can edit it, link to it, and it appears in the graph.

Limits and safety:
- Only `http` and `https` addresses are accepted, without user names.
- Addresses that resolve to this computer are refused (loopback, link-local,
  unspecified and multicast). Redirects are checked the same way.
- Only HTML and plain text pages up to 5 MB are saved. The download times out
  after 20 seconds.
- Pages that need JavaScript to show their content, or a login, save little or
  nothing.
- Saving a website is the only time Page contacts a site. The page isn't refreshed
  later; save it again to get a new copy.

## API and MCP

- `GET /api/v1/vaults/{id}/sources` lists sources (`id`, `relative_path`, `kind`,
  `size_bytes`).
- `GET /api/v1/vaults/{id}/sources/{source_id}` returns one source's extracted text and
  a `revision` (the SHA-256 of the file).
- `POST /api/v1/vaults/{id}/web-pages` with `{"url": "..."}` saves a page and returns
  the new note, like creating one.
- Search hits and Ask sources include `kind`: `note`, `pdf`, `code` or `text`.

Error codes:

| Code | Status | Meaning |
|---|---|---|
| `source_not_found` | 404 | No source has that ID |
| `source_unreadable` | 422 | Its text couldn't be extracted |
| `invalid_url` | 422 | The address isn't a public http(s) address |
| `unsupported_page` | 415 | The address isn't an HTML or text page, or it's over 5 MB |
| `web_fetch_failed` | 502 | The page couldn't be downloaded |

The MCP tools return sources alongside notes, each with a `kind`. `read_note` also
reads a source by its path.

## Storage

Vector-cache migration 4 lets cached embeddings belong to sources as well as notes.
It removes the cache's foreign key to the notes table and keeps the existing vectors.
