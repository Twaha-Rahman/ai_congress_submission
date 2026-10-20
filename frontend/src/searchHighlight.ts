export function searchRanges(text: string, search: string, identifier = false) {
  let query = search.trim().toLowerCase();
  if (query.startsWith("#")) query = identifier ? query.slice(1) : "";
  if (!query) return [] as { start: number; end: number }[];

  // Case folding can expand characters (e.g. İ). Map matches back to the original
  // text so highlighting never changes or splits a source character.
  const starts: number[] = [];
  const ends: number[] = [];
  let offset = 0;
  for (const character of text) {
    for (let i = 0; i < character.toLowerCase().length; i++) {
      starts.push(offset);
      ends.push(offset + character.length);
    }
    offset += character.length;
  }
  const folded = text.toLowerCase();
  const ranges: { start: number; end: number }[] = [];
  let from = 0;
  while (from < folded.length) {
    const start = folded.indexOf(query, from);
    if (start === -1) break;
    const range = { start: starts[start], end: ends[start + query.length - 1] };
    const previous = ranges.at(-1);
    if (previous && previous.end > range.start) previous.end = range.end;
    else ranges.push(range);
    from = start + query.length;
  }
  return ranges;
}

export function matchingExcerpt(text: string, search: string, length = 140) {
  const match = searchRanges(text, search)[0];
  if (!match) return "";
  if (text.length <= length) return text;
  const start = Math.max(0, match.start - 35);
  const end = Math.min(text.length, Math.max(start + length, match.end + 35));
  return `${start ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`;
}
