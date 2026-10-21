import { merge } from "./merge.js";

/**
 * Pedantry's @web/test-runner config (Playwright, three browsers). Call it from
 * your own `web-test-runner.config.js`:
 *
 *     import { webTestRunnerConfig } from "@dryan/pedantry/web-test-runner";
 *     export default await webTestRunnerConfig({ files: ["test/**\/*.test.js"] });
 *
 * Needs the optional peer dependencies @web/test-runner and
 * @web/test-runner-playwright. Plain objects in `overrides` merge into the
 * defaults; arrays (including `browsers`) replace them.
 *
 * @param {Record<string, unknown>} [overrides]
 * @returns {Promise<Record<string, unknown>>}
 */
export async function webTestRunnerConfig(overrides = {}) {
  const { playwrightLauncher } = await import("@web/test-runner-playwright");

  return merge(
    {
      files: ["src/**/*.test.ts", "tests/**/*.test.ts"],
      browsers: [
        playwrightLauncher({ product: "chromium" }),
        playwrightLauncher({ product: "firefox" }),
        playwrightLauncher({ product: "webkit" }),
      ],
      nodeResolve: true,
      coverage: true,
      coverageConfig: {
        report: true,
        reportDir: "coverage",
        threshold: { statements: 80, branches: 80, functions: 80, lines: 80 },
      },
      testFramework: { config: { timeout: 3000 } },
      // Preserve symlinks for monorepo setups
      preserveSymlinks: true,
    },
    overrides,
  );
}
