import type { ActivityEvent, ActivityPage } from "./types";

function eventOrder(a: ActivityEvent,b:ActivityEvent){
  const stamp=(event:ActivityEvent)=>event.created_at.includes(".")?event.created_at:event.created_at.replace("Z",".000000Z");
  const x=stamp(a),y=stamp(b);
  return x===y?(a.id<b.id?1:a.id>b.id?-1:0):x<y?1:-1;
}
/** Refresh the visible window without discarding older loaded records or skipping a new gap. */
export function mergeActivity(previous:ActivityPage|null,page:ActivityPage,append:boolean,preserve:boolean):ActivityPage{
  if(!previous||!append&&!preserve)return page;
  const events=new Map(previous.events.map(event=>[event.id,event]));
  for(const event of page.events)events.set(event.id,event);
  const overlap=previous.events.some(event=>event.id===page.events.at(-1)?.id);
  return {...page,events:[...events.values()].sort(eventOrder),next_cursor:!append&&overlap?previous.next_cursor:page.next_cursor};
}
