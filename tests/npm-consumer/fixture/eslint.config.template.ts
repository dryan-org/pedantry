import type { Linter } from "eslint";
import pedantry from "@dryan/pedantry/eslint";

const config: Linter.Config[] = [...pedantry];

export default config;
