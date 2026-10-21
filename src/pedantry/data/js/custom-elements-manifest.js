import { merge } from "./merge.js";

/**
 * Pedantry's Custom Elements Manifest config (generates custom-elements.json,
 * which VS Code and documentation tools use for autocomplete). Call it from
 * your own `custom-elements-manifest.config.js`:
 *
 *     import { customElementsManifestConfig } from "@dryan/pedantry/custom-elements-manifest";
 *     export default customElementsManifestConfig({ plugins: [] });
 *
 * @param {Record<string, unknown>} [overrides]
 * @returns {Record<string, unknown>}
 */
export function customElementsManifestConfig(overrides = {}) {
  return merge(
    {
      globs: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts", "src/**/*.spec.ts"],
      outdir: ".",
      plugins: [],
    },
    overrides,
  );
}
