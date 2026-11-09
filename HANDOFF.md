# rfp-review 작업 인계

## 1. 가장 먼저 알아야 할 상태

- 사용자가 다른 환경으로 옮기기 위해 **작업 중단, 이 인계 문서 작성, 현재 작업 커밋**을 요청했다.
- **현재 코드는 이전 개선 작업의 결과다. 아래 간소화 요구사항은 아직 구현하지 않았다.** README/SKILL에 남은 별도 보고서·회신·고정 기준 안내를 새로운 요구사항으로 오해하지 말 것.
- 간소화 요구사항 인터뷰는 사용자가 확정했다. Planner 계획과 Architect/Critic 검토까지 끝났다.
- Architect: **CLEAR / APPROVE**, Critic: **OKAY**. 둘 다 같은 stage-01-planner 계획을 검토했다.
- 그러나 **최종 의도 확인 기록과 final/pending-approval 계획 저장 전에 사용자가 중단했다. 간소화 구현·파일 삭제는 아직 승인되지 않았다.** 이번 커밋 승인은 간소화 구현 승인과 다르다.
- 새로운 환경에서는 이 문서부터 읽고 남은 계획 마무리와 구현 승인 경계를 지킬 것. 완료된 이전 Ultragoal을 재실행하지 말 것.
- 사용자는 과도한 질문·검토·상태 관리 개발에 강한 피로감을 보였다. 이미 확정한 입력 역할 등을 다시 질문하지 말고, 실제 필요한 변경과 집중 검증만 할 것.

## 2. 사용자 확정 요구사항 — 변경하지 말 것

> 지정된 엑셀 지침만을 근거로 작성 중인 한글 RFP를 검토하여 원문을 바꾸지 않고 문제 위치에 형광펜·메모·수정안과 필요한 ‘확인 필요’ 사유를 남긴 별도 한글 파일과 짧은 완료 안내만 제공하되, 원본·기존 결과 보호와 중간 재개는 유지하도록 기존 스킬을 단순화한다.

- **Excel = 정확한 검토 지침. HWP/HWPX = 사람이 1차 또는 N차로 작성한 RFP.** Excel은 결과 보고서가 아니다.
- 본문을 직접 고치지 않는다. 형광펜·메모에 문제와 수정안을 남긴다.
- 최종 전달은 **한글 검토본 + 짧은 완료 안내**뿐이다.
- 별도 수정요청표 XLSX, 회신 TXT/초안, 구매팀 확인사항 목록은 제외한다.
- 사용자가 **중간 진행 상태 저장과 이어서 처리**를 명시적으로 선택했다. 단순화 명목으로 재개 기능을 없애면 안 된다.
- ‘확인 필요’와 이유는 한글 메모에 남긴다. 단, 해당 항목 자체가 Excel 지침의 범위 안에 있어야 한다.
- **지침에 없는 규칙·법규·임계값·상식·추측으로 지적을 추가하지 않는다.** 외부 지식을 독립 근거로 보충하지 않는다. 지침 밖 지적을 ‘확인 필요’로 우회해서도 안 된다.
- 각 지적은 실제 Excel 항목과 RFP 내용에 연결되어야 한다. 문구·근거·위치를 지어내지 않는다. 자료 부족을 적합이나 확정 오류로 바꾸지 않는다.
- 원본·기존 결과·실제 입찰자료·기존 작업물은 보존한다. 기존 결과 덮어쓰기 금지.
- 단일 스킬 `rfp-review` 유지. 새로운 플랫폼·러너·규칙 엔진·사용자 관리 작업 폴더·워크트리는 만들지 않는다.
- 출력 기본 위치는 기존처럼 **주 RFP 파일 부모의 `output/`**, 사용자 지정 경로가 있으면 우선한다. 설치 경로나 cwd를 기본 출력 위치로 삼지 않는다.
- 입력/Excel이 달라졌으면 이전 판정을 조용히 재사용하지 않는다.

## 3. 검토된 계획의 결정과 변경 대상

**선택 A:** 기존 생산자·검증기·메모 소비자를 실제 Excel 항목에 직접 연결하고 고정 기준/부가 보고 경로를 제거한다. 변환·계산·안전한 재개/게시 구현은 가능한 한 재사용한다.

**기각한 B:** 내장 기준을 그대로 둔 채 Excel 허용 목록으로 필터링. 초기 변경은 작지만 이중 기준과 오래된 정책값의 유출 위험을 계속 관리해야 한다.

| 대상 | 계획된 처리 |
|---|---|
| `scripts/extract_text.py` | Excel 입력 유지. 실제 workbook/시트/셀 출처를 보존한다. Excel 출력 제거와 혼동하지 않는다. |
| `scripts/checklist_items.py` | 고정 Markdown 체크리스트 파서·시트기호/SW 선택·`SCRIPT_SCOPE` 결합·external finding 자동 생성을 제거하고, 실제 Excel의 항목 manifest/출처를 다루도록 변경한다. |
| `scripts/check_numbers.py` | 무조건 전체 검사와 고정 ID 발행을 없앤다. 실제 Excel 항목 및 수치 기준에 연결된 계산만 수행한다. 기존 산술 함수는 재사용한다. |
| `scripts/validate_review.py` | 지침 원문/셀·항목 ID·수치 조건·RFP 문서/위치/인용을 공통 검증한다. 내장 체크리스트/threshold 의존, 다른 항목의 근거 허용, 문서 전체를 합친 인용 검사 등을 정리한다. |
| `scripts/annotate_hwpx.py`, `scripts/safe_annotate.py` | 같은 지침 검증을 사용한다. 범위 내 수정필요/확인필요가 한글에 남도록 옛 대상 필터와 기준 상속을 제거한다. 복구와 no-clobber는 유지한다. |
| `scripts/review_workspace.py` | 기존 begin/status/checkpoint/무효화/게시/보호 기능 재사용. 최종 게시를 검토본 HWPX 하나로 제한하고 XLSX/TXT 게시 경로를 제거한다. 상태 시스템 전체 재작성 금지. |
| `README.md`, `SKILL.md`, `references/facts-schema.md`, `references/output-format.md` | 새 입력·근거 계약과 단일 결과 흐름으로 갱신한다. |
| `references/feedback-notes.md` | 필요하면 비권위 회귀 사례 설명으로 유지하되 런타임 필수 기준에서 제외한다. |
| `scripts/make_report.py` | 소비자와 문서 예시, 보고 전용 테스트를 먼저 정리한 뒤 제거한다. |
| `references/checklist.md`, `references/thresholds.json`, `references/standard-phrases.md` | 소비자가 실제 Excel 계약으로 전환된 뒤 고정 기준·인용·문구 재유입 경로로서 제거한다. 사용자 Excel은 삭제 대상이 아니다. |
| `scripts/convert_to_hwpx.py`, `scripts/resave_hwpx.py`, `scripts/strip_scripts.py`, `scripts/show_lines.py`, `scripts/outline.py` | 변환·복구·읽기 기능 재사용. 단, outline 번호 누락 등을 지침 없이 자동 지적으로 만드는 안내는 제거한다. |
| `tests/test_*.py` 7개 | 변경된 계약에 맞춰 fixture와 기대값을 수정한다. 보고 전용 테스트만 제거/대체하고 원본 보호·본문 보존·재개 회귀를 지우지 않는다. |

### 중요한 실제 소비자 함정

- `annotate_hwpx.py`의 `checklist_item`, `finding_target`, `load_findings`, `memo_lines`는 고정 기준 상속과 작성자 전용 필터를 갖고 있다. 현재는 `확인필요`도 `질의`/`include_check` 조건에 따라 빠진다.
- 별도 구매팀 목록만 없애고 이 필터를 그대로 두면 **Excel 범위 내 확인필요가 최종 결과에서 사라진다.** 담당자 표시는 필요하면 메모 안에 남기되, 담당자 때문에 관련 지적을 숨기지 않는다.
- `safe_annotate._author_actionable` 등 복구 경로도 같은 계약으로 바꿔야 한다.
- `checklist_items.py`는 고정 체크리스트에서 구매팀용 외부 확인 finding을 자동 생성한다. 이 경로도 제거 대상이다.
- `tests/test_rendering.py`에는 옛 대상 제외와 make_report 동작 기대가 함께 있다. 테스트 파일 전체를 삭제하면 안 된다.
- `extract_text.from_xlsx`는 현재 `openpyxl.load_workbook(..., data_only=True, read_only=True)`로 읽는다. 수식 캐시 없음·병합 셀 등으로 지침이 읽히지 않았는데 빈 검토 성공으로 처리하면 안 된다.

## 4. 검토된 최소 데이터 계약

- 기존 workspace에서 RFP를 primary, 지정 Excel을 `--input 지침=<xlsx>`로 등록하여 둘 다 fingerprint와 내부 복사를 유지한다.
- 기존 `items/coverage.json`을 단일 항목 manifest로 재사용한다. 별도 registry나 규칙 저장소를 만들지 않는다.
- manifest에는 실제 입력 Excel ID/hash, 시트, 기준 셀범위, 실제 셀 원문, 항목 ID, 제한된 읽기 파일 목록을 기록한다. 고정 헤더나 ①~⑥ 시트를 요구하지 않는다.
- 항목 ID는 workbook SHA-256 + 시트 + 기준 셀범위를 정규화해 만든다. 동일 입력에서 안정적이고 Excel 변경 시 달라져야 한다.
- 모델은 manifest 항목만 검토한다. finding에는 지침 ID와 RFP 문서ID·위치·인용·판정·사유·수정안/확인 내용을 연결한다. Excel에 없는 필수 등급을 만들어내지 않는다.
- 숫자 검사도 각 하위 판정마다 연결을 강제한다. 기준값·단위·비교 방향·적용 조건은 실제 Excel 셀에 맞아야 한다. 85/70/100/VAT/기간 등 내장 정책 숫자를 독립 기준으로 쓰지 않는다.
- 기존 함수로 표현할 수 없는 계산을 위해 수식 DSL을 새로 만들지 않는다. 지침에 따른 모델 검토로 넘기되, 코드의 계산 미지원 자체를 RFP 결함으로 표시하지 않는다.
- 공통 loader는 `checklist_items.py`, 공통 finding 검증은 `validate_review.py`에 둔다. 기존 역방향 `SCRIPT_SCOPE` import를 제거하여 순환 의존을 피한다.
- `check_numbers`/`validate_review`/`annotate_hwpx`에 필수 `--guidelines <coverage.json>`을 연결하고 safe_annotate도 전달한다.
- 원 workbook과 셀을 대조한다. 자기신고 JSON의 hash만 맞는 것으로 검증 완료 처리하지 않는다. 미등록 ID, 다른 항목 근거, 위조 수치/인용/문서 위치, 중복 결과를 거부한다.
- 위치를 확정하지 못하면 실제 인접 제목/문구 또는 기존 요약 메모에 불확실성을 밝힌다. 정확한 위치에 달았다고 거짓 보고하지 않는다. 안전한 메모 생성도 불가능하면 실패 안내와 내부 상태 보존으로 끝낸다.
- 구형 고정 체크리스트 결과는 새 검증에서 거부하되 과거 workspace를 삭제하지 않는다. 호환 레이어나 migration을 추가하지 않는다.

## 5. 구현 순서와 집중 검증 — 아직 실행 승인 없음

순서: **Excel 항목/출처 → 모델·숫자·검증 계약 → 메모·복구 소비자 → 게시/문서/고정 경로 제거 → 관련 테스트**.

완료 기준:
1. 실제 Excel의 임의 시트명/항목을 읽으며, 지침 부재·미판독을 내장 기준으로 대체하지 않는다.
2. 지침 없는 규칙은 메모 0건. 관련 Excel 항목을 추가/변경했을 때만 해당 검토/기준이 바뀐다.
3. 범위 내 근거 부족은 이유 있는 확인필요 메모가 되고 범위 밖 자료 부족은 지적하지 않는다.
4. 문제 위치에 형광펜·문제·Excel 근거·수정안이 있고 RFP 본문/표/개체와 기존 사용자 메모를 보존한다.
5. 성공 시 최종 파일은 HWPX 하나, 안내는 짧게. 내부 TXT/JSON과 별도 보고서/회신/목록은 전달하지 않는다.
6. 중단 후 재개, 변경 입력의 stale 차단, 기존 결과 충돌 시 별도 이름, 동일 게시 재시도 중복 없음, 원본/기존 결과 hash 불변.
7. ZIP/XML 검사와 **실제 한/글 열기·메모 확인**을 구분한다. 실제 열기를 실행하지 않고 성공했다고 쓰지 않는다.

- 관련 테스트: `test_extraction_evidence.py`, `test_review_contract.py`, `test_numeric_context.py`, `test_scripts.py`, `test_rendering.py`, `test_safe_annotate.py`, `test_workspace.py`.
- 현재 표준 명령: `python -m unittest discover -s tests`. 새 구현 후 변경 범위에 맞춰 한 번 검증한다. Windows 한/글 COM 확인은 별도이며 설치 환경이 필요하다.
- 실제 스킬에 합성 Excel+RFP를 주어 지침 밖 유혹/지침 내 오류/자료 부족을 확인한다. 정답 findings를 미리 넣은 테스트만으로 모델 검토 성공을 주장하지 않는다.
- 새로운 benchmark 플랫폼이나 이전의 방대한 다중 검토 캠페인을 만들지 않는다. 측정하지 않은 속도 개선을 주장하지 않는다.
- ‘할루시네이션 금지’는 근거·인용·범위·검토 사례로 검증할 요구사항이다. 유효한 셀 인용만으로 모든 의미 판단이 무오류라고 보증할 수는 없다.

## 6. 현재 코드에 이미 완료된 이전 작업

현재 커밋 대상에는 과거 개선 작업과 그 전의 미커밋 작업이 함께 포함된다. 새 간소화 구현으로 표현하면 안 된다.

- HWP/HWPX 추출·위치·개체 증거, 중복 이름/기존 출력 보호.
- 근거 유형·적용성·문서 역할/범위·확인 대상이 있는 판정 계약과 수치/부가세/평가 배점 처리.
- 실제 메모 생성과 실패 복구, 원본 보존, 한/글 재열기 검증.
- workspace v3: 입력 fingerprint, checkpoint 의존성, 상태 보존/재개, 원자적 no-clobber 게시, 소유권 기반 임시 파일 처리, 게시 계획 불변성, manifest 중단 복구.
- 이전 최종 기록: **151 tests run, 150 passed, 1 skipped**. symlink 권한 관련 1건 skip; 별도 실제 Windows junction 보존 확인 기록이 있다.
- 실제 합성 A–D, 예산 E/F/G, 공고–RFP 공동수급 J-N/J-P 검토·메모·한/글 재열기 증거가 이전 환경에 남아 있다.
- 이전 G004는 최종 gate 통과 후 complete, G001/G002/G003는 superseded다. 완료된 이 목표를 다시 활성화하지 않는다.
- 위 테스트/COM 결과는 **이전 실행 기록**이며 간소화 코드의 검증 결과가 아니다. 인계/커밋을 위해 COM이나 의미 검토를 다시 실행하지 않는다.

## 7. 로컬 기록과 다른 환경으로 옮길 때의 한계

`.gjc/`, `tests/artifacts/review_*.json`, 실제 입찰자료/ZIP, `output/`, OS 임시 디렉터리는 Git에서 제외되어 있다. **이 문서는 그 파일 없이도 핵심 요구사항과 계획을 이어갈 수 있게 작성했다.** 실제 사용자 Excel/RFP는 별도로 안전하게 전달해야 하며 저장소에 올리지 않는다.

원래 환경에서의 기록:
- session: `01a1a930-9604-776b-858b-be66a55be851`
- 새 plan run: `rfp-review-minimal-20261109`
- spec: `.gjc/_session-01a1a930-9604-776b-858b-be66a55be851/specs/deep-interview-rfp-review-minimal.md`
- plan 디렉터리: `.gjc/_session-01a1a930-9604-776b-858b-be66a55be851/plans/ralplan/rfp-review-minimal-20261109/`
- `stage-01-planner.md`: `e66092fe233f75cd69bcb3a3a0f1989b591d06f3fdf5759af8522a64500b49ec`
- `stage-01-intent.md`: `a7abe5cf47fa90862c3e56c065989e858d860eebc5c70e0f466ed59a62980ac6`
- `stage-01-architect.md`: `7d8d4adab8b0ef64283ca79633d911f5de4031c411963850b0c4356ef86608d7`
- `stage-01-critic.md`: `80dd10cee9f7d18d75616562b599034185c0a6b0ba754d98d2bf67cd95c3c303`
- Reviewer IDs: `17-MinimalRfpArchitect`, `18-MinimalRfpCritic`; Planner: `16-MinimalRfpPlanner`.
- 역할 에이전트의 writer는 owner-session 제한으로 거부되어 부모가 동일 원문을 native writer로 저장했다. 리뷰 자체는 독립적으로 수행됐다.
- **새 run의 post-interview/final/pending-approval 파일은 아직 없다.** 이전 UUID run의 pending-approval을 새 목표의 최종 계획으로 착각하지 않는다.

다른 환경에서는 위 경로·에이전트 ID·임시 결과가 존재한다고 가정하지 않는다. 파일이 없다고 제품 변경을 완료했다거나 실행 승인을 받았다고 기록하지 않는다. 이 인계 문서와 커밋된 소스를 기준으로 계획을 마무리하고 별도 실행 승인을 확인한다.
