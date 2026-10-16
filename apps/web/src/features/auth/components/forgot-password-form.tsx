"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { TurnstileField } from "@/components/shared/turnstile-field";
import { Button } from "@/components/ui/button";
import { useChallengeStore } from "@/features/auth/challenge-store";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { IdentifierInput } from "@/features/auth/components/identifier-input";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import { useForgotPassword } from "@/features/auth/hooks/use-auth-mutations";
import { requestCodeSchema } from "@/features/auth/schemas/auth.schema";
export function ForgotPasswordForm() {
  const router = useRouter();
  const mutation = useForgotPassword();
  const feedback = useAuthFeedback();
  const setChallenge = useChallengeStore((state) => state.setChallenge);
  const [token, setToken] = useState("");
  const [resetKey, setResetKey] = useState(0);
  const form = useForm({
    resolver: zodResolver(requestCodeSchema),
    defaultValues: { identifier: "" },
  });
  const submit = form.handleSubmit(async (input) => {
    try {
      setChallenge(await mutation.mutateAsync({ input, token }), "reset");
      router.push("/reset-password");
    } catch (error) {
      feedback.fail(error);
    } finally {
      setToken("");
      setResetKey((key) => key + 1);
    }
  });
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Forgot your password?</h1>
      <p className="text-muted-foreground">
        If an account exists, we will send a reset code to your email or WhatsApp.
      </p>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <div>
          <label htmlFor="identifier">Email or phone</label>
          <IdentifierInput id="identifier" {...form.register("identifier")} />
          <FieldError message={form.formState.errors.identifier?.message} />
        </div>
        <TurnstileField action="password_forgot" onToken={setToken} resetKey={resetKey} />
        <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
        <Button type="submit" disabled={mutation.isPending || !token || feedback.wait > 0}>
          {feedback.wait ? `Try again in ${String(feedback.wait)}s` : "Send reset code"}
        </Button>
      </form>
      <Link href="/login" className="underline">
        Back to sign in
      </Link>
    </div>
  );
}
