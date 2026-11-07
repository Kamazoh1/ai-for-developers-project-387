import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../api/dist/openapi.yaml",
  output: "src/api",
  plugins: ["@hey-api/client-fetch", "@hey-api/sdk", "@hey-api/typescript"],
});
