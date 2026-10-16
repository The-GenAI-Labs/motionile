"use client";
import dynamic from "next/dynamic";

import { env } from "@/config/env";
const Turnstile = dynamic(
  () => import("@marsidev/react-turnstile").then((module) => module.Turnstile),
  { ssr: false, loading: () => <p role="status">Loading security check...</p> },
);
export function TurnstileField({
  action,
  onToken,
  resetKey,
}: {
  action: string;
  onToken: (token: string) => void;
  resetKey: number;
}) {
  const siteKey =
    env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ??
    (new URL(env.NEXT_PUBLIC_SITE_URL).hostname === "localhost"
      ? "1x00000000000000000000AA"
      : undefined);
  if (!siteKey) return <p role="alert">Sign-in security is unavailable. Please try again later.</p>;
  return (
    <Turnstile
      key={resetKey}
      siteKey={siteKey}
      options={{ action, theme: "dark" }}
      onSuccess={onToken}
      onExpire={() => {
        onToken("");
      }}
      onError={() => {
        onToken("");
      }}
    />
  );
}
