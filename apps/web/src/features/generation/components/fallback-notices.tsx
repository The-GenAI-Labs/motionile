"use client";

import { InfoIcon } from "lucide-react";

import { useStoryboard } from "@/features/generation/hooks/use-storyboard";
import type { Job } from "@/features/generation/types/generation.types";

export function FallbackNotices({ job }: { job: Job }) {
  const storyboard = useStoryboard(job.id, job.fallbackSceneIds.length > 0);
  if (job.fallbackSceneIds.length === 0) {
    return null;
  }
  const scenes = storyboard.data?.content.scenes ?? [];
  return (
    <section
      aria-labelledby="fallback-heading"
      className="space-y-2 rounded-lg border bg-surface p-4"
    >
      <h3 id="fallback-heading" className="flex items-center gap-2 text-sm font-semibold">
        <InfoIcon aria-hidden="true" className="size-4" />
        Some scenes use a simpler layout
      </h3>
      <ul
        aria-label="Scenes with a simple layout"
        className="space-y-1 text-sm text-subtle-foreground"
      >
        {job.fallbackSceneIds.map((sceneId) => {
          const index = scenes.findIndex((scene) => scene.id === sceneId);
          const scene = scenes[index];
          return (
            <li key={sceneId}>
              {index === -1
                ? `Scene ${sceneId} used a simple text layout.`
                : `Scene ${String(index + 1)} used a simple text layout${scene ? `: ${scene.goal}` : ""}.`}
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-muted-foreground">
        Revise the video and pick these scenes to try a richer layout again.
      </p>
    </section>
  );
}
