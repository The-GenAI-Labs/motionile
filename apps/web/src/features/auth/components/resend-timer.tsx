"use client";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
export function ResendTimer({
  seconds,
  onResend,
  disabled = false,
}: {
  seconds: number;
  onResend: () => void;
  disabled?: boolean;
}) {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setRemaining((value) => Math.max(0, value - 1));
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return (
    <Button type="button" variant="link" disabled={disabled || remaining > 0} onClick={onResend}>
      {remaining > 0 ? `Resend in ${String(remaining)}s` : "Resend code"}
    </Button>
  );
}
