import { customElementsManifestConfig } from "@dryan/pedantry/custom-elements-manifest";
import { rollupConfig } from "@dryan/pedantry/rollup";
import { vitestConfig } from "@dryan/pedantry/vitest";
import { webTestRunnerConfig } from "@dryan/pedantry/web-test-runner";
import prettier from "@dryan/pedantry/prettier";

const vitest = vitestConfig({ test: { environment: "jsdom" } }, { root: "/x" });
if (vitest.test?.environment !== "jsdom") throw new Error("override lost");
if (!vitest.test?.globals) throw new Error("default lost");
if (vitest.resolve?.alias["@components"] !== "/x/src/components")
  throw new Error("alias root");

const cem = customElementsManifestConfig({ outdir: "out" });
if (cem.outdir !== "out" || !Array.isArray(cem.globs)) throw new Error("cem");

const rollup = await rollupConfig({ input: "src/x.ts" });
if (rollup.input !== "src/x.ts" || rollup.output.format !== "es")
  throw new Error("rollup");

const wtr = await webTestRunnerConfig({ files: ["a.test.js"] });
if (wtr.files[0] !== "a.test.js" || wtr.browsers.length !== 3)
  throw new Error("wtr");

if (Object.keys(prettier).length !== 0) throw new Error("prettier");
console.log("helpers ok");
