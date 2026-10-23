"use client";

import { useRef, useState } from "react";

import { isRetryableCloneError } from "@/features/voices/errors";
import { useSubmitClone } from "@/features/voices/hooks/use-clone-attempt";
import type { CloneSubmitFormValues } from "@/features/voices/schemas/voices.schema";
import type { Voice } from "@/features/voices/types/voices.types";

interface PendingSubmit extends CloneSubmitFormValues {
  idempotencyKey: string;
}

export const useCloneSubmit = (attemptId: string | null) => {
  const mutation = useSubmitClone(attemptId);
  const pending = useRef<PendingSubmit | null>(null);
  const [error, setError] = useState<unknown>(null);

  const submit = async (values: CloneSubmitFormValues): Promise<Voice | null> => {
    const previous = pending.current;
    const attempt: PendingSubmit =
      previous?.name === values.name && previous.language === values.language
        ? previous
        : { ...values, idempotencyKey: crypto.randomUUID() };
    pending.current = attempt;
    setError(null);
    try {
      const voice = await mutation.mutateAsync(attempt);
      pending.current = null;
      return voice;
    } catch (failure) {
      if (!isRetryableCloneError(failure)) {
        pending.current = null;
      }
      setError(failure);
      return null;
    }
  };

  return { submit, error, isPending: mutation.isPending };
};
