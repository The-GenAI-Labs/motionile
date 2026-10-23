import { CheckCircle2Icon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  sortIssues,
  type ValidationReport as Report,
} from "@/features/admin-render/schemas/admin-render.schema";
import { formatTimestampMs } from "@/lib/utils/format";

const DASH = "-";

export function ValidationReport({ report }: { report: Report | null }) {
  if (report === null) {
    return null;
  }
  const issues = sortIssues(report.issues);
  const errors = issues.filter((issue) => issue.severity === "error").length;
  const warnings = issues.length - errors;
  return (
    <section aria-labelledby="validation-heading" className="space-y-3">
      <h2 id="validation-heading" className="text-xl font-semibold">
        Validation report
      </h2>
      {issues.length === 0 ? (
        <p role="status" className="flex items-center gap-2 text-sm text-success">
          <CheckCircle2Icon aria-hidden="true" className="size-4" />
          No issues found. The composition is valid.
        </p>
      ) : (
        <>
          <p className="text-sm text-subtle-foreground">
            {`${String(errors)} ${errors === 1 ? "error" : "errors"}, ${String(warnings)} ${warnings === 1 ? "warning" : "warnings"}. ${report.valid ? "The composition is valid." : "Errors block the render."}`}
          </p>
          <Table>
            <TableCaption className="sr-only">Validation issues, errors first</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Severity</TableHead>
                <TableHead scope="col">Code</TableHead>
                <TableHead scope="col">Message</TableHead>
                <TableHead scope="col">Scene</TableHead>
                <TableHead scope="col">Time</TableHead>
                <TableHead scope="col">Aspect</TableHead>
                <TableHead scope="col">Selector</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {issues.map((issue, index) => (
                <TableRow key={`${issue.code}-${String(index)}`}>
                  <TableCell>
                    <Badge variant={issue.severity === "error" ? "destructive" : "outline"}>
                      {issue.severity === "error" ? "Error" : "Warning"}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono">{issue.code}</TableCell>
                  <TableCell className="max-w-md whitespace-normal">{issue.message}</TableCell>
                  <TableCell className="font-mono">{issue.scene ?? DASH}</TableCell>
                  <TableCell className="font-mono">
                    {issue.timeMs === null || issue.timeMs === undefined
                      ? DASH
                      : formatTimestampMs(issue.timeMs)}
                  </TableCell>
                  <TableCell className="font-mono">{issue.aspect ?? DASH}</TableCell>
                  <TableCell className="font-mono">{issue.selector ?? DASH}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </section>
  );
}
