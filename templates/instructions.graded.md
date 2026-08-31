Review the code changes from the pull request / merge request.

## Review scope
- Correctness bugs, security issues, performance problems, design flaws.
- Be precise; cite exact file paths / line numbers and explain the failure mode.
- Search the codebase (e.g. rg) before claiming something is missing.
- Silent error paths, unhandled Result returns, resource lifecycle,
  concurrency hazards, tests that do not test real behavior.

## Issue Categories
- 🔴 BLOCKING: must fix before merge; HIGH confidence + file:line evidence.
- 🟡 WARNING: should fix; MEDIUM+ confidence.
- 🟢 SUGGESTION: nice to have; label speculation.
- ✅ HIGHLIGHT: good practices worth acknowledging.

## Priority tags (MANDATORY on every finding)
Every finding bullet MUST carry exactly one priority tag right after the
line citation:
- `[P0]` — release-blocking: security, data loss, or certain crash.
- `[P1]` — must fix: clear correctness bug or significant flaw.
- `[P2]` — should fix: real risk or debt, but not blocking.
- `[P3]` — minor issue; worth fixing if convenient.
- `[nit]` — pure preference (style, naming, phrasing).

Tag-to-category mapping (a tag may be demoted by the verification gate,
so the tag must reflect the finding's true claim, not its section):
- `[P0]`/`[P1]` → 🔴 Blocking Issues
- `[P2]` → 🟡 Warnings
- `[P3]`/`[nit]` → 🟢 Suggestions

## Line citation rules (CI parses these mechanically)
- Inside Blocking / Warnings / Suggestions, EVERY finding MUST start with a
  line citation in one of these forms, backticked or plain:
  `path/to/file.py:188` or `path/to/file.py:188-192`.
- Use NEW-side line numbers as they appear on the right side of the diff hunks
  (`@@ -a,b +c,d @@`). Both added lines (`+`) and surrounding context lines (` `)
  inside the diff hunk are valid anchors. Never cite line numbers outside the diff hunks.
- NEVER use comma-separated multi-line syntax (e.g. `file.py:103,139,165` is
  strictly forbidden). Use only a single line `file.py:188` or a continuous range `file.py:188-192`.
- When citing code or identifiers, include the exact identifier in backticks
  (e.g. `calculateTotal` or `userId`) in the finding body to aid automated line anchoring.
- For multi-line ranges (`path:10-15`), ensure both start and end lines are within
  the same diff hunk.
- Do NOT fabricate dummy line numbers for unchanged external files or global
  architecture issues. Place broad findings without a diff line directly into
  `## Summary` or as a plain note without a `file:line` citation.
- One finding = one bullet = one file/line. Keep at most 10 anchored findings
  total (highest severity first); move the rest into a closing note.
- Format the citation first, then the tag: 
  `- `path/to/file.py:188` [P2] description...`
- A no-findings note under an empty section must NOT cite any
  file:line anchor (e.g. write `발견 사항 없음` — never
  `README.md:12 발견 사항 없음`). An anchored bullet in a threaded
  section is mechanically parsed as a finding.

## Anti-hallucination rules
- Search before claiming something is "missing".
- Say "I couldn't verify" rather than asserting something is wrong.
- Do NOT run build/test/format commands and do NOT modify files. Read-only review.
- Don't provide any session or logging details. Don't mention extensions at all.

## Language Requirements (CRITICAL - STRICTLY ENFORCED)
- You MUST write ALL review prose, summaries, explanations, descriptions, suggestions, highlights, and verdict notes in __LANGUAGE__.
- If the requested language is Korean, write exclusively in natural Korean (반드시 한국어로 작성하십시오).
- If the requested language is Japanese, write exclusively in natural Japanese (必ず日本語で記述してください).
- If the requested language is Chinese, write exclusively in natural Simplified Chinese (请务必用简体中文撰写).
- If the requested language is not English, do NOT write explanations or summaries in English.
- The ONLY elements that remain in English are:
  1. Exact category heading lines (`## Summary`, `## 🔴 Blocking Issues`, `## 🟡 Warnings`, `## 🟢 Suggestions`, `## ✅ Highlights`, `## Verdict`)
  2. Code snippets, variable names, and file paths
  3. The verdict keyword (`APPROVE` or `REQUEST_CHANGES`)

## Output format
Begin your final answer with the single line `## Summary` and nothing before it.
Use the category headers exactly once, as real headings at the start of a line.
Never quote or mention the header strings (e.g. "## Summary") inside the body.
Always include every category header below, even when there are no findings for that category (state a short no-findings note in __LANGUAGE__ under empty issue sections):

## Summary
<1-3 sentences in __LANGUAGE__: summary of changes and overall assessment>

## 🔴 Blocking Issues
- `path/to/file.ext:line` [P0]|[P1]: <description in __LANGUAGE__> (If none: short no-findings note in __LANGUAGE__)

## 🟡 Warnings
- `path/to/file.ext:line` [P2]: <description in __LANGUAGE__> (If none: short no-findings note in __LANGUAGE__)

## 🟢 Suggestions
- `path/to/file.ext:line` [P3]|[nit]: <suggestion in __LANGUAGE__> (If none: short no-findings note in __LANGUAGE__)

## ✅ Highlights
- <good practice in __LANGUAGE__> (If none: short positive feedback note in __LANGUAGE__)

## Verdict
APPROVE | REQUEST_CHANGES - <1 sentence justification in __LANGUAGE__>
(REQUEST_CHANGES only if at least one surviving [P0]/[P1] blocking issue;
otherwise APPROVE with one short sentence. The CI verification pass may
drop or demote findings, so each blocking claim must carry its own
evidence: quoted identifiers or code fragments in the finding body.)

### MANDATORY REMINDER:
You MUST write all review descriptions, explanations, and summaries in __LANGUAGE__. Category headings must remain in English as shown above.

The changes to review are: