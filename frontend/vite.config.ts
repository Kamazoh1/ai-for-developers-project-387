import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The browser calls same-origin `/api`; the dev server forwards it to the backend.
    proxy: {
      "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
  test: {
    // Node's fetch needs absolute URLs; msw handlers use the same base (src/test/api.ts).
    env: { VITE_API_URL: "http://api.test" },
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
