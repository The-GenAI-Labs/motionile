"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { useChallengeStore } from "@/features/auth/challenge-store";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { OtpInput } from "@/features/auth/components/otp-input";
import { PasswordInput } from "@/features/auth/components/password-input";
import { ResendTimer } from "@/features/auth/components/resend-timer";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import { useResendCode, useResetPassword } from "@/features/auth/hooks/use-auth-mutations";
import { resetPasswordSchema } from "@/features/auth/schemas/auth.schema";
export function ResetPasswordForm() {
  const router = useRouter();
  const mutation = useResetPassword();
  const resend = useResendCode();
  const feedback = useAuthFeedback();
  const challenge = useChallengeStore((state) => state.challenge);
  const setChallenge = useChallengeStore((state) => state.setChallenge);
  const [resends, setResends] = useState(0);
  const form = useForm({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { code: "", newPassword: "", confirmPassword: "" },
  });
  const submit = form.handleSubmit(async ({ code, newPassword }) => {
    try {
      await mutation.mutateAsync({ code, newPassword });
      router.replace("/login?reset=success");
    } catch (error) {
      feedback.fail(error);
    }
  });
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Reset your password</h1>
      <p className="text-muted-foreground">
        {challenge
          ? `Enter the code sent to ${challenge.destination}.`
          : "Enter your reset code and choose a new password."}
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
          render={({ field }) => <OtpInput value={field.value} onChange={field.onChange} />}
        />
        <FieldError message={form.formState.errors.code?.message} />
        <div>
          <label htmlFor="new-password">New password</label>
          <PasswordInput
            id="new-password"
            autoComplete="new-password"
            strength
            {...form.register("newPassword")}
          />
          <FieldError message={form.formState.errors.newPassword?.message} />
        </div>
        <div>
          <label htmlFor="confirm-password">Confirm password</label>
          <PasswordInput
            id="confirm-password"
            autoComplete="new-password"
            {...form.register("confirmPassword")}
          />
          <FieldError message={form.formState.errors.confirmPassword?.message} />
        </div>
        <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
        <Button type="submit" disabled={mutation.isPending || feedback.wait > 0}>
          Reset password
        </Button>
      </form>
      <ResendTimer
        key={resends}
        seconds={challenge?.resendAfter ?? 60}
        disabled={resend.isPending || feedback.wait > 0}
        onResend={() => {
          void resend
            .mutateAsync()
            .then((result) => {
              setChallenge(result, "reset");
              setResends((value) => value + 1);
            })
            .catch(feedback.fail);
        }}
      />
      <p>
        <Link href="/forgot-password" className="underline">
          Request a new reset
        </Link>
      </p>
    </div>
  );
}
