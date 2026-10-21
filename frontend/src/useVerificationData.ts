import { useEffect, useRef, useState } from "react";

/** Independent, keyed reads: stale replies never replace another target's data. */
export function useVerificationData<T>(key: string, read: (signal: AbortSignal) => Promise<T>) {
  const reader = useRef(read);
  reader.current = read;
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string; data?: T; error: string; loading: boolean }>({ key: "", error: "", loading: false });
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, error: "", loading: true }));
    reader.current(controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ key, data, error: "", loading: false });
    }).catch(error => {
      if (!controller.signal.aborted) setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, error: error.message || "This information could not be loaded.", loading: false }));
    });
    return () => controller.abort();
  }, [key, revision]);
  return { data: key && state.key === key ? state.data : undefined,
    error: key && state.key === key ? state.error : "", loading: !!key && (state.key !== key || state.loading),
    retry: () => setRevision(value => value + 1) };
}
