import { createBaseConfig } from "@motionile/config/eslint";

export default [
  ...createBaseConfig({ tsconfigRootDir: import.meta.dirname }),
  {
    files: ["load/**/*.js"],
    languageOptions: {
      globals: { __ENV: "readonly", __VU: "readonly", __ITER: "readonly" },
    },
  },
  { ignores: ["zap-report/**"] },
];
