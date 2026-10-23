"use client";

import { useUpdatePreferences, useUserPreferences } from "@/features/users/hooks/use-user-settings";

export const useDefaultVoice = () => {
  const preferences = useUserPreferences();
  const update = useUpdatePreferences();
  const setDefaultVoice = (voiceId: string | null) => {
    const current = preferences.data;
    if (current === undefined) {
      return Promise.reject(new Error("Preferences are not loaded."));
    }
    return update.mutateAsync({
      defaultStyle: current.defaultStyle,
      pace: current.pace,
      language: current.language,
      depth: current.depth,
      defaultAspect: current.defaultAspect,
      captionsEnabled: current.captionsEnabled,
      defaultVoiceId: voiceId,
    });
  };
  return {
    defaultVoiceId: preferences.data?.defaultVoiceId ?? null,
    isReady: preferences.isSuccess,
    isError: preferences.isError,
    isUpdating: update.isPending,
    setDefaultVoice,
  };
};
