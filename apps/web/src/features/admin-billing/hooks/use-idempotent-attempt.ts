"use client";

import { useRef } from "react";

import { isRetryableAttemptError } from "@/features/admin-billing/errors";

interface Attempt {
  fingerprint: string;
  key: string;
}

export const useIdempotentAttempt = () => {
  const attempt = useRef<Attempt | null>(null);

  const keyFor = (fingerprint: string): string => {
    const current = attempt.current;
    if (current?.fingerprint === fingerprint) {
      return current.key;
    }
    const created = { fingerprint, key: crypto.randomUUID() };
    attempt.current = created;
    return created.key;
  };

  const settle = (failure?: unknown): void => {
    if (failure === undefined || !isRetryableAttemptError(failure)) {
      attempt.current = null;
    }
  };

  return { keyFor, settle };
};
