"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { CreateDraftDialog } from "@/features/admin-prompts/components/create-draft-dialog";
import { EvalRunsPanel } from "@/features/admin-prompts/components/eval-runs-panel";
import { PromptStatusBadge } from "@/features/admin-prompts/components/prompt-status-badge";
import { RollbackButton } from "@/features/admin-prompts/components/version-controls";
import { VersionDiff } from "@/features/admin-prompts/components/version-diff";
import { VersionsPanel } from "@/features/admin-prompts/components/versions-panel";
import { adminPromptsErrorMessage } from "@/features/admin-prompts/errors";
import {
  usePromptTemplates,
  usePromptVersions,
} from "@/features/admin-prompts/hooks/use-admin-prompts";
import { flattenCursorPages } from "@/lib/api/pagination";

export function TemplateDetail({ templateKey }: { templateKey: string }) {
  const templates = usePromptTemplates();
  const versions = usePromptVersions(templateKey);
  const template = templates.data?.items.find((item) => item.key === templateKey);
  const loaded = flattenCursorPages(versions.data?.pages);
  if (templates.isPending) {
    return (
      <Skeleton role="status" aria-hidden={false} aria-label="Loading template" className="h-96" />
    );
  }
  if (templates.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {adminPromptsErrorMessage(templates.error)}
      </p>
    );
  }
  if (template === undefined) {
    return (
      <p role="alert" className="text-sm text-destructive">
        This prompt template does not exist. Return to the list.
      </p>
    );
  }
  return (
    <div className="space-y-6">
      <DetailSection
        title="Template"
        actions={
          <>
            <CreateDraftDialog templateKey={templateKey} />
            <RollbackButton templateKey={templateKey} disabled={template.activeVersion === null} />
          </>
        }
      >
        <DetailList
          items={[
            { label: "Key", value: <span className="font-mono">{template.key}</span> },
            {
              label: "Active version",
              value: (
                <span className="font-mono">
                  {template.activeVersion === null ? "None" : `v${String(template.activeVersion)}`}
                </span>
              ),
            },
            {
              label: "Latest eval",
              value: <PromptStatusBadge status={template.latestEvalStatus} />,
            },
            {
              label: "Versions",
              value: <span className="font-mono">{template.versionCount}</span>,
            },
            { label: "Description", value: template.description ?? "No description" },
          ]}
        />
      </DetailSection>
      <VersionsPanel templateKey={templateKey} versions={versions} />
      <VersionDiff templateKey={templateKey} versions={loaded} />
      <EvalRunsPanel versions={loaded} />
    </div>
  );
}
