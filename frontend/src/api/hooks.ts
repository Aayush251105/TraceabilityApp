import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { Health, RunCard, RunDetail, RunEvent } from "./types";

export const keys = {
  runs: ["runs"] as const,
  run: (id: number) => ["run", id] as const,
  health: ["health"] as const,
};

export function useRuns() {
  return useQuery({
    queryKey: keys.runs,
    queryFn: () => api.get<{ runs: RunCard[] }>("/api/runs").then((r) => r.runs),
    refetchInterval: 5000,
  });
}

export function useRun(id: number | null) {
  return useQuery({
    queryKey: keys.run(id ?? -1),
    queryFn: () => api.get<RunDetail>(`/api/runs/${id}`),
    enabled: id != null,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => api.get<Health>("/api/health"),
    refetchInterval: 30000,
  });
}

export type StreamState = "connecting" | "open" | "closed";

/**
 * Live updates for one run (server-sent events).  `run` snapshots replace the
 * cached run detail; `log` events are collected in order.  The browser
 * reconnects by itself and resumes after the last event id it saw.
 */
export function useRunStream(id: number | null) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");

  useEffect(() => {
    if (id == null) return;
    setEvents([]);
    setState("connecting");
    const source = new EventSource(`/api/runs/${id}/stream`);
    source.onopen = () => setState("open");
    source.onerror = () => setState(source.readyState === EventSource.CLOSED ? "closed" : "connecting");
    source.addEventListener("run", (e) => {
      const snap = JSON.parse((e as MessageEvent).data) as RunDetail;
      qc.setQueryData<RunDetail>(keys.run(id), (old) => ({ ...old, ...snap }));
    });
    source.addEventListener("log", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as RunEvent;
      setEvents((prev) => (prev.length && prev[prev.length - 1].event_id >= ev.event_id ? prev : [...prev, ev]));
    });
    return () => source.close();
  }, [id, qc]);

  return { events, state };
}
