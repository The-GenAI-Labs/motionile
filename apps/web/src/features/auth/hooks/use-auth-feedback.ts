"use client";
import { useEffect, useRef, useState } from "react";

import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";
export const useAuthFeedback = () => {
  const [message, setMessage] = useState("");
  const [wait, setWait] = useState(0);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => {
      setWait((remaining) => Math.max(0, remaining - 1));
    }, 1000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [wait]);
  const fail = (error: unknown) => {
    const normalized = ApiError.from(error);
    setMessage(authErrorMessage(normalized));
    if (normalized.code === "rate_limited" || normalized.code === "otp_cooldown")
      setWait(normalized.retryAfterSeconds ?? 60);
    requestAnimationFrame(() => errorRef.current?.focus());
  };
  return { message, setMessage, wait, fail, errorRef };
};
