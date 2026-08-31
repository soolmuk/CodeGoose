# Contributing to CodeGoose

This repository is the **source of truth** for CodeGoose recipes, templates,
and render scripts. Generated CI files are artifacts — do not hand-edit them.
Improvements go into the recipe/templates, then you re-run the recipe.

## Recipe rules

- Follow the [Recipe Reference](https://goose-docs.ai/docs/guides/recipes/recipe-reference) schema
- After every recipe change, always:

  ```bash
  goose recipe validate <recipe>.yaml
  python3 scripts/update_deeplinks.py   # regenerate docs/launch.html + check README fallbacks
  ```

- Deep-link payloads live in `docs/launch.html` and the fallback blocks in both
  READMEs; `scripts/update_deeplinks.py --check` runs in CI to catch drift.
- `codegoose-review` is **read-only** (no builds, tests, or file edits)
- Do not hardcode project-specific instructions in the recipe; inject them with `--params instructions=`

## CI hardening checklist

Already reflected in the templates — apply to new platforms too:

- Post only the final response (after the `## Summary` sentinel)
- Clamp bodies to 55,000 characters
- Empty goose output → explicit failure
- `concurrency` + `timeout-minutes` required
- Exactly one provider API-key binding (preserve platform expressions as literals)

## Pull requests

Issues and pull requests welcome — PRs run this repo's own CodeGoose review.