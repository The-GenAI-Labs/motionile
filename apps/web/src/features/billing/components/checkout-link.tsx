"use client";

import type { Route } from "next";
import Link from "next/link";
import { type ReactNode, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { readCookie } from "@/lib/auth/cookies";

const subscribeToNothing = () => () => undefined;

const hasSessionHint = (): boolean => readCookie("mo_auth") !== null;

const serverHasSessionHint = (): boolean => false;

interface CheckoutLinkProps {
  path: string;
  children: ReactNode;
  variant?: "default" | "outline";
}

export function CheckoutLink({ path, children, variant = "default" }: CheckoutLinkProps) {
  const signedIn = useSyncExternalStore(subscribeToNothing, hasSessionHint, serverHasSessionHint);
  const href = signedIn ? path : `/login?next=${encodeURIComponent(path)}`;
  return (
    <Button asChild variant={variant} className="w-full">
      <Link href={href as Route}>{children}</Link>
    </Button>
  );
}
