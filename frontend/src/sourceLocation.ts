export function normalizedPassage(text: string) {
  return text.normalize("NFKC").replace(/[\s\u00ad]+/g, "");
}

/** Match preserved text to PDF text runs, tolerating only layout whitespace/ligatures. */
export function locatePassage(items: { str: string }[], quote: string) {
  let text = "";
  const ranges = items.map((item) => {
    const start = text.length;
    text += normalizedPassage(item.str);
    return { start, end: text.length };
  });
  const target = normalizedPassage(quote);
  const start = target ? text.indexOf(target) : -1;
  if (start < 0) return { indices: [] as number[], ambiguous: false };
  if (text.indexOf(target, start + 1) >= 0)
    return { indices: [] as number[], ambiguous: true };
  return {
    indices: ranges.flatMap((range, i) =>
      range.end > range.start &&
      range.end > start &&
      range.start < start + target.length
        ? [i]
        : [],
    ),
    ambiguous: false,
  };
}

export function savedSourcePassage(raw: string, quote: string) {
  const text = JSON.stringify(JSON.parse(raw), null, 2);
  const target = JSON.stringify(quote).slice(1, -1);
  const start = target ? text.indexOf(target) : -1;
  return { text, start, end: start < 0 ? -1 : start + target.length };
}
