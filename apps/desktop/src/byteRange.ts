/** Convert a UTF-8 byte range [start, end) of `text` to a UTF-16 string range. */
export function byteRangeToCharRange(text: string, start: number, end: number): [number, number] {
  const bytes = new TextEncoder().encode(text);
  const decoder = new TextDecoder();
  const from = decoder.decode(bytes.subarray(0, Math.min(start, bytes.length))).length;
  const to = decoder.decode(bytes.subarray(0, Math.min(end, bytes.length))).length;
  return [from, to];
}
