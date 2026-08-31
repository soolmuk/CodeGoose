// Rendered by soolmuk/CodeGoose scripts/render.py - do not hand-edit.
import jetbrains.buildServer.configs.kotlin.*
import jetbrains.buildServer.configs.kotlin.buildSteps.script
import jetbrains.buildServer.configs.kotlin.triggers.vcs

version = "0.1"

object CodeGooseReview : BuildType({
    id("GooseReview")
    name = "CodeGoose AI Review"

    params {
        param("env.GOOSE_PROVIDER", "__PROVIDER__")
        param("env.GOOSE_MODEL", "__GOOSE_MODEL__")
        param("env.__API_KEY_NAME__", "%env.__API_KEY_NAME__%")
    }

    vcs { defaultVcs() }

    // Execution timeout: a hung goose/LLM call must fail the build instead
    // of burning the agent forever (hardening checklist; was missing).
    executionTimeout = 25 * 60 // minutes

    triggers {
        vcs {
            branchFilter = "+:<default>"
        }
    }

    steps {
        script {
            name = "CodeGooseReview"
            id = "CodeGooseReview"
            scriptContent = """
                set -e
                curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh \\
                  | GOOSE_VERSION=v1.48.0 CONFIGURE=false GOOSE_BIN_DIR="${'$'}HOME/.local/bin" bash
                export PATH="${'$'}HOME/.local/bin:${'$'}PATH"
                mkdir -p ~/.config/goose
                cat <<'EOF' > ~/.config/goose/config.yaml
                GOOSE_PROVIDER: __PROVIDER__
                GOOSE_MODEL: __GOOSE_MODEL__
                keyring: false
                EOF
                set -e
                curl -fsSL https://raw.githubusercontent.com/soolmuk/CodeGoose/__RECIPES_REF__/scripts/inline_threads.py -o inline_threads.py
                [ -s inline_threads.py ] || { echo "Failed to download inline_threads.py helper" >&2; exit 1; }
                #[verify:begin]
                # Verification-gate helpers (issue #10): downloaded in all modes.
                curl -fsSL https://raw.githubusercontent.com/soolmuk/CodeGoose/__RECIPES_REF__/scripts/verify_findings.py -o verify_findings.py
                [ -s verify_findings.py ] || { echo "Failed to download verify_findings.py helper" >&2; exit 1; }
                curl -fsSL https://raw.githubusercontent.com/soolmuk/CodeGoose/__RECIPES_REF__/templates/instructions.reflection.md -o instructions.reflection.md
                [ -s instructions.reflection.md ] || { echo "Failed to download reflection instructions" >&2; exit 1; }
                #[verify:end]
                {
                  echo "## Files Changed"
                  git diff --stat HEAD~1..HEAD
                  echo ""
                  echo "## Changes Summary"
                  git diff HEAD~1..HEAD > pr.diff
                  cat pr.diff
                } > changes.txt
                cat <<'EOF' > instructions.txt
                __INSTRUCTIONS__
                EOF
                cat changes.txt >> instructions.txt
                export __API_KEY_NAME__="${'$'}__API_KEY_NAME__"
                goose run --instructions instructions.txt > raw.txt
                python3 inline_threads.py extract --raw raw.txt --out body.md || true
                if [ ! -s body.md ]; then
                  echo "goose produced no final review (no '## Summary' sentinel)" >&2
                  tail -n 40 raw.txt >&2 || true
                  exit 1
                fi
                #[verify:begin]
                # Verification gate (issue #10): single reflection pass + merge
                # in the same script block (the provider key export is NOT
                # repeated). TeamCity has no forge API, so the gate outcomes are
                # recorded as artifacts.
                python3 verify_findings.py extract --body body.md --out findings.json
                if [ -s findings.json ] && [ "$(python3 -c 'import json;print(len(json.load(open("findings.json"))))')" != "0" ]; then
                  cat instructions.reflection.md > reflection_input.txt
                  {
                    echo ""
                    echo "## Findings under verification"
                    cat findings.json
                    echo ""
                    echo "## Diff context (trimmed around citations)"
                    python3 verify_findings.py hunks --diff pr.diff --findings findings.json --out hunks.txt
                    cat hunks.txt
                  } >> reflection_input.txt
                  goose run --instructions reflection_input.txt > reflect_raw.txt
                  if python3 verify_findings.py reflect-parse --raw reflect_raw.txt --out scores.json; then
                    python3 verify_findings.py merge --body body.md --scores scores.json \\
                      --profile __VERIFY_PROFILE__ --mode __VERIFY_MODE__ \\
                      --out-final body.md --out-dropped dropped.json \\
                      --lang "__LANGUAGE__"
                  else
                    # One corrective retry, then fail-open (D-2). The retry
                    # carries the ACTUAL parse failure reason so the model
                    # can correct the specific mistake (not a blind repeat).
                    printf '%s\n' \
                      'Your previous reply could not be parsed. Output MUST be exactly:' \
                      '## Reflection' \
                      '```json' \
                      '{"findings":[{"anchor":"<echo exactly>","score":<0-10>,"why":"<English>"}]}' \
                      '```' \
                      'No prose before or after the json block.' > correction.txt
                    { echo ""; echo "Parse failure reason:"; \
                      python3 verify_findings.py reflect-parse --raw reflect_raw.txt --out /dev/null 2>&1 || true; \
                    } >> correction.txt
                    cat correction.txt > reflection_retry.txt
                    cat reflection_input.txt >> reflection_retry.txt
                    goose run --instructions reflection_retry.txt > reflect_raw2.txt
                    if python3 verify_findings.py reflect-parse --raw reflect_raw2.txt --out scores.json; then
                      python3 verify_findings.py merge --body body.md --scores scores.json \\
                        --profile __VERIFY_PROFILE__ --mode __VERIFY_MODE__ \\
                        --out-final body.md --out-dropped dropped.json \\
                        --lang "__LANGUAGE__"
                    else
                      { python3 verify_findings.py banner --lang "__LANGUAGE__"; echo ""; } | cat - body.md > body_banner.md && mv body_banner.md body.md
                    fi
                  fi
                fi
                #[verify:end]
                # TeamCity has no forge comment API by default: keep the report as
                # an artifact. prepare() still strips the machine-readable threads
                # block, clamps the body to 55,000 chars and recaps unanchored
                # findings, so pr_review.txt stays human-readable.
                python3 inline_threads.py prepare --body body.md --diff pr.diff \
                  --out-clean pr_review.txt --out-threads threads.json
                if [ ! -s pr_review.txt ]; then
                  echo "review body is empty after removing the threads block" >&2
                  exit 1
                fi
                cat pr_review.txt
                cp pr_review.txt artifacts/ 2>/dev/null || true
                #[verify:begin]
                cp dropped.json artifacts/pr_review_dropped.txt 2>/dev/null || true
                #[verify:end]
            """.trimIndent()
        }
    }

    artifactRules = "+:pr_review.txt,+:pr_review_dropped.txt,+:findings.json,+:scores.json,+:dropped.json"
})