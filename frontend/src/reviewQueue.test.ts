import { test } from "node:test";
import assert from "node:assert/strict";
import { reviewQueue, unreviewedFindings } from "./reviewQueue";
import { readView, selectedFinding } from "./viewState";
import type { Finding } from "./types";
const finding=(id:string,state:Finding["review_state"],source="source"):Finding=>({finding_id:id,review_state:state,finding_type:"contradiction",subject:"general_policy",severity:"high",created_at:"2026-10-22T00:00:00Z",detail:{},affected_scope:{kind:"policy",description:"All staff"},evidence:[{source_id:source,quote:"Expenses require approval"}]} as Finding);

test("reviewed findings leave the queue and count while saved links retain access to their details",()=>{
  const records=[finding("open","open"),finding("ack","acknowledged"),finding("resolved","resolved"),finding("dismissed","dismissed")];
  const legacy=readView("?state=resolved");
  assert.deepEqual(reviewQueue(records,legacy).map(item=>item.finding_id),["open"]);
  assert.equal(unreviewedFindings(records).length,1);
  const after=records.map(item=>item.finding_id==="open"?{...item,review_state:"acknowledged" as const}:item);
  assert.deepEqual(reviewQueue(after,readView("")),[]);assert.equal(unreviewedFindings(after).length,0);
  assert.equal(selectedFinding(readView("?finding=resolved"),after,[]).id,"resolved");
  assert.equal(records[0].review_state,"open");
});
test("queue filtering changes visible results without changing the global unreviewed count",()=>{
  const records=[finding("one","open","first"),finding("two","open","second"),finding("reviewed","resolved","first")];
  assert.deepEqual(reviewQueue(records,{...readView(""),forSource:"first",search:"expenses"}).map(item=>item.finding_id),["one"]);
  assert.deepEqual(reviewQueue(records,{...readView(""),search:"missing"}),[]);
  assert.equal(unreviewedFindings(records).length,2);
});
