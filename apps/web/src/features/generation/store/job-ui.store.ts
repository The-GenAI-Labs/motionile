import { create } from "zustand";

import type { ConnectionState } from "@/features/generation/types/generation.types";

interface JobUiState {
  connections: Readonly<Record<string, ConnectionState>>;
  collapsedScenes: Readonly<Record<string, readonly string[]>>;
  setConnection: (jobId: string, state: ConnectionState) => void;
  clearConnection: (jobId: string) => void;
  toggleScene: (jobId: string, sceneId: string) => void;
  reset: () => void;
}

export const useJobUiStore = create<JobUiState>()((set) => ({
  connections: {},
  collapsedScenes: {},
  setConnection: (jobId, state) => {
    set((current) => ({ connections: { ...current.connections, [jobId]: state } }));
  },
  clearConnection: (jobId) => {
    set((current) => ({
      connections: Object.fromEntries(
        Object.entries(current.connections).filter(([id]) => id !== jobId),
      ),
    }));
  },
  toggleScene: (jobId, sceneId) => {
    set((current) => {
      const collapsed = current.collapsedScenes[jobId] ?? [];
      return {
        collapsedScenes: {
          ...current.collapsedScenes,
          [jobId]: collapsed.includes(sceneId)
            ? collapsed.filter((id) => id !== sceneId)
            : [...collapsed, sceneId],
        },
      };
    });
  },
  reset: () => {
    set({ connections: {}, collapsedScenes: {} });
  },
}));

export const useJobConnection = (jobId: string): ConnectionState | null =>
  useJobUiStore((state) => state.connections[jobId] ?? null);
