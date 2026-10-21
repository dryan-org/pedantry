import { customElementsManifestConfig } from "@dryan/pedantry/custom-elements-manifest";
import { rollupConfig } from "@dryan/pedantry/rollup";
import { vitestConfig } from "@dryan/pedantry/vitest";
import { webTestRunnerConfig } from "@dryan/pedantry/web-test-runner";

export const vitest = vitestConfig({ test: { globals: false } });
export const manifest = customElementsManifestConfig();
export const rollup = rollupConfig({ input: "src/index.ts" });
export const wtr = webTestRunnerConfig();
