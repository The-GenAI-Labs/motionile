"use client";
import { Button } from "@/components/ui/button";
import { env } from "@/config/env";
import { authErrorMessage } from "@/features/auth/errors";
import { useLinkProvider } from "@/features/auth/hooks/use-auth-mutations";
import { safeNextPath } from "@/lib/auth/routes";
const providers = [
  { id: "google", name: "Google", mark: "G" },
  { id: "github", name: "GitHub", mark: "⌘" },
  { id: "microsoft", name: "Microsoft", mark: "⊞" },
] as const;
export function OAuthButtons({
  next = "/dashboard",
  intent = "login",
  linked = [],
}: {
  next?: string;
  intent?: "login" | "link";
  linked?: string[];
}) {
  const link = useLinkProvider();
  return (
    <div className="space-y-2">
      {providers
        .filter((provider) => !linked.includes(provider.id))
        .map((provider) =>
          intent === "login" ? (
            <Button key={provider.id} asChild variant="outline" className="w-full">
              <a
                href={`${env.NEXT_PUBLIC_API_URL}/v1/auth/oauth/${provider.id}/start?${new URLSearchParams({ next: safeNextPath(next), intent })}`}
              >
                <span aria-hidden="true">{provider.mark}</span>Continue with {provider.name}
              </a>
            </Button>
          ) : (
            <Button
              key={provider.id}
              type="button"
              variant="outline"
              disabled={link.isPending}
              onClick={() => {
                link.mutate(provider.id);
              }}
            >
              Link {provider.name}
            </Button>
          ),
        )}
      {link.error ? <p role="alert">{authErrorMessage(link.error)}</p> : null}
    </div>
  );
}
