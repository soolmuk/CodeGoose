# Changelog

Notable changes to CodeGoose are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.3] - 2026-09-01

### Security
- **Checksum gate hardening (all four platform templates)** — kai-cameo-mcp
  #106 review follow-ups:
  - Every downloaded helper asset now carries an explicit
    listed-in-SHA256SUMS guard (`grep -q "  <asset>$" SHA256SUMS`) BEFORE the
    `--ignore-missing` digest check. Verified locally: `--ignore-missing`
    alone would silently pass an asset missing from the manifest (empty grep
    output feeds sha256sum --check with exit 0), so the listing guard closes
    the completeness foot-gun.
  - The style instructions asset (graded-review/summary) is keyed in the
    manifest by its RELEASE basename but saved locally as
    `instructions.template.md`, so `--ignore-missing` could NEVER match it —
    its digest was effectively unverified. Templates now rewrite the
    manifest line to the local name and check it strictly
    (`sha256sum --strict --check /tmp/style.sum`), with a matching failure
    demonstrated to fail the job.
  - Comments corrected to state the actual guarantee: this is asset/transport
    INTEGRITY, not authenticity — SHA256SUMS rides the same release channel,
    so a fully compromised release account could replace it too (the
    accepted trade-off of the auto-tracking model). The earlier
    "swapped/compromised asset must fail" phrasing overstated the boundary.
- `scripts/verify.py`: renders FAIL when a helper download lacks the
  explicit listing guard, when the style asset is not verified via the
  rewritten manifest line, or (github) when `actions: read` is missing.

## [0.4.2] - 2026-09-01

### Fixed
- github template: `actions: read` restored (0.4.0 dropped the actions
  scope entirely). `gh pr view`'s statusCheckRollup includes
  `checkSuite.workflowRun`, which requires the actions scope — with none
  at all, the gather step fails with "Resource not accessible by
  integration" (first CI run of kai-cameo-mcp #106, 2026-09-01). Least
  privilege here is read, not absent; write is still never needed.
  verify.py now requires `actions: read` and continues to forbid
  `actions: write`.

## [0.4.1] - 2026-09-01

### Fixed
- github template: the verification-gate region (rebuilt when the dead
  pre-SHA check was removed in 0.4.0) used a 2-space deeper base indent
  than the surrounding step; shell semantics were unaffected (verified
  `bash -n` + verify.py PASS on every platform/style/mode combination)
  but the region is back to the step's canonical 10-space indentation.

## [0.4.0] - 2026-09-01

### Fixed
- github template: removed the dead "PR head moved" pre-SHA check from the
  verification gate (CodeGoose review, kai-cameo-mcp PR #105). It compared
  `HEAD_SHA` with the head sha re-read from the SAME event payload
  (`GITHUB_EVENT_PATH`), so the comparison was always equal and the guard
  never fired. The posting step's live `gh pr view` staleness check is the
  real guard and stays. The gitea template's equivalent pre-check queries
  the live API and is kept.

### Security
- **Credential hygiene + release-asset integrity (v6 contract)** — follow-ups
  from the CodeRabbit/CodeGoose review of kai-cameo-mcp PR #105:
  - `persist-credentials: false` on the checkout step (github + gitea
    templates): the goose review step runs an LLM with shell access over
    attacker-controlled diff content, and a persisted job token in
    `.git/config` is a prompt-injection exfiltration path. No step relies on
    persisted git credentials (`gh` calls pass `GH_TOKEN`/`REVIEW_TOKEN` in
    env explicitly; the github goose step is deliberately token-free).
  - **Release-asset checksum verification (all four platform templates)**:
    the release pipeline now builds a `SHA256SUMS` manifest in the gate job
    (every manifest asset, verified with `sha256sum --strict --check` before
    publishing) and attaches it to the release; rendered workflows download
    `SHA256SUMS` from the same release base and verify each fetched
    helper/instruction asset with
    `sha256sum --strict --check --ignore-missing` before use. This closes the
    self-declared integrity gap (the workflow pins actions and the installer
    but previously executed its own release assets unverified). Consumers
    gain integrity once they re-render; existing rendered files keep working
    (same assets, verification added on re-render).
- **Least privilege**: the github template no longer requests
  `actions: write` — `upload-artifact` v4 uses the runner's
  `ACTIONS_RUNTIME_TOKEN` (verified in actions/toolkit source), not
  `GITHUB_TOKEN`; the artifact upload needs no `actions` scope.
- `scripts/verify.py` **v6 contract**: renders FAIL when checkout persists
  credentials, when a template fetches release assets without checksum
  verification, or when the github workflow requests `actions: write`.

## [0.3.0] - 2026-09-01

### Fixed
- github template: **provider-key echo-leak redaction** — a hostile PR diff
  could prompt-inject the model step into repeating the provider API key
  into the review body, which is posted to the (public) PR thread. A new
  redaction step now scrubs the literal key from every review artifact
  BEFORE posting (the key never appears as a command argument or in step
  logs), and the job fails if the key survives in body.md. verify.py allows
  the second key binding only inside the redaction step and fails renders
  that post without redacting.
- github template: the workflow now requests `checks: read` and
  `statuses: read` — `gh pr view` in the gather step queries the GraphQL
  `statusCheckRollup` and the job token cannot read it on private repos
  without those scopes (the gather step failed). Previously these scopes
  were hand-patched into a consumer's rendered file (lost on the next
  render); they now live in the template and verify.py enforces them.

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