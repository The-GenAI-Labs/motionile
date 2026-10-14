import type { ReactNode } from "react";

interface StatusPageProps {
  code: string;
  title: string;
  description: string;
  actions: ReactNode;
}

export function StatusPage({ code, title, description, actions }: StatusPageProps) {
  return (
    <main
      id="main"
      className="mx-auto flex min-h-dvh w-full max-w-xl flex-col items-start justify-center gap-6 px-6"
    >
      <p className="font-mono text-sm text-muted-foreground">{code}</p>
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
      <p className="text-subtle-foreground">{description}</p>
      <div className="flex flex-wrap gap-3">{actions}</div>
    </main>
  );
}
