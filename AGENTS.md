# Agent Instructions

@.pedantry/AGENTS.md

---

## This repo

Pedantry ships two things from one repo and one tag: the `@dryan/pedantry` npm package and the `pedantry` CLI.

- **Shared agent rules live in `src/pedantry/data/AGENTS.md`.** `pedantry sync` writes that file to `.pedantry/AGENTS.md` in every repo (this one included). Edit the source, then run `uv run pedantry sync` here; never edit `.pedantry/`.
- **npm exports** (`eslint`, `tsconfig`, `prettier`, `stylelint`, `vitest`, `rollup`, `web-test-runner`, `custom-elements-manifest`) are plain JS plus `.d.ts` in `src/pedantry/data/js/`. `package.json` `exports` points there; there is no build step. `npm test` packs the package, installs it into `tests/npm-consumer/fixture`, and runs eslint, tsc, prettier and stylelint with it.
- **What `sync` writes** is defined in `src/pedantry/content.py`. Changing it changes every consumer on its next version bump, so treat edits as releases.
- **`pedantry migrate`** recognises stale v1 copies through `src/pedantry/data/legacy.json`, built from git history by `scripts/build_legacy.py`. Do not edit it by hand.
- **Release:** bump `version` in both `package.json` and `pyproject.toml` (and the `[tool.pedantry]` pin), run `uv run pedantry sync --upgrade`, merge, then tag `vX.Y.Z`.
- **Checks:** `uv run pytest`, `uv run ruff check .`, `uv run ty check src tests`, `npx eslint .`, `npx tsc --noEmit`, `npx prettier --check .`, `node --test tests/npm-consumer/`.
