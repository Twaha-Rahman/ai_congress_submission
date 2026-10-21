import { searchRanges } from "./searchHighlight";
import type { VersionDiff } from "./types";

type Passage = VersionDiff["passages"][number];
/** Split at both diff and search boundaries without changing literal source text. */
export function versionTextRuns(passage: Passage, side: "before" | "after", query: string) {
  const part=passage[side];
  if(!part)return [];
  const chunks=passage.kind==="changed"?passage.chunks.filter(chunk=>chunk.kind!==(side==="before"?"added":"removed")):[{kind:passage.kind==="added"?"added":passage.kind==="removed"?"removed":"unchanged",text:part.text}];
  let offset=0;
  const spans=chunks.map(chunk=>{const start=offset;offset+=chunk.text.length;return {...chunk,start,end:offset};});
  const matches=searchRanges(part.text,query);
  const cuts=[...new Set([0,part.text.length,...spans.flatMap(span=>[span.start,span.end]),...matches.flatMap(match=>[match.start,match.end])])].sort((a,b)=>a-b);
  return cuts.slice(0,-1).map((start,index)=>({text:part.text.slice(start,cuts[index+1]),kind:spans.find(span=>span.start<=start&&start<span.end)?.kind||"unchanged",matched:matches.some(match=>match.start<=start&&start<match.end)}));
}
