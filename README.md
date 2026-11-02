# rfp-review — 제안요청서·공고문 입찰서류 검토 스킬

구매팀이 요청부서가 작성한 **(입찰)제안요청서·입찰공고문(안)·원가계산보고서**를 기관 입찰
체크리스트(국가계약법, 협상에 의한 계약체결기준, 감사원 공공계약 실무가이드 2024)로 검토해
**위반·누락·불일치**를 찾고, 원본 한글(HWPX) 문서의 해당 위치에 **형광펜과 메모(문제·수정안·근거)**를
달아 작성자에게 돌려보낼 파일과 회신 메시지를 만든다. (요청 시 수정요청표 엑셀도 생성)

이 저장소는 [Claude Code](https://claude.com/claude-code)의 **Skill**로 동작한다.
`~/.claude/skills/rfp-review/` 에 내용을 두면 Claude가 관련 요청 시 자동으로 불러 쓴다.

> ⚠️ 이 결과는 **AI 1차 검토**다. 최종 판단은 구매팀 담당자가 한다.

---

## 1. 저장소 구성

```
rfp-review/
├── SKILL.md                     # 스킬 본문 — Claude가 따르는 검토 절차(0~6단계)
├── references/                  # 판정 기준 (여기만 고치면 동작이 바뀐다)
│   ├── checklist.md             #   입찰 체크리스트 v4 (①~⑥ 시트, 항목별 근거·판정방식)
│   ├── thresholds.json          #   금액·비율·일수 등 수치 기준 (check_numbers.py가 읽음)
│   ├── facts-schema.md          #   facts.json 작성법 (check_numbers.py 입력 형식)
│   ├── output-format.md         #   review.json 형식 (판정 결과 형식)
│   └── standard-phrases.md      #   표준 수정안 문구 (S-01 ~ S-13, ※초안)
└── scripts/                     # 결정적 처리기 (Python)
    ├── convert_to_hwpx.py       #   .hwp → .hwpx 변환 (한/글 COM)
    ├── extract_text.py          #   문서 → 위치표시 텍스트 (HWPX/HWP/PDF/DOCX/XLSX)
    ├── check_numbers.py         #   facts.json → 수치 항목 판정 (numeric_findings.json)
    ├── annotate_hwpx.py         #   HWPX에 형광펜·메모 삽입 (핵심 산출물)
    ├── make_report.py           #   검토 결과 → 수정요청표 엑셀
    ├── safe_annotate.py         #   annotate 래퍼 — 한/글이 못 여는 메모를 자동 회피
    ├── resave_hwpx.py           #   메모본을 한/글로 재저장(보안 경고 제거)
    └── strip_scripts.py         #   HWPX 내 문서 스크립트 제거(변조 경고 제거)
```

샘플 입찰 문서와 검토 생성물은 `.gitignore`로 제외되어 있다(아래 **5. 보안** 참조).

---

## 2. 검토 파이프라인

Claude는 `SKILL.md`의 절차에 따라 아래 흐름으로 스크립트를 조합한다.

```
[.hwp]                                              ① 변환(필요 시)
  └─ convert_to_hwpx.py ──▶ [.hwpx]

[.hwpx / .pdf / .docx / .xlsx]                      ② 텍스트 추출
  └─ extract_text.py ──▶ extracted/*.txt  (줄마다 [p.3] / [문단 41] / [시트!행] 위치표시)

[facts.json]  (모델이 문서에서 값 추출, facts-schema.md 형식)   ③ 수치 판정
  └─ check_numbers.py ──▶ numeric_findings.json

[review.json] (모델이 항목별 검토, output-format.md 형식)       ④ 문서 판정

numeric_findings.json + review.json                ⑤ 산출물 생성
  ├─ annotate_hwpx.py ──▶ *_검토메모.hwpx   (형광펜+메모가 달린 한글 파일)
  └─ make_report.py   ──▶ 수정요청표_*.xlsx (요청 시)
```

**역할 분담이 핵심이다.**
- **스크립트**: 결정적 판정만 한다 — 수치 계산(check_numbers), 위치 매칭·메모 삽입(annotate),
  표 생성(make_report). 같은 입력이면 항상 같은 결과.
- **모델(Claude)**: 문서에서 값·문장을 뽑아 `facts.json`/`review.json`을 쓰고, 판정의 맥락을
  해석한다. 스크립트 판정이 맥락상 틀리면 같은 id로 `review.json`에 덮어쓴다.

---

## 3. 실행 환경

- **Python 3.10+**
- 메모·형광펜 산출물(`annotate_hwpx.py`)과 `.hwp` 변환(`convert_to_hwpx.py`)은
  **Windows + 한/글(Hancom Office) 설치 + pywin32** 환경에서만 동작한다(COM 자동화).
  그 외 환경에서는 텍스트 추출·수치 판정·엑셀 생성까지만 가능하다.

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

### 수동 실행 예시

```bash
python scripts/convert_to_hwpx.py "제안요청서.hwp"                       # → 제안요청서.hwpx
python scripts/extract_text.py 제안요청서.hwpx 공고문.hwpx 원가.xlsx -o extracted/
python scripts/check_numbers.py facts.json -o numeric_findings.json
python scripts/annotate_hwpx.py 제안요청서.hwpx numeric_findings.json review.json \
    --doc 제안요청서 -o 제안요청서_검토메모.hwpx
python scripts/make_report.py numeric_findings.json review.json -o 수정요청표.xlsx
```

---

## 4. 체크리스트/기준 개정

법령·예규가 바뀌면 **`references/` 파일만** 고치면 된다. 스크립트 코드는 건드리지 않는다.

- 점검 항목·근거 변경 → `references/checklist.md` (항목별 `[문서]/[계산]/[확인]` 태그 유지)
- 금액·비율·일수 변경 → `references/thresholds.json` (check_numbers.py에 자동 반영)
- 확정 수정안 문구 변경 → `references/standard-phrases.md`

`standard-phrases.md`는 현재 **초안 상태**다. 구매팀이 실제 쓰는 확정 문구로 교체하는 것이 좋다.

---

## 5. 보안 — 업로드 전 확인사항

**이 저장소에는 자격증명·API 키·비밀번호가 없다.** 다만 다음은 공개 저장소에 올리면 안 되므로
`.gitignore`로 제외되어 있다. 커밋 전에 반드시 확인한다.

| 제외 대상 | 이유 |
|---|---|
| `Sample/` | **실제 입찰 문서**(기관 제안요청서·공고문 원본·검토 산출물). 내부 자료이므로 공개 금지. |
| `extracted/`, `*_검토메모.hwpx`, `facts.json`, `review.json`, `numeric_findings.json`, `수정요청표*.xlsx` | 특정 사업 검토 생성물. 사업명·금액·업체 정보가 들어갈 수 있음. |
| `.omc/`, `.claude/` | 개인 작업 세션 상태·전사(transcript). 세션 ID 등 개인 작업 흔적. |
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
