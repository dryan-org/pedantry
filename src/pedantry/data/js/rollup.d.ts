import type { RollupOptions } from "rollup";

export declare function rollupConfig(
  overrides?: Record<string, unknown>,
): Promise<RollupOptions>;
