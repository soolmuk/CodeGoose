# Changelog

Notable changes to CodeGoose are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- 0.2.0 (planned): switch templates/recipes from `raw.../main` URLs to
  `releases/latest/download` assets so installed workflows track the
  latest release automatically (no re-render needed).