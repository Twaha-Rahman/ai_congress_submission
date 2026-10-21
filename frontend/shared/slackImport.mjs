/** Shared browser/server validation for saved Slack message snapshots. */
export const maxSlackBytes = 5 * 1024 * 1024;
export const maxSlackMessages = 200;
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);

export function slackTimestamp(raw) {
  if (typeof raw !== "string") throw new Error("Each message needs a timestamp.");
  const value = raw.trim();
  const epoch = /^(\d{1,12})(?:\.(\d{1,6}))?$/.exec(value);
  if (epoch) {
    const date = new Date(Number(epoch[1]) * 1000);
    if (!Number.isFinite(date.valueOf()) || date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) throw new Error("A message timestamp is outside the supported calendar.");
    return `${date.toISOString().slice(0, 19)}.${(epoch[2] || "").padEnd(6, "0")}Z`;
  }
  const iso = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!iso) throw new Error("Use Slack epoch timestamps or ISO dates with a timezone for every message.");
  const wall = `${iso[1]}T${iso[2]}`;
  const probe = new Date(`${wall}Z`);
  if (!Number.isFinite(probe.valueOf()) || probe.toISOString().slice(0, 19) !== wall || probe.getUTCFullYear() < 1) throw new Error("A message contains an invalid calendar date or time.");
  const utc = new Date(`${wall}${iso[4]}`);
  if (!Number.isFinite(utc.valueOf()) || utc.getUTCFullYear() < 1 || utc.getUTCFullYear() > 9999) throw new Error("A message contains an invalid timezone.");
  return `${utc.toISOString().slice(0, 19)}.${(iso[3] || "").padEnd(6, "0")}Z`;
}

export function parseSavedSlack(text) {
  if (typeof text !== "string" || !text.trim()) throw new Error("Choose a nonempty saved Slack JSON file.");
  if (new TextEncoder().encode(text).length > maxSlackBytes) throw new Error("Choose a saved Slack file smaller than 5 MB.");
  let data;
  try { data = JSON.parse(text.replace(/^\uFEFF/, "")); }
  catch { throw new Error("This file is not valid JSON. Choose a saved Slack event or message batch."); }
  if (!object(data) || ("event" in data) === ("events" in data)) throw new Error("Use a saved JSON object containing either event or events. Full workspace exports and ZIP files are not supported.");
  const events = "event" in data ? [data.event] : data.events;
  if (!Array.isArray(events) || !events.length) throw new Error("The saved file contains no messages.");
  if (events.length > maxSlackMessages) throw new Error("Import up to 200 messages at a time. Split this batch into smaller files.");
  const channel = object(data.channel) ? { ...data.channel } : {};
  if (data.channel !== undefined && !object(data.channel) && typeof data.channel !== "string") throw new Error("The channel must be an ID or a channel object.");
  if (typeof data.channel === "string") channel.id = data.channel;
  if (channel.id !== undefined && (typeof channel.id !== "string" || !channel.id.trim() || channel.id.length > 128)) throw new Error("The saved channel ID is invalid.");
  const ids = new Set(channel.id ? [channel.id] : []);
  const times = [];
  let totalText = 0;
  const seen = new Set();
  const messages = events.map((item, index) => {
    if (!object(item) || (item.type !== undefined && item.type !== "message") ||
        (item.subtype && !["bot_message", "thread_broadcast"].includes(item.subtype))) throw new Error(`Message ${index + 1} is not a saved text-message snapshot. Edit/delete notifications must be saved as the current message instead.`);
    if (typeof item.text !== "string" || !item.text.trim()) throw new Error(`Message ${index + 1} has no text.`);
    if (item.channel !== undefined && (typeof item.channel !== "string" || !item.channel.trim() || item.channel.length > 128)) throw new Error(`Message ${index + 1} has an invalid channel.`);
    if (item.channel) ids.add(item.channel);
    const ts = item.ts || item.event_ts;
    const timestamp = slackTimestamp(ts);
    if (seen.has(timestamp)) throw new Error("The file contains multiple snapshots of the same message timestamp. Keep one current snapshot per message.");
    seen.add(timestamp); times.push(timestamp); totalText += item.text.length;
    if (item.thread_ts !== undefined) slackTimestamp(item.thread_ts);
    return { ...item, ts };
  });
  if (ids.size > 1) throw new Error("Import one channel per file so its access and applicability stay explicit.");
  const id = [...ids][0];
  if (id !== undefined && (typeof id !== "string" || !id.trim() || id.length > 128)) throw new Error("The saved channel ID is invalid.");
  if (channel.name !== undefined && (typeof channel.name !== "string" || !channel.name.trim() || channel.name.length > 128)) throw new Error("The saved channel name is invalid.");
  if (id) channel.id = id;
  for (const item of messages) {
    if (item.thread_ts && slackTimestamp(item.thread_ts) !== slackTimestamp(item.ts) && !seen.has(slackTimestamp(item.thread_ts))) throw new Error("A thread reply is missing its parent. Include the parent message in the saved batch.");
  }
  if (totalText > 100000) throw new Error("The batch contains too much text. Split it into files with up to 100,000 message characters.");
  times.sort();
  return { payload: { ...(Object.keys(channel).length ? { channel } : {}), events: messages }, count: messages.length,
    channelLabel: channel.name ? `#${channel.name}` : id || "Channel not recorded", oldest: times[0], newest: times.at(-1) };
}

export function buildSavedSlackManifest(metadata, newest) {
  if (!object(metadata)) throw new Error("Complete the saved Slack source details.");
  const required = (value, label, max = 128) => {
    if (typeof value !== "string" || !value.trim() || value.trim().length > max) throw new Error(`${label} must contain between 1 and ${max} characters.`);
    return value.trim();
  };
  const identity = required(metadata.source_identity, "Source name");
  if (identity.startsWith("slack:")) throw new Error("Choose a source name without the reserved slack: prefix.");
  if (!object(metadata.scope) || metadata.scope.kind !== "policy" || !object(metadata.scope.attributes || {})) throw new Error("Describe who and what these messages apply to.");
  const pairs = Object.entries(metadata.scope.attributes || {}).map(([key, value]) => [required(key, "Scope label"), required(value, "Scope value", 500)]);
  if (new Set(pairs.map(([key]) => key)).size !== pairs.length) throw new Error("Use each scope label only once.");
  const attributes = Object.fromEntries(pairs);
  if (!["demo_shareable", "restricted"].includes(metadata.sensitivity)) throw new Error("Choose who can read this source.");
  if (!object(metadata.permissions) || typeof metadata.permissions.hosted_model !== "boolean") throw new Error("Choose the model-processing permission.");
  return { schema_version: "1", source_identity: identity,
    version_label: required(metadata.version_label, "Version"), policy_family: required(metadata.policy_family, "Policy category"),
    source_type: "slack", subject: "general_policy", authority: "informal",
    scope: { kind: "policy", description: required(metadata.scope.description, "Applicability", 1000), attributes },
    effective_from: null, effective_to: null, publication_time: slackTimestamp(newest),
    sensitivity: metadata.sensitivity, permissions: { hosted_model: metadata.permissions.hosted_model, office_export: false } };
}
