/**
 * Merge `overrides` over `base`. Plain objects merge recursively; everything
 * else (arrays, functions, primitives) is replaced.
 */
export declare function merge<T extends Record<string, unknown>>(
  base: T,
  overrides?: Record<string, unknown>,
): T;
