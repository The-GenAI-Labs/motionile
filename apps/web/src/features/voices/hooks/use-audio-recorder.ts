"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

export type RecorderStatus = "idle" | "requesting" | "recording" | "denied" | "error";

export interface RecordedClip {
  blob: Blob;
  durationMs: number;
  filename: string;
  url: string;
}

interface UseAudioRecorderOptions {
  maxMs: number;
  onComplete: (clip: RecordedClip) => void;
}

interface Session {
  recorder: MediaRecorder;
  stream: MediaStream;
  context: AudioContext;
  analyser: AnalyserNode;
  timer: number;
  startedAt: number;
  chunks: Blob[];
  discard: boolean;
}

export const TICK_MS = 100;
export const LEVEL_GAIN = 400;
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
] as const;
const EXTENSIONS: Readonly<Record<string, string>> = {
  "audio/webm": "webm",
  "audio/mp4": "m4a",
  "audio/ogg": "ogg",
};
const DENIED_ERRORS = new Set(["NotAllowedError", "SecurityError", "PermissionDeniedError"]);

const mediaDevices = (): MediaDevices | undefined => (navigator as Partial<Navigator>).mediaDevices;

export const isRecordingSupported = (): boolean =>
  typeof MediaRecorder !== "undefined" &&
  typeof navigator !== "undefined" &&
  typeof mediaDevices()?.getUserMedia === "function";

const subscribeNothing = (): (() => void) => () => undefined;

export const pickMimeType = (): string | undefined =>
  MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate));

export const extensionFor = (mimeType: string): string =>
  EXTENSIONS[mimeType.split(";")[0] ?? ""] ?? "webm";

export const rmsLevel = (samples: Uint8Array): number => {
  if (samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (const sample of samples) {
    const centered = (sample - 128) / 128;
    sum += centered * centered;
  }
  return Math.min(100, Math.round(Math.sqrt(sum / samples.length) * LEVEL_GAIN));
};

const releaseSession = (session: Session): void => {
  window.clearInterval(session.timer);
  for (const track of session.stream.getTracks()) {
    track.stop();
  }
  void session.context.close().catch(() => undefined);
};

export const useAudioRecorder = ({ maxMs, onComplete }: UseAudioRecorderOptions) => {
  const supported = useSyncExternalStore(subscribeNothing, isRecordingSupported, () => false);
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [level, setLevel] = useState(0);
  const session = useRef<Session | null>(null);
  const completion = useRef(onComplete);

  useEffect(() => {
    completion.current = onComplete;
  }, [onComplete]);

  useEffect(
    () => () => {
      const active = session.current;
      if (active === null) {
        return;
      }
      active.discard = true;
      if (active.recorder.state !== "inactive") {
        active.recorder.stop();
      } else {
        releaseSession(active);
      }
    },
    [],
  );

  const stop = (): void => {
    const active = session.current;
    if (active !== null && active.recorder.state !== "inactive") {
      active.recorder.stop();
    }
  };

  const finish = (active: Session, mimeType: string): void => {
    releaseSession(active);
    session.current = null;
    setLevel(0);
    if (active.discard) {
      return;
    }
    setStatus("idle");
    const durationMs = Math.min(maxMs, Math.round(performance.now() - active.startedAt));
    setElapsedMs(durationMs);
    const blob = new Blob(active.chunks, { type: mimeType });
    completion.current({
      blob,
      url: URL.createObjectURL(blob),
      durationMs,
      filename: `recording.${extensionFor(mimeType)}`,
    });
  };

  const start = async (): Promise<void> => {
    if (!supported || session.current !== null) {
      return;
    }
    setStatus("requesting");
    setElapsedMs(0);
    const devices = mediaDevices();
    if (devices === undefined) {
      setStatus("error");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await devices.getUserMedia({ audio: true });
    } catch (failure) {
      setStatus(
        failure instanceof DOMException && DENIED_ERRORS.has(failure.name) ? "denied" : "error",
      );
      return;
    }
    try {
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const active: Session = {
        recorder,
        stream,
        context,
        analyser,
        startedAt: performance.now(),
        chunks: [],
        discard: false,
        timer: window.setInterval(() => {
          const elapsed = Math.round(performance.now() - active.startedAt);
          setElapsedMs(Math.min(elapsed, maxMs));
          analyser.getByteTimeDomainData(samples);
          setLevel(rmsLevel(samples));
          if (elapsed >= maxMs) {
            stop();
          }
        }, TICK_MS),
      };
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          active.chunks.push(event.data);
        }
      };
      recorder.onstop = () => {
        finish(active, recorder.mimeType === "" ? (mimeType ?? "audio/webm") : recorder.mimeType);
      };
      session.current = active;
      recorder.start();
      setStatus("recording");
    } catch {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      setStatus("error");
    }
  };

  return { supported, status, elapsedMs, level, start, stop };
};
