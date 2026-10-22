import type { Source } from "./types";

export type WithdrawalScope = "version" | "all_versions";
export interface WithdrawalPreview {
  source_id: string;
  source_identity: string;
  scope: WithdrawalScope;
  versions: {
    source_id: string;
    version_label: string;
    status: string;
    ingested_at: string;
  }[];
  version_count: number;
  finding_count: number;
  open_finding_count: number;
  job_count: number;
  answer_count: number;
  snapshot: string;
}

/** A withdrawn source stays selectable for an explicit earlier knowledge cutoff. */
export function availableSource(source: Source, knownAt?: string) {
  if (source.status !== "withdrawn") return true;
  if (!knownAt || !source.withdrawal?.withdrawn_at) return false;
  const moment = Date.parse(
    /(?:Z|[+-]\d{2}:?\d{2})$/i.test(knownAt) ? knownAt : `${knownAt}Z`,
  );
  return (
    Number.isFinite(moment) &&
    moment < Date.parse(source.withdrawal.withdrawn_at)
  );
}
