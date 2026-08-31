#!/usr/bin/env python3
"""Regenerate the goose deep-link launch page (docs/launch.html).

Deterministic companion to `goose recipe deeplink`:
  1. Runs `goose recipe deeplink <recipe>.yaml` for both CodeGoose recipes.
  2. Renders docs/launch.html from templates/launch.html with the base64
     payloads substituted.
  3. Verifies that README.md / README.ko.md embed the same payloads
     (fallback instructions only) and reports drift.

Why: GitHub strips non-allowlisted URL schemes (goose://) from rendered
Markdown, so raw README badges are dead links on github.com. The launch
page is served verbatim by GitHub Pages, where goose:// hrefs work.

Usage:
  python3 scripts/update_deeplinks.py [--check]
    --check: verify only, exit 1 on drift (no writes)

Run this whenever a recipe YAML changes, in the same commit as the recipe
edit, together with `goose recipe validate` + `goose recipe deeplink`.

Failure mode: in write mode all three delivery sites are validated BEFORE
anything is written. If a README fallback block is missing, the run exits 1
and leaves the working tree untouched.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RECIPES = {
    "review": "codegoose-review.yaml",
    "setup": "codegoose-setup.yaml",
}
LAUNCH_TEMPLATE = REPO / "templates" / "launch.html"
LAUNCH_TARGET = REPO / "docs" / "launch.html"
READMES = [REPO / "README.md", REPO / "README.ko.md"]

# Unique tokens inside templates/launch.html. The payloads are substituted
# for these tokens, so repeated runs stay byte-stable.
TOKENS = {"review": "__DL_REVIEW__", "setup": "__DL_SETUP__"}


GOOSE_DEEPLINK_TIMEOUT_SECS = 120


def goose_deeplink(recipe_path: Path) -> str:
    """Return the full goose://recipe?config=... link for a recipe file."""
    try:
        result = subprocess.run(
            ["goose", "recipe", "deeplink", str(recipe_path)],
            capture_output=True,
            text=True,
            timeout=GOOSE_DEEPLINK_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"goose recipe deeplink timed out after {GOOSE_DEEPLINK_TIMEOUT_SECS}s "
            f"for {recipe_path}; is the goose CLI hung?"
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"goose recipe deeplink failed for {recipe_path}: {result.stderr.strip()}"
        )
    # Capture the ENTIRE payload up to whitespace first. If we matched with a
    # URL-safe-only character class instead, a future goose CLI emitting
    # standard base64 would silently truncate at the first `+` or `/` and
    # the guard below could never fire (truncated text contains neither).
    match = re.search(r"goose://recipe\?config=(\S+)", result.stdout)
    if not match:
        raise RuntimeError(f"no deeplink found in goose output for {recipe_path}")
    link = "goose://recipe?config=" + match.group(1)
    payload = match.group(1)
    if re.search(r"[+/=]", payload[:-2] if payload.endswith("=") else payload):
        # Standard base64 detected (goose emits URL-safe base64). Fail loudly
        # instead of producing a link the browser/OS may mangle.
        raise RuntimeError(
            f"unexpected standard-base64 characters in deeplink payload for "
            f"{recipe_path}; update this script's URL-scheme assumptions"
        )
    # Final sanity: the payload must decode to JSON with the expected keys.
    # Reuses decode_payload so generation and verification share one
    # normalization point.
    try:
        data = decode_payload(payload)
    except ValueError as e:
        raise RuntimeError(
            f"deeplink payload for {recipe_path} does not decode to valid JSON: {e}"
        )
    if "title" not in data or "version" not in data:
        raise RuntimeError(
            f"deeplink payload for {recipe_path} is missing title/version keys"
        )
    return link


def payload_of(link: str) -> str:
    """Extract the raw base64 payload from a full goose:// link."""
    return link.split("=", 1)[1]


def decode_payload(payload: str) -> dict:
    """Decode a URL-safe base64 payload into its recipe JSON.

    Single normalization point for both generation and verification, so a
    future goose CLI that starts emitting base64 padding (or slightly
    different-but-equivalent encodings) is compared by decoded semantics
    rather than fragile byte-for-byte string identity.
    """
    stripped = payload.rstrip("=")
    try:
        # Strict validation: without it, characters outside the base64
        # alphabet are silently DISCARDED by b64decode, which would turn
        # some malformed committed payloads into "valid" (but wrong) JSON
        # rather than triggering the documented ValueError fallback.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", stripped):
            raise ValueError("payload contains non-base64 characters")
        decoded = base64.urlsafe_b64decode(
            stripped + "=" * (-len(stripped) % 4)
        ).decode("utf-8")
        return json.loads(decoded)
    # binascii.Error, UnicodeDecodeError and json.JSONDecodeError are all
    # ValueError subclasses, so catching ValueError alone covers every
    # decode/parse failure while letting real programming errors
    # (AttributeError, TypeError, ...) propagate unmasked.
    except ValueError as e:
        raise ValueError(f"payload does not decode to valid JSON: {e}")


def payloads_equal(a: str, b: str) -> bool:
    """Compare two payloads by decoded recipe semantics, not raw bytes.

    Comparison is canonical, type-strict JSON: each side is decoded and
    re-serialized with sorted keys. This avoids Python dict == leniency
    where True == 1 and 1 == 1.0, so a bool/int/float type toggle in a
    recipe counts as real drift instead of silently passing.

    Fallback contract: if either side fails to decode, the payloads are
    compared as raw strings. This is a conservative fallback — it returns
    True only for byte-identical strings, so garbage never compares equal
    to a valid payload. In practice `b` (fresh CLI output) is always valid
    because goose_deeplink already validated it, so the fallback can only
    fire for a malformed `a` (committed garbage), which then compares
    unequal and correctly reports drift.
    """
    try:
        return canonical_json(decode_payload(a)) == canonical_json(decode_payload(b))
    except ValueError:
        # Conservative fallback for malformed input: raw string equality.
        # The length pre-check makes it explicit that garbage payloads of
        # differing lengths never compare equal either.
        if len(a) != len(b):
            return False
        return a == b


def canonical_json(data) -> str:
    """Type-strict, order-independent serialization for semantic equality."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def decode_title(link: str) -> str:
    data = decode_payload(payload_of(link))
    return f"{data.get('title')} v{data.get('version')}"


def render_launch(links: dict) -> str:
    template = LAUNCH_TEMPLATE.read_text(encoding="utf-8")
    out = template
    for key, token in TOKENS.items():
        occurrences = out.count(token)
        expected = 2  # href attribute + textarea copy-paste fallback
        if occurrences != expected:
            raise RuntimeError(
                f"expected {expected} occurrences of {token} in {LAUNCH_TEMPLATE}, found {occurrences}"
            )
        out = out.replace(token, payload_of(links[key]))
    return out


# Single source of truth for README fallback blocks, shared by BOTH
# validation (extract_readme_payloads) and rewriting
# (rewrite_readme_fallbacks). All groups are named so neither caller
# depends on positional group numbers.
# The fence is preceded by \s* so a hand-edited indented block is still
# matched — it must be rewritten, not silently skipped (round-8 finding).
README_BLOCK_RE = re.compile(
    r"(?P<prefix><!-- codegoose-deeplink:(?P<key>review|setup) -->\s*\n\s*```text\n)"
    r"(?P<payload>goose://recipe\?config=[A-Za-z0-9\-_=]+)"
    r"(?P<suffix>\n```)"
)


def rewrite_readme_fallbacks(text: str, links: dict) -> str:
    """Replace the goose:// payload inside each README fallback block.

    Matches the blocks produced by this script; keeps everything else
    (prose, markers, fence placement) byte-identical so repeated runs are
    stable and diffs stay minimal.
    """

    def sub(m):
        key = m.group("key")
        return m.group("prefix") + links[key] + m.group("suffix")

    return README_BLOCK_RE.sub(sub, text)


def extract_readme_payloads(text: str) -> dict:
    """Return {key: payload} for goose:// links embedded in a README.

    Uses the SAME README_BLOCK_RE as rewrite_readme_fallbacks, so a block
    that passes validation here is guaranteed to be rewritable there (and
    vice versa) — the silent-failure divergence found in round-8 review
    cannot recur by construction.
    """
    found = {}
    for m in README_BLOCK_RE.finditer(text):
        found[m.group("key")] = payload_of(m.group("payload"))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify only, no writes")
    args = parser.parse_args()

    links = {k: goose_deeplink(REPO / v) for k, v in RECIPES.items()}
    for k, link in links.items():
        print(f"[{k}] {decode_title(link)} -> {len(payload_of(link))} b64 chars")

    rendered = render_launch(links)

    def launch_matches_current() -> bool:
        """Hybrid comparison of the committed launch page vs `rendered`.

        Two-part contract:
          1. Everything EXCEPT the payload strings (prose, layout, structure)
             must match `rendered` byte-for-byte, so template-only edits to
             templates/launch.html still detect as drift.
          2. The payload strings themselves are compared semantically
             (payloads_equal), so a goose CLI encoding change (e.g. base64
             padding) does not false-DRIFT a page committed by an older CLI.
        """
        current = LAUNCH_TARGET.read_text(encoding="utf-8")
        current_links = re.findall(r"goose://recipe\?config=([A-Za-z0-9\-_=]+)", current)
        rendered_links = re.findall(r"goose://recipe\?config=([A-Za-z0-9\-_=]+)", rendered)
        # Length check FIRST: zip truncates to the shorter side and all()
        # over an empty sequence is True, so a count mismatch (e.g. a third
        # recipe added) would otherwise masquerade as up-to-date.
        if len(current_links) != len(rendered_links):
            return False
        # Replace payloads with a fixed sentinel on BOTH sides and require
        # byte equality of what remains (part 1 of the contract).
        # re.sub (not str.replace) so the substitution is positional per
        # occurrence; str.replace(1) would clobber the first textual
        # occurrence, which could be a payload embedded inside prose.
        link_pattern = re.compile(r"goose://recipe\?config=[A-Za-z0-9\-_=]+")
        sentinel = "__PAYLOAD__"
        current_skel = link_pattern.sub(sentinel, current)
        rendered_skel = link_pattern.sub(sentinel, rendered)
        if current_skel != rendered_skel:
            return False
        # Payloads compare semantically (part 2 of the contract).
        return all(
            payloads_equal(c, r) for c, r in zip(current_links, rendered_links)
        )

    if args.check:
        ok = True
        if LAUNCH_TARGET.exists():
            if not launch_matches_current():
                print("DRIFT: docs/launch.html is out of date with recipes")
                ok = False
            else:
                print("docs/launch.html: up to date")
        else:
            print("DRIFT: docs/launch.html is missing")
            ok = False
        icon_src = REPO / "assets" / "codegoose-icon.png"
        icon_dst = LAUNCH_TARGET.parent / "codegoose-icon.png"
        if not icon_dst.exists():
            print(f"DRIFT: {icon_dst} is missing (run scripts/update_deeplinks.py)")
            ok = False
        elif icon_dst.read_bytes() != icon_src.read_bytes():
            print(f"DRIFT: {icon_dst} differs from {icon_src}")
            ok = False
        else:
            print("docs/codegoose-icon.png: up to date")
        for readme in READMES:
            text = readme.read_text(encoding="utf-8")
            found = extract_readme_payloads(text)
            for key in ("review", "setup"):
                if key not in found:
                    print(f"DRIFT: {readme.name} {key} fallback block is missing")
                    ok = False
                elif not payloads_equal(found[key], payload_of(links[key])):
                    print(f"DRIFT: {readme.name} {key} fallback block is stale")
                    ok = False
                else:
                    print(f"{readme.name} [{key}]: up to date")
        return 0 if ok else 1

    # Validate BEFORE writing anything, so a failed run leaves the working
    # tree untouched instead of half-updated (atomicity over partial writes).
    failed = False
    readme_states = []  # (readme, updated_text) pairs to write after validation
    for readme in READMES:
        text = readme.read_text(encoding="utf-8")
        missing = [k for k in ("review", "setup") if k not in extract_readme_payloads(text)]
        if missing:
            # A missing fallback block means one of the three delivery sites
            # would silently stay stale after regeneration. Fail loudly per
            # the repo's loud-failure rule; --check in CI would catch this,
            # but the generator must not hide the problem either.
            print(
                f"ERROR: {readme.name} has no deeplink fallback block for {missing}; "
                "add <!-- codegoose-deeplink:key --> fenced blocks manually."
            )
            failed = True
            continue
        readme_states.append((readme, rewrite_readme_fallbacks(text, links)))
    if failed:
        return 1

    # All three delivery sites validated — write now.
    LAUNCH_TARGET.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_TARGET.write_text(rendered, encoding="utf-8")
    print(f"WROTE {LAUNCH_TARGET}")

    # GitHub Pages (source: /docs on main) publishes only docs/, so the icon
    # must live inside docs/ for the launch page to render. Keep the template
    # pointing at ./codegoose-icon.png and copy the canonical asset on render.
    icon_src = REPO / "assets" / "codegoose-icon.png"
    icon_dst = LAUNCH_TARGET.parent / "codegoose-icon.png"
    icon_dst.write_bytes(icon_src.read_bytes())
    print(f"WROTE {icon_dst}")

    for readme, updated in readme_states:
        if updated != readme.read_text(encoding="utf-8"):
            readme.write_text(updated, encoding="utf-8")
            print(f"WROTE {readme} (fallback blocks updated)")
        else:
            print(f"OK {readme} (already up to date)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
