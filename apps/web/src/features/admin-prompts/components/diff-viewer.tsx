import { parseDiffLines } from "@/features/admin-prompts/schemas/admin-prompts.schema";
import type { DiffLineKind, PromptDiff } from "@/features/admin-prompts/types/admin-prompts.types";
import { cn } from "@/lib/utils/cn";

const lineClasses = {
  header: "font-semibold text-foreground",
  hunk: "text-muted-foreground",
  added: "bg-success/15 text-success",
  removed: "bg-destructive/20 text-destructive",
  context: "text-subtle-foreground",
} as const satisfies Record<DiffLineKind, string>;

const lineLabels = {
  header: "File: ",
  hunk: "Section: ",
  added: "Added: ",
  removed: "Removed: ",
  context: "Unchanged: ",
} as const satisfies Record<DiffLineKind, string>;

export function DiffViewer({ diff }: { diff: PromptDiff }) {
  const lines = parseDiffLines(diff.lines);
  const label = `Unified diff of ${diff.key} from version ${String(diff.fromVersion)} to version ${String(diff.toVersion)}`;
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm text-subtle-foreground">
        Version {diff.fromVersion} to version {diff.toVersion}:{" "}
        <span className="font-mono text-success">{diff.added} lines added</span>,{" "}
        <span className="font-mono text-destructive">{diff.removed} lines removed</span>
      </figcaption>
      {lines.length === 0 ? (
        <p role="status" className="text-sm text-muted-foreground">
          These two versions are identical.
        </p>
      ) : (
        <pre
          role="region"
          aria-label={label}
          tabIndex={0}
          className="max-h-[32rem] overflow-auto rounded-lg border bg-background p-3 font-mono text-xs focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {lines.map((line) => (
            <code
              key={line.id}
              className={cn("block px-1 break-words whitespace-pre-wrap", lineClasses[line.kind])}
            >
              <span className="sr-only">{lineLabels[line.kind]}</span>
              {line.text}
            </code>
          ))}
        </pre>
      )}
    </figure>
  );
}
