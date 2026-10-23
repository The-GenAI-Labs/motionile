"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelTestbedRender,
  createGoldenRender,
  createTestbedRender,
  getTestbedRender,
  listBedMusicTracks,
  listGoldenCompositions,
} from "@/features/admin-render/api/admin-render.api";
import { buildGoldenRequest, buildTestbedForm } from "@/features/admin-render/multipart";
import { adminRenderKeys } from "@/features/admin-render/query-keys";
import {
  type GoldenFormValues,
  isTerminalStatus,
  type RenderFormValues,
} from "@/features/admin-render/schemas/admin-render.schema";

export const MUSIC_STALE_MS = 60_000;

export const useGoldenCompositions = () =>
  useQuery({
    queryKey: adminRenderKeys.golden(),
    queryFn: listGoldenCompositions,
    select: (catalog) => catalog.items,
  });

export const useBedMusicTracks = () =>
  useQuery({
    queryKey: adminRenderKeys.musicTracks(),
    queryFn: listBedMusicTracks,
    select: (list) => list.items,
    staleTime: MUSIC_STALE_MS,
  });

export const useCreateTestbedRender = () =>
  useMutation({
    mutationFn: (values: RenderFormValues) => createTestbedRender(buildTestbedForm(values)),
  });

export const useCreateGoldenRender = (name: string) =>
  useMutation({
    mutationFn: (values: GoldenFormValues) => createGoldenRender(name, buildGoldenRequest(values)),
  });

interface UseTestbedRenderOptions {
  pollMs?: number | false;
}

export const useTestbedRender = (
  renderId: string,
  { pollMs = false }: UseTestbedRenderOptions = {},
) =>
  useQuery({
    queryKey: adminRenderKeys.render(renderId),
    queryFn: () => getTestbedRender(renderId),
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status) ? false : pollMs),
  });

export const useCancelTestbedRender = (renderId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => cancelTestbedRender(renderId),
    onSuccess: () => client.invalidateQueries({ queryKey: adminRenderKeys.render(renderId) }),
  });
};
