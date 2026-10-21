/**
 * Pedantry's Prettier config for CommonJS consumers (no "type": "module").
 * Same content as prettier.js: `require()` of an ES module hands back a
 * namespace object whose `__esModule` and `default` keys Prettier reads as
 * options, so `exports` points `require` at this file instead.
 *
 * @type {import("prettier").Config}
 */
module.exports = {};
