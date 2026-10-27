import { defineConfig } from "vitest/config";

// Vitest 5 dropped poolOptions; maxWorkers caps the thread pool at 4.
export default defineConfig({
  test: {
    environment: "jsdom",
    pool: "threads",
    maxWorkers: 4,
    setupFiles: ["test/setup.ts"],
  },
});
