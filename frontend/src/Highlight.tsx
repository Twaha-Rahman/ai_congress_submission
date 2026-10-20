import { Fragment } from "react";
import { searchRanges, matchingExcerpt } from "./searchHighlight";
import { findingTag, findingTitle, scopeLabel, typeLabels } from "./presentation";
import type { Finding } from "./types";

export default function Highlight({
  text,
  query,
  identifier = false,
}: {
  text: string;
  query: string;
  identifier?: boolean;
}) {
  const ranges = searchRanges(text, query, identifier);
  return (
    <span>
      {ranges.map((range, index) => (
        <Fragment key={range.start}>
          {text.slice(index ? ranges[index - 1].end : 0, range.start)}
          <mark className="search-match">{text.slice(range.start, range.end)}</mark>
        </Fragment>
      ))}
      {text.slice(ranges.at(-1)?.end || 0)}
    </span>
  );
}

/** Show the reason for a result when its match is outside the usual queue labels. */
export function QueueMatchContext({ finding, query }: {
  finding: Finding;
  query: string;
}) {
  const visibleMatch = [
    findingTitle(finding),
    typeLabels[finding.finding_type],
    scopeLabel(finding.affected_scope),
  ].some((text) => searchRanges(text, query).length) ||
    searchRanges(findingTag(finding), query, true).length;
  if (visibleMatch) return null;
  if (searchRanges(finding.finding_id, query, true).length)
    return (
      <p className="queue-id-match">
        <Highlight text={finding.finding_id} query={query} identifier />
      </p>
    );
  const quote = finding.evidence.find((e) => searchRanges(e.quote, query).length)?.quote;
  return quote ? (
    <p className="queue-quote-match">
      “<Highlight text={matchingExcerpt(quote, query)} query={query} />”
    </p>
  ) : null;
}
