import type {
  Finding,
  FindingResponse,
  Office,
  ReviewAction,
  ReviewState,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers: {
      ...options.headers,
      "X-Meridian-UI": "1",
      ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
    },
  });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401 && body.error?.code === "unauthenticated")
      window.dispatchEvent(new Event("meridian:unauthenticated"));
    throw new ApiError(
      response.status,
      body.error?.code || "request_failed",
      body.error?.message || "The request could not be completed.",
      body.error?.detail || {},
    );
  }
  return body as T;
}

export async function getFinding(
  office: Office,
  id: string,
  signal?: AbortSignal,
) {
  const response = await api<FindingResponse>(
    `${office}/findings/${encodeURIComponent(id)}`,
    { signal },
  );
  const { payload, ...record } = response.finding;
  return {
    finding: { ...payload, ...record } as Finding,
    reviews: response.reviews || [],
  };
}

export function reviewFinding(
  office: Office,
  id: string,
  action: ReviewAction,
  reason: string,
  revisions: string[],
  snapshotId: string,
) {
  return api<{ new_state: ReviewState; actor: string; event_id: string }>(
    `${office}/findings/${encodeURIComponent(id)}/reviews`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        reason,
        referenced_revision_ids: revisions,
        expected_snapshot_id: snapshotId,
      }),
    },
  );
}
