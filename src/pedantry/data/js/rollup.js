import { merge } from "./merge.js";

/**
 * Pedantry's Rollup config for Web Components. Call it from your own
 * `rollup.config.js` (Rollup accepts a promise):
 *
 *     import { rollupConfig } from "@dryan/pedantry/rollup";
 *     export default rollupConfig({ input: "src/my-element.ts" });
 *
 * Needs these optional peer dependencies installed in the repo:
 * @rollup/plugin-node-resolve, @rollup/plugin-commonjs,
 * @rollup/plugin-typescript, @rollup/plugin-terser, rollup-plugin-summary.
 *
 * Plain objects in `overrides` merge into the defaults; arrays (including
 * `plugins` and `external`) replace them.
 *
 * @param {Record<string, unknown>} [overrides]
 * @returns {Promise<import("rollup").RollupOptions>}
 */
export async function rollupConfig(overrides = {}) {
  const [{ default: resolve }, { default: commonjs }, { default: typescript }] =
    await Promise.all([
      import("@rollup/plugin-node-resolve"),
      import("@rollup/plugin-commonjs"),
      import("@rollup/plugin-typescript"),
    ]);
  const [{ default: terser }, { default: summary }] = await Promise.all([
    import("@rollup/plugin-terser"),
    import("rollup-plugin-summary"),
  ]);

  const production = !process.env["ROLLUP_WATCH"];

  return /** @type {import("rollup").RollupOptions} */ (
    merge(
      {
        input: "src/index.ts",
        output: { dir: "dist", format: "es", sourcemap: true },
        plugins: [
          resolve(),
          commonjs(),
          typescript({
            declaration: true,
            declarationDir: "dist/types",
            rootDir: "src",
          }),
          production && terser({ ecma: 2020, module: true }),
          summary(),
        ],
        // Lit is typically externalized in library builds
        external: [/^lit/],
        preserveEntrySignatures: "strict",
      },
      overrides,
    )
  );
}
