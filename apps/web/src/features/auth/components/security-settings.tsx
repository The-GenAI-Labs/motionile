"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { FieldError, FormFeedback } from "@/features/auth/components/form-feedback";
import { OAuthButtons } from "@/features/auth/components/oauth-buttons";
import { OtpInput } from "@/features/auth/components/otp-input";
import { PasswordInput } from "@/features/auth/components/password-input";
import { ResendTimer } from "@/features/auth/components/resend-timer";
import { authErrorMessage } from "@/features/auth/errors";
import { useAuthFeedback } from "@/features/auth/hooks/use-auth-feedback";
import {
  useChangePassword,
  useLogoutAll,
  useRequestSetPassword,
  useResendCode,
  useRevokeSession,
  useSetPassword,
  useUnlinkProvider,
} from "@/features/auth/hooks/use-auth-mutations";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";
import { useSessions } from "@/features/auth/hooks/use-sessions";
import { changePasswordSchema, resetPasswordSchema } from "@/features/auth/schemas/auth.schema";
import type { OAuthProvider } from "@/features/auth/types/auth.types";
function ChangePasswordForm() {
  const mutation = useChangePassword();
  const feedback = useAuthFeedback();
  const [saved, setSaved] = useState(false);
  const form = useForm({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { currentPassword: "", newPassword: "", confirmPassword: "" },
  });
  const submit = form.handleSubmit(async ({ currentPassword, newPassword }) => {
    setSaved(false);
    try {
      await mutation.mutateAsync({ currentPassword, newPassword });
      form.reset();
      feedback.setMessage("");
      setSaved(true);
    } catch (error) {
      feedback.fail(error);
    }
  });
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      {(["currentPassword", "newPassword", "confirmPassword"] as const).map((field) => (
        <div key={field}>
          <label htmlFor={field}>
            {field === "currentPassword"
              ? "Current password"
              : field === "newPassword"
                ? "New password"
                : "Confirm password"}
          </label>
          <PasswordInput
            id={field}
            autoComplete={field === "currentPassword" ? "current-password" : "new-password"}
            {...form.register(field)}
          />
          <FieldError message={form.formState.errors[field]?.message} />
        </div>
      ))}
      <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
      {saved ? <p role="status">Password changed. Other sessions have been signed out.</p> : null}
      <Button type="submit" disabled={mutation.isPending || feedback.wait > 0}>
        Change password
      </Button>
    </form>
  );
}
function SetPasswordForm() {
  const request = useRequestSetPassword();
  const resend = useResendCode();
  const challenge = resend.data ?? request.data;
  const mutation = useSetPassword();
  const feedback = useAuthFeedback();
  const form = useForm({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { code: "", newPassword: "", confirmPassword: "" },
  });
  const submit = form.handleSubmit(async ({ code, newPassword }) => {
    try {
      await mutation.mutateAsync({ code, newPassword });
      form.reset();
    } catch (error) {
      feedback.fail(error);
    }
  });
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground">
        Add a password using a code sent to your verified contact.
      </p>
      {challenge ? (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            void submit(event);
          }}
        >
          <p>Code sent to {challenge.destination}.</p>
          <Controller
            control={form.control}
            name="code"
            render={({ field }) => <OtpInput value={field.value} onChange={field.onChange} />}
          />
          <FieldError message={form.formState.errors.code?.message} />
          {(["newPassword", "confirmPassword"] as const).map((field) => (
            <div key={field}>
              <label htmlFor={field}>
                {field === "newPassword" ? "New password" : "Confirm password"}
              </label>
              <PasswordInput id={field} autoComplete="new-password" {...form.register(field)} />
              <FieldError message={form.formState.errors[field]?.message} />
            </div>
          ))}
          <Button type="submit" disabled={mutation.isPending || feedback.wait > 0}>
            Set password
          </Button>
          <ResendTimer
            key={resend.submittedAt}
            seconds={challenge.resendAfter}
            disabled={resend.isPending || feedback.wait > 0}
            onResend={() => {
              void resend.mutateAsync().catch(feedback.fail);
            }}
          />
        </form>
      ) : (
        <Button
          disabled={request.isPending || feedback.wait > 0}
          onClick={() => {
            void request.mutateAsync().catch(feedback.fail);
          }}
        >
          Send verification code
        </Button>
      )}
      <FormFeedback message={feedback.message} errorRef={feedback.errorRef} />
    </div>
  );
}
export function SecuritySettings() {
  const user = useCurrentUser();
  const sessions = useSessions();
  const revoke = useRevokeSession();
  const logoutAll = useLogoutAll();
  const unlink = useUnlinkProvider();
  if (user.isPending) return <p role="status">Loading security settings…</p>;
  if (user.error) return <p role="alert">{authErrorMessage(user.error)}</p>;
  const me = user.data;
  const anotherMethod =
    me.hasPassword ||
    me.contacts.some((contact) => contact.verified) ||
    me.linkedProviders.length > 1;
  const sessionItems = sessions.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="mx-auto max-w-3xl space-y-10">
      <div>
        <h1 className="text-3xl font-semibold">Security</h1>
        <p className="mt-2 text-muted-foreground">
          Manage your sign-in methods and active sessions.
        </p>
      </div>
      <section
        className="space-y-4 rounded-xl border bg-surface p-6"
        aria-labelledby="sessions-heading"
      >
        <h2 id="sessions-heading" className="text-xl font-semibold">
          Sessions
        </h2>
        {sessions.isPending ? <p role="status">Loading sessions…</p> : null}
        {sessions.error ? <p role="alert">{authErrorMessage(sessions.error)}</p> : null}
        <ul className="space-y-4">
          {sessionItems.map((session) => (
            <li
              key={session.id}
              className="flex flex-wrap items-center justify-between gap-3 border-b pb-4"
            >
              <div>
                <p>
                  {session.deviceLabel ?? "Unknown device"}{" "}
                  {session.current ? <strong>Current session</strong> : null}
                </p>
                <p className="font-mono text-sm text-muted-foreground">
                  {session.ip ?? "Unknown IP"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Last active{" "}
                  <time dateTime={session.lastUsedAt}>
                    {new Date(session.lastUsedAt).toLocaleString()}
                  </time>
                </p>
              </div>
              {!session.current ? (
                <ConfirmDialog
                  title="Revoke session?"
                  description="This device will need to sign in again."
                  trigger={<Button variant="outline">Revoke session</Button>}
                  confirmLabel="Revoke session"
                  onConfirm={() => revoke.mutateAsync(session.id)}
                />
              ) : null}
            </li>
          ))}
        </ul>
        {sessions.hasNextPage ? (
          <Button
            variant="outline"
            disabled={sessions.isFetchingNextPage}
            onClick={() => {
              void sessions.fetchNextPage();
            }}
          >
            Load more sessions
          </Button>
        ) : null}
        {revoke.error ? <p role="alert">{authErrorMessage(revoke.error)}</p> : null}
        <ConfirmDialog
          title="Sign out everywhere?"
          description="Every device, including this one, will be signed out."
          trigger={<Button variant="destructive">Sign out everywhere</Button>}
          confirmLabel="Sign out everywhere"
          onConfirm={() => logoutAll.mutateAsync()}
        />
        {logoutAll.error ? <p role="alert">{authErrorMessage(logoutAll.error)}</p> : null}
      </section>
      <section
        className="space-y-4 rounded-xl border bg-surface p-6"
        aria-labelledby="password-heading"
      >
        <h2 id="password-heading" className="text-xl font-semibold">
          Password
        </h2>
        {me.hasPassword ? <ChangePasswordForm /> : <SetPasswordForm />}
      </section>
      <section
        className="space-y-4 rounded-xl border bg-surface p-6"
        aria-labelledby="accounts-heading"
      >
        <h2 id="accounts-heading" className="text-xl font-semibold">
          Linked accounts
        </h2>
        <ul className="space-y-3">
          {me.linkedProviders.map((provider) => {
            const name =
              provider === "github" ? "GitHub" : provider === "google" ? "Google" : "Microsoft";
            return (
              <li key={provider} className="flex items-center justify-between gap-4">
                <span>{name}</span>
                <ConfirmDialog
                  title={`Unlink ${name}?`}
                  description="You will need another method to sign in."
                  trigger={
                    <Button variant="outline" disabled={!anotherMethod}>
                      Unlink {name}
                    </Button>
                  }
                  confirmLabel={`Unlink ${name}`}
                  onConfirm={() => unlink.mutateAsync(provider as OAuthProvider)}
                />
              </li>
            );
          })}
        </ul>
        {!anotherMethod ? (
          <p className="text-sm text-muted-foreground">
            Add another sign-in method before unlinking your last account.
          </p>
        ) : null}
        {unlink.error ? <p role="alert">{authErrorMessage(unlink.error)}</p> : null}
        <OAuthButtons intent="link" linked={me.linkedProviders} />
      </section>
    </div>
  );
}
