import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { HealthCheck } from "../api/types";

interface AppStateValue {
  health: HealthCheck | null;
  healthError: string | null;
  refreshHealth: () => Promise<void>;
}

const AppStateContext = createContext<AppStateValue | undefined>(undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const intervalRef = useRef<number | undefined>(undefined);

  const refreshHealth = useCallback(async () => {
    try {
      const result = await api.health();
      setHealth(result);
      setHealthError(null);
    } catch (err) {
      setHealthError(err instanceof Error ? err.message : "Failed to reach the API");
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    intervalRef.current = window.setInterval(refreshHealth, 15000);
    return () => window.clearInterval(intervalRef.current);
  }, [refreshHealth]);

  return (
    <AppStateContext.Provider value={{ health, healthError, refreshHealth }}>{children}</AppStateContext.Provider>
  );
}

export function useAppState(): AppStateValue {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState must be used within AppStateProvider");
  return ctx;
}
