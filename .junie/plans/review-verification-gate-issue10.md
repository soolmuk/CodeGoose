---
sessionId: session-260831-110100-verify-gate
---

# Requirements

### Overview & Goals
CodeGoose PR 리뷰의 오탐(false positive)을 줄이기 위해, 1차 리뷰 생성 뒤 **단일 강화 검증(reflection) 패스 + 결정론적 병합 게이트**를 추가한다 (이슈 #10).

소유자 초안("3명 전문가 서브에이전트 + 만장일치 게시")은 벤치마크 조사(CodeRabbit / Qodo-PR-Agent / Gitar + Martian 독립 벤치마크 + pi-pr-review 공개 스펙)에서 다음 근거로 수정되었다:

- 업계 표준은 투표·만장일치가 아니라 **생성 → 단일 강화 검증 패스 → 결정론적 하드체크 → 사람 피드백 루프**다.
  - CodeRabbit: 별도 judge 모델이 근거 못 댄 파인딩을 drop.
  - Qodo(PR-Agent): 추론 모델이 제안 전체를 한 번에 재검토, 0-10 점수 + 사유, 0점 drop, 임계값 7-8 초과 금지 권고.
  - pi-pr-review: P0~P3/nit 우선순위 태그, `request_changes`는 "검증된 P0/P1 존재 시"만, 상위 심각도일수록 증거 요건 강화.
- 4도구 병렬 실험(146 PR, 679 파인딩): 서로 다른 지적 위치 617개 중 **93.4%가 정확히 1개 도구만 발견**, 4개 전부 발견 0건 → 다수결 게이트는 재현율(re-call) 붕괴.
- 독립 벤치마크 최고 도구도 정밀도 ~49% → "오탐 제거"와 "재현율 보존"의 균형이 설계 목표.

또한 계획 수립 후 **3인 전문가 서브에이전트가 실측 파일 검토**(CI/CD 파이프라인, LLM 아키텍처, Python 구현)를 수행했고, 9개 블로커를 포함한 수정사항이 본 문서에 반영되었다. 셋 모두 판정 APPROVE-WITH-CHANGES.

### Scope
- **In Scope:**
  - 신규 `scripts/verify_findings.py` (extract / reflect-parse / merge / selftest)
  - 신규 `templates/instructions.reflection.md` (반증 프레이밍 검증 지시문)
  - `templates/instructions.graded.md`에 [P0]~[nit] 우선순위 태그 도입
  - 4개 플랫폼 CI 템플릿에 검증 단계 삽입 (같은 스텝 내 2차 goose 호출, fail-open 폴백, gitea 가드/TeamCity 타임아웃 기존 결함 보강 포함)
  - `scripts/render.py`, `scripts/verify.py` 계약 갱신 (동일 커밋)
  - `codegoose-setup.yaml` 신규 파라미터 + 딥링크 재생성 (동일 커밋)
  - README 2개 문서화, 이슈 #10 갱신·종결
- **Out of Scope:**
  - **v2: 3-렌즈 발견 확장 (sub_recipes)** — 별도 이슈로 이월 (sub_recipes는 실험적 기능)
  - `codegoose-review.yaml` 세션 내 성찰 단계 — v1 제외 (CI 배포 경로는 이 레시피를 사용하지 않음; 검증 논리의 단일 진실 원천 유지)
  - 피드백 학습 루프(Gitar식 기각 기억) — 데이터 축적 후 별도 이슈
  - **이 PR에서 `.github/workflows/codegoose-review.yml` (dogfood 아티팩트) 재렌더 제외** — 셀프부트스트랩 충돌 방지 (아래 블로커 B1). 머지 직후 후속 커밋으로 재렌더.

### Public Decisions (소유자 확정)
| # | 결정 | 내용 |
|---|---|---|
| D-1 (개정) | 폐기 파인딩 처리 | **(a) 게시물에 통계 라인만 게시**: "검증으로 N건 제외됨 — 상세는 CI 로그". 폐기 내용 자체는 게시 안 함(원안 존중), 숫자만 남겨 "nothing is silently dropped" 불변식 + shadow 측정 데이터 확보. |
| D-2 (개정) | 리플렉션 실패 | **fail-open**: 교정 메시지 포함 재시도 1회 → 2회 실패 시 "⚠️ 검증 미적용" 배너와 함께 1차 리뷰 그대로 게시. (완성된 유효 리뷰의 소실이 더 큰 손실; 배너로 "조용한 성공 금지" 규칙 준수) |
| D-3 | 프로필 기본값 | conservative (2D 매트릭스 하단 표) |
| D-4 (개정) | 모델 | **v1 = 엄격한 단일 모델**: 리뷰·리플렉션 두 패스 모두 setup에서 선정한 하나의 `goose_model`·하나의 provider 키·하나의 config.yaml을 공유. `reflect_model` 파라미터는 v1에서 **삭제** — 교차 모델은 shadow 실측(D-6)이 게이트 효과 부족을 입증할 때만 v1.5 옵션으로 도입. |
| D-5 | sub_recipes | v1 미사용 (CI는 `--instructions` 모드 유지) |
| D-6 (신규) | shadow-mode | `verification_gate=shadow` 옵션: 리플렉션 실행·기록만 하고 게시물은 원본 1차 리뷰. 이 저장소 dogfood로 N개 PR 실측(keep/demote/drop률) 후 `on` 전환. |
| D-7 (신규) | 착수 전제 | `goose run --instructions` 툴 가용성 스모크 테스트 1회 (B4 참조) |

### 게이트 정책: 2차원 매트릭스 (우선순위 × 리플렉션 점수)
점수 의미론 (**타당도(validity) 축** — 심각도는 P태그가 담당):
- **0-3**: 반증됨 / 인용 증거 없음
- **4-6**: 그럴듯하나 미검증
- **7-10**: diff/코드에서 구체적 증거 확인

| 주장 우선순위 | score ≥ 7 | score 4-6 | score ≤ 3 |
|---|---|---|---|
| **[P0]/[P1]** (🔴 차단 주장) | ✅ 유지 (차단 유지) | ⬇️ **강등 → 🟡 섹션, 태그 [P2] 재작성** | ❌ 폐기 |
| **[P2]** (🟡) | ✅ 유지 | ✅ 유지 | ❌ 폐기 |
| **[P3]/[nit]** (🟢) | ✅ 유지 | ✅ 유지 | ❌ 폐기 |

- strict 프로필: 모든 우선순위에 동일 임계 (≤4 drop, 5-7 강등, ≥8 keep)
- unmatched 파인딩: **conservative=KEEP(+stderr WARN), strict=DROP**
- Verdict 재계산: `REQUEST_CHANGES` ⇔ 생존한 [P0]/[P1] ≥ 1개. Verdict **섹션 전체 재생성** (dash 없는 `APPROVE.` 형태도 처리).
- P태그 ↔ 섹션 매핑: `[P0]/[P1]`→🔴, `[P2]`→🟡, `[P3]/[nit]`→🟢. 태그 없는 legacy 불릿은 섹션 기준 폴백 (🔴→P1, 🟡→P2, 🟢→P3).

# Architecture

### 최종 파이프라인 (v1)
```
PR 정보 수집 (기존, 불변)
→ goose 리뷰 패스 (기존 instructions.graded.md, [P] 태그 포맷 추가)
→ inline_threads.py extract → body.md
→ verify_findings.py extract --body body.md --out findings.json
→ (사전 SHA 체크: PR head 이동 시 조기 종료 — 2차 LLM 비용 방지)
→ goose 리플렉션 패스 (instructions.reflection.md, 같은 스텝 run 블록 내,
    입력 = findings.json + pr.diff [재획득 금지], 출력 > reflect_raw.txt)
→ verify_findings.py reflect-parse --raw reflect_raw.txt --out scores.json
   (실패 시: 교정 메시지 포함 재시도 1회 → 2회 실패 시 fail-open 폴백:
    "⚠️ 검증 미적용" 배너 + body.md 그대로 게시)
→ verify_findings.py merge --body body.md --scores scores.json
   --profile conservative|strict --mode enforce|shadow
   --out-final body.md (그 자리 덮어씀) --out-dropped dropped.json --lang <__LANGUAGE__>
→ (기존 head-SHA 가드: prepare 직전 유지)
→ inline_threads.py prepare --body body.md --diff pr.diff (기존, 리터럴 계약 유지)
→ 게시 (기존 그대로)
→ dropped.json → CI job summary / TeamCity artifact pr_review_dropped.txt (PR 미게시)
```

### 병합(merge) 설계 원칙 (실측 기반)
- `inline_threads.py`에서 **파싱 프리미티브만 import 재사용** (`LENIENT_HEADING_RE`, `KNOWN_SECTIONS`, `SECTION_CATEGORY`, `_bullet_texts`, `_parse_anchor_candidates`, `normalize_path`, `truncate_body`).
  ⚠️ `split_threads()`의 `clean` 반환값은 **원문 전체**(섹션 보존용)이며 bullets에 소스 라인 위치가 없음 → 재결합에 사용 불가 (실측 확인). merge는 **위치 보존 섹션 워크를 자체 구현** (L157-172와 동일한 순회로 섹션별 원시 라인 스팬 수집 → 불릿 단위 드롭/이동/태그 재작성 → 알려지지 않은 헤딩은 제자리 통과).
- 앵커 매칭은 문자열 동등이 아니라 **정규화 매칭**: reflection 앵커에도 `_parse_anchor_candidates` + `normalize_path` 적용 (백틱/`./`/`a/`·`b/` 접두/line_end 드리프트 흡수 + URL 가드 획득). 비교 키 = (normalize_path(path), line).
- `findings.json`은 **정규화된 앵커**(`f"{path}:{line}"` / `f"{path}:{line}-{line_end}"`)를 출력하고 리플렉션 프롬프트에 "이 값 그대로 echo" 지시 → 매칭 견고화.
- **기계적 증거 휴리스틱은 v1에서 삭제** (한국어 산문에서 구조적 false negative — 실측). 근거 요구는 리플렉션 **프롬프트**로 이전 ("why에 근거가 된 식별자·코드 조각 포함").
- 중복 앵커: reflect-parse는 전체 보존 + WARN. merge는 **first-match-wins** 탐욕 순서 매칭.
- order-index 폴백: `len(scores) == len(findings)`일 때만 허용 + WARN.
- 강등: 불릿 원문은 그대로 두되 첫 등장 태그만 `[P2]`로 재작성 (legacy 불릿은 `[P2] ` 접두 추가), 인용-선행 서식 유지 (다운스트림 PATH_LINE_RE 앵커링은 태그 위치 양측 실측 OK).
- 빈 섹션 note: **드롭으로 새로 빈 섹션에만** 생성 (모델이 쓴 기존 note 보존, 중복 금지). ko/en 하드코딩 테이블 + 미지 언어 영어 폴백 + WARN.
- 55,000 클램프: merge가 `truncate_body` 재사용으로 final에 적용 + `prepare`가 body_clean에 재적용 (이중 클램프 무해).
- ANSI 정규식: `inline_threads.py`에서 모듈 상수 `ANSI_RE`로 추출(소규모 리팩터) 후 `verify_findings.py`가 재사용 (복붙 금지 — drift 원천).

### 리플렉션 지시문 설계 (templates/instructions.reflection.md)
- **반증 프레이밍**: "각 파인딩을 반증하라. 반증에 성공하면 0-3, 실패하면 7-10. '그럴듯해 보인다'는 통과가 아니다."
- **검증(verification) 루브릭만 제공** — 발견(discovery) 루브릭(instructions.graded.md)은 미제공 (동의 편향 회귀 방지). P-level 정의, 증거 기준, 반증의 의미 포함.
- **밴드 앵커 + 캘리브레이션 사전**: "이 생성기의 파인딩은 평가 기준 20-40%가 결함" 강제 보정 주입 (동일 모델 keep-rate 인플레이션 저지).
- **페르소나 분리**: "이 파인딩은 당신이 작성한 것이 아님. 최소 1건은 틀렸다고 가정하라."
- 새 파인딩 추가 금지 (검증 전용).
- **토큰 예산**: 리플렉션 입력은 전체 diff 재주입이 아니라 **인용 라인 주변 hunk 트리밍**(±수 줄) 포함. (instructions.txt에 이미 전체 diff가 있음 — 이중 주입으로 컨텍스트 오버플로 방지)
- 출력: `## Reflection` 센티널 + ```json 블록 1개: `{"findings":[{"anchor":..., "score":0-10, "why":...}]}`. why는 내부용(비게시) English 고정 — 기계 신뢰성 우선.
- score 스키마 관용: `8.0`/`"8"` 숫자로 코어스, 0-10 범위 밖은 해당 항목 무시 + WARN. why 누락 허용(빈 문자열).

### CI 템플릿 변경 (4개 플랫폼 공통 요구사항)
1. **같은 스텝 run 블록 내 2차 goose 호출** — API 키 바인딩 "정확히 1개" 계약(verify.py) 유지. 별도 스텝+별도 env 금지. GitLab은 `export` 재반복 금지.
2. **사전 SHA 체크** (리플렉션 직전, 저비용): PR head 이동 시 조기 종료. 기존 head-SHA 가드는 **prepare 직전 유지** (기존 배치가 정확함 — reflect 앞으로 이동만 하면 안 됨). GitHub 스텝에 `GH_TOKEN: ${{ github.token }}` 추가 필요(PROVIDER 키 아님 — verify 영향 없음).
3. **fail-open 폴백** (D-2): reflect-parse 2회 실패 시 body.md 원본 게시 + "⚠️ 검증 미적용" 배너.
4. **pr.diff 재획득 금지** — reflect/merge는 body.md + pr.diff + findings.json만 소비 (앵커 기준 일관성).
5. `#[verify:begin]/#[verify:end]` 마커: **완전한 셸 문장 + 완전한 YAML 스텝 경계에만** 배치. Kotlin DSL 레벨(컴파일 깨짐)과 `cat <<'EOF'` 경계(heredoc 조기 종료) 금지. render.py는 제거 후 잔존 마커 0 단언. TeamCity는 scriptContent 내부 bash 주석으로만.
6. **TeamCity 보강**: `artifactRules`에 dropped 산출물 추가(`+:pr_review.txt,+:pr_review_dropped.txt,+:findings.json,+:scores.json,+:dropped.json`) + **빌드 타임아웃 추가**(기존 부재 — 하드닝 체크리스트 위반 상태).
7. **gitea 가드 보강**: gitea 템플릿에 head-SHA 가드가 없는 것이 기존 결함으로 발견됨 → 이 PR에서 GitHub과 동일한 가드 이식.
8. timeout-minutes: 15 → 25 (4개 플랫폼 전부 + verify.py 리터럴 3곳 동일 커밋 갱신).

### render.py / verify.py 계약 (동일 커밋 필수)
- **플레이스홀더 최소화**: 리플렉션 지시문 자체는 `inline_threads.py`와 동일한 **curl 다운로드 패턴**으로 전달 (플레이스홀더 아님). 불가피한 신규 플레이스홀더는 `__VERIFY_PROFILE__`, `__VERIFY_MODE__`, `__VERIFY_MAX_NITS__` 최소 집합으로 — **render.py 치환 목록 + verify.py PLACEHOLDERS 튜플 동시 갱신** (누락 시 침묵적 미치환 배포).
- **단일 모델 (D-4)**: 리플렉션 패스는 별도 모델 플레이스홀더·별도 config 없이 기존 `config.yaml`의 `GOOSE_MODEL`을 그대로 재사용 — per-call 모델 오버라이드 메커니즘 불필요 (검토자 ① MAJOR-4 해소, 두 goose 호출은 완전히 동일한 설정).
- `merge --out-final`은 **body.md를 그 자리에 덮어씀** → 기존 `verify.py`의 `"prepare --body body.md"` 리터럴 체크 그대로 통과.
- verify.py 신규 체크: verification on 시 — 리플렉션 스텝 존재, verify_findings.py 다운로드 존재, 마커 쌍 균형, reflect 원본 파일명이 게시 경로 미등장, `helper_selftest_errors`에 `verify_findings.py selftest` 추가. off/shadow 시 — 마커 부재.
- render.py 가드: 값 라인 == `EOF` 금지 (heredoc 조기 종료 방지), 값 내 `${{` 경고.
- 치환 순서 문서화 (`__INSTRUCTIONS__` 루프 첫 번째 → 지시문 내 리터럴 플레이스홀더 토큰 금지 규칙).

### 서브에이전트 검토 블로커 9건 요약 (본 계획에 반영 완료)
| # | 출처 | 블로커 | 반영 |
|---|---|---|---|
| B1 | CI/CD | 셀프부트스트랩: dogfood 아티팩트가 main의 구버전 헬퍼를 받아 PR CI 영구 적녹 | dogfood 재렌더 PR에서 제외 (Scope) |
| B2 | CI/CD | verify.py 타임아웃 리터럴 3곳·prepare 리터럴·PLACEHOLDERS 미갱신 시 4플랫폼 FAIL/침묵 배포 | 동일 커밋 갱신 계약 (Architecture) |
| B3 | CI/CD | 두 번째 goose의 API 키 바인딩 물리 조건 | 같은 스텝 run 블록 배치 (CI 요구사항 1) |
| B4 | LLM | 실행모델 모순 (원샷 vs repo checkout 검증) | 스모크 테스트 전제 (D-7), 툴 미지원 시 diff 범위 검증으로 축소 |
| B5 | LLM | 점수 의미론 미정의 + 측정 계획 부재 | 타당도 축 밴드 앵커 + 캘리브레이션 사전 + shadow-mode (D-6) |
| B6 | LLM | 동일 재시도 무의미 + fail-closed가 리뷰 소실 | 교정 재시도 + fail-open (D-2) |
| B7 | Python | split_threads clean=원문 전체, 위치 부재 → rebuild 이중 포함 | 파싱 프리미티브만 재사용 + 자체 위치 보존 워크 |
| B8 | Python | 플레이스홀더 미치환 배포 (render 치환 목록 하드코딩) | curl 다운로드 패턴 + 최소 플레이스홀더 + 동일 커밋 갱신 |
| B9 | Python | 증거 휴리스틱 한국어 구조적 false negative | 기계 검사 v1 삭제, 프롬프트로 이전 |

### 리스크 테이블
| 리스크 | 영향 | 완화 |
|---|---|---|
| 동일 모델 상관 편향 (단일 모델 정책, D-4) | 검증 효과 저하 | 프롬프트/절차 보완 4종: 반증 프레이밍 + 캘리브레이션 사전 + 페르소나 분리 + 검증 루브릭만 제공. shadow 실측(D-6)으로 게이트 효과 검증 — 부족이 입증되면 v1.5에서 교차 모델 도입 |
| 리플렉션 JSON 파싱 실패 | CI 실패율 | 관용 파서(펜스/산문 관용, 첫 `{`~마지막 `}` 폴백) + 교정 재시도 + fail-open |
| Verdict/Summary 재작성 문장 품질 | 게시 품질 | Verdict 섹션 전체 재생성 + Summary에 검증 노트 append (병합 스크립트의 명시적 책임) |
| 기존 사용자 산출물 드리프트 | 혼란 | 기존 정책: setup 레시피 재실행으로 갱신. README에 verification 도입 안내 |
| 비공개 리포 비용 2배 | 채택 저해 | `verification_gate=off` 옵션 + shadow 모드 + 비용 문서화 |
| 병합물 자기모순 (빈 Blocking + RC 등) | 게시 품질 | Verdict 재계산 규칙 통일 + 3곳(graded/README/reflection 프롬프트) 동시 반영 |
| heredoc/`${{`/Kotlin 마커 사고 | 배포 붕괴 | render.py 가드 3종 + 마커 배치 규칙 + verify 체크 |

### Functional Requirements
- **FR-1** 파인딩 목록을 `verify_findings.py extract`가 graded 본문에서 결정론적으로 추출 (정규화 앵커, 섹션, P태그, 본문; 인용 없는 불릿은 검증 대상 외 — 원문에 잔류하므로 무손실).
- **FR-2** 리플렉션 지시문은 반증 프레이밍 + 밴드 앵커 + 캘리브레이션 사전으로 score를 산출하고, `## Reflection` + JSON 블록만 출력한다.
- **FR-3** `merge`는 2D 매트릭스에 따라 keep/demote/drop을 판정하고, 강등 시 태그 재작성 + 섹션 이동, drop 시 dropped.json 기록, Verdict 섹션 재생성, Summary에 검증 노트 append, 55k 클램프를 적용한다.
- **FR-4** shadow 모드에서는 게시물을 원본 1차 리뷰로 유지하고 판정은 dropped.json + job summary에만 기록한다.
- **FR-5** fail-open 폴백이 "⚠️ 검증 미적용" 배너와 함께 1차 리뷰를 게시한다.
- **FR-6** 4개 플랫폼 전부에서 API 키 바인딩 1개, 하드닝 체크리스트, prepare 리터럴 계약이 유지된다.
- **FR-7** selftest가 단위 + end-to-end(merged final.md → `inline_threads.prepare` 재파싱 통과) 케이스를 포함한다.

### Test Plan
1. `python3 scripts/inline_threads.py selftest` (ANSI_RE 리팩터 후 기존 전 통과)
2. `python3 scripts/verify_findings.py selftest`:
   - 한국어 본문 + 정상 scores → keep/demote/drop 정확
   - Verdict 플립 (전 blockings drop → APPROVE) / dash 없는 `APPROVE.` 형태 재작성
   - 펜스 전후 산문, 라벨 없는 ``` 펜스, why 내 삼중 백틱
   - 중복 앵커 first-wins / unmatched conservative-keep·strict-drop
   - 카운트 일치 시만 order-index 폴백 / `## Reflection` 부재 → exit 1 / ANSI 오염
   - 강등 태그 재작성 + 🟡 이동 (인용 앞/뒤 태그 양측), 드롭으로 빈 섹션 note + 기존 note 무손상
   - **e2e: merged final.md → split_threads + validate_and_anchor 통과**
   - 임계값 경계, 빈 findings, final.md 55k 클램프
3. 렌더/검증 매트릭스: 4플랫폼 × {graded-review} × verification {on, off, shadow} `render --dry-run` → verify.py PASS (API 키 1개, 마커 균형, 타임아웃 25)
4. `goose run --instructions` 스모크 (D-7): 툴 가용성 실증
5. 종단 스모크: 새니티 리포 PR → 게시물 + job summary dropped 기록 + 인라인 앵커 정상 + (shadow→on 전환 실측)

# Delivery Steps

### Step 0: 착수 전제 확인
- [ ] D-7 스모크: `goose run --instructions` 툴 가용성 확인 (B4). 툴 미지원 시 리플렉션을 "diff 범위 검증"으로 축소하고 지시문에서 repo 탐색 문구 제거.

### Step 1: scripts/verify_findings.py (신규) + inline_threads.py 소규모 리팩터
- [ ] ANSI_RE 모듈 상수 추출 (cmd_extract 재사용화)
- [ ] extract: split_threads 기반 발견 목록 → findings.json (정규화 앵커, 섹션, P태그+legacy 폴백, 본문)
- [ ] reflect-parse: 센티널 → 첫 ```json 펜스 → 관용 파서 (첫 `{`~마지막 `}` 폴백, 펜스 무라벨 수용) → 스키마 관용 코어스
- [ ] merge: 위치 보존 자체 워크, 2D 매트릭스, 강등 태그 재작성, Verdict 섹션 재생성, Summary 노트 append, 빈 섹션 note, truncate_body, dropped.json, `N kept / M demoted / K dropped / U unmatched` 로그 라인
- [ ] selftest 전 케이스 (Test Plan 2)

### Step 2: templates/instructions.reflection.md + instructions.graded.md
- [ ] reflection: 반증 프레이밍, 검증 루브릭만, 밴드 앵커, 캘리브레이션 사전, 페르소나 분리, hunk 트리밍 입력, echo 지시, why English
- [ ] graded: 파인딩별 [P0]~[nit] 태그 필수화 + 매핑 표 + Verdict 규칙 문구 동기화

### Step 3: render.py + verify.py 계약 갱신 (동일 커밋)
- [ ] 치환 목록 + PLACEHOLDERS 동시 갱신, 마커 제거 로직 + 잔존 0 단언, EOF/`${{` 가드, docstring 갱신 (모델 관련 플레이스홀더 없음 — 단일 모델, D-4)
- [ ] verify.py: 타임아웃 리터럴 3곳 25, 리터럴 유지 확인(merge 덮어쓰기 방식), 신규 하드닝 체크, helper_selftest 확장

### Step 4: 4개 플랫폼 템플릿
- [ ] github: 같은 스텝 2차 goose, 사전 SHA 체크(GH_TOKEN), fail-open, 마커 배치, timeout 25
- [ ] gitlab: export 재반복 금지, 동일 흐름
- [ ] gitea: 동일 흐름 + head-SHA 가드 이식(기존 결함 보강)
- [ ] teamcity: scriptContent 내 bash 주석 마커, artifactRules 확장, 빌드 타임아웃 추가(기존 결함 보강)

### Step 5: 레시피 + 문서 + 배포 (동일 커밋)
- [ ] codegoose-setup.yaml: verification_gate(on|off|shadow, 기본 on), verify_gate_profile 파라미터 + `goose recipe validate` (모델 파라미터는 기존 goose_model 단일 유지)
- [ ] `python3 scripts/update_deeplinks.py` (launch.html + README 2개 — 딥링크 드리프트 방지, 동일 커밋)
- [ ] README.md / README.ko.md: 게이트 설명, 비용 ~2x, 임계값 권고(7-8 초과 금지), shadow 안내, 재렌더 안내
- [ ] 이슈 #10: 최종 설계 + 종결 상태 갱신
- [ ] 렌더/검증 매트릭스 전 조합 PASS 확인

### Step 6: 머지 후 후속 커밋 (PR 범위 외)
- [ ] `.github/workflows/codegoose-review.yml` 재렌더 (dogfood, verification=on) — B1
- [ ] dogfood PR로 shadow→on 실측 (D-6): keep/demote/drop률 기록, 필요 시 프로필 튜닝