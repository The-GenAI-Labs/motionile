"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { TurnstileField } from "@/components/shared/turnstile-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useChallengeStore } from "@/features/auth/challenge-store";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { IdentifierInput } from "@/features/auth/components/identifier-input";
import { OAuthButtons } from "@/features/auth/components/oauth-buttons";
import { PasswordInput } from "@/features/auth/components/password-input";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import { useRegister } from "@/features/auth/hooks/use-auth-mutations";
import { registerSchema } from "@/features/auth/schemas/auth.schema";
import { safeNextPath } from "@/lib/auth/routes";
export function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const [token, setToken] = useState("");
  const [resetKey, setResetKey] = useState(0);
  const feedback = useAuthFeedback();
  const mutation = useRegister();
  const setChallenge = useChallengeStore((state) => state.setChallenge);
  const form = useForm<z.input<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: { name: "", identifier: "", password: "", confirmPassword: "", terms: false },
  });
  const submit = form.handleSubmit(async (values) => {
    feedback.setMessage("");
    try {
      const { name, identifier, password } = values;
      const input = {
        name,
        password,
        ...(identifier.includes("@") ? { email: identifier } : { phone: identifier }),
      };
      setChallenge(await mutation.mutateAsync({ input, token }), "verify");
      router.push(`/verify?next=${encodeURIComponent(next)}`);
    } catch (error) {
      feedback.fail(error);
    } finally {
      setToken("");
      setResetKey((key) => key + 1);
    }
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Create your account</h1>
        <p className="mt-2 text-muted-foreground">
          Start creating with Motionile. Verify your email or phone to continue.
        </p>
      </div>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <div>
          <label htmlFor="name">Name</label>
          <Input id="name" autoComplete="name" {...form.register("name")} />
          <FieldError message={form.formState.errors.name?.message} />
        </div>
        <div>
          <label htmlFor="identifier">Email or phone</label>
          <IdentifierInput id="identifier" {...form.register("identifier")} />
          <FieldError message={form.formState.errors.identifier?.message} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            strength
            {...form.register("password")}
          />
          <FieldError message={form.formState.errors.password?.message} />
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
        <div>
          <label className="flex gap-2">
            <input type="checkbox" {...form.register("terms")} />I agree to the Terms and Privacy
            Policy
          </label>
          <FieldError message={form.formState.errors.terms?.message} />
        </div>
        <TurnstileField action="register" onToken={setToken} resetKey={resetKey} />
        <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
        <Button
          className="w-full"
          type="submit"
          disabled={mutation.isPending || !token || feedback.wait > 0}
        >
          {feedback.wait ? `Try again in ${String(feedback.wait)}s` : "Create account"}
        </Button>
      </form>
      <OAuthButtons next={next} />
      <p>
        Already have an account?{" "}
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
