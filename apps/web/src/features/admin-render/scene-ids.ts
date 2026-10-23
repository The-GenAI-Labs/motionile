import { MAX_SCENES, SCENE_ID_PATTERN } from "@/features/admin-render/schemas/admin-render.schema";

export interface SceneExtraction {
  sceneIds: string[];
  issues: string[];
}

export const extractScenes = (html: string): SceneExtraction => {
  const document = new DOMParser().parseFromString(html, "text/html");
  const sceneIds: string[] = [];
  const issues: string[] = [];
  const seen = new Set<string>();
  for (const element of document.querySelectorAll("[data-scene]")) {
    const sceneId = (element.getAttribute("data-scene") ?? "").trim();
    if (sceneId === "") {
      issues.push("A scene element has an empty data-scene value.");
    } else if (!SCENE_ID_PATTERN.test(sceneId)) {
      issues.push(
        `The scene ID ${sceneId} is invalid. Use letters, digits, hyphens or underscores, up to 64 characters.`,
      );
    } else if (seen.has(sceneId)) {
      issues.push(`The scene ID ${sceneId} is used more than once.`);
    } else {
      seen.add(sceneId);
      sceneIds.push(sceneId);
    }
  }
  if (sceneIds.length > MAX_SCENES) {
    issues.push(`The composition has more than ${String(MAX_SCENES)} scenes.`);
  }
  return { sceneIds, issues };
};

export const extractSceneIds = (html: string): string[] => extractScenes(html).sceneIds;
