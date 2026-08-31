#!/usr/bin/env python3
"""Verification gate for CodeGoose PR reviews (issue #10, plan v1).

A first-pass graded review may contain false positives. This script adds a
single strengthening verification (reflection) pass plus a deterministic
merge gate:

    goose graded review (body.md)
      -> extract            findings.json (normalized anchors)
      -> goose reflection   reflect_raw.txt (LLM scores 0-10 per finding)
      -> reflect-parse      scores.json (tolerant JSON parse; exit 1 on junk)
      -> merge              final body.md (in-place), dropped.json
      -> (existing) inline_threads.py prepare --body body.md ...

Commands:
  extract        --body B --out F            (deterministic finding list)
  reflect-parse  --raw R --out S             (## Reflection sentinel + json)
  merge          --body B --scores S --profile conservative|strict
                 --mode enforce|shadow --out-final F --out-dropped D
                 [--lang L]
  selftest                                  (exit 0 = pass)

Gate policy (2D matrix, priority x validity score):
  score 0-3   refuted / no quoted evidence
  score 4-6   plausible but unverified
  score 7-10  concrete evidence confirmed in diff/code
  [P0]/[P1]   >=7 keep | 4-6 demote to [P2] in Warnings | <=3 drop
  [P2]        >=7 keep | 4-6 keep | <=3 drop
  [P3]/[nit]  >=7 keep | 4-6 keep | <=3 drop
  strict profile: <=4 drop, 5-7 demote, >=8 keep (every priority)
  unmatched finding: conservative=KEEP(+WARN), strict=DROP
  Verdict: REQUEST_CHANGES iff >=1 surviving [P0]/[P1] bullet.

Reuses parsing primitives from inline_threads.py (import, not copy):
LENIENT_HEADING_RE, KNOWN_SECTIONS, SECTION_CATEGORY, _bullet_texts,
_parse_anchor_candidates, normalize_path, truncate_body, ANSI_RE.
merge() does its own position-preserving section walk because
split_threads()'s `clean` return value has no source line positions.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from inline_threads import (
    ANSI_RE,
    LENIENT_HEADING_RE,
    KNOWN_SECTIONS,
    SECTION_CATEGORY,
    _bullet_texts,
    _parse_anchor_candidates,
    normalize_path,
    truncate_body,
)

# ---------------------------------------------------------------------------
# Section / priority mapping tables
# ---------------------------------------------------------------------------

SECTION_EMOJI = {
    "BLOCKING": "🔴 Blocking Issues",
    "WARNING": "🟡 Warnings",
    "SUGGESTION": "🟢 Suggestions",
}
EMOJI_SECTION = {v: k for k, v in SECTION_EMOJI.items()}

# P-tag -> canonical priority level.
PTAG_PRIORITY = {"P0": "high", "P1": "high", "P2": "medium",
                 "P3": "low", "nit": "low"}
# Section-based fallback for legacy bullets without a P-tag.
SECTION_FALLBACK_PRIORITY = {"BLOCKING": "high", "WARNING": "medium",
                             "SUGGESTION": "low"}

PTAG_RE = re.compile(r"\[(P0|P1|P2|P3|nit)\]")

# Language table for the empty-section note. Unknown languages fall back
# to English with a stderr WARN (see merge).
EMPTY_SECTION_NOTES = {
    "ko": "(검증 단계에서 이 카테고리의 파인딩이 모두 제외되었습니다. "
          "상세는 CI 로그의 dropped.json을 참고하세요.)",
    "en": "(All findings in this category were removed by the verification "
          "pass. See the CI log's dropped.json for details.)",
}

# Fail-open banner (D-2): the original first-pass review is posted with
# this header when reflection parsing fails twice.
FAILOPEN_BANNERS = {
    "ko": "⚠️ 검증 미적용 — 리플렉션 출력 파싱 2회 실패, 원본 1차 리뷰를 게시합니다.",
    "en": "⚠️ Verification not applied — reflection output failed to parse "
          "twice; posting the original first-pass review.",
}

BULLET_RE = re.compile(r"^(\s*)([-*])\s+(.*)$")
VERDICT_RE = re.compile(r"^\s*## Verdict\b")
SUMMARY_HEADING = "Summary"


def _warn(msg):
    print(f"WARN: {msg}", file=sys.stderr)


def _lang_key(lang):
    """Map the __LANGUAGE__ parameter to a note-table key."""
    l = (lang or "").strip().lower()
    if "한국" in l or l.startswith("ko") or "korean" in l:
        return "ko"
    if l and not l.startswith("en"):
        # Unknown language: fall back to English notes with a WARN (plan
        # L96: unknown language -> English fallback + WARN).
        _warn(f"unknown language {lang!r}: falling back to English notes")
    return "en"


def _bullet_priority(bullet_text, section):
    """Return (priority, has_ptag) for a joined bullet text."""
    m = PTAG_RE.search(bullet_text)
    if m:
        return PTAG_PRIORITY[m.group(1)], True
    return SECTION_FALLBACK_PRIORITY[section], False


# ---------------------------------------------------------------------------
# Body walk: position-preserving section split
# ---------------------------------------------------------------------------

def _walk_sections(text):
    """Yield (kind, payload) over the body while keeping source positions.

    kind is one of:
      'pre'    payload: (index, line)      — lines before any known heading
      'span'   payload: (heading, start, end)  — known section span,
                 start = heading line index, end = exclusive end
    """
    lines = text.split("\n")
    spans = []
    cur = None
    for i, raw in enumerate(lines):
        m = LENIENT_HEADING_RE.match(raw)
        token = raw.strip().lstrip("#").strip()
        if m and token in KNOWN_SECTIONS:
            if cur is not None:
                spans.append((cur[0], cur[1], i))
            cur = (token, i)
    if cur is not None:
        spans.append((cur[0], cur[1], len(lines)))
    return lines, spans


def _span_bullets(lines, start, end):
    """Yield bullet dicts {start, end, text} for lines[start:end].

    Continuation prose (joined into `text`) only extends a bullet while no
    blank line intervenes — mirrors inline_threads._bullet_texts. The
    deletion span, however, STOPS at the first blank line: independent
    model prose after a blank line must survive a bullet deletion.
    """
    cur = None
    out = []
    for i in range(start + 1, end):
        raw = lines[i]
        m = BULLET_RE.match(raw)
        if m:
            if cur:
                out.append(cur)
            cur = {"start": i, "end": i, "text": m.group(3).strip()}
        elif cur is not None:
            if LENIENT_HEADING_RE.match(raw):
                break
            if not raw.strip():
                # Blank line: TEXT continues on the next non-blank line
                # (mirrors inline_threads._bullet_texts), but the DELETION
                # SPAN stops here — prose after a blank line is
                # independent and must survive deletion.
                if "text_end" not in cur:
                    cur["text_end"] = i - 1
                continue
            if raw.strip():
                # Join into text even across blank lines: parser parity
                # with inline_threads._bullet_texts (extract and prepare
                # must agree on WHAT the findings are).
                cur["end"] = i
                cur["text"] += " " + raw.strip()
    if cur:
        out.append(cur)
    return out


def _anchor_of(bullet_text):
    """First parseable anchor candidate -> (path, line, line_end|None)."""
    cands = _parse_anchor_candidates(bullet_text)
    if not cands:
        return None
    c = cands[0]
    return (c["path"], c["line"], c["line_end"])


def _anchor_str(key):
    path, line, end = key
    s = f"{path}:{line}"
    if end is not None:
        s += f"-{end}"
    return s


def _parse_score_anchor(anchor):
    """Normalize a reflection echo anchor to the key form, or None."""
    m = re.match(r"^\s*(?:`([^\s:]+)`|([^\s:]+)):(\d+)(?:-(\d+))?\s*$",
                 str(anchor))
    if not m:
        return None
    raw_path = m.group(1) or m.group(2)
    path = normalize_path(raw_path)
    if not path:
        return None
    line = int(m.group(3))
    end = int(m.group(4)) if m.group(4) else None
    if line < 1 or (end is not None and end < line):
        return None
    return (path, line, end)


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def extract_findings(text):
    """Deterministically list verifiable findings from a graded body.

    Findings without a parseable anchor are skipped (not verifiable; they
    remain in the prose untouched, so nothing is lost).
    """
    lines, spans = _walk_sections(text)
    findings = []
    for heading, start, end in spans:
        section = EMOJI_SECTION.get(heading)
        if section is None:
            continue
        for b in _span_bullets(lines, start, end):
            key = _anchor_of(b["text"])
            if key is None:
                continue
            priority, _tagged = _bullet_priority(b["text"], section)
            findings.append({
                "anchor": _anchor_str(key),
                "section": section,
                "priority": priority,
                "body": b["text"],
            })
    return findings


def cmd_extract(args):
    body = Path(args.body).read_text(encoding="utf-8", errors="ignore")
    body = ANSI_RE.sub("", body)
    findings = extract_findings(body)
    Path(args.out).write_text(
        json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"extract: {len(findings)} verifiable findings")
    return 0


# ---------------------------------------------------------------------------
# reflect-parse
# ---------------------------------------------------------------------------

REFLECTION_SENTINEL = "## Reflection"


def _coerce_score(v):
    """Tolerant score coercion: 8 / 8.0 / "8" -> 8.0; else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        s = float(v)
    elif isinstance(v, str):
        try:
            s = float(v.strip())
        except ValueError:
            return None
    else:
        return None
    if 0.0 <= s <= 10.0:
        return s
    return None


def parse_reflection(raw):
    """Parse ## Reflection output. Returns (scores, errors).

    Tolerant: accepts fences labeled json or not; falls back to the first
    '{' .. last '}' span when no fence is found. Score schema is coerced
    (numbers/strings); out-of-range items are ignored with a WARN.
    """
    errors = []
    raw = ANSI_RE.sub("", raw)
    idx = raw.find(REFLECTION_SENTINEL)
    # Prefer a line-anchored sentinel (parity with the first-pass
    # extraction in inline_threads.cmd_extract), fall back to the first
    # inline occurrence: session banners may glue text onto the line.
    anchored = [m.start() for m in
                re.finditer(r"(?m)^## Reflection", raw)]
    if anchored:
        idx = anchored[0]
    if idx < 0:
        return None, ["no '## Reflection' sentinel in reflect output"]
    text = raw[idx + len(REFLECTION_SENTINEL):]

    # Fence markers must start a line: an inner ``` inside a "why" string
    # must not terminate the payload early. (?m) + anchor keeps it robust.
    fence = re.search(r"(?m)^```(?:json)?[ \t]*\r?\n(.*?)^```[ \t]*$",
                      text, re.S)
    payload = None
    if fence:
        payload = fence.group(1)
    else:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            payload = text[s:e + 1]
            errors.append("no fenced ```json block; used brace fallback")
        else:
            return None, ["no JSON object found after '## Reflection'"]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        return None, [f"JSON decode error: {e}"]

    items = None
    if isinstance(data, dict) and "findings" in data:
        items = data["findings"]
    elif isinstance(data, list):
        items = data
    else:
        return None, ["JSON must be {'findings': [...]} or a list"]
    if not isinstance(items, list):
        return None, ["'findings' must be a list"]

    scores = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"score item #{i} is not an object; ignored")
            continue
        anchor = item.get("anchor")
        if not isinstance(anchor, str) or not anchor.strip():
            errors.append(f"score item #{i} has no anchor string; ignored")
            continue
        score = _coerce_score(item.get("score"))
        if score is None:
            errors.append(f"score item #{i} ({anchor}) score out of range "
                          f"or missing; ignored")
            continue
        why = item.get("why", "")
        if not isinstance(why, str):
            why = ""
        scores.append({"anchor": anchor.strip(), "score": score, "why": why})
    seen_anchors = set()
    for s in scores:
        if s["anchor"] in seen_anchors:
            # Plan L93: reflect-parse preserves duplicates and WARNs;
            # first-match-wins is applied later by merge.
            errors.append(f"duplicate score anchor kept: {s['anchor']!r} "
                          "(merge applies first-match-wins)")
        seen_anchors.add(s["anchor"])
    return scores, errors


def cmd_reflect_parse(args):
    raw = Path(args.raw).read_text(encoding="utf-8", errors="ignore")
    scores, errors = parse_reflection(raw)
    if scores is None:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for e in errors:
        _warn(e)
    Path(args.out).write_text(
        json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"reflect-parse: {len(scores)} scores")
    return 0


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def gate_decision(priority, score, profile):
    """2D matrix: priority x score -> 'keep' | 'demote' | 'drop'.

    strict profile (plan: "모든 우선순위에 동일 임계"): <=4 drop,
    5-7 demote, >=8 keep for EVERY priority.
    conservative (default): the standard 2D matrix below.
    """
    if profile == "strict":
        if score >= 8.0:
            return "keep"
        if score >= 5.0:
            return "demote"
        return "drop"
    if score <= 3.0:
        return "drop"
    if priority == "high" and score <= 6.0:
        return "demote"
    return "keep"


def _rewrite_demoted_line(line):
    """Rewrite a bullet's first P-tag to [P2], or prefix one when legacy."""
    m = BULLET_RE.match(line)
    if not m:
        return line
    indent, marker, rest = m.groups()
    tag = PTAG_RE.search(rest)
    if tag:
        rest = rest.replace(tag.group(0), "[P2]", 1)
        return f"{indent}{marker} {rest}"
    return f"{indent}{marker} [P2] {rest}"


def _regenerate_verdict(lines, blocking_alive, lang_key):
    """Replace every Verdict section body with a fresh verdict paragraph.

    Handles 'APPROVE.', 'APPROVE - ...' and dash-less forms uniformly by
    regenerating the WHOLE section.
    """
    just = {
        "ko": ("검증을 통과한 차단 이슈가 남아 있어 머지 전 수정이 필요합니다."
               if blocking_alive else
               "검증을 통과한 파인딩에 차단 이슈가 없습니다."),
        "en": ("At least one verified blocking issue remains."
               if blocking_alive else
               "No verified blocking issues remain after verification."),
    }
    verdict_word = "REQUEST_CHANGES" if blocking_alive else "APPROVE"
    out, i, found = [], 0, False
    while i < len(lines):
        if VERDICT_RE.match(lines[i]):
            found = True
            out.append("## Verdict")
            out.append(f"{verdict_word} - {just.get(lang_key, just['en'])}")
            j = i + 1
            while j < len(lines) and not LENIENT_HEADING_RE.match(lines[j]):
                j += 1
            i = j
        else:
            out.append(lines[i])
            i += 1
    if not found:
        _warn("no ## Verdict section found; verdict not regenerated")
    return out, found


def _append_summary_note(text, note_line):
    """Append one verification note bullet at the end of ## Summary."""
    lines = text.split("\n")
    i = 0
    found = False
    while i < len(lines):
        token = lines[i].strip().lstrip("#").strip()
        if LENIENT_HEADING_RE.match(lines[i]) and token == SUMMARY_HEADING:
            found = True
            break
        i += 1
    if not found:
        _warn("no ## Summary section found; verification note not appended")
        return text
    j = i + 1
    while j < len(lines) and not LENIENT_HEADING_RE.match(lines[j]):
        j += 1
    note = note_line.rstrip("\n")
    # Idempotency: strip any PREVIOUS verification note from the Summary
    # span before appending (re-merge on an already-merged body must not
    # stack two "[검증] ..." bullets — observed live in the smoke re-run).
    stale_prefixes = ("- [검증]", "- [Verified]")
    span = [l for l in lines[i:j]
            if not l.lstrip().startswith(stale_prefixes)]
    new = lines[:j] + [note] + lines[j:]
    return "\n".join(lines[:i] + span + [note] + lines[j:])


def merge_body(text, scores, profile="conservative", mode="enforce",
               lang=""):
    """Apply the gate to a graded body. Returns (final_text, report).

    report = {"kept": int, "demoted": int, "dropped": int, "unmatched": int,
              "dropped_records": [...], "order_fallback": bool}
    """
    lang_key = _lang_key(lang)
    lines, spans = _walk_sections(text)

    # 1. Collect bullets with positions per threaded section.
    bullets = []  # {section, start, end, text, key, priority, tagged}
    for heading, s, e in spans:
        section = EMOJI_SECTION.get(heading)
        if section is None:
            continue
        for b in _span_bullets(lines, s, e):
            key = _anchor_of(b["text"])
            priority, tagged = _bullet_priority(b["text"], section)
            bullets.append({"section": section, "start": b["start"],
                            # Deletion span stops at the first blank line
                            # (text_end); the full span is only for text
                            # assembly. Falls back to end when no blank
                            # line intervenes.
                            "end": b.get("text_end", b["end"]),
                            "text": b["text"],
                            "key": key, "priority": priority,
                            "tagged": tagged})

    # 2. Score map keyed by normalized (path, line); first occurrence
    #    wins. line_end is deliberately NOT part of the key: the plan
    #    (L90) requires line_end drift to be absorbed (the model echoing
    #    "file:2" for a "file:2-4" finding must still match).
    score_map, dup = {}, 0
    for s in scores:
        full_key = _parse_score_anchor(s["anchor"])
        if full_key is None:
            _warn(f"unparseable score anchor: {s['anchor']!r}")
            continue
        key = (full_key[0], full_key[1])
        if key in score_map:
            dup += 1
        else:
            score_map[key] = dict(s, _full_key=full_key)
    if dup:
        _warn(f"{dup} duplicate score anchor(s); first occurrence wins")

    # 3. Order-index fallback: only when the counts match exactly and
    #    anchor matching left unmatched bullets.
    # Bullet keys are also reduced to (path, line) for matching; a line_end
    # mismatch between finding and echo is a WARN, never a miss.
    def _match_key(b):
        return (b["key"][0], b["key"][1]) if b["key"] is not None else None

    anchor_matched = {i for i, b in enumerate(bullets)
                      if _match_key(b) is not None and _match_key(b) in score_map}
    order_fallback = False
    if len(scores) == len(bullets) and bullets \
            and len(anchor_matched) != len(bullets):
        order_fallback = True
        _warn("score count matches findings but anchors did not align; "
              "using order-index matching")

    # 4. Decisions.
    decisions = {}
    unmatched = 0
    for i, b in enumerate(bullets):
        # FR-1: bullets without a parseable anchor were never verification
        # targets (extract skipped them). They must survive every profile
        # untouched — the reflection pass has no say over them.
        if b["key"] is None:
            decisions[i] = ("keep", None)
            continue
        s = None
        if order_fallback:
            s = scores[i]
        elif _match_key(b) is not None and _match_key(b) in score_map:
            s = score_map[_match_key(b)]
            if b["key"][2] is not None and s.get("_full_key") \
                    and s["_full_key"][2] != b["key"][2]:
                _warn(f"line_end drift absorbed for {_anchor_str(b['key'])}")
        if s is None:
            unmatched += 1
            if profile == "conservative":
                _warn(f"unmatched finding kept (conservative): "
                      f"{b['text'][:60]!r}")
                decisions[i] = ("keep", None)
            else:
                decisions[i] = ("drop", None)
            continue
        decisions[i] = (gate_decision(b["priority"], s["score"], profile),
                        s["score"])

    # Total-parse-failure detection: the reflection pass produced scores
    # that matched NOTHING. Treat it as a failed verification (D-2) —
    # otherwise the review would be posted with a "[Verified] N kept"
    # note while no finding was actually verified (silent success).
    gate_effectively_failed = bool(bullets) and unmatched == len(bullets) \
        and not order_fallback

    # Gate statistics count only VERIFICATION TARGETS (anchor-bearing
    # findings). Anchorless bullets are kept verbatim per FR-1 but were
    # never graded — counting them would inflate the "[검증] N kept" line
    # (caught live in the dogfood smoke test: 3 kept for 1 real finding).
    kept = sum(1 for i, (d, _) in decisions.items()
               if d == "keep" and bullets[i]["key"] is not None)
    demoted = sum(1 for d, _ in decisions.values() if d == "demote")
    dropped = sum(1 for d, _ in decisions.values() if d == "drop")

    # 5. Line-level edits: deletions, tag rewrites.
    delete_marks = set()
    demote_blocks = []  # (bullet idx, [rewritten lines])
    dropped_records = []
    for i, (decision, score) in decisions.items():
        b = bullets[i]
        if decision == "drop":
            for li in range(b["start"], b["end"] + 1):
                delete_marks.add(li)
            dropped_records.append({
                "anchor": _anchor_str(b["key"]) if b["key"] is not None else "",
                "body": b["text"][:400],
                "section": b["section"],
                "priority": b["priority"],
                "score": score,
            })
        elif decision == "demote":
            block = [_rewrite_demoted_line(lines[b["start"]])]
            block += lines[b["start"] + 1:b["end"] + 1]
            demote_blocks.append((i, block))
    # A demoted bullet moves to Warnings ONLY when a Warnings span exists.
    # Without one, keep it in place (rewritten tag, no relocation) —
    # never delete without re-inserting (nothing is silently dropped).
    warnings_span_probe = next(((s, e) for h, s, e in spans
                                if h == "🟡 Warnings"), None)
    relocatable = []
    for i, block in demote_blocks:
        if warnings_span_probe is not None:
            relocatable.append((i, block))
            b = bullets[i]
            for li in range(b["start"], b["end"] + 1):
                delete_marks.add(li)
        else:
            # Keep-in-place demotion: only rewrite the tag, keep lines.
            b = bullets[i]
            lines[b["start"]] = _rewrite_demoted_line(lines[b["start"]])
    demote_blocks = relocatable

    # 6. Empty-section detection BEFORE rebuilding: a threaded section
    #    whose entire span content is marked for deletion gets a synthesized
    #    note. Pre-existing model prose (non-bullet lines inside the span)
    #    is never marked, so notes only appear when OUR drops emptied the
    #    section — model-written notes are preserved untouched.
    emptied_sections = set()
    for heading, s, e in spans:
        if EMOJI_SECTION.get(heading) is None:
            continue
        # Only non-blank surviving lines count as section content; blank
        # separators do not keep a section "alive".
        remaining = [li for li in range(s + 1, e)
                     if li not in delete_marks and lines[li].strip()]
        # Sections with NO bullets at all (model wrote a prose note) are
        # never candidates — there was nothing to drop.
        had_bullets = bool(_span_bullets(lines, s, e))
        if not remaining and had_bullets:
            emptied_sections.add(heading)
    # A section that will RECEIVE demoted bullets is not empty: drop its
    # empty-note candidacy and any model no-findings note ("없음") so the
    # section never shows both a note and live bullets (self-contradiction).
    demote_target_sections = set()
    if demote_blocks and warnings_span_probe is not None:
        demote_target_sections.add("🟡 Warnings")
        ws, we = warnings_span_probe
        # Collect no-findings note lines inside the Warnings span to
        # delete when demote blocks are inserted there.
        for li in range(ws + 1, we):
            if lines[li].strip() and not BULLET_RE.match(lines[li]):
                # Prose note (e.g. "없음", "none"): remove it to avoid
                # "no findings" + demoted bullets coexisting.
                delete_marks.add(li)
    emptied_sections -= demote_target_sections

    # 7. Single ordered rebuild: drop marked lines, insert demote blocks
    #    at the end of the Warnings span, and insert empty-section notes
    #    right after an emptied section's heading line.
    warnings_span = next(((s, e) for h, s, e in spans
                           if h == "🟡 Warnings"), None)
    out = []
    for orig_i in range(len(lines)):
        if orig_i in delete_marks:
            continue
        out.append(lines[orig_i])
        # Heading lines trigger their section's post-processing. Insert the
        # empty note ONLY for sections emptied by our drops; a section the
        # model already wrote a no-findings note under is untouched.
        m = LENIENT_HEADING_RE.match(lines[orig_i])
        token = lines[orig_i].strip().lstrip("#").strip()
        if m and token in EMOJI_SECTION:
            if token in emptied_sections:
                # Prose line, not a bullet: must never become an inline
                # thread candidate downstream.
                out.append(EMPTY_SECTION_NOTES[lang_key])
    # Insert demoted blocks at each threaded span end (in span order).
    if demote_blocks:
        if warnings_span is None:
            # Unreachable: keep-in-place handling above guarantees
            # demote_blocks is empty when there is no Warnings span.
            _warn("no Warnings section found; demoted bullets kept in "
                  "place (tag rewritten only)")
        else:
            block_all = []
            for _i, block in demote_blocks:
                block_all.extend(block)
            # warnings_span indices refer to the ORIGINAL line array.
            # Map the original span end (next heading's line index, or
            # EOF) onto the rebuilt `out` array: walk `out` counting
            # non-deleted original lines until we pass the span end.
            ws, we = warnings_span
            # Number of surviving original lines strictly before the span
            # end equals the insert position in `out`.
            survivors_before = sum(1 for oi in range(we)
                                   if oi not in delete_marks)
            out = out[:survivors_before] + block_all + out[survivors_before:]

    # 8. Verdict regeneration + Summary note.
    blocking_alive = False
    # Recompute from the FINAL merged line array (`out`): a Blocking span
    # bullet with [P0]/[P1] (or legacy untagged high-priority bullet) —
    # but ONLY if it carries a parseable file:line anchor. FR-1: an
    # anchorless bullet (e.g. the model's "발견 사항 없음" note written as a
    # bullet) was never a verification target and must never count as a
    # blocking claim, or the verdict contradicts the body ("no findings"
    # section + REQUEST_CHANGES — caught live in the dogfood smoke test).
    final_spans = _rebuild_spans(out)
    for h, s, e in final_spans:
        if h != "🔴 Blocking Issues":
            continue
        for b in _span_bullets(out, s, e):
            if _anchor_of(b["text"]) is None:
                # Anchorless prose bullets are not blocking claims.
                continue
            priority, _ = _bullet_priority(b["text"], "BLOCKING")
            if priority == "high":
                blocking_alive = True
                break
    out, _found_verdict = _regenerate_verdict(out, blocking_alive, lang_key)

    stats_note = (f"- [검증] {kept}건 유지 / {demoted}건 강등 / "
                  f"{dropped}건 제외 — 제외된 파인딩 상세는 CI 로그를 확인하세요."
                  if lang_key == "ko" else
                  f"- [Verified] {kept} kept / {demoted} demoted / "
                  f"{dropped} dropped — see the CI log for dropped findings.")
    body = "\n".join(out)
    if mode == "enforce":
        if gate_effectively_failed:
            # D-2 fail-open: the parse "succeeded" but matched nothing —
            # post the ORIGINAL review with the fail-open banner instead
            # of a misleading "[Verified] N kept" note.
            banner = FAILOPEN_BANNERS[lang_key] + \
                " (no score matched any finding)"
            original = truncate_body(text)
            final_text = banner + "\n\n" + original
        else:
            body = _append_summary_note(body, stats_note)
            final_text = truncate_body(body)
    else:  # shadow: gate outcomes recorded only; body stays untouched
        final_text = truncate_body(text)

    report = {"kept": kept, "demoted": demoted, "dropped": dropped,
              "unmatched": unmatched, "order_fallback": order_fallback,
              "gate_effectively_failed": gate_effectively_failed,
              "dropped_records": dropped_records}
    return final_text, report


def _rebuild_spans(lines):
    spans = []
    cur = None
    for i, raw in enumerate(lines):
        m = LENIENT_HEADING_RE.match(raw)
        token = raw.strip().lstrip("#").strip()
        if m and token in KNOWN_SECTIONS:
            if cur is not None:
                spans.append((cur[0], cur[1], i))
            cur = (token, i)
    if cur is not None:
        spans.append((cur[0], cur[1], len(lines)))
    return spans


def cmd_merge(args):
    body = Path(args.body).read_text(encoding="utf-8", errors="ignore")
    body = ANSI_RE.sub("", body)
    scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    final_text, report = merge_body(body, scores,
                                    profile=args.profile,
                                    mode=args.mode,
                                    lang=getattr(args, "lang", "") or "")

    if args.out_final:
        Path(args.out_final).write_text(final_text, encoding="utf-8")
    if args.out_dropped:
        Path(args.out_dropped).write_text(
            json.dumps(report, ensure_ascii=False, indent=1),
            encoding="utf-8")
    print(f"merge: {report['kept']} kept / {report['demoted']} demoted / "
          f"{report['dropped']} dropped / {report['unmatched']} unmatched")
    return 0


def cmd_banner(args):
    """Emit the fail-open banner line for --lang (used by CI templates)."""
    print(FAILOPEN_BANNERS[_lang_key(args.lang)])
    return 0


def cmd_hunks(args):
    """Emit diff hunks trimmed around each finding's citation (±context).

    The reflection prompt must NOT re-inject the full diff (the first pass
    already had it); this keeps the token budget bounded while still
    giving the verifier the exact code around every citation.
    """
    import inline_threads as it

    diff_text = Path(args.diff).read_text(encoding="utf-8", errors="ignore")
    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    ctx = max(0, args.context)

    # Collect per-file (line ranges) to trim from a full-diff walk.
    targets = {}  # path -> set of line numbers to keep around
    for f in findings:
        m = re.match(r"^\s*([^\s:]+):(\d+)(?:-(\d+))?\s*$", f.get("anchor", ""))
        if not m:
            continue
        path = normalize_path(m.group(1))
        line = int(m.group(2))
        end = int(m.group(3)) if m.group(3) else line
        if not path:
            continue
        targets.setdefault(path, set()).update(range(line - ctx, end + ctx + 1))

    out_lines = []
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
            m = it.HUNK_RE.match(raw)
            if m and cur_path and cur_path in targets:
                new_start = int(m.group(1))
                new_count = int(m.group(2) or 1)
                seen = 0
                in_hunk = True
                out_lines.append(f"### {cur_path} @@ {raw}")
            else:
                in_hunk = False
            continue
        if not in_hunk or cur_path is None:
            continue
        if seen >= new_count:
            in_hunk = False
            continue
        if raw.startswith("+") or raw.startswith(" "):
            line_no = new_start + seen
            if line_no in targets[cur_path]:
                out_lines.append(raw)
            seen += 1
            if seen >= new_count:
                in_hunk = False
    Path(args.out).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def _e2e(final_text, diff_text):
    """FR-7: merged output must survive inline_threads.prepare parsing."""
    import inline_threads as it
    clean, bullets = it.split_threads(final_text)
    assert isinstance(clean, str) and isinstance(bullets, list)
    anchors = it.parse_diff_anchors_with_content(diff_text)
    clean2, comments = it.validate_and_anchor(clean, bullets, anchors)
    return clean2, comments


SAMPLE_DIFF = (
    "diff --git a/src/a.py b/src/a.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -1,4 +1,5 @@\n"
    " import os\n"
    "+x = 1\n"
    " \n"
    " def main():\n"
    "     pass\n"
)

SAMPLE_BODY = (
    "## Summary\n전반적으로 구조가 좋습니다.\n"
    "\n"
    "## 🔴 Blocking Issues\n"
    "- `src/a.py:2` [P0] x 변수가 상수로 덮어써집니다.\n"
    "- `src/a.py:3` [P1] 공백 라인이 잘못되었습니다.\n"
    "\n"
    "## 🟡 Warnings\n"
    "- `src/a.py:4` [P2] `main`에 docstring이 없습니다.\n"
    "\n"
    "## 🟢 Suggestions\n"
    "- `src/a.py:5` [nit] pass 대신 구현을 권장합니다.\n"
    "\n"
    "## ✅ Highlights\n"
    "- 커밋 구조가 깔끔합니다.\n"
    "\n"
    "## Verdict\n"
    "REQUEST_CHANGES - 차단 이슈 2건.\n"
)


def _selftest():
    # --- extract ---------------------------------------------------------
    body = ANSI_RE.sub("", SAMPLE_BODY)
    findings = extract_findings(body)
    assert len(findings) == 4, findings
    assert findings[0]["anchor"] == "src/a.py:2"
    assert findings[0]["priority"] == "high"
    assert findings[0]["section"] == "BLOCKING"
    assert findings[2]["priority"] == "medium"
    assert findings[3]["priority"] == "low"
    # legacy bullet (no P-tag) falls back by section
    legacy = ("## Summary\n\n## 🔴 Blocking Issues\n"
              "- `src/a.py:2` legacy 태그 없는 불릿.\n\n"
              "## 🟡 Warnings\n없음\n\n## 🟢 Suggestions\n없음\n\n"
              "## ✅ Highlights\n- 좋음\n\n## Verdict\nAPPROVE.\n")
    lf = extract_findings(ANSI_RE.sub("", legacy))
    assert lf and lf[0]["priority"] == "high", lf

    # --- reflect-parse ---------------------------------------------------
    good = (
        "## Reflection\n```json\n"
        '{"findings":[{"anchor":"src/a.py:2","score":8,"why":"confirmed"},'
        '{"anchor":"src/a.py:3","score":"5.0","why":"plausible"},'
        '{"anchor":"src/a.py:4","score":2,"why":"refuted"}]}\n'
        "```\n"
    )
    scores, errs = parse_reflection(good)
    assert scores is not None and len(scores) == 3, (scores, errs)
    assert not errs
    assert scores[1]["score"] == 5.0  # string coerced
    # prose around fences, unlabeled fence
    prose = ("Some preamble text.\n## Reflection\n아래는 결과입니다.\n"
             "```\n[{\"anchor\":\"src/a.py:2\",\"score\":9}]\n```\n"
             "closing remarks")
    scores, errs = parse_reflection(prose)
    assert scores is not None and len(scores) == 1, (scores, errs)
    # no sentinel -> None
    scores, errs = parse_reflection("no sentinel here")
    assert scores is None
    # brace fallback when fence missing
    bf = "## Reflection\n{\"findings\":[{\"anchor\":\"src/a.py:2\",\"score\":7}]}"
    scores, errs = parse_reflection(bf)
    assert scores is not None and len(scores) == 1
    assert any("fallback" in e for e in errs), errs
    # out-of-range score ignored
    oor = ("## Reflection\n```json\n"
           '{"findings":[{"anchor":"src/a.py:2","score":42},'
           '{"anchor":"src/a.py:3","score":3}]}\n```')
    scores, errs = parse_reflection(oor)
    assert scores is not None and len(scores) == 1, scores
    assert errs, "expected a WARN for the out-of-range score"
    # why with triple backticks must not break fence extraction (fence
    # regex uses the FIRST ```json fence; inner ticks only appear in why)
    tricky_why = ("## Reflection\n```json\n"
                  '{"findings":[{"anchor":"src/a.py:2","score":8,'
                  '"why":"see ```code``` block"}]}\n```')
    scores, errs = parse_reflection(tricky_why)
    assert scores is not None and len(scores) == 1, (scores, errs)
    # duplicate anchors preserved (merge applies first-wins)
    dup = ("## Reflection\n```json\n"
           '{"findings":[{"anchor":"src/a.py:2","score":1},'
           '{"anchor":"src/a.py:2","score":9}]}\n```')
    scores, errs = parse_reflection(dup)
    assert len(scores) == 2
    # ANSI pollution is stripped
    ansi = ("\x1b[31m## Reflection\x1b[0m\n```json\n"
            '{"findings":[{"anchor":"src/a.py:2","score":8}]}\n```')
    scores, errs = parse_reflection(ansi)
    assert scores is not None and len(scores) == 1, (scores, errs)

    # --- merge: keep / demote / drop -------------------------------------
    sc_keep_all = [{"anchor": a, "score": 9, "why": ""} for a in
                   ("src/a.py:2", "src/a.py:3", "src/a.py:4", "src/a.py:5")]
    final, rep = merge_body(SAMPLE_BODY, sc_keep_all, "conservative",
                            "enforce", "Korean")
    assert rep["kept"] == 4 and rep["dropped"] == 0, rep
    assert "REQUEST_CHANGES" in final
    # P0/P1 demote at 4-6: moved to Warnings, retagged [P2]
    sc_demote = [
        {"anchor": "src/a.py:2", "score": 5, "why": ""},
        {"anchor": "src/a.py:3", "score": 9, "why": ""},
        {"anchor": "src/a.py:4", "score": 9, "why": ""},
        {"anchor": "src/a.py:5", "score": 9, "why": ""},
    ]
    final, rep = merge_body(SAMPLE_BODY, sc_demote, "conservative",
                            "enforce", "Korean")
    assert rep["demoted"] == 1, rep
    w = final.split("## 🟡 Warnings")[1].split("##")[0]
    assert "[P2]" in w and "x 변수가" in w, final
    assert "src/a.py:2" not in final.split("## 🟡 Warnings")[0].split(
        "## 🔴 Blocking Issues")[1], "demoted bullet must leave Blocking"
    assert "src/a.py:3" in final  # kept P1 stays
    assert "REQUEST_CHANGES" in final  # one P1 survives
    # P0 dropped at <=3 + all blockings gone -> verdict flips to APPROVE
    sc_drop_all = [
        {"anchor": "src/a.py:2", "score": 2, "why": "refuted"},
        {"anchor": "src/a.py:3", "score": 1, "why": "refuted"},
        {"anchor": "src/a.py:4", "score": 9, "why": ""},
        {"anchor": "src/a.py:5", "score": 9, "why": ""},
    ]
    final, rep = merge_body(SAMPLE_BODY, sc_drop_all, "conservative",
                            "enforce", "Korean")
    assert rep["dropped"] == 2, rep
    assert "APPROVE" in final and "REQUEST_CHANGES" not in final
    # dash-less 'APPROVE.' verdict form is regenerated cleanly
    dotted = SAMPLE_BODY.replace("REQUEST_CHANGES - 차단 이슈 2건.",
                                 "APPROVE.")
    final2, rep2 = merge_body(dotted, sc_drop_all, "conservative",
                             "enforce", "Korean")
    assert "## Verdict\nAPPROVE - " in final2, final2
    assert final2.count("APPROVE.") == 0, "dotted form must be replaced"
    # empty Blocking section note (ko) synthesized, Highlights intact
    assert "검증 단계에서" in final, "empty-section note missing"
    assert "커밋 구조가 깔끔합니다" in final
    # Summary verification note appended exactly once
    assert final.count("[검증]") == 1, final

    # --- merge: unmatched ------------------------------------------------
    sc_partial = [{"anchor": "src/a.py:2", "score": 9, "why": ""}]
    final, rep = merge_body(SAMPLE_BODY, sc_partial, "conservative",
                            "enforce", "Korean")
    assert rep["unmatched"] == 3, rep
    # conservative unmatched policy: unmatched findings are KEPT, so all
    # 4 bullets survive (1 matched keep + 3 unmatched keeps).
    assert rep["kept"] == 4 and rep["dropped"] == 0, rep
    final, rep = merge_body(SAMPLE_BODY, sc_partial, "strict", "enforce",
                            "Korean")
    assert rep["unmatched"] == 3 and rep["dropped"] >= 3, rep

    # --- merge: order-index fallback -------------------------------------
    sc_order = [{"anchor": "wrong/path.py:1", "score": 9},
               {"anchor": "wrong/path.py:2", "score": 9},
               {"anchor": "wrong/path.py:3", "score": 9},
               {"anchor": "wrong/path.py:4", "score": 9}]
    final, rep = merge_body(SAMPLE_BODY, sc_order, "conservative",
                            "enforce", "Korean")
    assert rep["order_fallback"] is True, rep
    assert rep["kept"] == 4

    # --- merge: strict profile thresholds --------------------------------
    sc_strict = [
        {"anchor": "src/a.py:2", "score": 7, "why": ""},   # high 7 -> demote
        {"anchor": "src/a.py:3", "score": 4, "why": ""},   # high 4 -> drop
        {"anchor": "src/a.py:4", "score": 5, "why": ""},   # medium 5 -> demote
        {"anchor": "src/a.py:5", "score": 3, "why": ""},   # low 3 -> drop
    ]
    final, rep = merge_body(SAMPLE_BODY, sc_strict, "strict", "enforce",
                            "Korean")
    assert rep["demoted"] == 2 and rep["dropped"] == 2, rep
    assert "APPROVE" in final  # both blockers gone

    # --- merge: shadow mode ----------------------------------------------
    final, rep = merge_body(SAMPLE_BODY, sc_drop_all, "conservative",
                            "shadow", "Korean")
    assert "REQUEST_CHANGES - 차단 이슈 2건." in final
    assert rep["dropped"] == 2, "shadow must still record gate outcomes"
    assert "[검증]" not in final

    # --- merge: empty findings + empty scores -----------------------------
    empty_body = ("## Summary\n문제 없음.\n\n## 🔴 Blocking Issues\n없음\n\n"
                  "## 🟡 Warnings\n없음\n\n## 🟢 Suggestions\n없음\n\n"
                  "## ✅ Highlights\n- 좋음\n\n## Verdict\nAPPROVE.\n")
    final, rep = merge_body(empty_body, [], "conservative", "enforce",
                            "Korean")
    assert rep["kept"] == 0 and rep["dropped"] == 0
    assert "APPROVE" in final

    # --- e2e: merged final must re-parse through inline_threads -----------
    final, rep = merge_body(SAMPLE_BODY, sc_drop_all, "conservative",
                            "enforce", "Korean")
    clean2, comments = _e2e(final, SAMPLE_DIFF)
    assert "APPROVE" in final
    # The kept warnings/suggestions bullets still anchor to the diff.
    assert any(c["path"] == "src/a.py" for c in comments), comments
    # A fully-dropped Blocking section keeps the synthesized note, which
    # must not break prepare's bullet parsing.
    assert "검증 단계에서" in final

    # --- 55k clamp --------------------------------------------------------
    big = "## Summary\n" + ("설명 " * 40000) + "\n\n" + SAMPLE_BODY.split(
        "## Summary\n", 1)[1]
    final, rep = merge_body(big, sc_drop_all, "conservative", "enforce",
                            "Korean")
    assert len(final) <= 55000 + 200, len(final)

    # --- legacy bullets: demote adds [P2] prefix; verdict counts legacy ---
    legacy_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` legacy 차단 불릿.\n"
        "\n## 🟡 Warnings\n없음\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES - legacy 차단.\n"
    )
    sc_leg = [{"anchor": "src/a.py:2", "score": 5, "why": ""}]
    final, rep = merge_body(legacy_body, sc_leg, "conservative", "enforce",
                            "Korean")
    assert rep["demoted"] == 1, rep
    assert "[P2] `src/a.py:2`" in final, final
    assert "REQUEST_CHANGES" not in final, \
        "demoted legacy blocker must flip the verdict to APPROVE"
    assert "APPROVE" in final

    # --- tag before/after citation both anchor downstream ---------------
    body_post_tag = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` 태그 뒤 인용 불릿.\n"
        "\n## 🟡 Warnings\n없음\n\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_pt = [{"anchor": "src/a.py:2", "score": 5, "why": ""}]
    final, rep = merge_body(body_post_tag, sc_pt, "conservative",
                            "enforce", "Korean")
    w2 = final.split("## 🟡 Warnings")[1].split("## 🟢")[0]
    assert "[P2] `src/a.py:2`" in w2, final
    clean2, comments = _e2e(final, SAMPLE_DIFF)
    assert any(c["path"] == "src/a.py" and c["line"] == 2 for c in comments), \
        comments

    # --- existing model note under an emptied section is preserved --------
    noted_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` 드랍될 파인딩.\n"
        "\n"
        "이 섹션은 모델이 쓴 노트입니다.\n"
        "\n## 🟡 Warnings\n없음\n\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_note = [{"anchor": "src/a.py:2", "score": 1, "why": ""}]
    final, rep = merge_body(noted_body, sc_note, "conservative",
                            "enforce", "Korean")
    assert rep["dropped"] == 1
    assert "이 섹션은 모델이 쓴 노트입니다" in final, \
        "pre-existing model note must survive"
    assert "검증 단계에서" not in final, \
        "no empty-note when the model note keeps the section non-empty"

    # --- review-regression: demote without a Warnings section (MAJOR-1)
    nowarn_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` 강등될 차단.\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_nw = [{"anchor": "src/a.py:2", "score": 5, "why": ""}]
    final, rep = merge_body(nowarn_body, sc_nw, "conservative", "enforce",
                            "Korean")
    assert rep["demoted"] == 1, rep
    assert "`src/a.py:2`" in final and "[P2]" in final, \
        "keep-in-place demotion must retain the bullet (never silently lost)"

    # --- review-regression: empty Warnings + demote (MAJOR-2, test E) ---
    emptywarn_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` [P1] 강등 대상.\n"
        "\n## 🟡 Warnings\n"
        "- `src/a.py:4` [P2] 드랍될 경고.\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_ew = [{"anchor": "src/a.py:2", "score": 5, "why": ""},
             {"anchor": "src/a.py:4", "score": 1, "why": ""}]
    final, rep = merge_body(emptywarn_body, sc_ew, "conservative", "enforce",
                            "Korean")
    w_sec = final.split("## 🟡 Warnings")[1].split("## 🟢")[0]
    assert "`src/a.py:2` [P2]" in w_sec, final
    assert "검증 단계에서" not in w_sec, \
        "section receiving demoted bullets must not carry the empty note"

    # --- review-regression: '없음' note removed when demote lands (test 1) ---
    nonote_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` [P1] 강등 대상.\n"
        "\n## 🟡 Warnings\n없음\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    final, rep = merge_body(nonote_body, sc_ew, "conservative", "enforce",
                            "Korean")
    w_sec = final.split("## 🟡 Warnings")[1].split("## 🟢")[0]
    assert "`src/a.py:2` [P2]" in w_sec, final
    assert "없음" not in w_sec, \
        "the no-findings note must be removed when demoted bullets land"

    # --- review-regression: anchorless bullet survives strict (MAJOR-3) ---
    anchorless_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- 전반적인 에러 핸들링 부재(인용 없음).\n"
        "\n## 🟡 Warnings\n없음\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    final, rep = merge_body(anchorless_body, [], "strict", "enforce",
                            "Korean")
    assert "전반적인 에러 핸들링 부재" in final, \
        "FR-1: anchorless bullets are not verification targets and must " \
        "survive every profile"

    # --- review-regression: line_end drift absorbed (MAJOR-5, test Q) ------
    drift_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2-4` [P1] 범위 파인딩.\n"
        "\n## 🟡 Warnings\n없음\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_drift = [{"anchor": "src/a.py:2", "score": 9, "why": ""},
                {"anchor": "src/a.py:2-9", "score": 9, "why": ""}]
    final, rep = merge_body(drift_body, sc_drift, "strict", "enforce",
                            "Korean")
    assert rep["unmatched"] == 0, rep
    assert "`src/a.py:2-4`" in final, \
        "line_end drift must be absorbed (plan L90)"

    # --- review-regression: dropped_records carry the real anchor ---------
    sc_drop1 = [{"anchor": "src/a.py:2", "score": 1, "why": ""}]
    final, rep = merge_body(SAMPLE_BODY, sc_drop1, "conservative",
                            "enforce", "Korean")
    rec = rep["dropped_records"][0]
    assert rec["anchor"] == "src/a.py:2", rec
    assert rec["anchor"].startswith("`") is False, rec

    # --- review-regression: blank-line-separated anchor bullet still
    # extracts (parser parity with inline_threads, MAJOR-4, test F) --------
    split_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- `src/a.py:2` [P0] 첫 문장.\n"
        "이어지는 설명.\n"
        "\n"
        "별도 산문 노트.\n"
        "\n## 🟡 Warnings\n없음\n"
        "\n## 🟢 Suggestions\n없음\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    fnd = extract_findings(split_body)
    assert len(fnd) == 1 and fnd[0]["anchor"] == "src/a.py:2", fnd
    assert "이어지는 설명" in fnd[0]["body"], fnd
    sc_split = [{"anchor": "src/a.py:2", "score": 1, "why": ""}]
    final, rep = merge_body(split_body, sc_split, "conservative", "enforce",
                            "Korean")
    assert "별도 산문 노트" in final, "independent prose must survive the drop"
    assert "첫 문장" not in final.split("별도 산문 노트")[0], \
        "dropped bullet must be removed (with its continuation text)"

    # --- review-regression: total score mismatch -> fail-open banner ------
    garbage_body = SAMPLE_BODY
    sc_garbage = [{"anchor": "totally/other.py:1", "score": 9, "why": ""}]
    final, rep = merge_body(garbage_body, sc_garbage, "conservative",
                            "enforce", "Korean")
    assert rep["gate_effectively_failed"] is True, rep
    assert "검증 미적용" in final, \
        "a parse that matched nothing must fail open, not post a " \
        "misleading [Verified] note"
    assert "[검증]" not in final

    # --- dogfood smoke regression: anchorless no-findings bullets -----
    # Live failure (PR #13 smoke): the model wrote its "발견 사항 없음"
    # notes as bullets; the verdict flip claimed a blocking issue and the
    # stats line said "3 kept" for a single real finding. Both fixed:
    # anchorless bullets neither block nor inflate the gate statistics.
    nofind_body = (
        "## Summary\n요약.\n"
        "\n## 🔴 Blocking Issues\n"
        "- 발견 사항 없음. 영향이 없습니다.\n"
        "\n## 🟡 Warnings\n"
        "- 발견 사항 없음. 위험 요소가 없습니다.\n"
        "\n## 🟢 Suggestions\n"
        "- `src/a.py:2` [nit] 진짜 파인딩.\n"
        "\n## ✅ Highlights\n- 좋음\n"
        "\n## Verdict\nREQUEST_CHANGES.\n"
    )
    sc_nf = [{"anchor": "src/a.py:2", "score": 9, "why": ""}]
    final, rep = merge_body(nofind_body, sc_nf, "conservative", "enforce",
                            "Korean")
    assert rep["kept"] == 1, rep  # only the anchor-bearing finding
    assert "1건 유지" in final, final
    assert "APPROVE" in final and "REQUEST_CHANGES" not in final, \
        "anchorless no-findings bullets must never keep the verdict " \
        "at REQUEST_CHANGES (body/verdict self-contradiction)"

    # --- re-merge idempotency: no stacked [검증] notes ------------------
    final2, rep2 = merge_body(final, sc_nf, "conservative", "enforce",
                              "Korean")
    assert final2.count("[검증]") == 1, \
        "re-merging an already-merged body must not stack verification notes"

    print("selftest: all checks passed")
    return 0


def main():
    ap = argparse.ArgumentParser(description="CodeGoose verification gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract")
    e.add_argument("--body", required=True)
    e.add_argument("--out", required=True)
    e.set_defaults(func=cmd_extract)

    r = sub.add_parser("reflect-parse")
    r.add_argument("--raw", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=cmd_reflect_parse)

    m = sub.add_parser("merge")
    m.add_argument("--body", required=True)
    m.add_argument("--scores", required=True)
    m.add_argument("--profile", default="conservative",
                   choices=["conservative", "strict"])
    m.add_argument("--mode", default="enforce",
                   choices=["enforce", "shadow"])
    m.add_argument("--out-final", required=True)
    m.add_argument("--out-dropped", required=True)
    m.add_argument("--lang", default="")
    m.set_defaults(func=cmd_merge)

    h = sub.add_parser("hunks")
    h.add_argument("--diff", required=True)
    h.add_argument("--findings", required=True)
    h.add_argument("--out", required=True)
    h.add_argument("--context", type=int, default=5,
                   help="context lines around each citation")
    h.set_defaults(func=cmd_hunks)

    b = sub.add_parser("banner")
    b.add_argument("--lang", default="")
    b.set_defaults(func=cmd_banner)

    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return _selftest()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())