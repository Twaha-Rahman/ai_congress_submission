import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeActivity } from "./activityRecords";
import type { ActivityEvent, ActivityPage } from "./types";
const event=(id:string,time:string):ActivityEvent=>({id,created_at:time,category:"transfer",outcome:"delivered",description:"",title:"",target_id:id,details:{}});
const page=(events:ActivityEvent[],next_cursor=""):ActivityPage=>({events,next_cursor,summary:{} as ActivityPage["summary"],model_calls:{}});
test("activity refresh preserves loaded history, updates existing records and retains the next unseen cursor",()=>{
  const previous=page([event("a","2026-10-21T00:00:00.000002Z"),event("b","2026-10-21T00:00:00Z")],"older");
  const fresh=page([event("c","2026-10-21T00:00:00.000003Z"),{...previous.events[0],outcome:"failed"}],"new-window");
  const merged=mergeActivity(previous,fresh,false,true);
  assert.deepEqual(merged.events.map(item=>item.id),["c","a","b"]);
  assert.equal(merged.next_cursor,"older");assert.equal(merged.events[1].outcome,"failed");
  const noOverlap=mergeActivity(previous,page([event("d","2026-10-22T00:00:00Z")],"gap"),false,true);
  assert.equal(noOverlap.next_cursor,"gap");
  assert.deepEqual(mergeActivity(noOverlap,page([event("e","2026-10-21T12:00:00Z"),previous.events[0]],"next"),true,true).events.map(item=>item.id),["d","e","a","b"]);
  assert.deepEqual(mergeActivity(previous,fresh,false,false),fresh);
});
