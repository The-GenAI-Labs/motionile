"use client";
import { create } from "zustand";

import type { AuthChallenge } from "@/features/auth/types/auth.types";
export const useChallengeStore = create<{
  challenge: AuthChallenge | null;
  purpose: "verify" | "otp" | "reset" | "set";
  setChallenge: (challenge: AuthChallenge, purpose: "verify" | "otp" | "reset" | "set") => void;
}>((set) => ({
  challenge: null,
  purpose: "verify",
  setChallenge: (challenge, purpose) => {
    set({ challenge, purpose });
  },
}));
