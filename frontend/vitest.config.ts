import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Required for Testing Library's automatic between-test cleanup.
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
});
