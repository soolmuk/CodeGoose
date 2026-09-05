#!/usr/bin/env python3
"""Deterministic renderer: platform template + params -> rendered config.

Usage:
  python3 render.py <platform> --provider P --model M --style S --language L
    --verification on|off|shadow [--profile conservative|strict]
    [--local] [--dry-run]

Fetches the platform template and the review-instructions asset name from
the LATEST CodeGoose release assets (manifest: scripts/release_assets.txt)
— never from a moving git ref — substitutes placeholders, and writes the
rendered file into the current repo at the platform's canonical target
path. Because templates and helpers are release assets, an installed
workflow keeps tracking the latest release at CI runtime: the rendered
config downloads helpers AND instructions from the same latest-release
base URL that render.py used (release-only distribution model).

Placeholders (all __UPPER__):
  __PROVIDER__ __GOOSE_MODEL__ __GOOSE_VERIFY_MODEL__ __LANGUAGE__ __API_KEY_NAME__
  __VERIFY_PROFILE__ __VERIFY_MODE__ (verification gate, on/shadow only)
  __STYLE_ASSET__ (asset basename, e.g. instructions.graded.md; the
    rendered config downloads it at CI runtime and substitutes
    __LANGUAGE__ into it, so instructions are NOT baked in at render time)

Verification gate (issue #10):
  on     templates include the reflection pass + merge gate
  shadow same pipeline, but merge --mode shadow (outcomes logged only)
  off    the #[verify:begin]/#[verify:end] marked region is REMOVED
  The reflection instructions (instructions.reflection.md asset) are
  downloaded at CI runtime with the same pattern as inline_threads.py,
  so a single model/provider/config serves both passes unless
  --verify-model overrides __GOOSE_VERIFY_MODEL__ (the reflection
  pass rewrites the config before its first goose invocation).
"""
import argparse
import os
import sys
import urllib.request
from pathlib import Path

# Release-asset download base: every consumer of CodeGoose fetches from the
# LATEST published release, never from a moving git ref (README 'Releases &
# versioning'). Environment override CODEGOOSE_RELEASE_BASE exists for
# mirrors/testbeds; committed templates always render the canonical base.
RELEASE_BASE = "https://github.com/soolmuk/CodeGoose/releases/latest/download"


def release_base():
    return os.environ.get("CODEGOOSE_RELEASE_BASE", RELEASE_BASE)


SOURCES = {
    "github": {
        "template": "github.workflow.yml",
        "target": ".github/workflows/codegoose-review.yml",
        "instructions": {
            "graded-review": "instructions.graded.md",
            "changes-summary": "instructions.summary.md",
        },
    },
    "gitlab": {
        "template": "gitlab.ci.yml",
        "target": ".gitlab-ci.yml",
        "instructions": {
            "graded-review": "instructions.graded.md",
            "changes-summary": "instructions.summary.md",
        },
    },
    "gitea": {
        "template": "gitea.workflow.yml",
        "target": ".gitea/workflows/codegoose-review.yml",
        "instructions": {
            "graded-review": "instructions.graded.md",
            "changes-summary": "instructions.summary.md",
        },
    },
    "teamcity": {
        "template": "teamcity.settings.kts",
        "target": ".teamcity/settings.kts",
        "instructions": {
            "graded-review": "instructions.graded.md",
            "changes-summary": "instructions.summary.md",
        },
    },
}

API_KEY_NAMES = {
    "ollama_cloud": "OLLAMA_CLOUD_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks-ai": "FIREWORKS_API_KEY",
}

PROVIDER_ALIASES = {
    "fireworks": "fireworks-ai",
    "fireworks_ai": "fireworks-ai",
}

VERIFY_BEGIN = "#[verify:begin]"
VERIFY_END = "#[verify:end]"


def strip_verify_region(text, keep):
    """Remove or keep the #[verify:begin]/#[verify:end] marked region.

    Markers must wrap complete shell sentences AND complete YAML step
    boundaries (never inside a Kotlin DSL string or a heredoc fence). When
    keep=True the markers themselves are dropped but the content stays;
    when keep=False the whole region including markers is removed. Any
    residual marker afterwards is a render bug and fails loudly.
    """
    if keep:
        lines = text.split("\n")
        out = []
        for line in lines:
            if line.strip() in (VERIFY_BEGIN, VERIFY_END):
                continue
            out.append(line)
        text = "\n".join(out)
    else:
        lines = text.split("\n")
        out, skipping = [], False
        for line in lines:
            if line.strip() == VERIFY_BEGIN:
                if skipping:
                    raise SystemExit(
                        "render: nested #[verify:begin] markers")
                skipping = True
                continue
            if line.strip() == VERIFY_END:
                if not skipping:
                    raise SystemExit(
                        "render: unmatched #[verify:end] marker")
                skipping = False
                continue
            if not skipping:
                out.append(line)
        if skipping:
            raise SystemExit("render: unterminated #[verify:begin] region")
        text = "\n".join(out)
    # Residual marker = template authoring bug; never ship it.
    if VERIFY_BEGIN in text or VERIFY_END in text:
        raise SystemExit("render: residual verify markers after strip")
    return text


def guard_values(text, template_eof_lines=frozenset()):
    """Harden rendered shells against heredoc/expression accidents."""
    problems = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped == "EOF" and line not in template_eof_lines:
            problems.append(f"value line is bare 'EOF' (heredoc terminator): {line!r}")
        if "${{" in stripped and "__" in stripped:
            problems.append(f"placeholder token inside a platform expression: {line!r}")
    return problems


def fetch(asset_name):
    """Download a release asset by basename from the latest release."""
    url = f"{release_base()}/{asset_name}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode()


def substitute(text, placeholder, value):
    """Replace every occurrence of placeholder with value.

    Two-phase:
      1. Lines that contain ONLY the placeholder (after optional indent) get
         indent-aware multi-line substitution so YAML block scalars stay valid.
      2. Remaining inline occurrences get a plain token substitution.
    """
    import re

    lines = text.split("\n")
    pat_alone = re.compile(r"^([ \t]*)" + re.escape(placeholder) + r"[ \t]*$")
    out = []
    for line in lines:
        m = pat_alone.match(line)
        if m:
            indent = m.group(1)
            out.append(indent + value.replace("\n", "\n" + indent))
        else:
            out.append(line)
    joined = "\n".join(out)
    return joined.replace(placeholder, value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=list(SOURCES))
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--verify-model", default=None,
                    help="model for the verification (reflection) pass; "
                         "defaults to --model (single-model behavior). "
                         "GitHub workflows only — rejected elsewhere. "
                         "With --verification off the value is unused")
    ap.add_argument("--style", required=True, choices=["graded-review", "changes-summary"])
    ap.add_argument("--language", default="Korean")
    ap.add_argument("--local", action="store_true",
                    help="render from local templates/ instead of release assets "
                         "(development / pre-release testing only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verification", default="on",
                    choices=["on", "off", "shadow"],
                    help="verification gate mode (issue #10)")
    ap.add_argument("--verify-profile", default="conservative",
                    choices=["conservative", "strict"],
                    help="gate profile used when verification is on/shadow")
    args = ap.parse_args()

    provider = PROVIDER_ALIASES.get(args.provider, args.provider)
    if provider not in API_KEY_NAMES:
        print(f"FAIL: unknown provider {args.provider}")
        return 2

    if args.verify_model and args.platform != "github":
        # The __GOOSE_VERIFY_MODEL__ switch only exists in the GitHub workflow
        # template; on other platforms the flag would silently no-op and the
        # reflection pass would keep the review model. Fail loud instead.
        print("FAIL: --verify-model is only supported on the github platform")
        return 2
    if args.verify_model and args.verification == "off":
        # --verification off strips the whole verify region including the
        # model switch, so --verify-model would be dead input. Warn (not
        # fail): the render is still valid, the user just gave a no-op value.
        print("WARN: --verify-model has no effect with --verification off")

    spec = SOURCES[args.platform]
    if args.local:
        # Development mode: render straight from the working-tree templates
        # without network access (used by tests / branch development). Only
        # the template is needed now: instructions are downloaded at CI
        # runtime, not baked in here.
        template = (Path("templates") / spec["template"]).read_text()
    else:
        try:
            template = fetch(spec["template"])
        except Exception as e:
            print(f"FAIL: could not download release assets from {release_base()}: {e}")
            return 2

    # Verification gate region handling comes FIRST: when off, the whole
    # marked region (including its placeholders) never reaches the
    # substitution loop.
    # Template's own heredoc terminator lines (whitelist for guard_values).
    template_eof_lines = {l for l in template.split("\n") if l.strip() == "EOF"}

    body = strip_verify_region(template, keep=args.verification != "off")
    verify_mode = "shadow" if args.verification == "shadow" else "enforce"

    # Substitution order is a CONTRACT (see the __LANGUAGE__ note below).
    for placeholder, value in [
        ("__LANGUAGE__", args.language),
        ("__RECIPES_BASE__", release_base()),
        ("__PROVIDER__", provider),
        ("__GOOSE_MODEL__", args.model),
        ("__GOOSE_VERIFY_MODEL__", args.verify_model or args.model),
        ("__API_KEY_NAME__", API_KEY_NAMES[provider]),
        ("__VERIFY_PROFILE__", args.verify_profile),
        ("__VERIFY_MODE__", verify_mode),
        ("__STYLE_ASSET__", spec["instructions"][args.style]),
    ]:
        body = substitute(body, placeholder, value)

    problems = guard_values(body, template_eof_lines)
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        return 2

    target = Path(spec["target"])
    if args.dry_run:
        print(body)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    print(f"WROTE {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())