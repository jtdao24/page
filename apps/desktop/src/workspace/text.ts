// Line-ending policy. Note content is never trimmed, normalized or given a
// final newline; only an explicit, confirmed conversion changes separators.

export type LineSeparator = "\n" | "\r\n" | "\r";

export interface LineEndings {
  /** The separator used to serialize the editor document. */
  separator: LineSeparator;
  /** True when the source mixes LF, CRLF and CR; the editor is then read-only. */
  mixed: boolean;
}

export function detectLineEndings(content: string): LineEndings {
  let crlf = 0;
  let cr = 0;
  let lf = 0;
  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    if (char === "\r") {
      if (content[index + 1] === "\n") {
        crlf += 1;
        index += 1;
      } else {
        cr += 1;
      }
    } else if (char === "\n") {
      lf += 1;
    }
  }
  const kinds = [crlf, cr, lf].filter((count) => count > 0).length;
  if (kinds > 1) return { separator: "\n", mixed: true };
  if (crlf > 0) return { separator: "\r\n", mixed: false };
  if (cr > 0) return { separator: "\r", mixed: false };
  // New notes and notes without separators use LF for inserted lines.
  return { separator: "\n", mixed: false };
}

/** Convert only the separators to LF; every other character is kept. */
export function convertToLf(content: string): string {
  return content.replace(/\r\n|\r/g, "\n");
}

export function describeSeparator(separator: LineSeparator): string {
  return separator === "\r\n" ? "CRLF" : separator === "\r" ? "CR" : "LF";
}
