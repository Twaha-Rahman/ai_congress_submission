export const maxSlackBytes: number;
export const maxSlackMessages: number;
export interface SavedSlackMessage extends Record<string, unknown> { text: string; ts: string; }
export interface SavedSlackData {
  payload: { channel?: Record<string, unknown>; events: SavedSlackMessage[] };
  count: number; channelLabel: string; oldest: string; newest: string;
}
export function slackTimestamp(raw: unknown): string;
export function parseSavedSlack(text: string): SavedSlackData;
export function buildSavedSlackManifest(metadata: unknown, newest: string): {
  schema_version: string; source_identity: string; version_label: string; policy_family: string;
  source_type: "slack"; subject: "general_policy"; authority: "informal";
  scope: { kind: "policy"; description: string; attributes: Record<string, string> };
  effective_from: null; effective_to: null; publication_time: string;
  sensitivity: "demo_shareable" | "restricted";
  permissions: { hosted_model: boolean; office_export: false };
};
