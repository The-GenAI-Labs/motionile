import { TriangleAlertIcon } from "lucide-react";

import { renderFailureMessage, renderStatusGuidance } from "@/features/admin-render/errors";
import type { RenderStatus } from "@/features/admin-render/types/admin-render.types";

interface FailurePanelProps {
  status: RenderStatus;
  errorCode: string | null | undefined;
  errorMessage: string | null | undefined;
}

export function FailurePanel({ status, errorCode, errorMessage }: FailurePanelProps) {
  if (status === "cancelled") {
    return (
      <section aria-labelledby="failure-heading" className="space-y-2">
        <h2 id="failure-heading" className="text-xl font-semibold">
          Render cancelled
        </h2>
        <p role="status" className="text-sm text-subtle-foreground">
          {renderStatusGuidance["cancelled"]}
        </p>
      </section>
    );
  }
  if (status !== "failed") {
    return null;
  }
  return (
    <section
      aria-labelledby="failure-heading"
      className="space-y-3 rounded-xl border border-destructive/50 bg-surface p-5"
    >
      <h2
        id="failure-heading"
        className="flex items-center gap-2 text-xl font-semibold text-destructive"
      >
        <TriangleAlertIcon aria-hidden="true" className="size-5" />
        Render failed
      </h2>
      <div role="alert" className="space-y-2 text-sm">
        {errorCode ? (
          <p>
            Error code: <span className="font-mono">{errorCode}</span>
          </p>
        ) : null}
        {errorMessage ? <p>{errorMessage}</p> : null}
        <p className="text-subtle-foreground">{renderFailureMessage(errorCode)}</p>
      </div>
    </section>
  );
}
