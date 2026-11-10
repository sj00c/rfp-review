# rfp-review

- 작성 중인 제안요청서(RFP)를 사용자가 준 검토 지침에 맞춰 점검하는 Agent Skill
- 결과: 고칠 곳에 형광펜·메모를 단 한/글(HWPX) 검토본
- AI 1차 검토. 최종 판단은 담당자

## 설치

- 필요: Python 3.10 이상 (필수 패키지 없음)
- 선택: Windows + 한/글(`.hwp` 변환·결과 열림 확인), `pip install pypdf`(PDF 읽기)
- Claude Code: `git clone https://github.com/sj00c/rfp-review ~/.claude/skills/rfp-review`
- Codex CLI: `git clone https://github.com/sj00c/rfp-review ~/.codex/skills/rfp-review`
- 업데이트: 설치 폴더에서 `git pull`

## 사용

- 요청: 지침 파일 + RFP를 주고 "검토해 줘"
- RFP: `.hwpx` 또는 `.hwp` (`.hwp`는 한/글이 깔린 Windows에서 자동으로 HWPX 변환. 그 밖의 환경은 한/글에서 HWPX로 저장해 줄 것)
- 지침·관련 문서: `.xlsx` `.xlsm` `.hwpx` `.hwp` `.docx` `.txt` `.md`
- 공고문·원가계산서 등 함께 주면 문서 간 대조
- PDF: `pip install pypdf`(또는 pdfplumber)가 있을 때만 읽음. 스캔 PDF·이미지는 읽지 않음
- 결과 위치: RFP 폴더의 `output/<RFP 이름>_검토메모.hwpx`
- 원본은 수정하지 않음. 같은 이름이 있으면 `_2`, `_3`으로 새로 저장

## 검토본

- 빨강(필수 수정): 참가자격·배점·금액·제출 방법 등 공고 전 반드시 고칠 곳
- 노랑(수정 필요): 그 밖의 오류(오타·번호·문구)
- 파랑(확인 요청): 문서만으로 판단할 수 없어 작성자 확인이 필요한 곳
- 메모 내용: 현재 문구, 문제, 수정안, 근거(지침 원문)
- 첫 문단에 전체 요약 메모
- 근거는 지침과 제출 문서뿐. 지침에 없는 내용은 지적하지 않음
- 예외: 오타·빈칸·금액 불일치·문서 간 모순은 지침 없이도 지적

## 구성

- `SKILL.md`: 에이전트가 따르는 규칙과 절차
- `scripts/hancom.py`: 한/글로 `.hwp` → `.hwpx` 변환, 결과 열림 확인, 재저장(Windows + 한/글, PowerShell 사용)
- `scripts/extract_text.py`: 문서 → 위치 표시 텍스트, 재개용 입력 확인
- `scripts/show_lines.py`: 추출 텍스트 나눠 보기
- `scripts/check_numbers.py`: 금액·합계 비교
- `scripts/validate_review.py`: 인용·근거가 실제 문서·지침에 있는지 검사
- `scripts/annotate_hwpx.py`: HWPX에 형광펜·메모 달기

## 주의

- 한/글이 없는 환경에서는 결과 파일이 한/글에서 열리는지 확인하지 못함. 한/글에서 한 번 직접 열어 볼 것
