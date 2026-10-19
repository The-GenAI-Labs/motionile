import { type ReactNode, useId } from "react";

interface DetailSectionProps {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}

export function DetailSection({ title, children, actions }: DetailSectionProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-4 rounded-xl border bg-surface p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="font-semibold">
          {title}
        </h2>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export interface DetailItem {
  label: string;
  value: ReactNode;
}

export function DetailList({ items }: { items: readonly DetailItem[] }) {
  return (
    <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="mt-1 break-words">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
