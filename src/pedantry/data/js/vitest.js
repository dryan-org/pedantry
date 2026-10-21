import { resolve } from "node:path";

import { merge } from "./merge.js";

/**
 * Pedantry's Vitest config. Call it from your own `vitest.config.ts`:
 *
 *     import { defineConfig } from "vitest/config";
 *     import { vitestConfig } from "@dryan/pedantry/vitest";
 *
 *     export default defineConfig(vitestConfig({ test: { environment: "jsdom" } }));
 *
 * Plain objects in `overrides` merge into the defaults; arrays replace them.
 * Path aliases resolve against `root` (default: the current directory).
 *
 * @param {Record<string, unknown>} [overrides]
 * @param {{ root?: string }} [options]
 * @returns {import("vitest/config").UserConfig}
 */
export function vitestConfig(overrides = {}, { root = process.cwd() } = {}) {
  const src = (/** @type {string} */ path) => resolve(root, "src", path);

  return merge(
    {
      test: {
        environment: "node",
        include: ["src/**/*.test.ts", "tests/**/*.test.ts", "**/*.spec.ts"],
        exclude: ["node_modules", "dist", "build", ".vscode"],
        coverage: {
          provider: "v8",
          reporter: ["text", "json", "html"],
          exclude: [
            "node_modules",
            "dist",
            "build",
            "**/*.test.ts",
            "**/*.spec.ts",
            "**/*.config.*",
            "**/types/**",
          ],
        },
        // Jest-like global API
        globals: true,
        testTimeout: 10000,
      },
      // Match the path aliases in tsconfig.json
      resolve: {
        alias: {
          "@": src("."),
          "~": src("."),
          "@components": src("components"),
          "@utils": src("utils"),
          "@styles": src("styles"),
          "@types": src("types"),
        },
      },
    },
    overrides,
  );
}
