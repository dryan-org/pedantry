import type { Linter } from "eslint";

import pedantry from "./src/pedantry/data/js/eslint.js";

const config: Linter.Config[] = [
  ...pedantry,
  {
    // Installed and linted by tests/npm-consumer, with the packed package
    ignores: ["tests/npm-consumer/fixture/**"],
  },
];

export default config;
