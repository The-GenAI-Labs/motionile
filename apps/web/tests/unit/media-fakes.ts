import { vi } from "vitest";

export interface FakeRecorderControls {
  stream: MediaStream;
  getUserMedia: ReturnType<typeof vi.fn>;
  stopTrack: ReturnType<typeof vi.fn>;
  contextClosed: ReturnType<typeof vi.fn>;
  restore: () => void;
}

interface Options {
  denied?: boolean;
  level?: number;
}

export const installFakeRecording = ({
  denied = false,
  level = 160,
}: Options = {}): FakeRecorderControls => {
  const stopTrack = vi.fn();
  const contextClosed = vi.fn(() => Promise.resolve());
  const stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream;
  const getUserMedia = vi.fn(() =>
    denied
      ? Promise.reject(new DOMException("blocked", "NotAllowedError"))
      : Promise.resolve(stream),
  );

  class FakeRecorder {
    static isTypeSupported = (): boolean => true;
    state: "inactive" | "recording" = "inactive";
    mimeType = "audio/webm;codecs=opus";
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    start(): void {
      this.state = "recording";
    }
    stop(): void {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["audio-bytes"]) });
      this.onstop?.();
    }
  }
  class FakeAnalyser {
    fftSize = 1024;
    getByteTimeDomainData(samples: Uint8Array): void {
      samples.fill(level);
    }
  }
  class FakeContext {
    createAnalyser(): FakeAnalyser {
      return new FakeAnalyser();
    }
    createMediaStreamSource(): { connect: () => void } {
      return { connect: () => undefined };
    }
    close = contextClosed;
  }

  const originalDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("AudioContext", FakeContext);
  const createObjectURL = vi.fn(() => "blob:fake-recording");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));

  return {
    stream,
    getUserMedia,
    stopTrack,
    contextClosed,
    restore: () => {
      if (originalDevices === undefined) {
        Reflect.deleteProperty(navigator, "mediaDevices");
      } else {
        Object.defineProperty(navigator, "mediaDevices", originalDevices);
      }
      vi.unstubAllGlobals();
    },
  };
};

export const removeRecordingSupport = (): (() => void) => {
  vi.stubGlobal("MediaRecorder", undefined);
  return () => {
    vi.unstubAllGlobals();
  };
};
