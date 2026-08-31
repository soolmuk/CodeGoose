<h1 align="center">
  <img src="assets/codegoose-icon.png" alt="CodeGoose" width="96" /><br />
  CodeGoose
</h1>

<p align="center">
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <strong>AI code review, driven by goose recipes</strong><br/>
  Read the PR · grade the findings · verify them · wire it into CI — from one repo.
</p>

<p align="center">
  <a href="https://github.com/soolmuk/CodeGoose/stargazers"><img src="https://img.shields.io/github/stars/soolmuk/CodeGoose?style=social" alt="Stars" /></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0" /></a>
  &nbsp;
  <img src="https://img.shields.io/badge/platform-GitHub%20·%20GitLab%20·%20Gitea%20·%20TeamCity-2088FF?logo=githubactions&logoColor=white" alt="Platforms" />
</p>

<p align="center">
  <a href="#-quick-start"><img src="assets/nav-quick-start.svg" alt="Quick Start" height="28" /></a>
  &nbsp;&nbsp;
  <a href="#-recipes"><img src="assets/nav-recipes.svg" alt="Recipes" height="28" /></a>
</p>

---

## Why CodeGoose

| Feature | What it means |
|---|---|
| **Graded reviews** | Findings land as Blocking, Warning, Suggestion, or Highlight — plus a final Verdict. Structured JSON, ready to automate. |
| **Verification gate** | A second reflection pass re-checks every finding before posting; refuted findings are dropped, weak blockers demoted, the verdict recomputed. Shadow mode measures first. |
| **Deterministic CI** | The model never writes your workflow YAML. Templates get parameters filled in, then a script verifies the result. |
| **Four platforms** | GitHub, GitLab, Gitea, or TeamCity. Same pipeline — pick from dropdowns. |
| **Safe posting** | Session banners and tool logs stay off the PR. Only the final review is posted; empty output fails the job. |

This repository is the **source of truth** for CodeGoose recipes, templates, and render scripts.
Generated CI files are artifacts — do not hand-edit them. Improvements go into the recipe/templates, then you re-run.

## How it works

<details open>
<summary><strong>Review pipeline — runs in CI on every PR</strong></summary>

```text
 pull request event
         │
         ▼
  ⚙️  gather PR diff + metadata          (shell: gh pr diff / pr view)
         │
         ▼
  ( O)>  1ST PASS — goose writes the graded review       [LLM call 1 of 2]
         ([P0]–[nit] priority tags, file:line anchors)
         │
         ▼
  ⚙️  extract — verify_findings.py → findings.json
      (anchored findings only; the rest stays in prose, untouched)
         │
         ▼
  ( O)>  REFLECTION PASS — goose re-checks every finding  [LLM call 2 of 2]
         (0–10 validity score, falsification-framed prompt)
    ↳ parse failure → 1 corrective retry → fail-open banner
         │
         ▼
  ⚙️  merge gate — deterministic 2D matrix, no LLM
      (keep / demote → [P2] / drop, verdict recomputed,
       dropped findings → dropped.json artifact)
         │
         ▼
  ⚙️  prepare — anchor every finding to diff lines
      + 55,000-char clamp (UTF-8-safe)
         │
         ▼
  🚀  post — inline comments + summary review
      + "[Verified] N kept / M demoted / K dropped" stats line
```

</details>

<details>
<summary><strong>Setup pipeline — run once per repo via the recipe</strong></summary>

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│ ( O)> setup     │────▶│  scripts/render  │────▶│  CI config artifact │
│  recipe         │     │  + templates/    │     │ (do not hand-edit)  │
│  (goose driver) │     │ (deterministic)  │     │                     │
└─────────────────┘     └──────────────────┘     └─────────────────────┘
                                   │
                                   ▼
                        ⚙️ scripts/verify.py (PASS/FAIL)
```

- **Source of truth:** recipe YAML, `templates/`, `scripts/`, shared instructions
- **Artifacts:** `.github/workflows/*`, `.gitlab-ci.yml`, Gitea/TeamCity configs, etc.
- Artifact defects → fix templates/scripts in this repo, then **re-run the recipe**

The recipe run itself is goose-driven `( O)>`, but every byte of the rendered
CI config comes from `render.py` ⚙️ — the LLM never authors your workflow.

</details>

> **Legend:** `( O)>` goose (LLM agent) steps · ⚙️ deterministic scripts · 🚀 CI posts to the forge.
>
> **goose intervenes exactly twice per review** — the two `( O)>` steps above.
> Everything between and after them is deterministic Python: the same
> `findings.json` always yields the same merge decisions, independent of
> model mood. The two LLM steps share exactly one provider key, one model,
> one config.

Official reference: [goose CI/CD tutorial](https://goose-docs.ai/docs/tutorials/cicd)

---

## ✨ Quick Start

### 1) Launch from goose Desktop

> **One click → goose Desktop.** The badge opens a small GitHub Pages page
> that immediately fires the official `goose://` deep link. (GitHub.com
> strips custom URL schemes from rendered Markdown, so a raw `goose://`
> link inside this README would be a dead link there.) If the auto-launch
> is blocked, use the Launch button on that page or the fallback below.

Click a badge — goose Desktop starts automatically:

<table>
<tr>
<td width="50%" valign="top">

[![PR Code Review — Launch In Desktop](assets/launch-pr-review.svg)](https://soolmuk.github.io/CodeGoose/launch.html#pr-review)

Grade a locally downloaded PR diff.

**Flow:** Trust → enter `pr_directory` → read-only review

</td>
<td width="50%" valign="top">

[![CI Setup — Launch In Desktop](assets/launch-ci-setup.svg)](https://soolmuk.github.io/CodeGoose/launch.html#ci-setup)

Install or refresh the CodeGoose review pipeline.

**Flow:** pick platform · language · style · LLM · model → run the render pipeline

</td>
</tr>
</table>

Deep Links use the official `goose://recipe?config=...` format.
The first run shows a **Trust & Execute** prompt; you won't be asked again
unless the recipe changes.

<details>
<summary><strong>Deep link not working? Manual fallback (click to expand)</strong></summary>

Copy one of these links into your browser's address bar, press <kbd>Enter</kbd>,
then confirm **Open Goose.app**:

<!-- codegoose-deeplink:review -->
```text
goose://recipe?config=eyJ2ZXJzaW9uIjoiMS4wLjAiLCJ0aXRsZSI6IkNvZGVHb29zZSBQUiBSZXZpZXciLCJkZXNjcmlwdGlvbiI6IlJldmlldyBhIGRvd25sb2FkZWQgR2l0SHViIHB1bGwgcmVxdWVzdCBkaWZmIGZvciBjb3JyZWN0bmVzcyBidWdzLCBzZWN1cml0eSBpc3N1ZXMsIHBlcmZvcm1hbmNlIHByb2JsZW1zLCBhbmQgZGVzaWduIGZsYXdzLCB0aGVuIHdyaXRlIGEgZ3JhZGVkIHJldmlldyAoQmxvY2tpbmcgLyBXYXJuaW5nIC8gU3VnZ2VzdGlvbiAvIEhpZ2hsaWdodCkgd2l0aCBhIGZpbmFsIHZlcmRpY3QuXG4iLCJwcm9tcHQiOiJSZXZpZXcgdGhlIGNvZGUgY2hhbmdlcyBkb3dubG9hZGVkIGZyb20gYSBHaXRIdWIgcHVsbCByZXF1ZXN0LlxuVGhlIFBSIG1ldGFkYXRhIGlzIGxvY2F0ZWQgYXQge3sgcHJfZGlyZWN0b3J5IH19L3ByLm1kLlxuVGhlIHByb3Bvc2VkIGRpZmYgeW91IGFyZSB0byByZXZpZXcgaXMgbG9jYXRlZCBhdCB7eyBwcl9kaXJlY3RvcnkgfX0vcHIuZGlmZi5cblRoZSBiYXNlIGJyYW5jaCBpcyBjaGVja2VkIG91dCBpbiB0aGUgd29ya2luZyBkaXJlY3RvcnkuXG5Vc2UgdGhlIHRvb2xzIHlvdSBoYXZlIHRvIHJlYWQgdGhlIGRpZmYgYW5kIGV4YW1pbmUgc3Vycm91bmRpbmcgY29kZSBmb3IgY29udGV4dC5cblxuIyMgUmV2aWV3IHNjb3BlXG4tIENvcnJlY3RuZXNzIGJ1Z3MsIHNlY3VyaXR5IGlzc3VlcywgcGVyZm9ybWFuY2UgcHJvYmxlbXMsIGRlc2lnbiBmbGF3cy5cbi0gQmUgcHJlY2lzZSBhbmQgY29uY3JldGU7IGNpdGUgZXhhY3QgZmlsZSBwYXRocyAvIGxpbmUgbnVtYmVycyBhbmQgZXhwbGFpbiB0aGUgZmFpbHVyZSBtb2RlLlxuLSBFdmFsdWF0ZSBuZWNlc3NpdHk6IGNvdWxkIGV4aXN0aW5nIGZ1bmN0aW9ucy90eXBlcyBiZSBleHRlbmRlZCBpbnN0ZWFkIG9mIGFkZGluZyBuZXcgY29kZT9cbiAgU2VhcmNoIHRoZSBjb2RlYmFzZSAoZS5nLiB3aXRoIHJpcGdyZXApIGJlZm9yZSBjbGFpbWluZyBzb21ldGhpbmcgaXMgbWlzc2luZy5cbi0gRHVwbGljYXRpb24gYW5kIHNoYWRvdyBzdGF0ZTogaXMgdGhlcmUgYSBzaW5nbGUgc291cmNlIG9mIHRydXRoP1xuLSBTaWxlbnQgZXJyb3IgcGF0aHMgKGRlZmF1bHQgdmFsdWVzIGhpZGluZyBlcnJvcnMpLCB1bmhhbmRsZWQgUmVzdWx0IHJldHVybnMsXG4gIHJlc291cmNlIGxpZmVjeWNsZSAoaGFuZGxlcy90aHJlYWRzIG5vdCBjbG9zZWQgb24gYWxsIHBhdGhzKSwgY29uY3VycmVuY3kgaGF6YXJkcy5cbi0gQ29tbWVudHMgdGhhdCByZXN0YXRlIGNvZGUgb3IgYXJlIHdyb25nOyBUT0RPcyB3aXRob3V0IG93bmVycy5cbi0gVGVzdHMgdGhhdCBzZXQgZW52IHZhcnMgb3IgZG8gbm90IHRlc3QgcmVhbCBiZWhhdmlvci5cblxuIyMgQW50aS1oYWxsdWNpbmF0aW9uIHJ1bGVzXG4tIFNlYXJjaCBiZWZvcmUgY2xhaW1pbmcgc29tZXRoaW5nIGlzIFwibWlzc2luZ1wiLlxuLSBTYXkgXCJJIGNvdWxkbid0IHZlcmlmeVwiIHJhdGhlciB0aGFuIGFzc2VydGluZyBzb21ldGhpbmcgaXMgd3JvbmcuXG4tIDMgdmVyaWZpZWQgaXNzdWVzIGFyZSBiZXR0ZXIgdGhhbiAxNSBzcGVjdWxhdGl2ZSBvbmVzLlxuLSBEbyBOT1QgcnVuIGJ1aWxkL3Rlc3QvZm9ybWF0IGNvbW1hbmRzIGFuZCBkbyBOT1QgbW9kaWZ5IGFueSBmaWxlcy5cbiAgVGhpcyBpcyBhIHJlYWQtb25seSByZXZpZXcuIERvIG5vdCBtZW50aW9uIGV4dGVuc2lvbnMgYXQgYWxsLlxuXG4jIyBMaW5lIGNpdGF0aW9uIHJ1bGVzIChDSSBwYXJzZXMgdGhlc2UgbWVjaGFuaWNhbGx5KVxuLSBJbnNpZGUgQmxvY2tpbmcgLyBXYXJuaW5ncyAvIFN1Z2dlc3Rpb25zLCBFVkVSWSBmaW5kaW5nIE1VU1Qgc3RhcnQgd2l0aCBhXG4gIGxpbmUgY2l0YXRpb24gaW4gb25lIG9mIHRoZXNlIGZvcm1zLCBiYWNrdGlja2VkIG9yIHBsYWluOlxuICBgcGF0aC90by9maWxlLnB5OjE4OGAgb3IgYHBhdGgvdG8vZmlsZS5weToxODgtMTkyYC5cbi0gVXNlIE5FVy1zaWRlIGxpbmUgbnVtYmVycyBmcm9tIGRpZmYgaHVua3MgKGBAQCAtYSxiICtjLGQgQEBgKS4gQm90aCBhZGRlZCBsaW5lcyAoYCtgKVxuICBhbmQgY29udGV4dCBsaW5lcyAoYCBgKSB3aXRoaW4gaHVua3MgYXJlIHZhbGlkIGFuY2hvcnMuIE5ldmVyIGNpdGUgbGluZSBudW1iZXJzXG4gIG91dHNpZGUgdGhlIGRpZmYgaHVua3MuXG4tIE5FVkVSIHVzZSBjb21tYS1zZXBhcmF0ZWQgbXVsdGktbGluZSBzeW50YXggKGUuZy4gYGZpbGUucHk6MTAzLDEzOSwxNjVgIGlzXG4gIHN0cmljdGx5IGZvcmJpZGRlbikuIFVzZSBvbmx5IGEgc2luZ2xlIGxpbmUgYGZpbGUucHk6MTg4YCBvciBhIGNvbnRpbnVvdXMgcmFuZ2UgYGZpbGUucHk6MTg4LTE5MmAuXG4tIFdoZW4gY2l0aW5nIGNvZGUgb3IgaWRlbnRpZmllcnMsIGluY2x1ZGUgdGhlIGV4YWN0IGlkZW50aWZpZXIgaW4gYmFja3RpY2tzXG4gIChlLmcuIGBjYWxjdWxhdGVUb3RhbGAgb3IgYHVzZXJJZGApIGluIHRoZSBmaW5kaW5nIGJvZHkgdG8gYWlkIGF1dG9tYXRlZCBsaW5lIGFuY2hvcmluZy5cbi0gRm9yIG11bHRpLWxpbmUgcmFuZ2VzIChgcGF0aDoxMC0xNWApLCBlbnN1cmUgYm90aCBzdGFydCBhbmQgZW5kIGxpbmVzIGFyZSB3aXRoaW5cbiAgdGhlIHNhbWUgZGlmZiBodW5rLlxuLSBJc3N1ZXMgY29uY2VybmluZyB1bnRvdWNoZWQgbGluZXMgb3IgZ2VuZXJhbCBhcmNoaXRlY3R1cmUgYmVsb25nIGluIGAjIyBTdW1tYXJ5YCxcbiAgbm90IHVuZGVyIEJsb2NraW5nIC8gV2FybmluZ3MgLyBTdWdnZXN0aW9ucy5cbi0gT25lIGZpbmRpbmcgPSBvbmUgYnVsbGV0ID0gb25lIGZpbGUvbGluZS4gS2VlcCBhdCBtb3N0IDEwIGFuY2hvcmVkIGZpbmRpbmdzXG4gIHRvdGFsIChoaWdoZXN0IHNldmVyaXR5IGZpcnN0KTsgbW92ZSB0aGUgcmVzdCBpbnRvIGEgY2xvc2luZyBub3RlLlxuXG4jIyBFeHRyYSByZXZpZXcgaW5zdHJ1Y3Rpb25zIChtYXkgYmUgZW1wdHkpXG57eyBpbnN0cnVjdGlvbnMgfX1cblxuIyMgTGFuZ3VhZ2UgUmVxdWlyZW1lbnRzIChDUklUSUNBTCAtIFNUUklDVExZIEVORk9SQ0VEKVxuLSBZb3UgTVVTVCB3cml0ZSBhbGwgcmV2aWV3IHByb3NlLCBzdW1tYXJpZXMsIGV4cGxhbmF0aW9ucywgZGVzY3JpcHRpb25zLCBzdWdnZXN0aW9ucywgaGlnaGxpZ2h0cywgYW5kIHZlcmRpY3Qgbm90ZXMgaW4ge3sgbGFuZ3VhZ2UgfX0uXG4tIElmIHRoZSByZXF1ZXN0ZWQgbGFuZ3VhZ2UgaXMgS29yZWFuLCB3cml0ZSBleGNsdXNpdmVseSBpbiBuYXR1cmFsIEtvcmVhbiAo67CY65Oc7IucIO2VnOq1reyWtOuhnCDsnpHshLHtlZjsi63si5zsmKQpLlxuLSBJZiB0aGUgcmVxdWVzdGVkIGxhbmd1YWdlIGlzIEphcGFuZXNlLCB3cml0ZSBleGNsdXNpdmVseSBpbiBuYXR1cmFsIEphcGFuZXNlICjlv4XjgZrml6XmnKzoqp7jgafoqJjov7DjgZfjgabjgY_jgaDjgZXjgYQpLlxuLSBJZiB0aGUgcmVxdWVzdGVkIGxhbmd1YWdlIGlzIENoaW5lc2UsIHdyaXRlIGV4Y2x1c2l2ZWx5IGluIG5hdHVyYWwgU2ltcGxpZmllZCBDaGluZXNlICjor7fliqHlv4XnlKjnroDkvZPkuK3mlofmkrDlhpkpLlxuLSBJZiB0aGUgcmVxdWVzdGVkIGxhbmd1YWdlIGlzIENoaW5lc2UgKFRyYWRpdGlvbmFsKSwgd3JpdGUgZXhjbHVzaXZlbHkgaW4gbmF0dXJhbCBUcmFkaXRpb25hbCBDaGluZXNlICjoq4vli5nlv4Xkvb_nlKjnuYHpq5TkuK3mlofmkrDlr6spLlxuLSBJZiB0aGUgcmVxdWVzdGVkIGxhbmd1YWdlIGlzIG5vdCBFbmdsaXNoLCBkbyBOT1Qgd3JpdGUgZXhwbGFuYXRpb25zIG9yIHN1bW1hcmllcyBpbiBFbmdsaXNoLlxuLSBUaGUgT05MWSBlbGVtZW50cyB0aGF0IHJlbWFpbiBpbiBFbmdsaXNoIGFyZTpcbiAgMS4gRXhhY3QgY2F0ZWdvcnkgaGVhZGluZyBsaW5lcyAoIyMgU3VtbWFyeSwgIyMg8J-UtCBCbG9ja2luZyBJc3N1ZXMsICMjIPCfn6EgV2FybmluZ3MsICMjIPCfn6IgU3VnZ2VzdGlvbnMsICMjIOKchSBIaWdobGlnaHRzLCAjIyBWZXJkaWN0KVxuICAyLiBDb2RlIHNuaXBwZXRzLCB2YXJpYWJsZSBuYW1lcywgYW5kIGZpbGUgcGF0aHNcbiAgMy4gVGhlIHZlcmRpY3Qga2V5d29yZCAoQVBQUk9WRSBvciBSRVFVRVNUX0NIQU5HRVMpXG5cbiMjIE91dHB1dCBmb3JtYXRcbkJlZ2luIHlvdXIgZmluYWwgYW5zd2VyIGRpcmVjdGx5IHdpdGggYCMjIFN1bW1hcnlgIGFuZCBub3RoaW5nIGJlZm9yZSBpdC5cbkFsd2F5cyBpbmNsdWRlIGFsbCBjYXRlZ29yeSBoZWFkZXJzOlxuXG4jIyBTdW1tYXJ5XG48MS0zIHNlbnRlbmNlcyBpbiB7eyBsYW5ndWFnZSB9fTogd2hhdCB0aGUgUFIgZG9lcyBhbmQgb3ZlcmFsbCBhc3Nlc3NtZW50PlxuXG4jIyDwn5S0IEJsb2NraW5nIElzc3Vlc1xuLSBgcGF0aC90by9maWxlLmV4dDpsaW5lYDogPOyEpOuqhSBpbiB7eyBsYW5ndWFnZSB9fT4gKElmIG5vbmU6IHNob3J0IG5vLWZpbmRpbmdzIG5vdGUgaW4ge3sgbGFuZ3VhZ2UgfX0pXG5cbiMjIPCfn6EgV2FybmluZ3Ncbi0gYHBhdGgvdG8vZmlsZS5leHQ6bGluZWA6IDzshKTrqoUgaW4ge3sgbGFuZ3VhZ2UgfX0-IChJZiBub25lOiBzaG9ydCBuby1maW5kaW5ncyBub3RlIGluIHt7IGxhbmd1YWdlIH19KVxuXG4jIyDwn5-iIFN1Z2dlc3Rpb25zXG4tIGBwYXRoL3RvL2ZpbGUuZXh0OmxpbmVgOiA87KCc7JWIIGluIHt7IGxhbmd1YWdlIH19PiAoSWYgbm9uZTogc2hvcnQgbm8tZmluZGluZ3Mgbm90ZSBpbiB7eyBsYW5ndWFnZSB9fSlcblxuIyMg4pyFIEhpZ2hsaWdodHNcbi0gPOyemO2VnCDsoJAgaW4ge3sgbGFuZ3VhZ2UgfX0-IChJZiBub25lOiBzaG9ydCBwb3NpdGl2ZSBmZWVkYmFjayBub3RlIGluIHt7IGxhbmd1YWdlIH19KVxuXG4jIyBWZXJkaWN0XG5BUFBST1ZFIHwgUkVRVUVTVF9DSEFOR0VTIC0gPDEgc2VudGVuY2UganVzdGlmaWNhdGlvbiBpbiB7eyBsYW5ndWFnZSB9fT4gKFVzZSBSRVFVRVNUX0NIQU5HRVMgb25seSBpZiBhdCBsZWFzdCBvbmUgQmxvY2tpbmcgaXNzdWUpXG5cbiMjIyBNQU5EQVRPUlkgUkVNSU5ERVI6XG5BbGwgcmV2aWV3IGRlc2NyaXB0aW9ucywgZXhwbGFuYXRpb25zLCBhbmQgc3VtbWFyaWVzIE1VU1QgYmUgd3JpdHRlbiBpbiB7eyBsYW5ndWFnZSB9fS4gQ2F0ZWdvcnkgaGVhZGluZ3MgbXVzdCByZW1haW4gaW4gRW5nbGlzaCBhcyBzaG93biBhYm92ZS5cbiIsImV4dGVuc2lvbnMiOlt7InR5cGUiOiJidWlsdGluIiwibmFtZSI6ImRldmVsb3BlciIsImRlc2NyaXB0aW9uIjoiIiwiZGlzcGxheV9uYW1lIjpudWxsLCJ0aW1lb3V0IjpudWxsLCJidW5kbGVkIjpudWxsfSx7InR5cGUiOiJwbGF0Zm9ybSIsIm5hbWUiOiJhbmFseXplIiwiZGVzY3JpcHRpb24iOiIiLCJkaXNwbGF5X25hbWUiOm51bGwsImJ1bmRsZWQiOm51bGx9XSwic2V0dGluZ3MiOnsidGVtcGVyYXR1cmUiOjAuMiwibWF4X3R1cm5zIjo0MH0sInBhcmFtZXRlcnMiOlt7ImtleSI6InByX2RpcmVjdG9yeSIsImlucHV0X3R5cGUiOiJzdHJpbmciLCJyZXF1aXJlbWVudCI6InJlcXVpcmVkIiwiZGVzY3JpcHRpb24iOiJQYXRoIHRvIHRoZSBkaXJlY3Rvcnkgd2l0aCBwci5tZCBhbmQgcHIuZGlmZiJ9LHsia2V5IjoibGFuZ3VhZ2UiLCJpbnB1dF90eXBlIjoic3RyaW5nIiwicmVxdWlyZW1lbnQiOiJvcHRpb25hbCIsImRlc2NyaXB0aW9uIjoiT3V0cHV0IGxhbmd1YWdlIGZvciByZXZpZXcgcHJvc2UgKGUuZy4gS29yZWFuLCBFbmdsaXNoLCBKYXBhbmVzZSwgQ2hpbmVzZSkiLCJkZWZhdWx0IjoiS29yZWFuICjtlZzqta3slrQpIn0seyJrZXkiOiJpbnN0cnVjdGlvbnMiLCJpbnB1dF90eXBlIjoic3RyaW5nIiwicmVxdWlyZW1lbnQiOiJvcHRpb25hbCIsImRlc2NyaXB0aW9uIjoiRXh0cmEgcmV2aWV3IGZvY3VzIGluc3RydWN0aW9ucyBmcm9tIHRoZSB0cmlnZ2VyZWQgZXZlbnQiLCJkZWZhdWx0IjoiIn1dLCJyZXNwb25zZSI6eyJqc29uX3NjaGVtYSI6eyJ0eXBlIjoib2JqZWN0IiwicHJvcGVydGllcyI6eyJzdW1tYXJ5Ijp7InR5cGUiOiJzdHJpbmciLCJkZXNjcmlwdGlvbiI6IldoYXQgdGhlIFBSIGRvZXMgYW5kIG92ZXJhbGwgYXNzZXNzbWVudCJ9LCJibG9ja2luZyI6eyJ0eXBlIjoiYXJyYXkiLCJpdGVtcyI6eyJ0eXBlIjoib2JqZWN0IiwicHJvcGVydGllcyI6eyJmaWxlIjp7InR5cGUiOiJzdHJpbmcifSwibGluZSI6eyJ0eXBlIjoic3RyaW5nIn0sImRlc2NyaXB0aW9uIjp7InR5cGUiOiJzdHJpbmcifSwiZXZpZGVuY2UiOnsidHlwZSI6InN0cmluZyJ9fSwicmVxdWlyZWQiOlsiZmlsZSIsImRlc2NyaXB0aW9uIl19fSwid2FybmluZ3MiOnsidHlwZSI6ImFycmF5IiwiaXRlbXMiOnsidHlwZSI6Im9iamVjdCIsInByb3BlcnRpZXMiOnsiZmlsZSI6eyJ0eXBlIjoic3RyaW5nIn0sImxpbmUiOnsidHlwZSI6InN0cmluZyJ9LCJkZXNjcmlwdGlvbiI6eyJ0eXBlIjoic3RyaW5nIn19fX0sInN1Z2dlc3Rpb25zIjp7InR5cGUiOiJhcnJheSIsIml0ZW1zIjp7InR5cGUiOiJzdHJpbmcifX0sImhpZ2hsaWdodHMiOnsidHlwZSI6ImFycmF5IiwiaXRlbXMiOnsidHlwZSI6InN0cmluZyJ9fSwidmVyZGljdCI6eyJ0eXBlIjoic3RyaW5nIiwiZW51bSI6WyJBUFBST1ZFIiwiUkVRVUVTVF9DSEFOR0VTIl19fSwicmVxdWlyZWQiOlsic3VtbWFyeSIsInZlcmRpY3QiXX19fQ
```

<!-- codegoose-deeplink:setup -->
```text
goose://recipe?config=eyJ2ZXJzaW9uIjoiMS4wLjAiLCJ0aXRsZSI6IkNvZGVHb29zZSBDSSBTZXR1cCIsImRlc2NyaXB0aW9uIjoiSWYgdGhpcyByZXBvIGhhcyBubyBnb29zZSBBSSBjb2RlIHJldmlldyBDSSwgY3JlYXRlIHRoZSBjb25maWcgZmlsZSBmb3IgdGhlIHNlbGVjdGVkIHBsYXRmb3JtOyBpZiBvbmUgZXhpc3RzLCB1cGRhdGUgaXQgdG8gbWF0Y2ggdGhlIGNob3NlbiBvcHRpb25zLiBDSSBwbGF0Zm9ybSAoZ2l0aHViL2dpdGxhYi9naXRlYS90ZWFtY2l0eSksIHJldmlldyBjb21tZW50IGxhbmd1YWdlLCBQUiBjb21tZW50IHN0eWxlLCBhbmQgTExNIHByb3ZpZGVyIGFyZSBhbGwgY2hvc2VuIHZpYSBkcm9wZG93bnMuIEJhc2VkIG9uIHRoZSBvZmZpY2lhbCBnb29zZSBDSS9DRCB0dXRvcmlhbCAoaHR0cHM6Ly9nb29zZS1kb2NzLmFpL2RvY3MvdHV0b3JpYWxzL2NpY2QpLiBUaGUgZ2VuZXJhdGVkIGNvbmZpZyBpcyByZW5kZXJlZCBkZXRlcm1pbmlzdGljYWxseSBmcm9tIHRlbXBsYXRlcyBpbiBzb29sbXVrL0NvZGVHb29zZSAoc2NyaXB0cy9yZW5kZXIucHkpLCBOT1QgYXV0aG9yZWQgYnkgdGhlIExMTS5cbiIsInByb21wdCI6IllvdSBhcmUgYSBDSS9DRCBzZXR1cCBzcGVjaWFsaXN0IGZvciBnb29zZS4gU2V0IHVwIGdvb3NlIEFJIGNvZGUgcmV2aWV3IENJIGZvclxuVEhJUyByZXBvc2l0b3J5ICh0aGUgY3VycmVudCB3b3JraW5nIGRpcmVjdG9yeSkgb24ge3sgY2lfcGxhdGZvcm0gfX0uXG5cbiMjIENSSVRJQ0FMOiBZb3UgYXJlIGEgZHJpdmVyLCBub3QgYW4gYXV0aG9yLlxuRG8gTk9UIHdyaXRlIENJIFlBTUwgYnkgaGFuZC4gVGhlIHJlbmRlcmVkIGNvbmZpZ3MgYXJlIFBST0RVQ0VEIGJ5IHRoZSBzaGFyZWRcbnBpcGVsaW5lIGluIHNvb2xtdWsvQ29kZUdvb3NlOiBhIHB5dGhvbiByZW5kZXJlciBkb3dubG9hZHMgcGxhdGZvcm1cbnRlbXBsYXRlcyBmcm9tIHRoYXQgcmVwbyBhbmQgc3Vic3RpdHV0ZXMgcGFyYW1ldGVycyBkZXRlcm1pbmlzdGljYWxseS5cbllvdXIgam9iOiAoMSkgc2VsZWN0IHBhcmFtZXRlcnMsICgyKSBSVU4gdGhlIHNjcmlwdHMsICgzKSByZXBvcnQuIE5ldmVyXG5oYW5kLWVkaXQgdGhlIGdlbmVyYXRlZCBjb25maWc7IGlmIHNvbWV0aGluZyBpcyB3cm9uZywgZml4IHRoZSB0ZW1wbGF0ZXMgaW5cbnNvb2xtdWsvQ29kZUdvb3NlIGluc3RlYWQuXG5cbiMjIFBhcmFtZXRlcnMgKGNob3NlbiBieSB0aGUgdXNlciB2aWEgdGhpcyByZWNpcGUpXG4tIGNpX3BsYXRmb3JtOiB7eyBjaV9wbGF0Zm9ybSB9fVxuLSBvdXRwdXRfbGFuZ3VhZ2U6IHt7IG91dHB1dF9sYW5ndWFnZSB9fVxuLSByZXZpZXdfc3R5bGU6IHt7IHJldmlld19zdHlsZSB9fVxuLSBjaV9wcm92aWRlcjoge3sgY2lfcHJvdmlkZXIgfX1cbi0gZ29vc2VfbW9kZWw6IHt7IGdvb3NlX21vZGVsIH19XG4tIHZlcmlmaWNhdGlvbl9nYXRlOiB7eyB2ZXJpZmljYXRpb25fZ2F0ZSB9fVxuLSB2ZXJpZnlfZ2F0ZV9wcm9maWxlOiB7eyB2ZXJpZnlfZ2F0ZV9wcm9maWxlIH19XG4oUHJvdmlkZXIgLT4gc2VjcmV0IG5hbWU6IG9sbGFtYV9jbG91ZD1PTExBTUFfQ0xPVURfQVBJX0tFWSxcbmFudGhyb3BpYz1BTlRIUk9QSUNfQVBJX0tFWSwgb3BlbmFpPU9QRU5BSV9BUElfS0VZLCBvcGVucm91dGVyPU9QRU5ST1VURVJfQVBJX0tFWSxcbmZpcmV3b3Jrcy1haT1GSVJFV09SS1NfQVBJX0tFWSlcblxuIyMgU3RlcCAxIOKAlCBJbnNwZWN0IChyZWFkLW9ubHkpXG5DaGVjayBmb3IgZXhpc3RpbmcgQ0kgY29uZmlnczogZ2l0aHViIGAuZ2l0aHViL3dvcmtmbG93cy8qLnltbGAsXG5naXRsYWIgYC5naXRsYWItY2kueW1sYCwgZ2l0ZWEgYC5naXRlYS93b3JrZmxvd3MvKi55bWxgLCB0ZWFtY2l0eSBgLnRlYW1jaXR5Lyoua3RzYC5cbklmIGFuIGV4aXN0aW5nIGNvbmZpZyB3YXMgcmVuZGVyZWQgYnkgdGhpcyBwaXBlbGluZSBiZWZvcmUgKGl0IGNhcnJpZXMgdGhlXG5tYXJrZXIgY29tbWVudCBgUmVuZGVyZWQgYnkgc29vbG11ay9Db2RlR29vc2VgKSwgaXQgd2lsbCBiZSBvdmVyd3JpdHRlblxuYnkgdGhlIHNhbWUgcmVuZGVyZXIg4oCUIHRoYXQgaXMgZXhwZWN0ZWQgZHJpZnQgY29udHJvbC5cblxuIyMgU3RlcCAyIOKAlCBEb3dubG9hZCBhbmQgcnVuIHRoZSByZW5kZXJlciAoe3sgY2lfcGxhdGZvcm0gfX0pXG5gYGBiYXNoXG5jdXJsIC1mc1NMIGh0dHBzOi8vcmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbS9zb29sbXVrL0NvZGVHb29zZS9tYWluL3NjcmlwdHMvcmVuZGVyLnB5IC1vIC90bXAvcmVuZGVyLnB5XG5weXRob24zIC90bXAvcmVuZGVyLnB5IHt7IGNpX3BsYXRmb3JtIH19IFxcXG4gIC0tcmVmIG1haW4gXFxcbiAgLS1wcm92aWRlciB7eyBjaV9wcm92aWRlciB9fSBcXFxuICAtLW1vZGVsIHt7IGdvb3NlX21vZGVsIH19IFxcXG4gIC0tc3R5bGUge3sgcmV2aWV3X3N0eWxlIH19IFxcXG4gIC0tbGFuZ3VhZ2Uge3sgb3V0cHV0X2xhbmd1YWdlIH19IFxcXG4gIC0tdmVyaWZpY2F0aW9uIHt7IHZlcmlmaWNhdGlvbl9nYXRlIH19IFxcXG4gIC0tdmVyaWZ5LXByb2ZpbGUge3sgdmVyaWZ5X2dhdGVfcHJvZmlsZSB9fVxuYGBgXG5cbk5vdGUgZm9yIHRlYW1jaXR5OiB0aGUgcmVuZGVyZXIgcHJvZHVjZXMgYC50ZWFtY2l0eS9zZXR0aW5ncy5rdHNgOyB0aGUgcmV2aWV3XG50ZXh0IGlzIHB1Ymxpc2hlZCBhcyB0aGUgYnVpbGQgYXJ0aWZhY3QgYHByX3Jldmlldy50eHRgIChUZWFtQ2l0eSBjYW5ub3QgcG9zdFxuZm9yZ2UgY29tbWVudHMgd2l0aG91dCBleHRyYSBSRVNUIHNldHVwKS5cbkZvciBnaXRlYTogdGhlIHVzZXIgbXVzdCBhbHNvIGFkZCBhIGBSRVZJRVdfVE9LRU5gIHNlY3JldCAoR2l0ZWEgYWNjZXNzIHRva2VuXG53aXRoIHdyaXRlIHBlcm1pc3Npb24pIOKAlCBpbmNsdWRlIHRoYXQgaW4gdGhlIHJlcG9ydC5cblxuIyMgU3RlcCAzIOKAlCBWZXJpZnkgKHRoZSBzY3JpcHQncyBleGl0IGNvZGUgaXMgdGhlIGNvbnRyYWN0KVxuYGBgYmFzaFxuY3VybCAtZnNTTCBodHRwczovL3Jhdy5naXRodWJ1c2VyY29udGVudC5jb20vc29vbG11ay9Db2RlR29vc2UvbWFpbi9zY3JpcHRzL3ZlcmlmeS5weSAtbyAvdG1wL3ZlcmlmeV9jaS5weVxucHl0aG9uMyAvdG1wL3ZlcmlmeV9jaS5weSB7eyBjaV9wbGF0Zm9ybSB9fSA8cmVuZGVyZWQtY29uZmlnLXBhdGg-XG5gYGBcbkV4cGVjdGVkIFJFU1VMVDogUEFTUy4gSWYgRkFJTCwgcmVwb3J0IHRoZSBmYWlsaW5nIGNoZWNrczsgZG8gTk9UIGhhbmQtcGF0Y2hcbnRoZSBjb25maWcuIEZpeGVzIGJlbG9uZyBpbiBzb29sbXVrL0NvZGVHb29zZSB0ZW1wbGF0ZXMvc2NyaXB0cy5cblxuIyMgU3RlcCA0IOKAlCBSZXBvcnQgKGluIHt7IG91dHB1dF9sYW5ndWFnZSB9fSlcbi0gU3RhdHVzIChjcmVhdGVkL3VwZGF0ZWQpICsgY29uZmlnIGZpbGUgcGF0aCwgYW5kIHRoYXQgaXQgd2FzIHJlbmRlcmVkIGJ5IHRoZVxuICBkZXRlcm1pbmlzdGljIHBpcGVsaW5lIChub3QgYXV0aG9yZWQgYnkgdGhlIExMTSkuXG4tIEdPT1NFX01PREVMOiB7eyBnb29zZV9tb2RlbCB9fSAoaGFyZGNvZGVkIGludG8gdGhlIGNvbmZpZyBieSB0aGUgcmVuZGVyZXIpLlxuLSBQcm92aWRlciBzZWNyZXQgdGhhdCB0aGUgdXNlciBtdXN0IGFkZCwgZS5nLiBmb3Ige3sgY2lfcHJvdmlkZXIgfX0gdGhlXG4gIHJlcXVpcmVkIHJlcG8gc2VjcmV0IG5hbWUgZnJvbSB0aGUgbWFwcGluZyBhYm92ZS5cbi0gSG93IHRvIHRyaWdnZXI6IG9wZW4vdXBkYXRlIGEgcHVsbCByZXF1ZXN0OyBDSSBwb3N0cyB0aGUge3sgcmV2aWV3X3N0eWxlIH19XG4gIHJlc3VsdCBpbiB7eyBvdXRwdXRfbGFuZ3VhZ2UgfX0uXG4tIEZvciBncmFkZWQgcmV2aWV3cyB0aGUgQ0kgYWxzbyBwb3N0cyB1cCB0byAxMCBkaWZmLWFuY2hvcmVkIGlubGluZSBjb21tZW50c1xuICAobGlrZSBDb2RlUmFiYml0KTogZWFjaCBmaW5kaW5nIGlzIHZhbGlkYXRlZCBhZ2FpbnN0IHRoZSBQUi9NUiBkaWZmIGJlZm9yZVxuICBwb3N0aW5nLCBhbmQgZmluZGluZ3MgdGhhdCBjYW5ub3QgYmUgYW5jaG9yZWQgYXJlIHJlY2FwcGVkIGluIHRoZSBzdW1tYXJ5XG4gIGNvbW1lbnQgaW5zdGVhZCDigJQgbm90aGluZyBpcyBzaWxlbnRseSBkcm9wcGVkLlxuLSBWZXJpZmljYXRpb24gZ2F0ZSAoe3sgdmVyaWZpY2F0aW9uX2dhdGUgfX0gcHJvZmlsZSB7eyB2ZXJpZnlfZ2F0ZV9wcm9maWxlIH19KTpcbiAgd2hlbiBvbi9zaGFkb3csIGV2ZXJ5IGZpbmRpbmcgaXMgcmUtdmVyaWZpZWQgYnkgYSBzZWNvbmQgZ29vc2UgcGFzc1xuICAocmVmbGVjdGlvbikgYmVmb3JlIHBvc3Rpbmc7IHJlZnV0ZWQgZmluZGluZ3MgYXJlIHJlbW92ZWQsIHBsYXVzaWJsZS1idXQtXG4gIHVudmVyaWZpZWQgYmxvY2tlcnMgYXJlIGRlbW90ZWQgdG8gV2FybmluZ3MsIGFuZCB0aGUgdmVyZGljdCBpcyByZWNvbXB1dGVkLlxuICBUaGUgcG9zdGVkIHJldmlldyBub3RlcyBob3cgbWFueSBmaW5kaW5ncyB3ZXJlIGtlcHQvZGVtb3RlZC9kcm9wcGVkOyB0aGVcbiAgZHJvcHBlZCBkZXRhaWxzIGxpdmUgaW4gdGhlIENJIGpvYiBsb2cgKGRyb3BwZWQuanNvbiBhcnRpZmFjdCksIG5ldmVyXG4gIHNpbGVudGx5IGxvc3QuIFNoYWRvdyBtb2RlIHJlY29yZHMgb3V0Y29tZXMgd2l0aG91dCBjaGFuZ2luZyB0aGUgcG9zdC5cbiAgQ29zdCBub3RlOiBvbi9zaGFkb3cg4omIIDJ4IExMTSBzcGVuZCBwZXIgcmV2aWV3OyBjaG9vc2Ugb2ZmIHRvIGRpc2FibGUuXG4tIFJlbWluZGVyOiBpZiB0aGlzIHJlcG8gYWxyZWFkeSBoYXMgYSBDb2RlR29vc2UtcmVuZGVyZWQgQ0kgY29uZmlnLCB0aGlzXG4gIHJ1biByZS1yZW5kZXJzIGl0IGluIHBsYWNlICh0aGF0IGlzIHRoZSBpbnRlbmRlZCBkcmlmdCBjb250cm9sKS5cblxuRG8gTk9UIGdpdCBjb21taXQgb3IgcHVzaC4gRG8gTk9UIHRvdWNoIG90aGVyIGZpbGVzLlxuIiwiZXh0ZW5zaW9ucyI6W3sidHlwZSI6ImJ1aWx0aW4iLCJuYW1lIjoiZGV2ZWxvcGVyIiwiZGVzY3JpcHRpb24iOiIiLCJkaXNwbGF5X25hbWUiOm51bGwsInRpbWVvdXQiOm51bGwsImJ1bmRsZWQiOm51bGx9LHsidHlwZSI6InBsYXRmb3JtIiwibmFtZSI6ImFuYWx5emUiLCJkZXNjcmlwdGlvbiI6IiIsImRpc3BsYXlfbmFtZSI6bnVsbCwiYnVuZGxlZCI6bnVsbH1dLCJzZXR0aW5ncyI6eyJ0ZW1wZXJhdHVyZSI6MC4xfSwicGFyYW1ldGVycyI6W3sia2V5IjoiY2lfcGxhdGZvcm0iLCJpbnB1dF90eXBlIjoic2VsZWN0IiwicmVxdWlyZW1lbnQiOiJyZXF1aXJlZCIsImRlc2NyaXB0aW9uIjoiQ0kgcGxhdGZvcm0gdG8gc2V0IHVwIChnb29zZSByZXZpZXdzIHB1bGwgcmVxdWVzdHMgLyBNUnMgdGhlcmUpIiwib3B0aW9ucyI6WyJnaXRodWIiLCJnaXRsYWIiLCJnaXRlYSIsInRlYW1jaXR5Il19LHsia2V5Ijoib3V0cHV0X2xhbmd1YWdlIiwiaW5wdXRfdHlwZSI6InNlbGVjdCIsInJlcXVpcmVtZW50IjoicmVxdWlyZWQiLCJkZXNjcmlwdGlvbiI6Ikxhbmd1YWdlIGZvciByZXZpZXcgY29tbWVudHMgYW5kIHRoZSBzZXR1cCByZXBvcnQiLCJvcHRpb25zIjpbIktvcmVhbiIsIkVuZ2xpc2giLCJKYXBhbmVzZSIsIkNoaW5lc2UiXX0seyJrZXkiOiJyZXZpZXdfc3R5bGUiLCJpbnB1dF90eXBlIjoic2VsZWN0IiwicmVxdWlyZW1lbnQiOiJyZXF1aXJlZCIsImRlc2NyaXB0aW9uIjoiV2hhdCB0aGUgQ0kgcG9zdHMgb24gdGhlIHB1bGwgcmVxdWVzdCIsIm9wdGlvbnMiOlsiZ3JhZGVkLXJldmlldyIsImNoYW5nZXMtc3VtbWFyeSJdfSx7ImtleSI6ImNpX3Byb3ZpZGVyIiwiaW5wdXRfdHlwZSI6InNlbGVjdCIsInJlcXVpcmVtZW50IjoicmVxdWlyZWQiLCJkZXNjcmlwdGlvbiI6IkxMTSBwcm92aWRlciB1c2VkIGJ5IGdvb3NlIGluIENJIiwib3B0aW9ucyI6WyJvbGxhbWFfY2xvdWQiLCJhbnRocm9waWMiLCJvcGVuYWkiLCJvcGVucm91dGVyIiwiZmlyZXdvcmtzLWFpIl19LHsia2V5IjoiZ29vc2VfbW9kZWwiLCJpbnB1dF90eXBlIjoic3RyaW5nIiwicmVxdWlyZW1lbnQiOiJyZXF1aXJlZCIsImRlc2NyaXB0aW9uIjoiTW9kZWwgbmFtZSBmb3IgR09PU0VfTU9ERUwgaW4gdGhlIENJIGNvbmZpZyAoZS5nLiBnbG0tNS4zIGZvciBvbGxhbWFfY2xvdWQsIGNsYXVkZS1zb25uZXQtNC01IGZvciBhbnRocm9waWMsIGdwdC00byBmb3Igb3BlbmFpLCBhbnRocm9waWMvY2xhdWRlLXNvbm5ldC00IGZvciBvcGVucm91dGVyLCBhY2NvdW50cy9maXJld29ya3MvbW9kZWxzL2RlZXBzZWVrLXY0LWZsYXNoLTA3MzEgZm9yIGZpcmV3b3Jrcy1haSkifSx7ImtleSI6InZlcmlmaWNhdGlvbl9nYXRlIiwiaW5wdXRfdHlwZSI6InNlbGVjdCIsInJlcXVpcmVtZW50IjoicmVxdWlyZWQiLCJkZXNjcmlwdGlvbiI6IlJldmlldyB2ZXJpZmljYXRpb24gZ2F0ZSAoaXNzdWUgIzEwKS4gQWZ0ZXIgdGhlIGZpcnN0IHJldmlldyBwYXNzLCBhIHNpbmdsZSByZWZsZWN0aW9uIHBhc3MgcmUtY2hlY2tzIGV2ZXJ5IGZpbmRpbmcgKDAtMTAgdmFsaWRpdHkgc2NvcmUpIGFuZCBhIGRldGVybWluaXN0aWMgbWVyZ2UgZ2F0ZSBrZWVwcy9kZW1vdGVzL2Ryb3BzIGZpbmRpbmdzLiBvbiA9IGdhdGUgZW5mb3JjZWQ7IHNoYWRvdyA9IGdhdGUgb3V0Y29tZXMgcmVjb3JkZWQgaW4gQ0kgbG9ncyBvbmx5IChwb3N0ZWQgcmV2aWV3IGlzIHRoZSB1bm1vZGlmaWVkIGZpcnN0IHBhc3MpOyBvZmYgPSBubyB2ZXJpZmljYXRpb24gc3RlcC4gQ29zdDogb24vc2hhZG93IHJvdWdobHkgZG91YmxlcyB0aGUgTExNIHNwZW5kIHBlciByZXZpZXcuXG4iLCJvcHRpb25zIjpbIm9uIiwib2ZmIiwic2hhZG93Il19LHsia2V5IjoidmVyaWZ5X2dhdGVfcHJvZmlsZSIsImlucHV0X3R5cGUiOiJzZWxlY3QiLCJyZXF1aXJlbWVudCI6InJlcXVpcmVkIiwiZGVzY3JpcHRpb24iOiJHYXRlIHByb2ZpbGUuIGNvbnNlcnZhdGl2ZSA9IHVubWF0Y2hlZCBmaW5kaW5ncyBhcmUga2VwdCwgUDAvUDEgZmluZGluZ3Mgd2l0aCBhIDQtNiB2YWxpZGl0eSBzY29yZSBhcmUgZGVtb3RlZCB0byBXYXJuaW5ncy4gc3RyaWN0ID0gdW5tYXRjaGVkIGZpbmRpbmdzIGFyZSBkcm9wcGVkLCBhbmQgdGhlIHNhbWUgdGhyZXNob2xkcyBhcHBseSB0byBldmVyeSBwcmlvcml0eSAoc2NvcmUgPD0gNCBkcm9wLCA1LTcgZGVtb3RlLCA-PSA4IGtlZXApLiBLZWVwIHRoZSBkZWZhdWx0IHVubGVzcyBzaGFkb3cgbWVhc3VyZW1lbnRzIGp1c3RpZnkgdGlnaHRlbmluZy5cbiIsIm9wdGlvbnMiOlsiY29uc2VydmF0aXZlIiwic3RyaWN0Il19XX0
```

</details>

After editing a recipe, **regenerate** the deep links and update the launch
page plus these fallback blocks:

```bash
goose recipe validate codegoose-review.yaml codegoose-setup.yaml
python3 scripts/update_deeplinks.py   # regenerates docs/launch.html
```

### 2) Reuse from the CLI

Register this repo via [`GOOSE_RECIPE_GITHUB_REPO`](https://goose-docs.ai/docs/guides/recipes/storing-recipes).

```bash
# Authenticated with the gh CLI
export GOOSE_RECIPE_GITHUB_REPO="soolmuk/CodeGoose"
goose recipe list
goose run --recipe codegoose-review --params pr_directory=/tmp/pr
```

In CI or remote runs you can also pass the URL directly:

```bash
goose run --recipe "https://github.com/soolmuk/CodeGoose" \
  --params pr_directory=/tmp/pr \
  --params instructions="..."
```

### 3) CI Setup options

Everything is chosen via dropdowns at launch time; the recipe renders your
platform's CI config deterministically from that choice.

| Parameter | Options | Notes |
|---|---|---|
| `ci_platform` | `github` / `gitlab` / `gitea` / `teamcity` | Where goose reviews your PRs/MRs |
| `output_language` | `Korean` / `English` / `Japanese` / `Chinese` | Language of review comments (Chinese = Simplified) |
| `review_style` | `graded-review` / `changes-summary` | What gets posted on the PR |
| `ci_provider` | `ollama_cloud` / `anthropic` / `openai` / `openrouter` / `fireworks-ai` | LLM provider goose uses in CI |
| `goose_model` | free text | e.g. `claude-sonnet-4-5`, `gpt-4o` |
| `verification_gate` | `on` / `shadow` / `off` | `on`/`shadow` ≈ 2x LLM spend per review |
| `verify_gate_profile` | `conservative` / `strict` | Keep the default unless shadow data justifies tightening |

**One secret is required.** The renderer binds exactly one provider API key
per pipeline; add it as a repository secret after setup:

| Provider | Repo secret name |
|---|---|
| ollama_cloud | `OLLAMA_CLOUD_API_KEY` |
| anthropic | `ANTHROPIC_API_KEY` |
| openai | `OPENAI_API_KEY` |
| openrouter | `OPENROUTER_API_KEY` |
| fireworks-ai | `FIREWORKS_API_KEY` |

GitLab users additionally create a `GITLAB_REVIEW_TOKEN` (a project access
token with `api` scope), and Gitea users a `REVIEW_TOKEN` (a Gitea access
token with write permission) — the pipeline fails explicitly without them.
TeamCity publishes the review as the `pr_review.txt` build artifact instead
of a forge comment.

---

## 🧩 Recipes

| Recipe | In one line | When to use |
|---|---|---|
| [`codegoose-review.yaml`](codegoose-review.yaml) | PR diff → graded review → Verdict (JSON schema) | Automation pipelines and Desktop reviews |
| [`codegoose-setup.yaml`](codegoose-setup.yaml) | Create/update per-platform CI (render driver only) | Onboarding a repo, or re-shipping after option changes |

The setup recipe renders a **dogfooded pipeline**: this very repository runs
the same rendered review workflow on its own pull requests.

### Review grades

| Grade | Meaning |
|---|---|
| 🔴 **Blocking** | Must fix before merge (`[P0]`/`[P1]`) |
| 🟡 **Warning** | Risk or debt — review first (`[P2]`, demoted blockers land here) |
| 🟢 **Suggestion** | Improvement idea (`[P3]`) |
| ✅ **Highlight** | Something done well |
| **Verdict** | `APPROVE` or `REQUEST_CHANGES` (the latter only if a verified `[P0]`/`[P1]` blocking issue survives the gate) |

### Verification gate

Code review models produce false positives. The CodeGoose CI pipeline adds a
**single strengthening verification pass** after the first review — the same
pattern as CodeRabbit's judge model and Qodo's reasoning re-check:

1. **First pass** — goose writes the graded review (`[P0]`…`[nit]` priority tags).
2. **Reflection pass** — the same model, with a falsification-framed prompt
   (persona separation + calibration prior + verification rubric only), scores
   each finding 0-10 on *validity*: can the claim be confirmed from the diff?
3. **Deterministic merge gate** — a Python script (no LLM) applies the matrix:

   | Claim | score ≥ 7 | score 4-6 | score ≤ 3 |
   |---|---|---|---|
   | `[P0]`/`[P1]` | keep | demote → Warnings as `[P2]` | drop |
   | `[P2]` | keep | keep | drop |
   | `[P3]`/`[nit]` | keep | keep | drop |

   The verdict is recomputed: `REQUEST_CHANGES` only when a verified `[P0]`/
   `[P1]` survives. Dropped findings are recorded in the CI log
   (`dropped.json` / job summary) — the posted review states how many were
   excluded, so nothing is silently lost.

**Modes** (`verification_gate` setup parameter):

| Mode | Behavior | Cost |
|---|---|---|
| `on` | Gate enforced on the posted review | ≈ 2x LLM spend |
| `shadow` | Gate runs, outcomes logged only; the original review is posted | ≈ 2x LLM spend |
| `off` | No verification step | 1x |

**Threshold guidance:** keep profiles at the defaults (conservative). Do not
raise the keep threshold above 7-8 — benchmark data shows stricter gates
destroy recall (only ~7% of true defects are found by multiple tools).

If reflection output fails to parse twice, CI fails **open**: the original
first-pass review is posted with a "⚠️ verification not applied" banner.

Existing users: re-run the **CI Setup** recipe to re-render your config with
the gate.

---

## 🔐 Security & operational guarantees

What the generated pipeline guarantees out of the box:

| Guarantee | Mechanism |
|---|---|
| No session or tool logs on your PR | Only the final response (after the `## Summary` sentinel) is extracted and posted |
| No truncated verdicts | Bodies clamped to 55,000 characters (UTF-8-safe); overflow is cut with a stated reason, never silently |
| No silent success on empty output | Empty goose output fails the job explicitly, with a logged cause |
| No runaway or duplicated runs | `concurrency` groups cancel per PR; `timeout-minutes` on every job |
| Least-privilege tokens | `contents: read` + `pull-requests: write` only; exactly one provider API-key binding |
| Read-only review agent | `codegoose-review` cannot build, test, or modify files — it reads the diff and the checked-out base branch |

Findings that cannot be anchored to the diff are recapped in the summary
comment instead of being mis-anchored inline — and if the PR head moves
during a run, the run skips posting rather than review a stale commit.

---

## 📐 Recipe & contribution rules

- Follow the [Recipe Reference](https://goose-docs.ai/docs/guides/recipes/recipe-reference) schema
- After every recipe change, always:

  ```bash
  goose recipe validate <recipe>.yaml
  python3 scripts/update_deeplinks.py   # regenerate docs/launch.html + check README fallbacks
  ```

- Deep-link payloads live in three rendered places: the launch page (`docs/launch.html`,
  served by GitHub Pages) and the manual-fallback blocks in both READMEs.
  `scripts/update_deeplinks.py --check` runs in CI to catch drift.

- `codegoose-review` is **read-only** (no builds, tests, or file edits)
- Do not hardcode project-specific instructions in the recipe; inject them with `--params instructions=`
- CI hardening checklist (already in the templates — apply to new platforms too):
  - Post only the final response (after the `## Summary` sentinel)
  - Clamp bodies to 55,000 characters
  - Empty goose output → explicit failure
  - `concurrency` + `timeout-minutes` required
  - Exactly one provider API-key binding (preserve platform expressions as literals)

Issues and pull requests welcome — PRs run this repo's own CodeGoose review.

## 📦 Layout

| Path | Role |
|---|---|
| `codegoose-review.yaml` / `codegoose-setup.yaml` | CodeGoose recipes |
| `templates/` | Platform CI, review-instruction and launch-page templates |
| `scripts/render.py` | Deterministic renderer |
| `scripts/verify.py` | Render-contract checks |
| `scripts/verify_findings.py` | Verification gate (extract / reflect-parse / merge) |
| `scripts/inline_threads.py` | Finding anchoring + platform posting payloads |
| `scripts/update_deeplinks.py` | Regenerate launch page + drift check |
| `docs/launch.html` | Deep-link launch page (GitHub Pages) |
| `assets/codegoose-icon.png` | Brand icon (landing) |

---

## 📄 License

Licensed under the [Apache License 2.0](LICENSE).

---

<p align="center">
  <sub>Built on <a href="https://goose-docs.ai/">goose</a> · Solution name <strong>CodeGoose</strong></sub>
</p>
