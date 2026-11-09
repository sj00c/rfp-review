# 입찰서류 검토 — rfp-review

구매팀이 요청부서가 작성한 **(입찰)제안요청서·입찰공고문(안)·원가계산보고서**를 기관 입찰
체크리스트(국가계약법, 협상에 의한 계약체결기준, 감사원 공공계약 실무가이드 2024)로 검토해
**위반·누락·불일치**를 찾고, 원본 한글(HWPX) 문서의 해당 위치에 **형광펜과 메모(문제·수정안·근거)**를
달아 작성자에게 돌려보낼 파일과 회신 메시지를 만든다. (요청 시 수정요청표 엑셀도 생성)

이 저장소는 `SKILL.md`(frontmatter `name`·`description`) 형식의 **Agent Skill**이다. 하네스 전용 기능을 쓰지 않으므로
스킬 폴더를 읽는 코딩 하네스면 어디서나 그대로 동작한다. 폴더 이름은 `rfp-review`로 둔다(`name`과 같아야 한다).

| 하네스 | 설치 위치(사용자 전역) |
|---|---|
| Claude Code | `~/.claude/skills/rfp-review/` |
| Codex CLI | `~/.codex/skills/rfp-review/` |
| 그 외 | 하네스의 스킬 폴더. 스킬을 지원하지 않으면 `AGENTS.md` 등에 "입찰서류 검토 요청 시 `<경로>/rfp-review/SKILL.md`를 읽고 따른다"고 적는다 |

```bash
git clone http://161.122.37.49:8080/wyl4493/rfp-review.git ~/.codex/skills/rfp-review   # 예: Codex
```

사용자는 작성 중인 RFP와 관련 문서를 주고 “검토해 줘”라고 요청하면 된다.
스킬은 **`rfp-review` 하나**이며 추출·계산·메모 생성은 내부 처리 단계다.
별도 `rfp-run` 폴더나 Git 워크트리를 만들거나 중간 JSON을 직접 관리할 필요가 없다.

### 결과는 어디에 생기나?

기본 위치는 **주 입력 문서가 있는 폴더의 `output/`**다. 사용자가 출력 위치를 지정하면 그 경로를 우선한다.
이 저장소에 있는 문서를 검토하면 `C:\dev\rfp-review\output`에서 결과를 확인할 수 있다.
다른 폴더의 문서를 검토하면 그 문서 옆 `output`을 사용하며 설치 경로나 실행 위치에 고정하지 않는다.

```text
문서 폴더/
├── 제안요청서.hwp                   원본 그대로
└── output/
    ├── 제안요청서_검토메모.hwpx     기본 산출물
    ├── 제안요청서_2_검토메모.hwpx   기존 결과가 있으면 번호 증가
    └── 수정요청표_제안요청서.xlsx   요청 또는 메모 제공 불가 시
```

회신 초안은 기본적으로 채팅으로 제공하고 TXT는 요청할 때만 만든다.
구매팀 내부 확인사항은 작성자 수정 요청과 분리하여 **미해결 항목 전체의 이유·근거·담당 주체**를 채팅에 남긴다.
중간 변환본·추출 텍스트·JSON은 OS 임시 공간에서 처리한다. 결과 전달까지 성공하면 정리하고,
실패·중단 시에는 재개용 상태를 보존하여 위치를 안내한다. 원본·기존 결과·과거 작업 폴더는 자동 삭제하지 않는다.
최종 게시에만 출력 폴더의 전용 임시 파일을 사용한다. 완성된 바이트를 검증한 뒤 기존 파일을 덮어쓰지 않는 원자적 게시를 수행하며, 소유권이 확인된 임시 파일만 정리한다. 지원되지 않는 파일시스템이나 소유권 불명 상태에서는 자료를 보존하고 진단을 남긴다.

스크립트와 기준 파일은 `SKILL.md` 폴더 기준이다. 설치 코드와 실제 사업 문서·결과를 분리한다.

> ⚠️ 이 결과는 **AI 1차 검토**다. 최종 판단은 구매팀 담당자가 한다.

---

## 1. 저장소 구성

```
rfp-review/
├── SKILL.md                     # 에이전트가 따르는 규칙·검토·전달 절차
├── references/                  # 판정 기준 (여기만 고치면 동작이 바뀐다)
│   ├── checklist.md             #   입찰 체크리스트 v4 (①~⑥ 시트, 항목별 근거·판정방식)
│   ├── thresholds.json          #   금액·비율·일수 등 수치 기준 (check_numbers.py가 읽음)
│   ├── facts-schema.md          #   facts.json 작성법(영문) (check_numbers.py 입력 형식)
│   ├── output-format.md         #   review_<시트>.json 형식(영문) (판정 결과 형식)
│   ├── standard-phrases.md      #   표준 수정안 문구 (S-01 ~ S-13, ※초안)
│   └── feedback-notes.md        #   익명 피드백 사례·오탐/정탐 구분 (법적 근거 아님)
├── scripts/                     # 결정적 처리기 (Python)
│   ├── convert_to_hwpx.py       #   .hwp → .hwpx 변환 (한/글 COM)
│   ├── review_workspace.py      #   내부 임시 공간·재개·output 게시·정리
│   ├── extract_text.py          #   문서 → 위치표시 텍스트 (HWPX/HWP/PDF/DOCX/XLSX)
│   ├── show_lines.py            #   추출 텍스트를 줄 범위로 출력(하네스 출력 잘림 방지)
│   ├── outline.py               #   본문 제목 번호 목록·건너뜀/중복 표시
│   ├── checklist_items.py       #   적용 시트 항목만 출력 + 판정 주체(script/model/external)
│   ├── check_numbers.py         #   facts.json → 수치 항목 판정 (numeric_findings.json)
│   ├── validate_review.py       #   판정 검증: 원문 실재·근거 출처·id·항목 누락 검사
│   ├── annotate_hwpx.py         #   HWPX에 형광펜·메모 삽입 (핵심 산출물)
│   ├── make_report.py           #   검토 결과 → 수정요청표 엑셀
│   ├── safe_annotate.py         #   annotate 래퍼 — 한/글이 못 여는 메모를 자동 회피
│   ├── resave_hwpx.py           #   메모본을 한/글로 재저장(보안 경고 제거)
│   └── strip_scripts.py         #   HWPX 내 문서 스크립트 제거(변조 경고 제거)
└── tests/                       # 합성 자료 기반 회귀 테스트 (한/글 열기 검증과 별도)
```

샘플 입찰 문서와 검토 생성물은 `.gitignore`로 제외되어 있다(아래 **5. 보안** 참조).

---

## 2. 검토 파이프라인

에이전트는 `SKILL.md`의 절차에 따라 아래 흐름으로 스크립트를 조합한다.

```
[.hwp]                                              ① 변환(필요 시)
  └─ convert_to_hwpx.py ──▶ [.hwpx]

[.hwpx / .pdf / .docx / .xlsx]                      ② 텍스트 추출
  └─ extract_text.py ──▶ extracted/*.txt  (줄마다 [p.3] / [문단 41] / [시트!행] 위치표시)

[facts.json]  (모델이 문서에서 값 추출, facts-schema.md 형식)   ③ 수치 판정
  └─ check_numbers.py ──▶ numeric_findings.json

checklist_items.py ──▶ 적용 항목 목록 (판정 주체 표시)
[review_<시트>.json] (모델이 항목별 검토, output-format.md 형식)  ④ 문서 판정
  └─ validate_review.py ──▶ 원문·근거·누락 검사 (오류 0건까지 반복)

numeric_findings.json + review_*.json              ⑤ 산출물 생성
  ├─ annotate_hwpx.py ──▶ *_검토메모.hwpx   (형광펜+메모가 달린 한글 파일)
  └─ make_report.py   ──▶ 수정요청표_*.xlsx (요청 시)
```

**역할 분담이 핵심이다.**
- **스크립트**: 결정적 판정만 한다 — 수치 계산(check_numbers), 위치 매칭·메모 삽입(annotate),
  표 생성(make_report). 같은 입력이면 항상 같은 결과.
- **모델(에이전트)**: 문서에서 값·문장을 뽑아 `facts.json`/`review_<시트>.json`을 쓰고, 판정의 맥락을
  해석한다. 스크립트 판정이 맥락상 틀리면 facts.json을 고쳐 다시 돌린다.
- **검증기**: 모델이 쓴 원문이 실제 문서에 있는지, 근거가 체크리스트 근거란에 있는지, 적용 항목을
  빠짐없이 판정했는지 기계적으로 확인한다(할루시네이션 차단).

---

## 3. 실행 환경

- **Python 3.10+**
- HWPX 메모·형광펜 생성(`annotate_hwpx.py`)은 표준 라이브러리의 ZIP/XML 편집으로 동작한다.
- `.hwp` 변환과 한/글을 이용한 재저장·실제 열기 검증에는
  **Windows + 한/글(Hancom Office) 설치 + pywin32**가 필요하다.
  XML 구조 검사를 통과한 것만으로 한/글 실제 열기 성공을 주장하지 않는다.

### Python 의존성

| 스크립트 | 필요 패키지 | 비고 |
|---|---|---|
| extract_text.py | `pdfplumber` 또는 `pypdf`/`PyPDF2` (PDF), `openpyxl` (XLSX), `python-docx` 불필요(표준 zip 파싱) | HWPX/HWP는 표준 라이브러리만 사용 |
| check_numbers.py | 표준 라이브러리만 | — |
| make_report.py | `openpyxl` | — |
| annotate_hwpx.py / strip_scripts.py | 표준 라이브러리만 | HWPX는 zip+XML로 직접 편집 |
| convert_to_hwpx.py / resave_hwpx.py / safe_annotate.py | `pywin32`, (선택) `pyhwpx` | 한/글 COM 필요 |

```bash
pip install pdfplumber openpyxl pywin32
# 한/글 보안 경고 억제 모듈(FilePathCheckerModule.dll)을 번들로 쓰려면:
pip install pyhwpx
```

> **레지스트리 참고**: `convert_to_hwpx.py`는 한/글 자동화 보안 대화상자를 억제하기 위해
> `HKCU\Software\HNC\HwpAutomation\Modules`에 `FilePathCheckerModule` 경로를 등록한다.
> 악성 동작이 아니라 한/글 COM 자동화의 표준 패턴이며, 현재 사용자 레지스트리에만 쓴다.

### Agent의 실행 경로

보통 사용자는 아래 명령을 직접 실행하지 않는다. Agent가 `SKILL.md`를 따라 처리한다.
개발자가 점검할 때도 원본 옆에 중간물을 만들지 않고 먼저 내부 작업공간을 만든다.

```bash
python scripts/review_workspace.py begin "C:/문서/제안요청서.hwp" --input "공고문=C:/문서/공고문.hwpx" --reference references
python scripts/review_workspace.py status "<반환된 workspace 경로>"
```

반환된 입력 사본을 읽고 모든 중간 출력은 `<workspace>/work/`에 둔다.
스크립트는 설치 폴더의 절대 경로로 호출하며, HWP 변환에는 내부 목적지를 `-o`로 명시한다.
`checklist_items.py`의 `--sw`/`--non-sw`는 확인된 경우만 지정한다. 미지정은 SW 여부 미확인이지 비적용이 아니다.
생성된 `coverage.json`을 `validate_review.py --coverage`에 전달한다.

검증이 끝난 파일은 checkpoint 후 publish로 `output`에 저장한다. checkpoint 의존성은
`--depends-on`으로 연결하고 입력·기준·선행 결과가 바뀌면 영향받는 결과를 다시 만든다.
단, publish 계획이 시작된 뒤에는 게시 실패로 영수증이 없어도 해당 결과·선행 checkpoint를 바꾸지 않는다.
검토 내용을 바꿔야 하면 새 내부 임시 공간에서 시작하고 기존 계획·임시 파일 소유권은 보존한다.
구매팀 확인사항 전체와 별도의 작성자 회신 초안을 채팅으로 전달한 뒤에만 handoff checkpoint와 cleanup을 호출한다.
명령별 인자는 `python scripts/review_workspace.py <명령> --help`, 전체 절차는 `SKILL.md`에 있다.

### 검증 범위

`python -m unittest discover -s tests`는 계산·파일 보전·검증기·메모 구조를 확인한다.
별도로 합성 RFP를 실제 Agent에 제공하여 정상 사례의 오탐과 실제 오류의 탐지를 확인한다.
사전 작성한 JSON의 테스트 통과는 Agent 문맥 판단의 성공을 뜻하지 않는다.
한/글 COM을 실행하지 못한 환경에서는 실제 열기 검증을 미실행으로 표시한다.

---

## 4. 체크리스트/기준 개정

기준의 문구·값·적용 범위를 `references/`에서 관리한다. 계산 의미나 필드가 달라지면
계산기·검증기·메모·보고서 소비자와 테스트도 함께 수정해야 한다.
법령·공식 기준, 기관 운영 기준, 이번 사업의 조건을 구분하며 구매팀 사례를 보편적 법률로 일반화하지 않는다.

- 점검 항목·근거 변경 → `references/checklist.md` (항목별 `[문서]/[계산]/[확인]` 태그 유지)
- 금액·비율·일수 변경 → `references/thresholds.json` (check_numbers.py에 자동 반영)
- 확정 수정안 문구 변경 → `references/standard-phrases.md`
- 스크립트가 판정하는 항목·범위 변경 → `scripts/check_numbers.py`의 `SCRIPT_SCOPE` (판정 코드와 함께)
- 고친 뒤 `python -m unittest discover -s tests` — 체크리스트 참조·근거·스크립트 범위가 서로 맞는지 검사한다

`standard-phrases.md`는 현재 **초안 상태**다. 구매팀이 실제 쓰는 확정 문구로 교체하는 것이 좋다.

---

## 5. 보안 — 업로드 전 확인사항

**이 저장소에는 자격증명·API 키·비밀번호가 없다.** 다만 다음은 공개 저장소에 올리면 안 되므로
`.gitignore`로 제외되어 있다. 커밋 전에 반드시 확인한다.

| 제외 대상 | 이유 |
|---|---|
| `Sample/` | **실제 입찰 문서**(기관 제안요청서·공고문 원본·검토 산출물). 내부 자료이므로 공개 금지. |
| `output/`, `extracted/`, `*_검토메모.hwpx`, `*_검토회신.txt`, `facts.json`, `review*.json`, `review_notes.md`, `numeric_findings.json`, `수정요청표*.xlsx` | 특정 사업 검토 생성물. 사업명·금액·업체 정보가 들어갈 수 있음. |
| `RE_ RE_ *.zip` | 구매팀에서 받은 실제 문서와 피드백 첨부. 익명 사례 요약만 기준 자료로 관리한다. |
| `.omc/`, `.claude/`, `.codex/`, `.gjc/` | 개인 작업 세션 상태·전사(transcript). 세션 ID 등 개인 작업 흔적. |
| `__pycache__/` | 빌드 캐시. |

### 커밋 전 자가 점검
```bash
git status            # Sample/·.omc/·생성물이 staged 되지 않았는지 확인
git ls-files          # 추적 대상에 *.hwp / *.hwpx / facts.json 등이 없는지 확인
```

### 판단이 필요한 내용 (업로더가 결정)
`references/checklist.md`와 `thresholds.json`에는 **KIST 내부 운영 기준**이 일부 포함돼 있다
(예: "KIST 통상 운영은 가격 20% 이내", "가격 중시형 최대 50%", "KIST 실무 점검사항 1~4",
"KIST 내부 계약규정"). 자격증명은 아니지만 기관 내부 업무 관행이므로, 공개 저장소 공개가
적절한지 조직 차원에서 확인한 뒤 올리는 것을 권한다. (본 저장소가 KIST 조직 저장소라면 무방.)

---

## 6. 라이선스·근거 출처

체크리스트의 근거는 국가계약법령·계약예규 및 **감사원 공공계약 실무가이드(2024)** 쪽수를 인용한다.
근거 조문·문구는 `references/checklist.md`의 근거란에서만 가져오며, 스크립트/모델이 조문을
새로 지어내지 않는다.
