"use client";

import type { zAuditEntryResponse } from "@motionile/api-contract";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryStates } from "nuqs";
import { useState } from "react";
import type { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { auditEntries, type AuditParams } from "@/features/admin/api/admin.api";
import { adminKeys } from "@/features/admin/query-keys";

type AuditEntry = z.infer<typeof zAuditEntryResponse>;

const parsers = {
  actor: parseAsString.withDefault(""),
  action: parseAsString.withDefault(""),
  target: parseAsString.withDefault(""),
  from: parseAsString.withDefault(""),
  to: parseAsString.withDefault(""),
};

export function AuditLog() {
  const [filters, setFilters] = useQueryStates(parsers, { history: "push" });
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const params: AuditParams = {};
  if (filters.actor) params.actorUserId = filters.actor;
  if (filters.action) params.action = filters.action;
  if (filters.target) params.targetType = filters.target;
  if (filters.from) params.createdFrom = filters.from;
  if (filters.to) params.createdTo = filters.to;
  const query = useQuery({
    queryKey: [...adminKeys.all, "audit", filters],
    queryFn: () => auditEntries(params),
  });
  return (
    <div className="space-y-5">
      <section
        aria-label="Audit filters"
        className="grid gap-3 rounded-xl border bg-surface p-4 md:grid-cols-5"
      >
        <div>
          <Label htmlFor="audit-actor">Actor ID</Label>
          <Input
            id="audit-actor"
            value={filters.actor}
            onChange={(event) => void setFilters({ actor: event.target.value || null })}
          />
        </div>
        <div>
          <Label htmlFor="audit-action">Action</Label>
          <Input
            id="audit-action"
            value={filters.action}
            onChange={(event) => void setFilters({ action: event.target.value || null })}
          />
        </div>
        <div>
          <Label htmlFor="audit-target">Target type</Label>
          <Input
            id="audit-target"
            value={filters.target}
            onChange={(event) => void setFilters({ target: event.target.value || null })}
          />
        </div>
        <div>
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="datetime-local"
            value={filters.from}
            onChange={(event) => void setFilters({ from: event.target.value || null })}
          />
        </div>
        <div>
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="datetime-local"
            value={filters.to}
            onChange={(event) => void setFilters({ to: event.target.value || null })}
          />
        </div>
        <Button type="button" variant="outline" onClick={() => void setFilters(null)}>
          Clear filters
        </Button>
      </section>
      {query.isPending ? <p role="status">Loading audit entries…</p> : null}
      {query.isError ? (
        <p role="alert" className="text-destructive">
          Audit entries could not be loaded.
        </p>
      ) : null}
      {query.data ? (
        <ol className="space-y-3">
          {query.data.items.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className="w-full rounded-xl border bg-surface p-5 text-left focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
                onClick={() => {
                  setSelected(entry);
                }}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-mono text-sm">{entry.action}</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {new Date(entry.createdAt).toLocaleString()} ·{" "}
                      {entry.targetType ?? "platform"} {entry.targetId ?? ""}
                    </p>
                  </div>
                  <Badge variant="outline">{entry.actorType}</Badge>
                </div>
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      <Sheet
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <SheetContent className="overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Audit entry</SheetTitle>
            <SheetDescription>Request context and redacted event metadata.</SheetDescription>
          </SheetHeader>
          {selected ? (
            <dl className="grid gap-4 px-4 text-sm">
              <div>
                <dt className="text-muted-foreground">Action</dt>
                <dd className="font-mono">{selected.action}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Actor</dt>
                <dd>
                  {selected.actorType} {selected.actorUserId ?? ""}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Target</dt>
                <dd>
                  {selected.targetType ?? "platform"} {selected.targetId ?? ""}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">IP address</dt>
                <dd>{selected.ip ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Request ID</dt>
                <dd className="font-mono">{selected.requestId ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">User agent</dt>
                <dd>{selected.userAgent ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Metadata</dt>
                <dd>
                  <pre className="mt-1 overflow-auto rounded-lg bg-background p-3 font-mono text-xs">
                    {JSON.stringify(selected.metadata, null, 2)}
                  </pre>
                </dd>
              </div>
            </dl>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
