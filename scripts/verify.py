#!/usr/bin/env python3
"""Deterministic verifier for rendered CI configs. Exit code is the contract.

Usage:
  python3 verify.py <platform> <config-file>
platform: github | gitlab | gitea | teamcity

  v6 contract (credential hygiene + asset integrity, on top of v5):
  - GitHub/Gitea templates must set persist-credentials: false on the
    checkout step: the goose review step runs an LLM with shell access
    over attacker-controlled diff content, and a persisted job token in
    .git/config is a prompt-injection exfiltration path.
  - Every template must download the release SHA256SUMS manifest and
    verify each fetched helper/instruction asset with
    `sha256sum --strict --check --ignore-missing` before use — a swapped
    release asset must fail the job, not execute.
  v5 contract (supply-chain hardening, on top of v4):
  - the goose installer must be downloaded from a PINNED release tag (never
    the moving `stable` tag), saved to a file, verified against a SHA-256
    digest BEFORE execution, and executed from that file — never
    `curl | bash` unverified.
  - GitHub/Gitea templates must pin `actions/checkout` and
    `actions/upload-artifact` to full commit SHAs.
  - The GitHub goose step must NOT bind GH_TOKEN (secret isolation: the
    LLM step runs over attacker-controlled diff content; repo credentials
    must not be in its environment).
  v4 contract (release-only distribution, on top of the v3 gate contract):
  - every helper/instruction download must come from the CodeGoose release
    assets base (releases/latest/download/<basename>). Any legacy
    raw.githubusercontent.com/soolmuk/CodeGoose reference FAILS: consumers
    must never track a moving git ref.
  - review instructions are downloaded at CI runtime (release asset) and
    materialized via 'inline_threads.py lang' (language substitution +
    leftover-token check), NOT baked in at render time.
  v3 contract (verification gate, issue #10):
  - verification on: the render-time #[verify:begin]/#[verify:end] markers
    are gone, verify_findings.py is downloaded, the reflection + merge steps
    run in the SAME run block as the first goose call, and the fail-open
    banner fallback exists. verify_findings.py selftest must pass.
  - verification off/shadow: off => no verify_findings.py references at all;
    shadow => merge runs with --mode shadow.
  - timeout literals: 25 minutes on every platform.
  v2 contract (inline-review-threads):
  - The final response must still be extracted via the `## Summary` sentinel.
  - The 55,000-char clamp and thread->diff-anchor validation moved into the
    shared helper scripts/inline_threads.py; every template must run it.
  - GitHub / Gitea post a PR review with diff-anchored comments (falling back
    to a plain comment), GitLab posts the summary note + diff discussions,
    TeamCity keeps the artifact flow but with a cleaned body.
"""
import subprocess
import sys
from pathlib import Path

import yaml

PROVIDER_KEYS = ["OLLAMA_CLOUD_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "FIREWORKS_API_KEY"]
PLACEHOLDERS = ("__PROVIDER__", "__GOOSE_MODEL__", "__API_KEY_NAME__",
                "__LANGUAGE__", "__RECIPES_BASE__", "__STYLE_ASSET__",
                "__VERIFY_PROFILE__", "__VERIFY_MODE__")

# Release-only distribution invariants (v4 contract).
RELEASE_BASE_MARK = "releases/latest/download"
LEGACY_RAW_MARK = "raw.githubusercontent.com/soolmuk/CodeGoose"

VERIFY_BEGIN = "#[verify:begin]"
VERIFY_END = "#[verify:end]"


def verification_mode_of(t):
    """Detect the rendered verification mode from the config text."""
    if VERIFY_BEGIN in t or VERIFY_END in t:
        # Rendered on/shadow configs have the markers stripped; their
        # presence means this text is an un-rendered raw template.
        return "raw-template"
    if "verify_findings.py" in t:
        if "--mode shadow" in t:
            return "shadow"
        if "--mode enforce" in t:
            return "on"
    return "off"


def common_verify_checks(t, errs):
    """Verification-gate checks shared by all platforms (v3 contract)."""
    mode = verification_mode_of(t)
    if mode == "raw-template":
        errs.append("verify markers survived rendering; re-render with scripts/render.py")
        return mode
    # Deterministic-pipeline invariant: the first-pass goose call runs
    # exactly ONCE per config (a duplicated first-pass block after the
    # gate would overwrite the merged body.md and kill the gate results —
    # the exact failure mode caught in review).
    if t.count("goose run --instructions instructions.txt") != 1:
        errs.append(
            f"expected exactly 1 first-pass 'goose run --instructions "
            f"instructions.txt', found "
            f"{t.count('goose run --instructions instructions.txt')}")
    if mode in ("on", "shadow"):
        for frag in (
            "verify_findings.py extract --body body.md",
            "verify_findings.py reflect-parse",
            "verify_findings.py merge --body body.md",
            "instructions.reflection.md",
        ):
            if frag not in t:
                errs.append(f"verification gate missing step: {frag}")
        if "reflection_input.txt" not in t:
            errs.append("verification gate must run goose with reflection_input.txt")
        # reflect_raw must not flow into the posting path (body.md only).
        if "reflect_raw" in t.split("prepare --body body.md")[-1]:
            errs.append("reflect_raw files must not flow into the posting path")
        # merge --out-final body.md must be the LAST writer of body.md
        # before prepare: any subsequent overwrite of body.md discards
        # the gate's keep/demote/drop decisions. Check AFTER the LAST
        # merge occurrence (the retry path merges twice by design).
        gate_out_idx = t.rfind("merge --body body.md")
        # Skip past the merge command itself (its own --out-final is
        # legitimate); look for overwriters AFTER the command ends.
        gate_cmd_end = t.find("--lang", gate_out_idx)
        if gate_cmd_end >= 0:
            gate_cmd_end = t.find("\n", gate_cmd_end)
        if gate_cmd_end is not None and gate_cmd_end >= 0:
            gate_out_idx = gate_cmd_end
        prep_idx = t.find("prepare --body body.md")
        if gate_out_idx >= 0 and prep_idx > gate_out_idx:
            between = t[gate_out_idx:prep_idx]
            for overwriter in ("--out body.md", "--out-final body.md",
                               "--raw raw.txt"):
                if overwriter in between:
                    errs.append(
                        f"body.md is re-written after the merge gate "
                        f"({overwriter!r} between merge and prepare); "
                        "the gate results would be discarded")
        if mode == "shadow" and "--mode shadow" not in t:
            errs.append("shadow mode must pass --mode shadow to merge")
    else:
        if "verify_findings.py" in t:
            errs.append("verification off but verify_findings.py still referenced")
        if "reflection_input" in t:
            errs.append("verification off but reflection steps still referenced")
        if t.count("goose run --instructions") != 1:
            errs.append(
                "verification off must run goose exactly once "
                f"(found {t.count('goose run --instructions')})")
    return mode


def helper_selftest_errors():
    """Run the shared helper's built-in checks when it sits next to this script."""
    helper = Path(__file__).with_name("inline_threads.py")
    if not helper.exists():
        return []
    r = subprocess.run([sys.executable, str(helper), "selftest"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"inline_threads.py selftest failed: {r.stdout} {r.stderr}"]
    errs = []
    helper2 = Path(__file__).with_name("verify_findings.py")
    if helper2.exists():
        r2 = subprocess.run([sys.executable, str(helper2), "selftest"],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            errs.append(f"verify_findings.py selftest failed: {r2.stdout} {r2.stderr}")
    return errs


def common_inline_checks(t, errs):
    if "inline_threads.py" not in t:
        errs.append("must fetch scripts/inline_threads.py")
    if "prepare --body body.md" not in t:
        errs.append("must run inline_threads prepare (anchor validation + clamp)")


def common_supply_chain_checks(t, errs):
    """v5 contract: pinned, digest-verified installer; no unverified pipes."""
    if "releases/download/stable/download_cli.sh" in t:
        errs.append(
            "goose installer must be pinned to a release tag (found the "
            "moving `stable` tag)")
    if "bash download_cli.sh" not in t:
        errs.append(
            "installer must be saved to a file and executed from it "
            "(no unverified `curl | bash` pipe)")
    if "sha256sum --strict --check" not in t:
        errs.append(
            "installer must be verified against a SHA-256 digest before "
            "execution")
    if t.count("download_cli.sh") > 0 and "ab5ae40513348ec4e6047cc7338040aab2df5246800c111d22065766ba6013f0" not in t:
        errs.append("installer digest literal missing")


def common_credential_checks(t, errs):
    """v6 contract: no persisted checkout credentials; verified assets."""
    if "actions/checkout@" in t and "persist-credentials: false" not in t:
        errs.append(
            "checkout must set persist-credentials: false (the goose step "
            "runs an LLM with shell access over attacker-controlled diff "
            "content; a persisted job token in .git/config is an "
            "exfiltration path)")
    if "sha256sum --strict --check --ignore-missing SHA256SUMS" not in t:
        errs.append(
            "downloaded release assets must be verified against the release "
            "SHA256SUMS manifest (sha256sum --strict --check "
            "--ignore-missing SHA256SUMS)")
    if "SHA256SUMS -o SHA256SUMS" not in t:
        errs.append("template must download the SHA256SUMS manifest asset")


def common_release_checks(t, errs):
    """v4 contract: consumers fetch release assets only, never git refs."""
    if LEGACY_RAW_MARK in t:
        errs.append(
            "legacy raw.githubusercontent.com/soolmuk/CodeGoose reference: "
            "consumers must fetch releases/latest/download assets only")
    if RELEASE_BASE_MARK not in t:
        errs.append("missing releases/latest/download base (release-only distribution)")
    # Instructions are downloaded at CI runtime and materialized with the
    # language substitution (substring check tolerant of line wrapping).
    if "inline_threads.py lang" not in t:
        errs.append("must materialize instructions via inline_threads.py lang")
    if "--instruction-file instructions.template.md" not in t:
        errs.append("must download the style instructions asset and pass it to lang")
    if "__STYLE_ASSET__" not in t and "instructions.template.md" in t:
        pass  # style asset name substituted at render; presence checked via PLACEHOLDERS


def check_github(t):
    errs = []
    d = yaml.safe_load(t)
    # YAML 1.1: bare `on:` parses as boolean True
    trigger = d.get("on") or d.get(True) or {}
    if list(trigger.keys() if isinstance(trigger, dict) else []) != ["pull_request"]:
        errs.append("trigger must be pull_request only")
    if "codegoose-review" not in d.get("jobs", {}):
        errs.append("missing jobs.codegoose-review")
    else:
        job = d["jobs"]["codegoose-review"]
        if job.get("timeout-minutes") != 25:
            errs.append("missing timeout-minutes: 25")
    if "concurrency" not in d:
        errs.append("missing concurrency group")
    if d.get("permissions", {}).get("pull-requests") != "write":
        errs.append("missing pull-requests:write")
    for scope in ("checks", "statuses"):
        if d.get("permissions", {}).get(scope) != "read":
            errs.append(f"missing {scope}:read (gh pr view needs the "
                        "statusCheckRollup on private repos)")
    key_refs = sum(t.count(f"secrets.{k}") for k in PROVIDER_KEYS)
    if key_refs not in (1, 2):
        errs.append(
            f"expected 1 (model) or 2 (model + redaction) secrets.*_API_KEY "
            f"bindings, found {key_refs}")
    if key_refs == 2 and "Redact provider key from review output" not in t:
        errs.append(
            "a second provider key binding is only allowed in the "
            "redaction step")
    if "gh pr comment" not in t:
        errs.append("must post via gh pr comment")
    if "inline_threads.py extract --raw" not in t \
            and "re.finditer(r'(?m)^## Summary', raw)" not in t:
        errs.append("must extract only final response via ## Summary sentinel")
    if t.count("exit 1") < 1:
        errs.append("empty-review must fail the job explicitly")
    common_inline_checks(t, errs)
    if "github-payload" not in t or "/reviews" not in t:
        errs.append("must post inline comments through the PR review API")
    if "gh pr comment" not in t:
        errs.append("must keep a gh pr comment fallback")
    if "falling back to a plain comment" not in t:
        errs.append("inline failures must fall back to a plain comment")
    if "head.sha" not in t:
        errs.append("review must be pinned to the PR head sha")
    if "actions/upload-artifact" not in t:
        errs.append("github workflow must upload the verification-gate artifacts")
    if "actions: write" in t:
        errs.append(
            "github workflow must NOT request actions: write (least "
            "privilege): upload-artifact v4 uses the runner's "
            "ACTIONS_RUNTIME_TOKEN, not GITHUB_TOKEN")
    if d.get("permissions", {}).get("actions") != "read":
        errs.append(
            "github workflow needs actions: read — gh pr view's "
            "statusCheckRollup includes checkSuite.workflowRun, which "
            "requires the actions scope (any less fails with 'Resource "
            "not accessible by integration'; write is never needed)")
    if "actions/checkout@" in t and "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" not in t:
        errs.append("actions/checkout must be pinned to a full commit SHA")
    if "actions/upload-artifact@" in t and "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" not in t:
        errs.append("actions/upload-artifact must be pinned to a full commit SHA")
    common_verify_checks(t, errs)
    common_release_checks(t, errs)
    common_supply_chain_checks(t, errs)
    common_credential_checks(t, errs)
    # Echo-leak defense (v5): the review body is posted to a public PR
    # thread; the provider key must be scrubbed from artifacts BEFORE the
    # posting step, and the key must never appear as a command argument.
    redact_idx = t.find("- name: Redact provider key from review output")
    post_idx = t.find("- name: Post review to PR")
    if redact_idx < 0 or post_idx < redact_idx:
        errs.append("missing a provider-key redaction step BEFORE posting")
    elif "sed -i" in t[redact_idx:post_idx] or "grep -F" in t[redact_idx:post_idx]:
        errs.append("redaction must not pass the key as a command argument")
    # Secret isolation (v5): the goose step runs an LLM over attacker-
    # controlled diff content and must not bind GH_TOKEN. The run block
    # between "Run goose" and "Post review to PR" must be token-free.
    goose_idx = t.find("- name: Run goose")
    post_idx = t.find("- name: Post review to PR")
    if goose_idx >= 0 and post_idx > goose_idx:
        block = t[goose_idx:post_idx]
        # Only an actual env BINDING violates isolation (comments may
        # explain why the token is absent).
        import re as _re
        if _re.search(r"^\s*GH_TOKEN\s*:", block, _re.MULTILINE):
            errs.append(
                "the goose step must not bind GH_TOKEN (secret isolation "
                "over attacker-controlled diff content)")
    for ph in PLACEHOLDERS:
        if ph in t:
            errs.append(f"unsubstituted placeholder: {ph}")
    return errs


def check_gitlab(t):
    errs = []
    d = yaml.safe_load(t)  # syntax
    if "merge_request_event" not in t:
        errs.append("MR trigger missing")
    if "codegoose_review" not in d:
        errs.append("missing job codegoose_review")
    else:
        job = d["codegoose_review"]
        if job.get("timeout") != "25 minutes":
            errs.append("missing timeout: 25 minutes")
    if "inline_threads.py extract --raw" not in t and "re.finditer(r'(?m)^## Summary', raw)" not in t:
        errs.append("must extract only final response via ## Summary sentinel")
    if t.count("exit 1") < 1:
        errs.append("empty-review must fail the job explicitly")
    if sum(t.count(k) for k in PROVIDER_KEYS) < 1:
        errs.append("provider key binding missing")
    common_inline_checks(t, errs)
    # diff-anchored discussions need the 3-sha position from the versions data
    for frag in ('position_type: "text"', "head_sha", "base_sha", "start_sha",
                 "new_path", "new_line"):
        if frag not in t:
            errs.append(f"diff discussion payload missing {frag}")
    if "/notes" not in t:
        errs.append("summary note posting missing")
    if "/discussions" not in t:
        errs.append("inline discussion posting missing")
    if "pr.diff" not in t:
        errs.append("pr.diff must be produced for anchor validation")
    common_verify_checks(t, errs)
    common_release_checks(t, errs)
    common_supply_chain_checks(t, errs)
    common_credential_checks(t, errs)
    for ph in PLACEHOLDERS:
        if ph in t:
            errs.append(f"unsubstituted placeholder: {ph}")
    return errs


def check_gitea(t):
    errs = []
    d = yaml.safe_load(t)
    trigger = d.get("on") or d.get(True) or {}
    if list(trigger.keys() if isinstance(trigger, dict) else []) != ["pull_request"]:
        errs.append("trigger must be pull_request only")
    if "codegoose-review" not in d.get("jobs", {}):
        errs.append("missing jobs.codegoose-review")
    else:
        job = d["jobs"]["codegoose-review"]
        if job.get("timeout-minutes") != 25:
            errs.append("missing timeout-minutes: 25")
    if "concurrency" not in d:
        errs.append("missing concurrency group")
    if "permissions" in d:
        errs.append("gitea template must NOT have permissions block")
    key_refs = sum(t.count(f"secrets.{k}") for k in PROVIDER_KEYS)
    if key_refs < 1:
        errs.append("provider key binding missing")
    if "REVIEW_TOKEN" not in t:
        errs.append("REVIEW_TOKEN secret binding missing")
    if "inline_threads.py extract --raw" not in t and "re.finditer(r'(?m)^## Summary', raw)" not in t:
        errs.append("must extract only final response via ## Summary sentinel")
    common_inline_checks(t, errs)
    if "/pulls/" not in t or "/reviews" not in t:
        errs.append("must try the PR review API with inline comments")
    if "/issues/" not in t or "/comments" not in t:
        errs.append("must keep the plain-comment fallback")
    if "head.sha" not in t:
        errs.append("review must be pinned to the PR head sha")
    common_verify_checks(t, errs)
    common_release_checks(t, errs)
    if "actions/checkout@" in t and "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" not in t:
        errs.append("actions/checkout must be pinned to a full commit SHA")
    common_supply_chain_checks(t, errs)
    common_credential_checks(t, errs)
    for ph in PLACEHOLDERS:
        if ph in t:
            errs.append(f"unsubstituted placeholder: {ph}")
    return errs


def check_teamcity(t):
    errs = []
    if "GOOSE_PROVIDER" not in t:
        errs.append("env.GOOSE_PROVIDER parameter missing")
    if "GOOSE_MODEL" not in t:
        errs.append("env.GOOSE_MODEL parameter missing")
    if sum(t.count(k) for k in PROVIDER_KEYS) < 1:
        errs.append("provider key binding missing")
    if "inline_threads.py extract --raw" not in t and "re.finditer(r'(?m)^## Summary', raw)" not in t:
        errs.append("must extract only final response via ## Summary sentinel")
    if "inline_threads.py" not in t or "prepare --body body.md" not in t:
        errs.append("must run inline_threads prepare (threads block stripped + clamp)")
    if "pr_review.txt" not in t:
        errs.append("pr_review.txt artifact missing")
    if "pr.diff" not in t:
        errs.append("pr.diff must be produced for anchor validation")
    common_verify_checks(t, errs)
    common_release_checks(t, errs)
    common_supply_chain_checks(t, errs)
    common_credential_checks(t, errs)
    if "executionTimeout" not in t:
        errs.append("TeamCity build must set executionTimeout")
    for ph in PLACEHOLDERS:
        if ph in t:
            errs.append(f"unsubstituted placeholder: {ph}")
    return errs


CHECKERS = {
    "github": check_github,
    "gitlab": check_gitlab,
    "gitea": check_gitea,
    "teamcity": check_teamcity,
}


def main():
    if len(sys.argv) != 3:
        print("usage: verify.py <platform> <config-file>")
        return 2
    platform, path = sys.argv[1], sys.argv[2]
    if platform not in CHECKERS:
        print("FAIL: unknown platform", platform)
        return 2
    if path == "-":
        t = sys.stdin.read()
    else:
        t = Path(path).read_text(encoding="utf-8", errors="ignore")
    errs = helper_selftest_errors() + CHECKERS[platform](t)
    for e in errs:
        print("FAIL:", e)
    print("RESULT:", "PASS" if not errs else "FAIL")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())