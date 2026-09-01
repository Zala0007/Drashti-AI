import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    // UI suites change shared browser state such as location hashes and global fetch.
    // Run files sequentially to keep those operator-workflow tests deterministic.
    fileParallelism: false,
  },
});
