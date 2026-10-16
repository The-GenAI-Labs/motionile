"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { useChallengeStore } from "@/features/auth/challenge-store";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { OtpInput } from "@/features/auth/components/otp-input";
import { ResendTimer } from "@/features/auth/components/resend-timer";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import { useResendCode, useVerify, useVerifyOtp } from "@/features/auth/hooks/use-auth-mutations";
import { codeSchema } from "@/features/auth/schemas/auth.schema";
import { safeNextPath } from "@/lib/auth/routes";
export function VerifyForm() {
  const params = useSearchParams();
  const router = useRouter();
  const next = safeNextPath(params.get("next"));
  const challenge = useChallengeStore((state) => state.challenge);
  const setChallenge = useChallengeStore((state) => state.setChallenge);
  const purpose = params.get("purpose") === "otp" ? "otp" : "verify";
  const verify = useVerify();
  const otp = useVerifyOtp();
  const resend = useResendCode();
  const feedback = useAuthFeedback();
  const [resends, setResends] = useState(0);
  const form = useForm({ resolver: zodResolver(codeSchema), defaultValues: { code: "" } });
  const busy = verify.isPending || otp.isPending;
  const submit = form.handleSubmit(async (input) => {
    if (busy || feedback.wait) return;
    feedback.setMessage("");
    try {
      await (purpose === "otp" ? otp : verify).mutateAsync(input);
      router.replace(next as Route);
      router.refresh();
    } catch (error) {
      feedback.fail(error);
      form.setValue("code", "");
    }
  });
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">
        Check your {challenge?.channel === "whatsapp" ? "WhatsApp" : "inbox"}
      </h1>
      <p className="text-muted-foreground">
        {challenge
          ? `Enter the code sent to ${challenge.destination} via ${challenge.channel === "email" ? "email" : "WhatsApp"}.`
          : "Enter the code sent to your email or phone. If your request expired, start again."}
      </p>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <Controller
          control={form.control}
          name="code"
          render={({ field }) => (
            <OtpInput
              value={field.value}
              onChange={field.onChange}
              disabled={busy}
              onComplete={() => {
                void submit();
              }}
            />
          )}
        />
        <FieldError message={form.formState.errors.code?.message} />
        <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
        <Button type="submit" className="w-full" disabled={busy || feedback.wait > 0}>
          Verify code
        </Button>
      </form>
      <ResendTimer
        key={resends}
        seconds={challenge?.resendAfter ?? 60}
        disabled={resend.isPending || feedback.wait > 0}
        onResend={() => {
          void resend
            .mutateAsync()
            .then((response) => {
              setChallenge(response, purpose);
              setResends((value) => value + 1);
              feedback.setMessage("");
              form.setValue("code", "");
            })
            .catch(feedback.fail);
        }}
      />
      <p>
        <Link className="underline" href={`/login?next=${encodeURIComponent(next)}`}>
          Use a different method
        </Link>
      </p>
    </div>
  );
}
