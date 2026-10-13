import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../../apps/server/openapi.json",
  output: {
    path: "src/generated",
    clean: true,
  },
  plugins: ["@hey-api/typescript", "zod"],
});
