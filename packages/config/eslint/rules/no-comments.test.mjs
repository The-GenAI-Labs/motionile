import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { afterAll, describe, it } from "vitest";

import noComments from "./no-comments.mjs";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tseslint.parser },
});

const forbidden = [{ messageId: "forbidden" }];

ruleTester.run("no-comments", noComments, {
  valid: [
    { code: "const answer = 42;" },
    { code: 'const url = "https://example.com/#anchor";' },
    { code: "const pattern = /\\/\\/ not a comment/u;" },
    { code: "// eslint-disable-next-line no-console\nconsole.log(1);" },
    { code: "// @ts-expect-error legacy typings are wrong\nconst value: number = '1';" },
    { code: "/* @ts-expect-error JSX attribute typing is incomplete */\nconst value = 1;" },
    { code: '/// <reference types="vite/client" />\nexport {};' },
    { code: '/// <reference path="./globals.d.ts" />\nexport {};' },
    { code: "#!/usr/bin/env node\nconst value = 1;" },
  ],
  invalid: [
    { code: "// explains the next line\nconst value = 1;", errors: forbidden },
    { code: "const value = 1; // trailing remark", errors: forbidden },
    { code: "/* block remark */\nconst value = 1;", errors: forbidden },
    { code: "/**\n * Documentation block\n */\nfunction run() {}", errors: forbidden },
    { code: "// const disabled = true;\nconst value = 1;", errors: forbidden },
    { code: "// eslint-disable-next-line\nconst value = 1;", errors: forbidden },
    { code: "// @ts-expect-error\nconst value = 1;", errors: forbidden },
    { code: "// TODO: remove later\nconst value = 1;", errors: forbidden },
    { code: "/// just three slashes\nconst value = 1;", errors: forbidden },
    { code: "// first\n// second\nconst value = 1;", errors: [...forbidden, ...forbidden] },
  ],
});
