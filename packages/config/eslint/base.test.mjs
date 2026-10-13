import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import { createBaseConfig } from "./base.mjs";

const lint = async (code) => {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: createBaseConfig({ tsconfigRootDir: import.meta.dirname }),
  });
  const [result] = await eslint.lintText(code, { filePath: "sample.mjs" });
  return result.messages.map((message) => message.ruleId);
};

describe("base config", () => {
  it("accepts code without comments", async () => {
    expect(await lint("export const answer = 42;\n")).toEqual([]);
  });

  it("reports ordinary comments", async () => {
    expect(await lint("export const answer = 42;\n// remark\n")).toContain("motionile/no-comments");
  });

  it("reports file-wide eslint-disable even though it silences other rules", async () => {
    const ruleIds = await lint("/* eslint-disable */\nexport const answer = 42;\n");
    expect(ruleIds).toContain("eslint-comments/no-use");
  });

  it("reports eslint-disable-next-line without a rule name", async () => {
    const ruleIds = await lint("// eslint-disable-next-line\nconsole.log(1);\n");
    expect(ruleIds).toContain("eslint-comments/no-unlimited-disable");
  });

  it("accepts eslint-disable-next-line naming a rule", async () => {
    expect(await lint("// eslint-disable-next-line no-console\nconsole.log(1);\n")).toEqual([]);
  });

  it("reports unsorted imports", async () => {
    const ruleIds = await lint('import { b } from "b";\nimport { a } from "a";\nexport { a, b };\n');
    expect(ruleIds).toContain("simple-import-sort/imports");
  });
});
