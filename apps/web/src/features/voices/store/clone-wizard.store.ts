import { create } from "zustand";

import type { RecordedClip } from "@/features/voices/hooks/use-audio-recorder";
import type { CloneStart } from "@/features/voices/types/voices.types";

export const wizardSteps = ["consent", "recording", "samples", "details", "status"] as const;

export type WizardStep = (typeof wizardSteps)[number];

export interface PendingUpload {
  id: string;
  name: string;
  status: "uploading" | "failed";
  message: string | null;
}

interface CloneWizardState {
  step: WizardStep;
  start: CloneStart | null;
  consentClip: RecordedClip | null;
  consentUploaded: boolean;
  uploads: PendingUpload[];
  submittedVoiceId: string | null;
  setStep: (step: WizardStep) => void;
  setStart: (start: CloneStart) => void;
  setConsentClip: (clip: RecordedClip | null) => void;
  setConsentUploaded: (uploaded: boolean) => void;
  addUpload: (upload: PendingUpload) => void;
  updateUpload: (id: string, change: Partial<PendingUpload>) => void;
  removeUpload: (id: string) => void;
  setSubmittedVoiceId: (voiceId: string) => void;
  reset: () => void;
}

const initialState = {
  step: "consent",
  start: null,
  consentClip: null,
  consentUploaded: false,
  uploads: [],
  submittedVoiceId: null,
} as const satisfies Partial<CloneWizardState>;

export const useCloneWizardStore = create<CloneWizardState>()((set) => ({
  ...initialState,
  uploads: [],
  setStep: (step) => {
    set({ step });
  },
  setStart: (start) => {
    set({ start, step: "recording", consentClip: null, consentUploaded: false, uploads: [] });
  },
  setConsentClip: (consentClip) => {
    set({ consentClip, consentUploaded: false });
  },
  setConsentUploaded: (consentUploaded) => {
    set({ consentUploaded });
  },
  addUpload: (upload) => {
    set((state) => ({ uploads: [...state.uploads, upload] }));
  },
  updateUpload: (id, change) => {
    set((state) => ({
      uploads: state.uploads.map((upload) =>
        upload.id === id ? { ...upload, ...change } : upload,
      ),
    }));
  },
  removeUpload: (id) => {
    set((state) => ({ uploads: state.uploads.filter((upload) => upload.id !== id) }));
  },
  setSubmittedVoiceId: (submittedVoiceId) => {
    set({ submittedVoiceId, step: "status" });
  },
  reset: () => {
    set({ ...initialState, uploads: [] });
  },
}));
