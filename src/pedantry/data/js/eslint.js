import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import eslint from "@eslint/js";
import prettierConfig from "eslint-config-prettier";
import json from "@eslint/json";
import globals from "globals";

/**
 * Major version of the TypeScript the project (not this package) has installed,
 * or null when it cannot be found. typescript-eslint reads the TypeScript JS
 * API, which TypeScript 7 (the native port) does not export.
 */
function typescriptMajor() {
  try {
    const require = createRequire(pathToFileURL(`${process.cwd()}/`));
    return Number.parseInt(require("typescript/package.json").version, 10);
  } catch {
    return null;
  }
}

const major = typescriptMajor();
const typescriptSupported = major === null || major < 7;
const tseslint = typescriptSupported
  ? (await import("typescript-eslint")).default
  : null;

if (!typescriptSupported) {
  console.warn(
    `@dryan/pedantry/eslint: TypeScript ${major} found. typescript-eslint cannot run on TypeScript 7 or later, so ESLint skips TypeScript files (use tsc for those). JavaScript and JSON are still linted.`,
  );
}

/** @type {import("eslint").Linter.Config[]} */
const config = [
  {
    // Global ignores
    ignores: [
      "node_modules/**",
      "dist/**",
      "build/**",
      ".vscode/**",
      ".rollup.cache/**",
      "coverage/**",
      "package-lock.json",
      "*.backup.*",
      "*.js", // Ignore generated JS files
      "!*.config.js", // But don't ignore config files
      "!eslint.config.js",
      "!eslint.config.ts",
      "!rollup.config.js",
      "!web-test-runner.config.js",
      "!scripts/**/*.js",
      // Python
      "__pycache__/**",
      "*.pyc",
      ".pytest_cache/**",
      ".ruff_cache/**",
      "*.egg-info/**",
      ".venv/**",
      "venv/**",
      // Files written by `pedantry sync`
      ".pedantry/**",
      // No parser for these without typescript-eslint (TypeScript 7 or later)
      ...(typescriptSupported ? [] : ["**/*.{ts,tsx,mts,cts}"]),
    ],
  },

  // JSON files
  {
    files: ["**/*.json"],
    ignores: ["**/tsconfig*.json"], // Exclude tsconfig which has comments
    language: "json/json",
    ...json.configs.recommended,
  },

  // JSONC files (JSON with Comments like tsconfig.json)
  {
    files: ["**/tsconfig*.json"],
    language: "json/jsonc",
    ...json.configs.recommended,
  },

  // Base configs
  {
    ...eslint.configs.recommended,
    files: ["**/*.{js,ts,jsx,tsx}"],
  },
  ...(tseslint?.configs.recommended ?? []).map((recommended) => ({
    ...recommended,
    files: ["**/*.{js,ts,jsx,tsx}"],
  })),
  {
    ...prettierConfig,
    files: ["**/*.{js,ts,jsx,tsx}"],
  },

  // JavaScript/TypeScript files - custom rules
  {
    files: ["**/*.js", "**/*.ts"],
    rules: {
      // Web Components often use property decorators
      [typescriptSupported
        ? "@typescript-eslint/no-unused-vars"
        : "no-unused-vars"]: [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          // Ignore decorator-related unused vars
          ignoreRestSiblings: true,
        },
      ],
    },
  },

  // Config files - add Node.js globals
  {
    files: ["*.config.js", "*.config.ts", "scripts/**/*.js", "scripts/**/*.ts"],
    languageOptions: {
      globals: globals.node,
    },
  },

  // Browser-based files - add browser globals
  {
    files: ["src/**/*.js", "src/**/*.ts"],
    languageOptions: {
      globals: globals.browser,
    },
  },

  // Test files - add test globals
  {
    files: ["**/*.test.js", "**/*.test.ts", "**/*.spec.js", "**/*.spec.ts"],
    languageOptions: {
      globals: globals.jest,
    },
  },
];

export default config;
