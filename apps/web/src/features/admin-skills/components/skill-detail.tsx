"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { EmbeddingBadge } from "@/features/admin-skills/components/embedding-badge";
import { adminSkillsErrorMessage } from "@/features/admin-skills/errors";
import { useSystemSkill } from "@/features/admin-skills/hooks/use-admin-skills";
import { checksumPrefix } from "@/features/admin-skills/schemas/admin-skills.schema";
import { formatCredits, formatDateTime } from "@/lib/utils/format";

export function SkillDetail({ slug }: { slug: string }) {
  const skill = useSystemSkill(slug);
  if (skill.isPending) {
    return (
      <Skeleton role="status" aria-hidden={false} aria-label="Loading skill" className="h-72" />
    );
  }
  if (skill.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{adminSkillsErrorMessage(skill.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void skill.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  const data = skill.data;
  return (
    <div className="space-y-6">
      <DetailSection title="Skill">
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{data.layer}</Badge>
          <EmbeddingBadge status={data.embeddingStatus} />
        </div>
        <p className="text-sm">{data.description}</p>
        <DetailList
          items={[
            { label: "Slug", value: <span className="font-mono">{data.slug}</span> },
            { label: "Current version", value: <span className="font-mono">v{data.version}</span> },
            {
              label: "Checksum",
              value: <span className="font-mono text-xs">{checksumPrefix(data.checksum)}</span>,
            },
            {
              label: "Tokens",
              value: <span className="font-mono">{formatCredits(data.tokenCount)}</span>,
            },
            { label: "Updated", value: formatDateTime(data.updatedAt) },
          ]}
        />
        <p className="text-sm text-muted-foreground">
          System skill text is never returned by the API, so only metadata is shown.
        </p>
      </DetailSection>
      <DetailSection title="Version history">
        <Table aria-label={`Versions of ${data.name}`}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Version</TableHead>
              <TableHead scope="col">Checksum</TableHead>
              <TableHead scope="col">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.versions.map((version) => (
              <TableRow key={version.number}>
                <TableCell className="font-mono">
                  v{version.number}
                  {version.number === data.version ? " (current)" : ""}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {checksumPrefix(version.checksum)}
                </TableCell>
                <TableCell>{formatDateTime(version.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DetailSection>
    </div>
  );
}
