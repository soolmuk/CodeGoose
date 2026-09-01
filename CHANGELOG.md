# Changelog

Notable changes to CodeGoose are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **Supply-chain hardening (all four platform templates)** — found by
  CodeGoose/CodeRabbit review on kai-cameo-mcp PR #105:
  - The goose installer is now downloaded from the **pinned v1.48.0 release
    tag** (was the moving `stable` tag), saved to a file, and **verified
    against a SHA-256 digest before execution** — never `curl | bash`
    unverified. The digest is the official GitHub release asset digest.
  - `actions/checkout` and `actions/upload-artifact` are pinned to **full
    commit SHAs** (github + gitea templates).
  - **Secret isolation (github template)**: the "Run goose" step no longer
    binds `GH_TOKEN`. It runs an LLM over attacker-controlled PR diff
    content, so a prompt injection could previously have exfiltrated repo
    credentials; the step now receives only the provider API key. The
    verification-gate pre-SHA check reads the PR head sha from the event
    payload file (`GITHUB_EVENT_PATH`) instead of `gh pr view`, removing
    the last token use from that step. Posting keeps using `GH_TOKEN` in
    its own step. `GOOSE_MODE` deliberately stays on auto (not chat): the
    reflection pass must read repository files to verify findings.
- `scripts/verify.py` **v5 contract**: renders FAIL when the installer is
  unpinned/unverified, actions use moving tags, or the github goose step
  binds `GH_TOKEN`.

## [0.1.0] - 2026-08-31

### Added
- Release infrastructure (this is the anchor release, not yet consumed by
  installed workflows):
  - `scripts/release_assets.txt` — single source of truth manifest for the
    assets every GitHub Release must carry.
  - `.github/workflows/release.yml` — on `v*` tag push: refuses to publish
    unless the asset manifest is fully satisfiable, helper selftests pass,
    all four platforms render+verify (dry-run), and both recipes validate;
    then creates the release and attaches the manifest assets.
  - `CHANGELOG.md` (this file).
- Release model policy: **the GitHub Release is the only distribution
  channel.** `main` is the development tick; consumers (rendered workflows
  and the setup recipe) fetch files from
  `https://github.com/soolmuk/CodeGoose/releases/latest/download/<basename>`
  so installed workflows always track the latest release. Automatic
  latest-tracking for installed workflows ships in the next release (0.2.0).

### Notes
- Assets in 0.1.0 are the pre-transition files and are not consumed by
  anyone yet; the manifest exists so the release pipeline can rehearse on
  a state where failure is harmless.

## [Unreleased]

## [0.2.0] - 2026-08-31

### Changed
- **Installed workflows now always track the latest release.** Every
  helper and instruction download in all four platform templates
  (GitHub, GitLab, Gitea, TeamCity) now fetches release assets from
  `https://github.com/soolmuk/CodeGoose/releases/latest/download/<basename>`
  instead of `raw.githubusercontent.com/.../main`. New releases take
  effect for existing installs on the next CI run — no re-render needed.
- Review instructions are no longer baked into the rendered config at
  render time: the workflow downloads the style instructions asset
  (`instructions.graded.md` / `instructions.summary.md`) at CI runtime
  and materializes it via the new `inline_threads.py lang` subcommand
  (language substitution + loud failure on leftover placeholder tokens).
  A release only needs to update one asset to change instructions for
  every existing install.
- `scripts/render.py` fetches templates from release assets (never from
  a git ref); the `--ref` flag is gone. `--local` renders from the
  working tree for development/pre-release testing.
  `CODEGOOSE_RELEASE_BASE` env override exists for mirrors/testbeds.
- `scripts/verify.py` v4 contract: rendered configs must reference
  `releases/latest/download` (legacy raw@main references FAIL), must
  download instructions at runtime and pass them to
  `inline_threads.py lang`.
- `codegoose-setup.yaml` downloads `render.py`/`verify.py` from the
  latest release; the recipe is now version-agnostic (no per-release
  recipe republishing needed). Deep links regenerated for all three
  delivery sites (docs/launch.html, README.md, README.ko.md).
- This repository's own review workflow re-rendered with the new model
  (first latest-tracking consumer).

### Migration
- Existing installs rendered from the pre-0.2.0 templates still fetch
  `raw@main`; run the CI Setup deep link once to switch to release
  tracking. Until then, helpers on `main` keep their additive-only CLI
  compatibility (new subcommands never break old flags).