# Pedantry

Opinionated linting and formatting configuration for TypeScript, JavaScript, CSS, and Python projects, tuned for Web Components (vanilla and Lit) and hybrid Python/JavaScript repos.

Pedantry is one repo with one version, delivered two ways:

- **The `pedantry` CLI** (Python, run with `uvx`) writes the files no tool can share: `.editorconfig`, `lefthook.yml`, a `.prettierignore` baseline, the ruff/ty/vulture/pytest block in `pyproject.toml`, and the shared agent rules.
- **The `@dryan/pedantry` npm package** carries the configs that tools import natively: ESLint, TypeScript, Prettier, Stylelint, and helpers for Vitest, Rollup, `@web/test-runner` and the Custom Elements Manifest.

Every repo pins a pedantry version. Upgrading is one edit plus `pedantry sync`, and `pedantry check` fails CI when a repo drifts.

## What it enforces

| Area                  | Tools                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| JavaScript/TypeScript | ESLint (flat config, typescript-eslint, JSON/JSONC), Prettier (defaults only), strict tsconfig |
| CSS                   | Stylelint (standard + recess order), Shadow DOM aware (`:host`, `::slotted`, `::part`)         |
| Python                | Ruff (lint and format), ty, Vulture, pytest, django-upgrade (Django only)                      |
| Git hooks             | Lefthook, running the tools above on staged files                                              |
| Editor                | EditorConfig                                                                                   |
| Agents                | Shared rules in `.pedantry/AGENTS.md`                                                          |

## Set up a repo

You need [uv](https://docs.astral.sh/uv/) (every Mac and CI runner here has it). Run the CLI straight from GitHub at a tag:

```zsh
uvx --from git+https://github.com/dryan-org/pedantry@v2.0.0 pedantry sync --type python --type typescript
```

`--type` is one or more of `python`, `typescript`, `javascript`, `css`, `django` (Django implies Python, JavaScript and CSS). The first sync also records the pin, so later runs need no options.

For a repo with a `package.json`, add the npm package (it is not published to npmjs.org; it installs from GitHub like any `github:` dependency):

```zsh
npm install --save-dev github:dryan-org/pedantry#v2.0.0
npm install --save-dev eslint prettier typescript   # whichever tools the repo uses
```

Then enable the hooks and commit:

```zsh
lefthook install
```

For Python tools the hooks call `uv run`, so the repo needs them as dev dependencies:

```zsh
uv add --dev ruff vulture ty pytest        # plus django-upgrade for Django
```

## The CLI

```text
pedantry sync    [--type T ...] [--vendor] [--upgrade] [--dry-run] [--force] [--json] [--path DIR]
pedantry check   [--diff] [--json] [--path DIR]
pedantry migrate [--type T ...] [--vendor] [--skip-npm] [--dry-run] [--json] [--path DIR]
pedantry version
```

### sync

Writes the managed files for the pinned version and types. Run it again and nothing changes.

| File                           | How it is managed                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| `lefthook.yml`                 | Whole file, stamped. Python tools via `uv run`; prettier, eslint and stylelint via `npx`.      |
| `.pedantry/AGENTS.md`          | Whole file, stamped. The shared agent rules.                                                   |
| `.editorconfig`                | Block between `# >>> pedantry` and `# <<< pedantry`. Anything outside the markers is yours.    |
| `.prettierignore`              | Same marked block.                                                                             |
| `pyproject.toml`               | Same marked block with ruff, ty, vulture, pytest (and django-upgrade). Python and Django only. |
| `pedantry.toml` (no pyproject) | The pin only.                                                                                  |
| `.pedantry/*` with `--vendor`  | Local copies of the JS configs, see below.                                                     |

Stamped files start with `pedantry X.Y.Z: managed by pedantry sync, do not edit.`

Safeguards: sync refuses to overwrite a `lefthook.yml` (or other whole-file target) that has no stamp, and it refuses to write a `pyproject.toml` that would define a managed table twice. In both cases it points you to `pedantry migrate`. `--force` overwrites anyway. `--dry-run` prints diffs and writes nothing.

### check

Exits 1 and lists the files that differ from what sync would write for the pinned version (`--diff` shows how). Edits outside the markers never count as drift. Run it in CI:

```yaml
- run: uvx --from git+https://github.com/dryan-org/pedantry@v2.0.0 pedantry check
```

### migrate

Moves a repo that uses the old `.pedantry` git submodule and copied files. It never commits.

1. Removes the submodule (`.gitmodules`, the index entry, the checkout), and replaces symlinks into it.
2. With a `package.json`, runs `npm install --save-dev github:dryan-org/pedantry#vX.Y.Z` (skip with `--skip-npm`).
3. Rewrites the `eslint.config.*` import to `@dryan/pedantry/eslint`, points `tsconfig.json` at `@dryan/pedantry/tsconfig` (dropping options identical to the base), drops `.pedantry` from ignores and excludes, and moves an empty `.prettierrc.json5` to `"prettier": "@dryan/pedantry/prettier"`.
4. Writes the pin and runs sync.
5. Prints a report: what it replaced (identical to pedantry, or a stale copy of an older pedantry), what it **preserved** (per-repo edits), and what needs a human.

What "preserved" means: hooks that differ from pedantry's move to `lefthook-local.yml`; editor and ignore rules go after the managed block; a `pyproject.toml` table you changed stays where it is and is listed under `keep` in `[tool.pedantry]`; tsconfig options that differ stay in the repo's `tsconfig.json`. Use `--dry-run` to see the plan first.

### Repo-specific changes

| To change                       | Edit                                                                                           |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| Hooks                           | `lefthook-local.yml` (lefthook merges it in)                                                   |
| Editor or prettier ignore rules | Below `# <<< pedantry`                                                                         |
| ruff, ty, vulture, pytest       | Outside the marked block. To own a whole managed table, add it to `keep` in `[tool.pedantry]`. |
| ESLint, TypeScript, Stylelint   | The repo's own config, which imports or extends `@dryan/pedantry/...`                          |
| Agent rules                     | The repo's own `AGENTS.md`, which keeps the line `@.pedantry/AGENTS.md`                        |

**Never edit a managed file by hand.** `pedantry check` will fail, and the next sync overwrites it.

## Versioning

Tags are `vX.Y.Z` and cover both the npm package and the CLI. A repo's pin lives in one place:

```toml
# pyproject.toml, or pedantry.toml (without the table header) in repos with no pyproject
[tool.pedantry]
version = "2.0.0"
types = ["python", "typescript"]
```

sync and check refuse to run when the running pedantry is not the pinned version, and print the exact `uvx --from ...@vX.Y.Z` command to use. To upgrade, run the new version with `--upgrade`:

```zsh
uvx --from git+https://github.com/dryan-org/pedantry@v2.1.0 pedantry sync --upgrade
```

and bump the npm dependency (`npm install --save-dev github:dryan-org/pedantry#v2.1.0`).

## The npm package

```ts
// eslint.config.ts
import type { Linter } from "eslint";
import pedantry from "@dryan/pedantry/eslint";

const config: Linter.Config[] = [
  ...pedantry,
  // repo overrides
];
export default config;
```

```jsonc
// tsconfig.json: only compilerOptions are shared. paths, include, exclude and
// outDir stay in the repo, because TypeScript resolves them relative to the file they are in.
{
  "extends": "@dryan/pedantry/tsconfig",
  "compilerOptions": { "outDir": "dist" },
}
```

```jsonc
// package.json
{ "prettier": "@dryan/pedantry/prettier" }
```

```js
// stylelint.config.mjs
export default { extends: ["@dryan/pedantry/stylelint"] };
```

Helpers take overrides (plain objects merge into the defaults, arrays replace them):

```ts
// vitest.config.ts
import { defineConfig } from "vitest/config";
import { vitestConfig } from "@dryan/pedantry/vitest";
export default defineConfig(vitestConfig({ test: { environment: "jsdom" } }));
```

```js
// rollup.config.js
import { rollupConfig } from "@dryan/pedantry/rollup";
export default rollupConfig({ input: "src/my-element.ts" });

// web-test-runner.config.js
import { webTestRunnerConfig } from "@dryan/pedantry/web-test-runner";
export default await webTestRunnerConfig({ files: ["test/**/*.test.js"] });

// custom-elements-manifest.config.js
import { customElementsManifestConfig } from "@dryan/pedantry/custom-elements-manifest";
export default customElementsManifestConfig();
```

The ESLint, Prettier and Stylelint configs and their plugins come with the package. The tools themselves (`eslint`, `prettier`, `stylelint`, `typescript`, `vitest`, `rollup` and its plugins, `@web/test-runner`) are the repo's own dev dependencies.

## Vendoring (repos without GitHub access)

For repos that cannot install from GitHub (for example Azure DevOps), sync writes everything locally:

```zsh
uvx --from git+https://github.com/dryan-org/pedantry@v2.0.0 pedantry sync --type typescript --vendor
```

This adds `.pedantry/eslint.config.ts`, `.pedantry/tsconfig.base.json`, `.pedantry/stylelint.config.mjs` and `.pedantry/helpers/*.js`, and records `vendor = true` in the pin so `check` covers them. The repo's own configs import them (`import pedantry from "./.pedantry/eslint.config"`, `"extends": "./.pedantry/tsconfig.base.json"`), and sync prints the `npm install --save-dev` line for the packages they import. Updates are manual: run sync again with a newer version.

## Development

```zsh
uv sync
uv run pytest                      # CLI tests: sync, check, migrate on fixture repos
npm ci --ignore-scripts
npm test                           # packs the npm package, installs it into a fixture, runs eslint/tsc/prettier/stylelint
uv run pedantry check              # this repo follows its own pin
```

The shared agent rules are `src/pedantry/data/AGENTS.md`; the npm files are in `src/pedantry/data/js/`. See `AGENTS.md` for the release steps.

## License

ISC
