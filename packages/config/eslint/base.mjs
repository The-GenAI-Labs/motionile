import js from "@eslint/js";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import simpleImportSort from "eslint-plugin-simple-import-sort";
import globals from "globals";
import tseslint from "typescript-eslint";

import motionilePlugin from "./plugin.mjs";

export const GENERATED_IGNORES = [
  "**/node_modules/**",
  "**/.next/**",
  "**/.turbo/**",
  "**/dist/**",
  "**/coverage/**",
  "**/playwright-report/**",
  "**/test-results/**",
  "**/src/generated/**",
  "**/next-env.d.ts",
  "**/tests/fixtures/**",
  "**/vendor/**",
];

export const createBaseConfig = ({ tsconfigRootDir }) =>
  tseslint.config(
    { ignores: GENERATED_IGNORES },
    js.configs.recommended,
    tseslint.configs.strictTypeChecked,
    tseslint.configs.stylisticTypeChecked,
    {
      languageOptions: {
        parserOptions: {
          projectService: true,
          tsconfigRootDir,
        },
        globals: { ...globals.node },
      },
      linterOptions: {
        reportUnusedDisableDirectives: "error",
        reportUnusedInlineConfigs: "error",
      },
      plugins: {
        "eslint-comments": eslintComments,
        motionile: motionilePlugin,
        "simple-import-sort": simpleImportSort,
      },
      rules: {
        "motionile/no-comments": "error",
        "eslint-comments/no-use": ["error", { allow: ["eslint-disable-next-line"] }],
        "eslint-comments/no-unlimited-disable": "error",
        "simple-import-sort/imports": "error",
        "simple-import-sort/exports": "error",
        "no-console": "error",
        eqeqeq: ["error", "always"],
        "@typescript-eslint/consistent-type-imports": [
          "error",
          { fixStyle: "inline-type-imports" },
        ],
        "@typescript-eslint/no-import-type-side-effects": "error",
        "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      },
    },
    {
      files: ["**/*.{js,mjs,cjs}"],
      extends: [tseslint.configs.disableTypeChecked],
    },
    {
      files: ["apps/server/src/**/*.js"],
      languageOptions: { globals: { ...globals.browser } },
    },
  );
