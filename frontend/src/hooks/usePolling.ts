import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch now and then every `interval` ms; `refresh` forces an immediate reload. */
export function usePolling<T>(load: () => Promise<T>, interval: number, enabled = true) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    refresh();
    const timer = window.setInterval(refresh, interval);
    return () => window.clearInterval(timer);
  }, [refresh, interval, enabled]);

  return { data, error, refresh };
}
