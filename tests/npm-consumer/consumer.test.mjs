import { execFileSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const work = mkdtempSync(join(tmpdir(), "pedantry-consumer-"));
const consumer = join(work, "consumer");

/** Run a command in a consumer directory (default: the fixture) and return its output. */
function run(command, args, { allowFailure = false, cwd = consumer } = {}) {
  try {
    return execFileSync(command, args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    if (allowFailure) return `${error.stdout}${error.stderr}`;
    throw new Error(
      `${command} ${args.join(" ")} failed\n${error.stdout}\n${error.stderr}`,
      {
        cause: error,
      },
    );
  }
}

describe("@dryan/pedantry installed into a consumer", () => {
  before(() => {
    const packed = JSON.parse(
      execFileSync("npm", ["pack", "--json", "--pack-destination", work], {
        cwd: repo,
        encoding: "utf8",
      }),
    );
    cpSync(join(here, "fixture"), consumer, { recursive: true });
    // Stored under other names so ESLint and Stylelint in this repo do not
    // discover them as nested configs; the consumer needs the real names.
    for (const [from, to] of [
      ["eslint.config.template.ts", "eslint.config.ts"],
      ["stylelint.config.template.mjs", "stylelint.config.mjs"],
    ]) {
      renameSync(join(consumer, from), join(consumer, to));
    }
    run("npm", [
      "install",
      "--no-audit",
      "--no-fund",
      "--ignore-scripts",
      join(work, packed[0].filename),
      "eslint",
      "typescript",
      "prettier",
      "stylelint",
      "vitest",
      "rollup",
      "@rollup/plugin-node-resolve",
      "@rollup/plugin-commonjs",
      "@rollup/plugin-typescript",
      "@rollup/plugin-terser",
      "rollup-plugin-summary",
      "@web/test-runner-playwright",
    ]);
  });

  after(() => {
    // The temp directory lives under the OS temp dir; leave cleanup to the OS
    // so a failing run can be inspected.
  });

  it("lints TypeScript and JSON with @dryan/pedantry/eslint", () => {
    run("npx", ["eslint", "."]);
  });

  it("flags a violation (the config is really applied)", () => {
    writeFileSync(join(consumer, "src", "bad.ts"), "const unused = 1;\n");
    const output = run("npx", ["eslint", "src/bad.ts"], { allowFailure: true });
    assert.match(output, /no-unused-vars/);
    run("rm", ["src/bad.ts"]);
  });

  it("type-checks with @dryan/pedantry/tsconfig", () => {
    run("npx", ["tsc", "--noEmit"]);
    const shown = run("npx", ["tsc", "--showConfig"]);
    assert.equal(JSON.parse(shown).compilerOptions.strict, true);
  });

  it("formats with @dryan/pedantry/prettier", () => {
    run("npx", ["prettier", "--check", "src", "package.json", "tsconfig.json"]);
  });

  it("lints CSS with @dryan/pedantry/stylelint", () => {
    run("npx", ["stylelint", "src/**/*.css"]);
  });

  it("exposes the build and test helpers", () => {
    const output = run("node", ["helpers.mjs"]);
    assert.match(output, /helpers ok/);
  });

  it("ships the exports declared in package.json", () => {
    const pkg = JSON.parse(readFileSync(join(repo, "package.json"), "utf8"));
    assert.deepEqual(Object.keys(pkg.exports).sort(), [
      "./custom-elements-manifest",
      "./eslint",
      "./package.json",
      "./prettier",
      "./rollup",
      "./stylelint",
      "./tsconfig",
      "./vitest",
      "./web-test-runner",
    ]);
  });
});

describe("@dryan/pedantry/eslint on TypeScript 7", () => {
  const consumer7 = join(work, "consumer7");

  before(() => {
    mkdirSync(join(consumer7, "src"), { recursive: true });
    cpSync(
      join(here, "fixture", "package.json"),
      join(consumer7, "package.json"),
    );
    cpSync(
      join(here, "fixture", "eslint.config.template.ts"),
      join(consumer7, "eslint.config.ts"),
    );
    writeFileSync(join(consumer7, "src", "ok.js"), "export const ok = 1;\n");
    writeFileSync(join(consumer7, "src", "bad.js"), "const unused = 1;\n");
    writeFileSync(join(consumer7, "src", "ts.ts"), "const x: number = 1;\n");
    const packed = readdirSync(work).find((name) => name.endsWith(".tgz"));
    run(
      "npm",
      [
        "install",
        "--no-audit",
        "--no-fund",
        "--ignore-scripts",
        join(work, packed),
        "eslint",
        "typescript@7",
      ],
      { cwd: consumer7 },
    );
  });

  it("loads, warns, and lints JavaScript without typescript-eslint", () => {
    const ok = run("npx", ["eslint", "src/ok.js"], { cwd: consumer7 });
    assert.doesNotMatch(ok, /error/);
    const bad = run("npx", ["eslint", "src/bad.js"], {
      cwd: consumer7,
      allowFailure: true,
    });
    assert.match(bad, /no-unused-vars/);
    assert.match(bad, /TypeScript 7/);
  });

  it("does not try to parse TypeScript files", () => {
    const output = run("npx", ["eslint", "."], {
      cwd: consumer7,
      allowFailure: true,
    });
    assert.doesNotMatch(output, /Parsing error|ts\.TypeFlags/);
    assert.doesNotMatch(output, /src\/ts\.ts/);
  });
});
