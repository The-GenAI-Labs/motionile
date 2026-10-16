"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { TurnstileField } from "@/components/shared/turnstile-field";
import { Button } from "@/components/ui/button";
import { useChallengeStore } from "@/features/auth/challenge-store";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { IdentifierInput } from "@/features/auth/components/identifier-input";
import { OAuthButtons } from "@/features/auth/components/oauth-buttons";
import { PasswordInput } from "@/features/auth/components/password-input";
import { authErrorMessages } from "@/features/auth/errors";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import { useLogin, useRequestOtp } from "@/features/auth/hooks/use-auth-mutations";
import { loginSchema, requestCodeSchema } from "@/features/auth/schemas/auth.schema";
import { ApiError } from "@/lib/api/api-error";
import { safeNextPath } from "@/lib/auth/routes";
export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const [method, setMethod] = useState<"password" | "otp">("password");
  const [token, setToken] = useState("");
  const [resetKey, setResetKey] = useState(0);
  const feedback = useAuthFeedback();
  const login = useLogin();
  const requestOtp = useRequestOtp();
  const setChallenge = useChallengeStore((state) => state.setChallenge);
  const form = useForm<z.input<typeof loginSchema>>({
    resolver: zodResolver(
      method === "password" ? loginSchema : requestCodeSchema.extend({ password: z.string() }),
    ),
    defaultValues: { identifier: "", password: "" },
  });
  const busy = login.isPending || requestOtp.isPending;
  const submit = form.handleSubmit(async (input) => {
    feedback.setMessage("");
    try {
      if (method === "password") {
        await login.mutateAsync({ input, token });
        router.replace(next as Route);
        router.refresh();
      } else {
        setChallenge(
          await requestOtp.mutateAsync({ input: { identifier: input.identifier }, token }),
          "otp",
        );
        router.push(`/verify?purpose=otp&next=${encodeURIComponent(next)}`);
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "verification_required") {
        if (error.challenge) setChallenge(error.challenge, "verify");
        router.push(`/verify?next=${encodeURIComponent(next)}`);
      } else feedback.fail(error);
    } finally {
      setToken("");
      setResetKey((key) => key + 1);
    }
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Welcome back</h1>
        <p className="mt-2 text-muted-foreground">Sign in to Motionile.</p>
      </div>
      {params.get("reason") === "expired" ? (
        <p role="status">Your session expired. Sign in to continue.</p>
      ) : null}
      {params.get("reset") === "success" ? (
        <p role="status">Password reset. Sign in with your new password.</p>
      ) : null}
      {params.has("error") ? <p role="alert">{authErrorMessages["oauth_failed"]}</p> : null}
      <div role="tablist" aria-label="Sign-in method" className="flex gap-2">
        {(["password", "otp"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            role="tab"
            aria-selected={method === value}
            tabIndex={method === value ? 0 : -1}
            onKeyDown={(event) => {
              if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                const target =
                  event.key === "Home"
                    ? "password"
                    : event.key === "End"
                      ? "otp"
                      : value === "password"
                        ? "otp"
                        : "password";
                document.getElementById(`tab-${target}`)?.click();
                document.getElementById(`tab-${target}`)?.focus();
              }
            }}
            aria-controls="login-panel"
            id={`tab-${value}`}
            variant={method === value ? "default" : "outline"}
            onClick={() => {
              setMethod(value);
              setToken("");
              setResetKey((key) => key + 1);
              form.clearErrors();
            }}
          >
            {value === "password" ? "Password" : "One-time code"}
          </Button>
        ))}
      </div>
      <div id="login-panel" role="tabpanel" aria-labelledby={`tab-${method}`}>
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="identifier">Email or phone</label>
            <IdentifierInput
              id="identifier"
              {...form.register("identifier")}
              aria-invalid={!!form.formState.errors.identifier}
            />
            <FieldError message={form.formState.errors.identifier?.message} />
          </div>
          {method === "password" ? (
            <div>
              <label htmlFor="password">Password</label>
              <PasswordInput
                id="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
              <FieldError message={form.formState.errors.password?.message} />
            </div>
          ) : null}
          <TurnstileField
            action={method === "password" ? "login" : "otp_request"}
            onToken={setToken}
            resetKey={resetKey}
          />
          <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
          <Button
            className="w-full"
            type="submit"
            disabled={busy || !token || feedback.wait > 0}
            aria-busy={busy}
          >
            {feedback.wait > 0
              ? `Try again in ${String(feedback.wait)}s`
              : method === "password"
                ? "Sign in"
                : "Send code"}
          </Button>
        </form>
      </div>
      <Link className="underline" href="/forgot-password">
        Forgot password?
      </Link>
      <OAuthButtons next={next} />
      <p className="text-sm text-muted-foreground">
        New to Motionile?{" "}
        <Link
          className="text-foreground underline"
          href={`/register?next=${encodeURIComponent(next)}`}
        >
          Create an account
        </Link>
      </p>
    </div>
  );
}
