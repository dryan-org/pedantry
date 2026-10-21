import type { Linter } from "eslint";

/** Pedantry's flat ESLint config. Spread it, then append repo overrides. */
declare const config: Linter.Config[];
export default config;
