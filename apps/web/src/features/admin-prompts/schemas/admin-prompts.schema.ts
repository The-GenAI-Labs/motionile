import { zDraftRequest } from "@motionile/api-contract";
import { z } from "zod";

import type {
  ActivationBlock,
  DiffLine,
  DraftInput,
} from "@/features/admin-prompts/types/admin-prompts.types";

export const PROMPTS_PAGE_SIZE = 25;
export const EVAL_RUNS_PAGE_SIZE = 25;
export const MIN_BODY_CHARS = 20;
export const MAX_BODY_CHARS = 60_000;
export const MAX_VARIABLES = 32;
export const VARIABLE_PATTERN = /^[a-z][a-z0-9_]*$/;
export const MAX_VARIABLE_LENGTH = 64;
export const PROMPT_KEY_PATTERN = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/;
export const MAX_KEY_LENGTH = 64;

export const EVAL_SUITES = ["safety", "planner", "cost", "scenes", "sync"] as const;

export const promptKeySchema = z.string().max(MAX_KEY_LENGTH).regex(PROMPT_KEY_PATTERN);

export const versionNumberSchema = z.int().gte(1).lte(2_147_483_647);

export const splitVariables = (value: string): string[] =>
  value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => item !== "");

export const draftFormSchema = z.object({
  body: z
    .string()
    .trim()
    .min(MIN_BODY_CHARS, `Write at least ${String(MIN_BODY_CHARS)} characters.`)
    .max(MAX_BODY_CHARS, `Use at most ${String(MAX_BODY_CHARS)} characters.`),
  variables: z.string().superRefine((value, ctx) => {
    const names = splitVariables(value);
    if (names.length > MAX_VARIABLES) {
      ctx.addIssue({
        code: "custom",
        message: `Declare at most ${String(MAX_VARIABLES)} variables.`,
      });
    }
    const invalid = names.find(
      (name) => name.length > MAX_VARIABLE_LENGTH || !VARIABLE_PATTERN.test(name),
    );
    if (invalid !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: `${invalid} is not a valid variable name. Use lowercase letters, digits and underscores, starting with a letter.`,
      });
    }
  }),
});

export type DraftFormValues = z.infer<typeof draftFormSchema>;

export const emptyDraftValues: DraftFormValues = { body: "", variables: "" };

export const toDraftInput = (values: DraftFormValues): DraftInput => ({
  body: values.body,
  variables: zDraftRequest.shape.variables.parse(splitVariables(values.variables)) ?? [],
});

export const MAX_RUN_VERSIONS = 20;

export const startEvalFormSchema = z.object({
  suite: z
    .string()
    .refine((value) => EVAL_SUITES.some((suite) => suite === value), "Choose a suite."),
  versionIds: z
    .array(z.uuid())
    .min(1, "Choose at least one version.")
    .max(MAX_RUN_VERSIONS, `Choose at most ${String(MAX_RUN_VERSIONS)} versions.`),
});

export type StartEvalFormValues = z.infer<typeof startEvalFormSchema>;

export const draftFieldNames = ["body", "variables"] as const;

export type DraftFieldName = (typeof draftFieldNames)[number];

export const draftFieldOf = (path: string): DraftFieldName | undefined =>
  draftFieldNames.find((name) => path === name || path.endsWith(`.${name}`));

const diffLineKind = (text: string): DiffLine["kind"] => {
  if (text.startsWith("+++") || text.startsWith("---")) {
    return "header";
  }
  if (text.startsWith("@@")) {
    return "hunk";
  }
  if (text.startsWith("+")) {
    return "added";
  }
  return text.startsWith("-") ? "removed" : "context";
};

export const parseDiffLines = (lines: readonly string[]): DiffLine[] =>
  lines.map((text, id) => ({ id, kind: diffLineKind(text), text }));

const splitSuites = (value: string | number | boolean | undefined): string[] =>
  typeof value === "string"
    ? value
        .split(",")
        .map((suite) => suite.trim())
        .filter((suite) => suite !== "")
    : [];

export const readActivationBlock = (
  extensions: Readonly<Record<string, string | number | boolean>>,
): ActivationBlock => ({
  missingSuites: splitSuites(extensions["missingSuites"]),
  failedSuites: splitSuites(extensions["failedSuites"]),
});

export const describeActivationBlock = (block: ActivationBlock): string => {
  const parts: string[] = [];
  if (block.missingSuites.length > 0) {
    parts.push(`No passing run yet for: ${block.missingSuites.join(", ")}.`);
  }
  if (block.failedSuites.length > 0) {
    parts.push(`The latest run failed for: ${block.failedSuites.join(", ")}.`);
  }
  const base = "Every required suite needs a finished, passing run that covers this version.";
  return parts.length === 0 ? base : `${base} ${parts.join(" ")}`;
};
