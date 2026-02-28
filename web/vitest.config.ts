import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url))
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["web/tests/**/*.test.ts?(x)"],
    setupFiles: ["web/tests/setup.ts"]
  }
});
