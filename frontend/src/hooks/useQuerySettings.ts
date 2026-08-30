import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_QUERY_SETTINGS,
  getQuerySettings,
  setQuerySettings,
  type QuerySettings,
} from "../lib/querySettings";

/**
 * React state wrapper around the per-session query settings (chat history on/off,
 * history depth, explanation on/off) persisted in localStorage. Re-reads from storage
 * whenever sessionId changes so switching sessions shows that session's own settings.
 */
export function useQuerySettings(sessionId: string) {
  const [settings, setSettings] = useState<QuerySettings>(() =>
    sessionId ? getQuerySettings(sessionId) : DEFAULT_QUERY_SETTINGS
  );

  useEffect(() => {
    setSettings(sessionId ? getQuerySettings(sessionId) : DEFAULT_QUERY_SETTINGS);
  }, [sessionId]);

  const update = useCallback(
    (patch: Partial<QuerySettings>) => {
      setSettings((prev) => {
        const next = { ...prev, ...patch };
        if (sessionId) setQuerySettings(sessionId, next);
        return next;
      });
    },
    [sessionId]
  );

  return {
    settings,
    setUseChatHistory: (value: boolean) => update({ useChatHistory: value }),
    setHistoryLimit: (value: number) => update({ historyLimit: value }),
    setIncludeExplanation: (value: boolean) => update({ includeExplanation: value }),
  };
}
