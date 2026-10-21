/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isPlainObject(value) {
  return (
    typeof value === "object" &&
    value !== null &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

/**
 * Merge `overrides` over `base`. Plain objects merge recursively; everything
 * else (arrays, functions, class instances, primitives) is replaced.
 *
 * @template {Record<string, unknown>} T
 * @param {T} base
 * @param {Record<string, unknown>} [overrides]
 * @returns {T}
 */
export function merge(base, overrides = {}) {
  /** @type {Record<string, unknown>} */
  const result = { ...base };
  for (const [key, value] of Object.entries(overrides)) {
    const current = result[key];
    result[key] =
      isPlainObject(current) && isPlainObject(value)
        ? merge(current, value)
        : value;
  }
  return /** @type {T} */ (result);
}
