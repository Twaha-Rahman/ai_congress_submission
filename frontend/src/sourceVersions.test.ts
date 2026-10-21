import { test } from "node:test";
import assert from "node:assert/strict";
import { versionTextRuns } from "./sourceVersions";
import type { VersionDiff } from "./types";

test("search crosses word-diff boundaries while retaining both exact source texts and change types",()=>{
  const row:VersionDiff["passages"][number]={kind:"changed",before:{clause_id:"a",page:1,section:null,text:"Staff may claim expenses."},after:{clause_id:"b",page:2,section:null,text:"Staff must claim expenses."},chunks:[{kind:"unchanged",text:"Staff "},{kind:"removed",text:"may"},{kind:"added",text:"must"},{kind:"unchanged",text:" claim expenses."}]};
  for(const side of ["before","after"] as const){
    const phrase=side==="before"?"may claim":"must claim";
    const runs=versionTextRuns(row,side,phrase);
    assert.equal(runs.map(run=>run.text).join(""),row[side]!.text);
    assert.equal(runs.filter(run=>run.matched).map(run=>run.text).join(""),phrase);
    assert.equal(runs.filter(run=>run.kind===(side==="before"?"removed":"added")).map(run=>run.text).join(""),side==="before"?"may":"must");
    assert.ok(runs.some(run=>run.matched&&run.kind==="unchanged"));
  }
  assert.deepEqual(versionTextRuns({...row,before:null},"before","Staff"),[]);
});
