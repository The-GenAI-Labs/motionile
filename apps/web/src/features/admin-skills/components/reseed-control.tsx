"use client";

import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { DetailList } from "@/features/admin-billing/components/detail-section";
import { adminSkillsErrorMessage } from "@/features/admin-skills/errors";
import { useReseedSkills } from "@/features/admin-skills/hooks/use-admin-skills";
import type { ReseedReport } from "@/features/admin-skills/types/admin-skills.types";

export function ReseedReportView({ report }: { report: ReseedReport }) {
  return (
    <section
      aria-label="Reseed result"
      role="status"
      className="space-y-3 rounded-xl border bg-surface p-4"
    >
      <h2 className="font-semibold">Last reseed</h2>
      <DetailList
        items={[
          { label: "Created", value: <span className="font-mono">{report.created}</span> },
          { label: "Updated", value: <span className="font-mono">{report.updated}</span> },
          { label: "Unchanged", value: <span className="font-mono">{report.unchanged}</span> },
          {
            label: "Descriptions embedded",
            value: <span className="font-mono">{report.embedded}</span>,
          },
        ]}
      />
    </section>
  );
}

export function ReseedControl({ onReseeded }: { onReseeded: (report: ReseedReport) => void }) {
  const reseed = useReseedSkills();
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFailure(null);
        }
      }}
      trigger={
        <Button variant="outline">
          <RefreshCwIcon aria-hidden="true" /> Reseed
        </Button>
      }
      title="Reseed the system skills?"
      description="Synchronizes the system skills with the shipped library. A changed skill gets a new version, earlier versions stay, and unchanged skills are left alone. Descriptions embedded with another model are embedded again."
      confirmLabel="Reseed"
      error={failure === null ? null : adminSkillsErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          const result = await reseed.mutateAsync();
          onReseeded(result);
          toast.success("System skills reseeded");
        } catch (error) {
          setFailure(error);
          throw error;
        }
      }}
    />
  );
}
