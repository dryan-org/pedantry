import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import prettierConfig from "eslint-config-prettier";
import json from "@eslint/json";
import globals from "globals";

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
  ...tseslint.configs.recommended.map((recommended) => ({
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
      "@typescript-eslint/no-unused-vars": [
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
