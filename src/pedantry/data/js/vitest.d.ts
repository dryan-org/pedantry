import type { UserConfig } from "vitest/config";

export declare function vitestConfig(
  overrides?: Record<string, unknown>,
  options?: { root?: string },
): UserConfig;
