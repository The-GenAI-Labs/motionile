import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { StageTiming } from "@/features/admin-render/schemas/admin-render.schema";
import { stageLabels } from "@/features/admin-render/schemas/admin-render.schema";
import type { RenderStage } from "@/features/admin-render/types/admin-render.types";
import { titleCase } from "@/lib/utils/format";

const MS_PER_SECOND = 1_000;

const labelFor = (stage: string): string =>
  stage in stageLabels ? stageLabels[stage as RenderStage] : titleCase(stage);

export const formatSeconds = (milliseconds: number): string =>
  `${(milliseconds / MS_PER_SECOND).toFixed(1)} s`;

export function TimingsTable({ timings }: { timings: readonly StageTiming[] }) {
  if (timings.length === 0) {
    return null;
  }
  const total = timings.reduce((sum, timing) => sum + timing.milliseconds, 0);
  return (
    <section aria-labelledby="timings-heading" className="space-y-3">
      <h2 id="timings-heading" className="text-xl font-semibold">
        Stage timings
      </h2>
      <Table>
        <TableCaption className="sr-only">Time spent in each render stage</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">Stage</TableHead>
            <TableHead scope="col" className="text-right">
              Duration
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {timings.map((timing) => (
            <TableRow key={timing.stage}>
              <TableCell>{labelFor(timing.stage)}</TableCell>
              <TableCell className="text-right font-mono">
                {formatSeconds(timing.milliseconds)}
              </TableCell>
            </TableRow>
          ))}
          <TableRow>
            <TableCell className="font-medium">Total</TableCell>
            <TableCell className="text-right font-mono font-medium">
              {formatSeconds(total)}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </section>
  );
}
