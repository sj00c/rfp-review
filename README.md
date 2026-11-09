# RFP 검토 — rfp-review

사용자가 준 **검토 지침 파일**(엑셀·한글·PDF·워드·텍스트)과 **작성 중인 제안요청서(RFP)**를 받아,
지침에 근거해 문제가 있는 곳에 **형광펜과 메모(문제·수정안·근거)**를 단 한글(HWPX) 검토본을 돌려준다.
예산·수치 불일치, 오타·빈칸·자리표시자, 문서 간 모순도 함께 확인한다.

- 근거는 **지침과 제출 문서뿐**이다. 지침에 없는 법령·기준·상식으로는 지적하지 않는다.
- 원본은 바꾸지 않는다. 결과는 새 파일이며 기존 결과도 덮어쓰지 않는다(`_2`, `_3` …).
- 결과물은 한글 검토본과 짧은 완료 안내뿐이다.

> ⚠️ 결과는 **AI 1차 검토**다. 최종 판단은 담당자가 한다.

## 설치

`SKILL.md` 형식의 Agent Skill이다. 폴더 이름은 `rfp-review`로 둔다.

| 하네스 | 설치 위치(사용자 전역) |
|---|---|
| Claude Code | `~/.claude/skills/rfp-review/` |
| Codex CLI | `~/.codex/skills/rfp-review/` |
| 그 외 | 하네스의 스킬 폴더. 스킬을 지원하지 않으면 `AGENTS.md` 등에 "RFP 검토 요청 시 `<경로>/rfp-review/SKILL.md`를 읽고 따른다"고 적는다 |

필요: Python 3.10+, 엑셀 지침이면 `openpyxl`. `.hwp` 변환과 한/글 열기 확인은 Windows + 한/글 + `pywin32`가 필요하다(`.hwpx`만 쓰면 불필요).

## 사용

지침 파일과 RFP 초안을 주고 "검토해 줘"라고 요청한다. 공고문·원가계산서 등을 함께 주면 문서 간 대조도 한다.

```text
문서 폴더/
├── 검토지침.xlsx                  원본 그대로
├── 제안요청서.hwp                 원본 그대로
└── output/
    ├── 제안요청서_검토메모.hwpx    결과
    └── 제안요청서_검토메모_2.hwpx  같은 이름이 이미 있으면 번호 증가
```

- 결과 위치: RFP가 있는 폴더의 `output/`, 또는 사용자가 지정한 폴더.
- 작업 중 파일은 `output/.rfp-review/<RFP 이름>/`에 두고, 끝나면 지운다. 중간에 멈추면 그 자리에서 이어 한다.
  이어 할 때 입력 파일이 바뀌었으면(`extract_text.py --check`) 처음부터 다시 한다.

## 구성

```
rfp-review/
├── SKILL.md                 에이전트가 따르는 규칙과 절차
├── scripts/
│   ├── extract_text.py      문서 → 위치 표시 텍스트([문단 n], [p.n], [시트!n행]), 입력 해시 기록·재개 확인
│   ├── show_lines.py        추출 텍스트를 8KB씩 나눠 보기
│   ├── check_numbers.py     같아야 할 값·합계를 정확히 계산해 어긋난 곳만 지적
│   ├── validate_review.py   인용이 문서에, 근거가 지침에 실제로 있는지 검사
│   ├── annotate_hwpx.py     HWPX에 형광펜·메모·요약 메모 달기(덮어쓰기 없음)
│   ├── convert_to_hwpx.py   .hwp → .hwpx (한/글 COM)
│   ├── strip_scripts.py     HWPX 문서 스크립트 제거('손상' 경고 대응)
│   ├── resave_hwpx.py       한/글로 다시 저장('손상' 경고 대응)
│   └── safe_annotate.py     한/글이 못 여는 메모만 요약 메모로 옮겨 다시 만들기(한/글 필요)
└── tests/                   python -m unittest discover -s tests
```

## 테스트

```bash
python -m unittest discover -s tests
```

HWPX는 최소 구조로 직접 만들어 한/글 없이 돌아간다. 실제 한/글에서 열리는지는 테스트하지 않는다(Windows에서 따로 확인).
