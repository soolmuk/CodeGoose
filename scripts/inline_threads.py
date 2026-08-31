#!/usr/bin/env python3
"""Derive inline review threads from the graded review prose — no LLM JSON block.

goose's graded review consists of fixed English-headed markdown sections:

    ## 🔴 Blocking Issues
    - `path/to/file.py:188-192` 설명 텍스트 한 문단 (Korean)
    ## 🟡 Warnings
    - bullets...
    ## 🟢 Suggestions
    - bullets...

CI calls this script to (1) strip those prose sections into bodyClean (the
summary comment), and (2) parse every bullet that quotes a ``path:line`` or
``path:line-line`` anchor (backticked or bare) into one inline thread.
Bullets whose anchor does not exist in the unified diff (new-side hunk lines
only) are traced back by content match; otherwise they are DROPPED from
inline posting but stay in the prose summary - never silently lost.

All text handling is UTF-8 char-safe; bodies are clamped to 55,000 chars.

Commands:
  prepare        --body B --diff D --out-clean C --out-threads T [--no-recap]
  github-payload --body-clean C --threads T --commit-id SHA --out P
  selftest       run built-in checks (exit 0 = pass)
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SECTION_BLOCKING = "## 🔴 Blocking Issues"
SECTION_WARNINGS = "## 🟡 Warnings"
SECTION_SUGGESTIONS = "## 🟢 Suggestions"
SECTION_HIGHLIGHTS = "## ✅ Highlights"
SECTION_VERDICT = "## Verdict"

SECTION_CATEGORIES = [
    ("🔴 Blocking Issues", "BLOCKING", "🔴"),
    ("🟡 Warnings", "WARNING", "🟡"),
    ("🟢 Suggestions", "SUGGESTION", "🟢"),
]
# Sections whose bullets get split into inline threads.
THREADED_SECTIONS = {"🔴 Blocking Issues", "🟡 Warnings", "🟢 Suggestions"}
KNOWN_SECTIONS = set(THREADED_SECTIONS) | {"✅ Highlights", "Verdict"}
CATEGORY_EMOJI = {c: e for _, c, e in SECTION_CATEGORIES}
SECTION_CATEGORY = {h: c for h, c, _ in SECTION_CATEGORIES}

MAX_THREADS = 10   # hard cap posted to the forge
MAX_COMMENT_BODY = 8000  # chars per inline comment
MAX_BODY = 55000   # chars for the summary body

LENIENT_HEADING_RE = re.compile(r"^\s*#{2,3}\s+")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

TRUNCATION_NOTE = "\n\n*(truncated by CI: body exceeded the 55,000-character limit)*\n"
NOT_ANCHORED_NOTE = (
    "\n\n## Not anchored to the diff\n"
    "(the following findings could not be pinned to a diff line, "
    "so no inline comment was created for them)\n"
)
PATH_LINE_RE = re.compile(r"[`\[]?/?([\w./\\-]+?)[`\]]?:(\d+)(?:-(\d+)|((?:,\s*\d+)+))?")
ANSI_RE = re.compile(r"\x1B(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def normalize_path(path):
    """Normalize file path representation across different quoting/prefix formats."""
    if not path:
        return ""
    p = path.strip().strip("`").strip("'\"").strip("[]()")
    p = p.replace("\\", "/")
    p = re.sub(r"^[ab]/", "", p)
    p = re.sub(r"^\./+", "", p)
    p = os.path.normpath(p).replace("\\", "/")
    p = p.lstrip("/")
    if p == ".":
        return ""
    return p


def _bullet_texts(section_text):
    """Yield each bullet line (and its continued body) from a section block."""
    bullet = None
    for raw in section_text.splitlines():
        stripped = raw.strip()
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            if bullet:
                yield bullet
            bullet = m.group(1).strip()
        elif stripped and not LENIENT_HEADING_RE.match(raw):
            if bullet is not None:
                bullet += " " + stripped
            # else: stray non-bullet text; ignored for anchor parsing
        # blank lines just continue paragraphs
    if bullet:
        yield bullet


def _parse_anchor_candidates(text):
    """Return list of candidate anchor dicts from text:
    [{'path': path, 'line': line, 'line_end': end, 'alt_lines': [lines...]}, ...]
    """
    candidates = []
    for m in PATH_LINE_RE.finditer(text):
        # Reject URL-port false positives (e.g. "https://host:443"). The
        # path group's character class includes "/", so the group or the
        # regex's "/" prefix can swallow part of a URL's "//" run. Count all
        # consecutive slashes around the token start: 2+ slashes, or a
        # single slash directly after ":" (URL scheme), disqualifies the
        # candidate. A lone leading slash stays allowed (root citation).
        tok_start = m.start(1)
        k = tok_start
        while k < m.end(1) and text[k] == "/":
            k += 1
        j = tok_start
        while j > 0 and text[j - 1] == "/":
            j -= 1
        leading = (tok_start - j) + (k - tok_start)
        if leading >= 2 or (leading == 1 and j > 0 and text[j - 1] == ":"):
            continue
        raw_path, line = m.group(1), int(m.group(2))
        path = normalize_path(raw_path)
        if not path or path == "dev/null" or line < 1:
            continue
        line_end = int(m.group(3)) if m.group(3) else None
        if line_end is not None and line_end < line:
            continue
        alt_lines = [line]
        if m.group(4):
            for extra in re.findall(r"\d+", m.group(4)):
                val = int(extra)
                if val >= 1 and val not in alt_lines:
                    alt_lines.append(val)
        candidates.append({
            "path": path,
            "line": line,
            "line_end": line_end,
            "alt_lines": alt_lines,
        })
    return candidates


def split_threads(text):
    """Strip the graded prose sections from body text; return (clean, bullets).

    `bullets` is a list of dicts {path, line, line_end, category, body}.
    Guided sections (Global summary, Highlights, Verdict) stay in the summary;
    only Blocking/Warning/Suggestion bullets become inline threads.
    When a section heading is present but has no parseable anchor bullets, the
    section is left in the summary untouched.
    """
    clean, bullets = [], []
    sections = []  # (heading, [lines])
    cur_head, cur_body = None, []
    for raw in text.splitlines():
        m = LENIENT_HEADING_RE.match(raw)
        token = raw.strip().lstrip("#").strip()
        is_known_heading = bool(m and token in KNOWN_SECTIONS)
        if is_known_heading:
            if cur_head is not None:
                sections.append((cur_head, cur_body))
            cur_head, cur_body = raw.strip().lstrip("#").strip(), []
            # Keep heading line itself in body (it's part of readable prose).
            cur_body.append(raw)
        elif cur_head is not None:
            cur_body.append(raw)
        else:
            clean.append(raw)
    if cur_head is not None:
        sections.append((cur_head, cur_body))

    for head, lines in sections:
        body = "\n".join(lines).rstrip() + "\n"
        if head in THREADED_SECTIONS:
            section_bullets = list(_bullet_texts("\n".join(lines[1:])))
            anchored, clean_bullets = [], []
            for b in section_bullets:
                cands = _parse_anchor_candidates(b)
                if cands:
                    c = cands[0]
                    anchored.append((b, c, cands))
                else:
                    clean_bullets.append("- " + b)
            if not anchored:
                # Nothing to inline: keep the section verbatim in the summary
                clean.append(body)
                continue
            bullets.extend(
                {"path": c["path"], "line": c["line"], "line_end": c["line_end"],
                 "alt_lines": c.get("alt_lines", [c["line"]]),
                 "all_candidates": cands,
                 "category": SECTION_CATEGORY[head], "body": txt}
                for txt, c, cands in anchored
            )
            # Keep the full section in the summary so a failed inline POST
            # still leaves every finding visible (no silent loss on fallback).
            clean.append(body)
        else:
            clean.append(body)
    clean_body = "\n".join(line for line in clean).rstrip() + "\n"
    return clean_body, bullets


# Hunk ranges per file: path -> list of (hunk_start, hunk_end) tuples
anchors_hunks = {}


def parse_diff_anchors(diff_text):
    """Map of new-file path -> set of new-side line numbers present in hunks.

    Context and added lines are both anchorable (this matches GitHub review
    comments and GitLab diff discussions).
    """
    global anchors_hunks
    anchors_hunks.clear()
    table = {}
    path = None
    in_hunk = False
    new_start = new_count = seen = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            in_hunk = False
            path = None
            continue
        if raw.startswith("+++ "):
            path = normalize_path(raw[4:].strip())
            if path == "dev/null" or not path:
                path = None
            continue
        if raw.startswith("--- ") or raw.startswith("index ") \
                or raw.startswith("old mode") or raw.startswith("new mode") \
                or raw.startswith("new file") or raw.startswith("deleted file") \
                or raw.startswith("similarity ") or raw.startswith("rename ") \
                or raw.startswith("copy ") or raw.startswith("Binary file"):
            continue
        if raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            if m:
                new_start = int(m.group(1))
                new_count = int(m.group(2) or 1)
                seen = 0
                in_hunk = True
                if path and new_count > 0:
                    anchors_hunks.setdefault(path, []).append(
                        (new_start, new_start + new_count - 1)
                    )
            continue
        if not in_hunk or path is None:
            continue
        if seen >= new_count:
            in_hunk = False
            continue
        # Context (' ') and added ('+') lines are both anchorable
        if raw.startswith("+") or raw.startswith(" "):
            table.setdefault(path, set()).add(new_start + seen)
            seen += 1
            if seen >= new_count:
                in_hunk = False
    return table


CODE_KEYWORDS = {
    "def", "return", "import", "from", "class", "function", "const", "let", "var",
    "if", "else", "elif", "for", "while", "try", "catch", "except", "finally",
    "true", "false", "none", "null", "undefined", "self", "this", "async", "await",
    "public", "private", "protected", "static", "void", "int", "str", "string", "bool"
}


def _extract_identifiers(text):
    """Extract code identifier tokens from text (letters/numbers/underscores)."""
    return set(w.lower() for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_$]*", text))


def _extract_backtick_identifiers(text):
    """Extract code identifiers specifically from backticked spans in text."""
    spans = re.findall(r"`([^`]+)`", text)
    tokens = set()
    for span in spans:
        tokens.update(w.lower() for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_$]*", span))
    return tokens


def _match_by_content(bullets, anchors):
    """Second-chance matching: fuzzy-align bullets with diff lines by identifier/token
    overlap when their quoted line number isn't present in the diff (the reviewer used
    old line numbering, or cited context around the change). Supports multilingual
    (e.g. Korean) reviews by extracting code symbols and backticked identifiers."""
    results = {}
    for b in bullets:
        path, ln = b["path"], b["line"]
        lines = anchors.get(path, set())
        # The citation already points at a diff line: keep it as-is.
        if ln in lines:
            continue

        body = b["body"]
        body_tokens = _extract_identifiers(body)
        bt_tokens = _extract_backtick_identifiers(body)

        meaningful_body = body_tokens - CODE_KEYWORDS
        meaningful_bt = bt_tokens - CODE_KEYWORDS

        if not meaningful_body and not meaningful_bt:
            continue

        best, best_score = None, 0.0
        for diff_line_num in lines:
            diffline = anchors_content.get((path, diff_line_num), "")
            if not diffline:
                continue
            diff_tokens = _extract_identifiers(diffline)
            meaningful_diff = diff_tokens - CODE_KEYWORDS
            if not meaningful_diff:
                continue

            score = 0.0
            # 1. Backtick symbol matches have highest priority
            if meaningful_bt and (meaningful_bt & diff_tokens):
                bt_overlap = len(meaningful_bt & diff_tokens) / len(meaningful_bt)
                diff_overlap = len(meaningful_body & meaningful_diff) / len(meaningful_diff)
                score = 1.0 + bt_overlap + 0.5 * diff_overlap
            # 2. Identifier overlap in general finding body
            elif meaningful_diff and (meaningful_body & meaningful_diff):
                overlap = len(meaningful_body & meaningful_diff)
                overlap_ratio = overlap / len(meaningful_diff)
                matching_tokens = meaningful_body & meaningful_diff
                if any(len(t) >= 3 for t in matching_tokens) and overlap_ratio >= 0.3:
                    score = overlap_ratio

            if score > 0:
                dist = abs(ln - diff_line_num)
                score -= min(dist * 0.001, 0.2)

            if score > best_score:
                best, best_score = diff_line_num, score

        if best is not None and best_score >= 0.3:
            results[(b["path"], b["line"])] = best
    return results


# diff text seen line-by-line, for content matching
anchors_content = {}


def parse_diff_anchors_with_content(diff_text):
    global anchors_content
    anchors_content.clear()
    table = parse_diff_anchors(diff_text)

    def content_table(diff_text):
        table = {}
        cur_path, in_hunk = None, False
        new_start = new_count = seen = 0
        for raw in diff_text.splitlines():
            if raw.startswith("diff --git"):
                in_hunk = False
                cur_path = None
                continue
            if raw.startswith("+++ "):
                cur_path = normalize_path(raw[4:].strip())
                if cur_path == "dev/null" or not cur_path:
                    cur_path = None
                continue
            if raw.startswith("--- ") or raw.startswith("index ") \
                    or raw.startswith("old mode") or raw.startswith("new mode") \
                    or raw.startswith("new file") or raw.startswith("deleted file") \
                    or raw.startswith("similarity ") or raw.startswith("rename ") \
                    or raw.startswith("copy ") or raw.startswith("Binary file"):
                continue
            if raw.startswith("@@"):
                m = HUNK_RE.match(raw)
                if m:
                    new_start = int(m.group(1))
                    new_count = int(m.group(2) or 1)
                    seen = 0
                    in_hunk = True
                continue
            if not in_hunk or cur_path is None:
                continue
            if seen >= new_count:
                in_hunk = False
                continue
            if raw.startswith("+") or raw.startswith(" "):
                table[(cur_path, new_start + seen)] = raw[1:].strip()
                seen += 1
                if seen >= new_count:
                    in_hunk = False
        return table

    anchors_content.update(content_table(diff_text))
    return table


def _is_in_same_hunk(path, start_line, end_line, anchors):
    """Check if start_line and end_line fall within the same contiguous diff hunk."""
    lines = anchors.get(path, set())
    if not lines or start_line not in lines or end_line not in lines:
        return False
    hunks = anchors_hunks.get(path, [])
    if hunks:
        return any(h_start <= start_line <= end_line <= h_end for h_start, h_end in hunks)
    return all(l in lines for l in range(start_line, end_line + 1))


def validate_and_anchor(clean, bullets, anchors, add_recap=True):
    """Return (clean_summary_with_recap, valid_comments)."""
    comments = []
    skipped = []
    # Keep only anchored, category-valid findings. Deduplicate on a stable
    # identity key: (path, line, category, normalized body) - an identical
    # finding appearing twice in the prose must post exactly once.
    identity = set()
    considered = bullets[:MAX_THREADS * 4]
    overflow = bullets[MAX_THREADS * 4:]
    # Overflow findings are still surfaced in the recap (no silent loss).
    for b in overflow:
        snippet = b["body"][:160] + ("…" if len(b["body"]) > 160 else "")
        reason = "(file not in diff) " if b["path"] not in anchors else "(line not in diff hunks) "
        skipped.append((b["path"], b["line"], b["category"], snippet, reason))
    for b in considered:
        lines = anchors.get(b["path"], set())
        start = b.get("start")
        le = b.get("line_end")
        target_path = b["path"]
        target_line = b["line"]

        # Check if primary line is in diff hunks; otherwise check alt_lines or candidates.
        # Cross-file candidates are only consulted when the primary file is NOT in
        # the diff at all: a finding about src/a.py must never be posted on
        # src/b.py just because the bullet also mentions it (misanchoring guard).
        # When the primary file IS in the diff, still try other same-file
        # candidates from the same bullet before giving up to the recap.
        if target_line not in lines:
            for alt in b.get("alt_lines", []):
                if alt in lines:
                    target_line = alt
                    le = None
                    break
        if target_line not in lines and b["path"] in anchors:
            for same_cand in b.get("all_candidates", []):
                if same_cand["path"] != b["path"] or same_cand["line"] == b["line"]:
                    continue  # cross-file handled below; primary tried above
                for alt in same_cand.get("alt_lines", []):
                    if alt in lines:
                        target_line = alt
                        le = None
                        break
                if target_line in lines:
                    break
        if target_line not in lines and b["path"] not in anchors:
            for other_cand in b.get("all_candidates", []):
                cand_lines = anchors.get(other_cand["path"], set())
                for alt in other_cand.get("alt_lines", []):
                    if alt in cand_lines:
                        target_path = other_cand["path"]
                        target_line = alt
                        lines = cand_lines
                        le = None
                        break
                if target_line in lines:
                    break

        # Range validation: check if start and end are in the same diff hunk
        if le is not None:
            if not _is_in_same_hunk(target_path, target_line, le, anchors):
                # Try finding hunk for target_line and clamping
                hunks = anchors_hunks.get(target_path, [])
                clamped_le = None
                for h_start, h_end in hunks:
                    if h_start <= target_line <= h_end:
                        if le > h_end and h_end > target_line:
                            clamped_le = h_end
                        break
                le = clamped_le

        if target_path and target_line >= 1 and lines and target_line in lines \
                and (start is None or start in lines):
            body_norm = " ".join(b["body"].split()).casefold()
            ident = (target_path, target_line, b["category"], body_norm)
            if ident in identity:
                continue
            identity.add(ident)
            emoji = CATEGORY_EMOJI[b["category"]]
            text = f"{emoji} **{b['category']}** — {' '.join(b['body'].split())}"
            c = {
                "path": target_path,
                "line": target_line,
                "side": "RIGHT",
                "body": text[:MAX_COMMENT_BODY],
            }
            if start is not None and start < target_line and _is_in_same_hunk(target_path, start, target_line, anchors):
                c["start_line"] = start
                c["start_side"] = "RIGHT"
            elif le is not None and le > target_line and _is_in_same_hunk(target_path, target_line, le, anchors):
                c["start_line"] = target_line
                c["line"] = le
                c["start_side"] = "RIGHT"
            comments.append(c)
        else:
            snippet = b["body"][:160] + ("…" if len(b["body"]) > 160 else "")
            reason = "(file not in diff) " if b["path"] not in anchors else "(line not in diff hunks) "
            skipped.append((b["path"], b["line"], b["category"], snippet, reason))
    if add_recap and skipped:
        clean += NOT_ANCHORED_NOTE
        for item in skipped[:10]:
            if len(item) == 5:
                path, line, category, snippet, reason = item
            else:
                path, line, category, snippet = item[:4]
                reason = ""
            clean += f"- [{category}] `{path}:{line}` {reason}{snippet}\n"
    if len(comments) > MAX_THREADS:
        # Keep the truncation visible in the summary (no silent loss).
        dropped = len(comments) - MAX_THREADS
        clean += (f"\n*(inline comment limit reached: {dropped} additional "
                  f"finding(s) below the fold remain in the prose above)*\n")
        comments = comments[:MAX_THREADS]
    return clean, comments


def truncate_body(clean):
    """Clamp the summary but always preserve the 'Not anchored' recap."""
    recap_marker = NOT_ANCHORED_NOTE
    recap = ""
    if recap_marker in clean:
        head, rest = clean.split(recap_marker, 1)
        clean, recap = head, recap_marker + rest
    if len(clean) > MAX_BODY:
        clean = clean[:MAX_BODY] + TRUNCATION_NOTE
    if recap:
        clean = clean.rstrip() + "\n" + recap
    return clean


def cmd_prepare(args):
    body = Path(args.body).read_text(encoding="utf-8", errors="ignore")
    body, bullets = split_threads(body)
    diff_text = Path(args.diff).read_text(encoding="utf-8", errors="ignore")
    anchors = parse_diff_anchors_with_content(diff_text)
    content_matches = _match_by_content(bullets, anchors)

    # Remap bullets whose quoted line wasn't in the diff
    for b in bullets:
        key = (b["path"], b["line"])
        lines = anchors.get(b["path"], set())
        if b["line"] in lines:
            continue
        alt_found = False
        for alt in b.get("alt_lines", []):
            if alt in lines:
                b["line"] = alt
                b["start"] = None
                alt_found = True
                break
        if alt_found:
            continue
        if key in content_matches:
            b["line"] = content_matches[key]
            b["start"] = None
        elif lines:
            # Snap to closest diff line if within tolerance (±3 lines)
            closest = min(lines, key=lambda l: abs(l - b["line"]))
            if abs(b["line"] - closest) <= 3:
                b["line"] = closest
                b["start"] = None

    clean, comments = validate_and_anchor(
        body, bullets, anchors, add_recap=not args.no_recap)
    clean = truncate_body(clean)
    Path(args.out_clean).write_text(clean, encoding="utf-8")
    Path(args.out_threads).write_text(
        json.dumps(comments, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"inline threads: {len(comments)} anchored / {len(bullets)} parsed")
    return 0


def cmd_github_payload(args):
    clean = Path(args.body_clean).read_text(encoding="utf-8")
    comments = json.loads(Path(args.threads).read_text(encoding="utf-8"))
    payload = {"commit_id": args.commit_id, "event": "COMMENT",
               "body": clean, "comments": comments}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    return 0


def cmd_extract(args):
    """Pull the graded review starting at the `## Summary` sentinel.

    Goose may prefix session banners, so the sentinel is not always at
    column 0 (models sometimes glue it onto the previous line). Prefer the
    first line-anchored sentinel; fall back to the last inline occurrence.
    ANSI CSI/OSC sequences are stripped.
    """
    raw = Path(args.raw).read_text(encoding="utf-8", errors="ignore")
    raw = ANSI_RE.sub("", raw)
    cand = [m.start() for m in re.finditer(r"(?m)^## Summary", raw)]
    idx = cand[0] if cand else raw.rfind("## Summary")
    text = raw[idx:] if idx >= 0 else ""
    Path(args.out).write_text(text, encoding="utf-8")
    return 0 if text.strip() else 1


def cmd_gitea_payload(args):
    """Gitea PR-review payload: line -> new_line_num; drop GitHub-only fields."""
    clean = Path(args.body_clean).read_text(encoding="utf-8")
    comments = json.loads(Path(args.threads).read_text(encoding="utf-8"))
    mapped = []
    for t in comments:
        item = {"body": t.get("body", ""), "new_line_num": t.get("line"),
                "path": t.get("path")}
        mapped.append(item)
    payload = {"commit_id": args.commit_id, "body": clean, "comments": mapped}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    return 0


def _selftest():
    diff = (
        "diff --git a/src/a.py b/src/a.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "+x = 1\n"
        " \n"
        " def main():\n"
        "@@ -10,0 +11,1 @@\n"
        "+added_line()\n"
        "diff --git a/bin.bin b/bin.bin\n"
        "Binary files differ\n"
    )
    anchors = parse_diff_anchors_with_content(diff)
    # Context lines (1, 3, 4) and added lines (2, 11) are all valid anchors.
    assert anchors == {"src/a.py": {1, 2, 3, 4, 11}}, anchors
    assert anchors_hunks == {"src/a.py": [(1, 4), (11, 11)]}, anchors_hunks

    # Path normalization tests
    assert normalize_path("./src/a.py") == "src/a.py"
    assert normalize_path("b/src/a.py") == "src/a.py"
    assert normalize_path("a/src/a.py") == "src/a.py"
    assert normalize_path("`src/a.py`") == "src/a.py"
    assert normalize_path("src\\a.py") == "src/a.py"
    assert normalize_path("/dev/null") == "dev/null"
    assert normalize_path(".github/workflows/codegoose-review.yml") == ".github/workflows/codegoose-review.yml"
    assert normalize_path("b/.github/workflows/codegoose-review.yml") == ".github/workflows/codegoose-review.yml"
    assert normalize_path("./.github/workflows/codegoose-review.yml") == ".github/workflows/codegoose-review.yml"
    assert normalize_path("a/.gitignore") == ".gitignore"
    assert normalize_path("./.gitignore") == ".gitignore"
    assert normalize_path(".gitignore") == ".gitignore"
    assert normalize_path("/.gitignore") == ".gitignore"

    body = (
        "## Summary\nlooks fine\n\n"
        "## 🔴 Blocking Issues\n"
        "- `./src/a.py:2` x 값이 덮어써져 오류가 발생할 수 있음.\n"
        "- 연관되지 않은 전체 아키텍처 리스크: 모듈 경계 불명확.\n"
        "\n"
        "## 🟡 Warnings\n"
        "- `src/a.py:3-4` 범위 이탈 가능성.\n"
        "- `src/a.py:5,11` 콤마 분리 다중 라인 테스트.\n"
        "- `src/a.py:99` `main` 함수 정의부에 docstring이 누락되었습니다.\n"
        "- `src/a.py:5` 함수 바로 다음 줄에 타입 어노테이션 누락.\n"
        "\n"
        "## 🟢 Suggestions\n"
        "- [src/never.py:9999] 경로 오타로 앵커 불가한 제안.\n"
        "- `src/a.py:103,139,165` diff 범위 밖 콤마 분리 제안.\n"
        "\n"
        "## ✅ Highlights\n"
        "- 좋은 커밋 구조.\n"
        "\n"
        "## Verdict\n"
        "REQUEST_CHANGES - 차단 이슈 1건.\n"
    )
    clean, bullets = split_threads(body)
    assert "x 값이 덮어써져" in clean, clean
    assert "범위 이탈 가능성" in clean
    assert "콤마 분리 다중 라인" in clean
    assert "docstring이 누락" in clean
    assert "타입 어노테이션 누락" in clean
    assert "경로 오타로 앵커 불가한 제안" in clean
    assert "diff 범위 밖 콤마 분리 제안" in clean
    assert "전체 아키텍처 리스크" in clean
    assert "Highlights" in clean
    assert "Verdict" in clean
    assert len(bullets) == 7, bullets
    assert bullets[0]["category"] == "BLOCKING"
    assert bullets[0]["path"] == "src/a.py" and bullets[0]["line"] == 2
    assert bullets[1]["line"] == 3 and bullets[1]["line_end"] == 4
    assert bullets[2]["line"] == 5 and bullets[2]["alt_lines"] == [5, 11]

    # Fuzzy matching for Korean review: line 99 citing `main` should match diff line 4
    mapped = _match_by_content(bullets, anchors)
    assert (bullets[0]["path"], 2) not in mapped
    assert mapped.get(("src/a.py", 99)) == 4, mapped

    # Simulate prepare line resolution (alt_lines + content match + snap)
    for b in bullets:
        key = (b["path"], b["line"])
        lines = anchors.get(b["path"], set())
        if b["line"] in lines:
            continue
        alt_found = False
        for alt in b.get("alt_lines", []):
            if alt in lines:
                b["line"] = alt
                b["start"] = None
                alt_found = True
                break
        if alt_found:
            continue
        if key in mapped:
            b["line"] = mapped[key]
            b["start"] = None
        elif lines:
            closest = min(lines, key=lambda l: abs(l - b["line"]))
            if abs(b["line"] - closest) <= 3:
                b["line"] = closest
                b["start"] = None

    # Line 5 was snapped to line 4
    assert any(b["line"] == 4 and "타입 어노테이션" in b["body"] for b in bullets)

    clean2, comments = validate_and_anchor(clean, bullets, anchors)
    paths = {c["path"] for c in comments}
    assert paths == {"src/a.py"}, comments
    assert "## Not anchored to the diff" in clean2
    assert "src/never.py" in clean2  # demoted recap keeps the finding
    assert "(file not in diff)" in clean2
    assert "src/a.py:103" in clean2

    # Verify comments
    assert any(c["line"] == 2 and c["body"].startswith("🔴") for c in comments), comments
    assert any(c.get("start_line") == 3 and c["line"] == 4 for c in comments), comments
    assert any(c["line"] == 11 and c["body"].startswith("🟡") for c in comments), comments
    assert any(c["line"] == 4 and "docstring" in c["body"] for c in comments), comments
    assert any(c["line"] == 4 and "타입 어노테이션" in c["body"] for c in comments), comments

    truncated = truncate_body("x" * (MAX_BODY + 500))
    assert len(truncated) <= MAX_BODY + len(TRUNCATION_NOTE)

    # Recap survives truncation when the prose alone exceeds the budget.
    long_body = "y" * (MAX_BODY + 500) + NOT_ANCHORED_NOTE + "- [X] `f:1` 사유\n"
    kept = truncate_body(long_body)
    assert "## Not anchored to the diff" in kept, "recap lost by truncation"
    assert "`f:1` 사유" in kept

    # empty sections must survive as prose
    body2 = "## Summary\nnothing found\n\n## Verdict\nAPPROVE.\n"
    clean3, bullets3 = split_threads(body2)
    assert bullets3 == [] and "Verdict" in clean3

    # Cross-file misanchor guard: a finding about src/a.py (in diff) whose
    # bullet also cites src/b.py (also in diff) must stay anchored to src/a.py
    # or fall into the recap — never be posted as a comment on src/b.py.
    # (Runs last: parse_diff_anchors_with_content replaces the shared hunk map.)
    diff2 = (
        "diff --git a/src/a.py b/src/a.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " old\n"
        "+new a\n"
        "diff --git a/src/b.py b/src/b.py\n"
        "index 3333333..4444444 100644\n"
        "--- a/src/b.py\n"
        "+++ b/src/b.py\n"
        "@@ -1,2 +1,2 @@\n"
        " old\n"
        "+new b\n"
    )
    anchors2 = parse_diff_anchors_with_content(diff2)
    body_xf = (
        "## Summary\n\n"
        "## 🔴 Blocking Issues\n"
        "- `src/a.py:999` 잘못된 라인 인용이지만 `src/b.py:2`도 함께 확인 필요.\n"
        "\n"
        "## 🟡 Warnings\n"
        "없음\n"
        "\n"
        "## 🟢 Suggestions\n"
        "- `src/b.py:1` b 단독 인용은 정상 앵커.\n"
        "\n"
        "## ✅ Highlights\n"
        "- 좋음.\n"
        "\n"
        "## Verdict\n"
        "APPROVE.\n"
    )
    clean_xf, bullets_xf = split_threads(body_xf)
    clean_xf2, comments_xf = validate_and_anchor(clean_xf, bullets_xf, anchors2)
    assert {c["path"] for c in comments_xf} == {"src/b.py"}, comments_xf
    assert any(c["path"] == "src/b.py" and c["line"] == 1 for c in comments_xf), comments_xf
    assert not any(c["line"] == 2 and c["path"] == "src/b.py" for c in comments_xf), \
        "misanchor: finding about src/a.py was posted on src/b.py"
    assert "src/a.py:999" in clean_xf2, "finding must survive in the recap"

    # URL-port false positives must never become anchor candidates.
    url_cases = [
        ("see https://example.com:443/docs and `src/a.py:2` real", ["src/a.py"]),
        ("http://host:8080/x", []),
        ("ftp://files.example.com:21/x", []),
        ("//protocol-relative.example.com:80/x", []),
    ]
    for txt, expect in url_cases:
        got = [c["path"] for c in _parse_anchor_candidates(txt)]
        assert sorted(got) == sorted(expect), f"URL guard failed on {txt!r}: {got}"

    # Same-file fallback: primary line invalid, another same-file citation valid.
    clean_sf, bullets_sf = split_threads(
        "## Summary\n\n"
        "## 🔴 Blocking Issues\n"
        "- `src/a.py:999` 잘못된 라인이지만 `src/a.py:2` 도 함께 수정 필요.\n"
        "\n## 🟡 Warnings\n없음\n\n## 🟢 Suggestions\n없음\n\n"
        "## ✅ Highlights\n- 좋음\n\n## Verdict\nREQUEST_CHANGES\n"
    )
    clean_sf2, comments_sf = validate_and_anchor(clean_sf, bullets_sf, anchors2)
    assert any(c["path"] == "src/a.py" and c["line"] == 2 for c in comments_sf), \
        f"same-file fallback lost a valid in-diff citation: {comments_sf}"
    assert not any(c["path"] == "src/b.py" for c in comments_sf), comments_sf

    print("selftest: all checks passed")
    return 0


def main():
    ap = argparse.ArgumentParser(description="goose inline review threads helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--body", required=True)
    p.add_argument("--diff", required=True)
    p.add_argument("--out-clean", required=True)
    p.add_argument("--out-threads", required=True)
    p.add_argument("--no-recap", action="store_true",
                   help="do not add the 'Not anchored' recap (non-PR platforms)")
    p.set_defaults(func=cmd_prepare)

    g = sub.add_parser("github-payload")
    g.add_argument("--body-clean", required=True)
    g.add_argument("--threads", required=True)
    g.add_argument("--commit-id", required=True)
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_github_payload)

    e = sub.add_parser("extract")
    e.add_argument("--raw", required=True)
    e.add_argument("--out", required=True)
    e.set_defaults(func=cmd_extract)

    gi = sub.add_parser("gitea-payload")
    gi.add_argument("--body-clean", required=True)
    gi.add_argument("--threads", required=True)
    gi.add_argument("--commit-id", required=True)
    gi.add_argument("--out", required=True)
    gi.set_defaults(func=cmd_gitea_payload)

    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return _selftest()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())