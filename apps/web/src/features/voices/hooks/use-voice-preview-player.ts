"use client";

import { useRef, useState } from "react";

import { voiceErrorMessage } from "@/features/voices/errors";
import { useVoicePreviewLoader } from "@/features/voices/hooks/use-voices";

export type PreviewStatus = "idle" | "loading" | "playing" | "paused" | "error";

export interface PreviewState {
  voiceId: string | null;
  status: PreviewStatus;
  message: string;
}

export interface PreviewTarget {
  id: string;
  name: string;
}

const IDLE: PreviewState = { voiceId: null, status: "idle", message: "" };

export const useVoicePreviewPlayer = () => {
  const loadPreview = useVoicePreviewLoader();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [state, setState] = useState<PreviewState>(IDLE);

  const toggle = async (target: PreviewTarget): Promise<void> => {
    const element = audioRef.current;
    if (element === null) {
      return;
    }
    if (state.voiceId === target.id && state.status !== "error" && element.src !== "") {
      if (element.paused) {
        await element.play().catch(() => undefined);
      } else {
        element.pause();
      }
      return;
    }
    element.pause();
    setState({ voiceId: target.id, status: "loading", message: "" });
    try {
      const preview = await loadPreview(target.id);
      element.src = preview.url;
      await element.play();
    } catch (failure) {
      setState({ voiceId: target.id, status: "error", message: voiceErrorMessage(failure) });
    }
  };

  const audioProps = {
    ref: audioRef,
    preload: "none" as const,
    onPlay: () => {
      setState((current) => ({ ...current, status: "playing", message: "" }));
    },
    onPause: () => {
      setState((current) =>
        current.status === "playing" ? { ...current, status: "paused", message: "" } : current,
      );
    },
    onEnded: () => {
      setState(IDLE);
    },
    onError: () => {
      setState((current) => ({
        ...current,
        status: "error",
        message: "The preview could not be played. Try again.",
      }));
    },
  };

  return { state, toggle, audioProps };
};
