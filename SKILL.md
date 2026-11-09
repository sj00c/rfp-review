---
name: rfp-review
description: "입찰서류 검토: 작성 중인 제안요청서(RFP)와 공고문·원가계산보고서·용역계약의뢰서를 사업 맥락에 맞게 점검합니다. 예산·기간·배점·오타·누락·불일치를 확인하고, 수정 위치에 이유와 수정안을 단 HWPX 및 회신 초안을 제공합니다. 제안요청서 검토, RFP 점검, 공고문 검토, 발주 전 사전검토에 사용합니다."
---

# 입찰서류 검토

Goal: the author opens the returned 한/글 file and finds a highlight and a short memo on every spot that must change. This is a first-pass AI review; say so in the reply. The purchasing team makes the final call.

Paths: `scripts/` and `references/` are relative to the folder containing this SKILL.md. Run them by absolute path (`python <skill-dir>/scripts/<name>.py`). Final files go in **the primary input's parent directory / `output`**, or the user's explicit output directory. For `C:/dev/rfp-review/제안요청서.hwp`, that is `C:/dev/rfp-review/output`. Never use the skill installation directory or current shell directory as an implicit destination. Review intermediates belong in the internal OS temporary workspace, not `rfp-run` or a new worktree. The publisher alone uses a short-lived same-directory transaction stage for atomic final delivery (§7a). Use `python3` or `py -3` if `python` is missing (Python 3.10+). Scripts print UTF-8; set `PYTHONIOENCODING=utf-8` if the shell garbles Korean.

Reference data (checklist, phrases) is Korean and every value you write into JSON (quotes, 요약, 조치, 수정안) is Korean. JSON keys are Korean and fixed; do not translate them.

## Ground rules (these prevent wrong findings)

1. **Evidence only from the documents and `references/`.** Do not use your own memory of laws, thresholds, article numbers, page numbers, or deadlines. It may be outdated or wrong. If you believe a reference is outdated, record `확인필요` and say why; never "correct" it yourself.
2. **Quote verbatim.** `원문` is copied character-for-character from the extracted text (spaces may differ). No paraphrase, no typo fixes. `validate_review.py` rejects quotes that are not in the text.
3. **`근거` comes only from the item's 근거 line** printed by `checklist_items.py`. If that line is empty, write `-`. Never add article numbers or pages.
4. **Absence needs a search, not a feeling.** Before claiming something is missing (누락/미기재), search every extracted file for at least two likely keywords and synonyms. Put the search terms in `문제점` (e.g. `"하도급", "재하청" 검색 결과 없음`). If you have not read or searched the whole text, the verdict is `확인필요`, not `수정필요`.
5. **Unknown stays unknown.** Missing values are `null` or omitted. Draft notices usually have no 공고일/마감일; do not invent dates, amounts, or periods.
6. **Do not recompute what the script judges.** Items marked `script` belong to `check_numbers.py`. For `script+` items, judge only the remainder shown.
7. **`external` items ([확인]) are always `확인필요`**, stating what to check and where. Never `적합` or `수정필요`.
8. **Uncertain → `확인필요`.** Only certain violations are `수정필요`.
9. **Institution practice is not law.** Text such as "KIST 통상 운영…" is internal practice: phrase findings as "기관 운영 기준과 다름", not as a legal violation.
10. **Examples in `references/` are illustrations.** Never copy their values (amounts, dates, quotes) into your output.
11. **Copy `중요도` from the checklist item.** Do not upgrade or downgrade it. `기타-n` findings are `확인`.

## Context before judgment

For every check establish **applicability → evidence → context → verdict → unresolved question → responsible audience**. Read the common contract in `references/output-format.md`; do not repeat a verbose generic justification for every nonapplicable item.

- Separate official criteria, institution practice, and this project's requirements. `references/feedback-notes.md` provides paired examples, never legal authority. A confirmed contradiction between two project clauses remains actionable even if legal applicability is unknown.
- Technical raw score (quantitative + qualitative), its maximum, conversion to the final technical weight, and the price weight are different values. A 100-point rubric weighted to 90 or 80 is not inherently inconsistent. Institution modes and a 70% floor require their own confirmed applicability.
- Distinguish current joint-bid permission from proof of **past** jointly performed contracts. Do not delete historical share evidence merely because current joint bids are prohibited.
- Compare the same budget scope/VAT basis and the same period meaning/start condition. Do not nominate the cost report as the unquestioned source of truth.
- For quantitative/qualitative overlap, compare the actual measured object, period, evidence and method. Shared vocabulary does not prove double scoring. Cite both positions for a real duplicate.
- “별도 통보” is not by itself a violation. Determine whether a meeting is actually required and affects participation. A standard retiree disclosure form is not by itself a penalty; distinguish additional project-specific obligations.
- Never equate unread equations/images with missing content. The extraction `.objects.json` inventory records presence and initially `미판독`; even an extracted equation string needs interpretation and an applicable criterion.
- The SW e-제안요청 도움 report is fallible supplementary evidence. Undelivered industry-code/competitive-product lists remain unavailable; do not invent them.
- Separate `대상: 작성자` changes/questions from `구매팀` and `외부확인` actions. Internal actions belong in the complete purchaser handoff, not the author's revision memo.

## Context budget

Read documents and references in bounded chunks. Tools may truncate shell or file output; follow the returned continuation or artifact reference rather than treating a truncated result as complete. Korean text consumes several bytes per character. Therefore:

- **Read each document once, in budgeted chunks, and take notes while reading** (step 3). Do not plan a second full pass per sheet: it doubles the cost and, after context compaction, invites judging from vague memory.
- Never print a whole file. Use `python scripts/show_lines.py <file> <start>`: it stops at 8KB and ends with `[next: N of M]`; continue from N until `[end of file]`. A file-read tool with line ranges is fine if it reports truncation. Never `cat`/`type`/`Get-Content` a whole file.
- Load references only at the step that needs them: `items/<sheet>.md` in step 2, `facts-schema.md` in step 3, `output-format.md` in step 5, `standard-phrases.md` only when writing a 수정안. Never read `references/checklist.md`.
- Scripts print a summary first and cap long lists; full lists go to the files they name (e.g. `validate_report.txt`).
- Write results to files as you go (`review_notes.md`, `facts.json`, one `review_<sheet>.json` per sheet). Long single outputs get cut off. Never paste JSON into chat.
- After compaction or when resuming, reload state from those files, not from memory.

## Steps

### 0. Inputs
- Required: 제안요청서. Recommended: 입찰공고문(안), 원가계산보고서, 용역계약의뢰서. Optional: 과업내용서, forms.
- If 공고문 or 원가계산보고서 is missing, continue. Cross-document items become `확인필요` ("<문서> 미제출로 대조 불가").
- Determine 계약유형 (용역/물품/공사), 낙찰방식 (협상/적격심사), and whether it is an SW project from the documents (cover page and first chunk). Ask the user only if the documents do not say.

### 0a. Internal workspace (Agent-managed)
Use `scripts/review_workspace.py`; the user does not manage its paths or tokens.
```bash
python <skill-dir>/scripts/review_workspace.py begin "<primary-input>" --input "공고문=<notice-path>" --reference "<skill-dir>/references"
```
Omit absent `--input` entries; use `--output-dir` only for a requested destination. Keep the returned `workspace` path in session notes. The manifest maps each original input to a uniquely named internal copy. Read those copies; create conversions, extracted text, notes, findings, reports and repair files only under `<workspace>/work/`.

All relative data paths in steps 1–7 below are relative to that `work/` directory, **not** the user's folder; invoke scripts by their absolute `<skill-dir>/scripts/...` paths and explicitly select internal output paths. Never change the user's originals. A fresh HWP conversion uses `convert_to_hwpx.py <internal.hwp> -o <workspace>/work/<unique>.hwpx`.

After a completed stage, checkpoint its relevant artifact:
```bash
python <skill-dir>/scripts/review_workspace.py checkpoint "<workspace>" facts work/facts.json
python <skill-dir>/scripts/review_workspace.py checkpoint "<workspace>" numeric work/numeric_findings.json --depends-on facts
```
Use dependencies for all downstream checkpoints. Before publication begins, after correcting a checkpointed file, refresh that checkpoint, then regenerate and checkpoint invalidated descendants. Once publication planning starts, its artifacts and their ancestors are immutable even if publication failed before producing any receipt. Changed review content requires a fresh internal workspace; never clear the old plan or discard its staging ownership. On resumption run `status "<workspace>"`; stale original/reference fingerprints require a fresh review, not reuse. Do not hide a failed status by editing the manifest. OS temp loss requires restart.

### 1. Extract text
```bash
python scripts/convert_to_hwpx.py "<internal-input.hwp>" -o "<workspace>/work/제안요청서.hwpx"
python scripts/extract_text.py <files...> -o extracted/
```
- Extract from the converted `.hwpx` so paragraph numbers match the annotation step. If conversion fails, extract from the `.hwp` (direct read works, but table cells lack row/column tags); memos then need the user to save as HWPX, otherwise deliver the Excel report.
- Each line starts with a location tag: `[문단 41]`, `[문단 52 표3 2-4]` (table 3, row 2, column 4), `[p.3]`, `[시트!12행]`. Put the tag in `위치`. Pair table values by row number so a score is never attached to the wrong item.
- Equations and images are objects, not text: they appear as `[수식: <script>]`, `[그림]`, `[개체]`. A formula shown as `[수식: …]` is present; never report it as blank. An `[그림]` may hold the content you are looking for (e.g. a scoring table pasted as an image): record `확인필요` ("그림으로 삽입되어 판독 불가"), not `수정필요`. Never quote these markers; quote the text next to them.
- A scanned-PDF warning means no usable text. Ask for a text PDF or the HWP.

### 2. Applicable items (before reading the documents)
| Sheet | When |
|---|---|
| ② RFP/notice | always |
| ① common | always |
| ③ negotiation / ④ eligibility review | the one matching 낙찰방식 |
| ⑤ services / ⑥ construction | the one matching 계약유형 (물품: neither) |

```bash
python scripts/checklist_items.py ①②③⑤ [--sw | --non-sw] -o items
```
- Read every sheet file listed in `items/coverage.json` → `파일` now, including numbered chunks such as `②-2.md`. They hold `model` and `script+` items plus contextual metadata. Ignore stale files not in that list. `script` items are omitted; the script covers them.
- Use `--sw` only for confirmed SW work, `--non-sw` only for confirmed non-SW work; neither means unknown and retains SW checks. `items/coverage.json` records the exact selected IDs. Do not delete unknown checks to improve apparent coverage.
- `items/review_external.json`: every `external` item prefilled as purchaser `확인필요`. Preserve the outside-procedure confirmation; document evidence may resolve a separate document subcheck but cannot prove an external approval happened.
- Together these are the full scope: every applicable item must end with at least one finding.

### 3. Read once, take notes
Read `references/facts-schema.md`, then every extracted file chunk by chunk. After each chunk append to `review_notes.md`:
```
## 제안요청서.txt 1-87 ✓
- ②-20: [문단 61] "제안서 인쇄본 10부와 USB 1개를 밀봉하여 제출"
- ②-5: [문단 12] "※ 유사용역 범위:" (공란)
- facts: 사업기간 [문단 8], 배점표 [문단 52 표3]
```
- Note evidence only: item id, location tag, a short verbatim snippet. No judgments, no summaries of irrelevant text.
- Fill `facts.json` as values appear.
- When every line of every file is covered, the notes are your index. Later steps reopen only the cited lines.
- Then run `python scripts/outline.py extracted/<file>.txt --gaps` per file: it lists body heading numbers that skip or repeat (e.g. `3.` followed by `5.`). Each real gap is a `기타-n` finding. Numbers made by 한/글 auto-numbering are not in the text, so confirm a gap in the neighbouring lines first.

### 4. Numeric items → script
1. `python scripts/check_numbers.py facts.json -o numeric_findings.json`
2. If a verdict contradicts the source (e.g. VAT read wrongly), fix `facts.json` and rerun. Never silently overwrite a numeric finding with the same `(id, 항목)` in another file. Record an unresolved contextual limitation as a separate named subcheck and explain it.
3. The script records `해당없음` only for established non-applicability, not because a field is missing. Unknown conditions and missing values remain `확인필요`. Do not duplicate the computed subchecks.

### 5. Document items → review files
Read `references/output-format.md`. Then one sheet at a time: for each item in `items/<sheet>.md`, start from the notes; reopen the cited lines (`show_lines.py <file> <line> <line+5>`) to copy quotes exactly; search `extracted/` to confirm an absence (ground rule 4). Write `review_<sheet>.json`. For `script+` items judge only the remainder named in the file.

- Blanks and leftover placeholders (`□` with nothing after, empty table cells, `OOO`, `202O년 OO월`, `[ ]`, "세부사항 추가") are `수정필요` whenever they decide scope, schedule, budget or evaluation. Quote the label next to the blank (e.g. `※ 유사용역 범위:`).
- `적합` carries no hidden requests. If anything must change, split it out as its own `수정필요`/`확인필요`.
- `수정안`: use `references/standard-phrases.md` when one fits and cite it (`S-07`). Keep its `[ ]` slots that you cannot fill from the documents. Do not write legal text that is not in that file; write an instruction instead (e.g. "협상에 의한 계약체결기준 [별표] 현행 원문으로 교체").
- One problem hitting several items → one finding, other ids in `연계`. The same problem at several places → reference findings (output-format.md) so every place gets a memo.
- Obvious errors outside the checklist (wrong project name, conflicting dates, TOC/body number mismatch, a named vendor or product) → `id: "기타-n"`, `중요도: "확인"`.

Frequent signals (for search, not proof): 인쇄본/제본/USB/CD/밀봉/현장 제출 → ②-20; 소프트웨어사업자 신고확인서 → ②-9, ⑤-5; "100분의 60" → ②-17; concrete 공고일/마감일 in the RFP → ②-4; 퇴직자 감점 → ②-27.

### 6. Validate (mandatory, loop until clean)
```bash
python scripts/validate_review.py numeric_findings.json items/review_external.json review_①.json review_②.json review_③.json review_⑤.json --extracted extracted/ --sheets ①②③⑤ --coverage items/coverage.json --report validate_report.txt
```
List the files explicitly; PowerShell does not expand `*`. It fails on: quotes not in the text, 근거 not in the checklist, unknown ids, missing items for the sheets, bad verdict/severity values, missing 수정안. Fix the cause (re-copy the quote from the text; drop invented 근거) and rerun until it reports 0 errors. Do not delete a finding just to silence an error.

### 7. Annotate
Once per HWPX document. `--doc` equals the `문서` value used in findings.
```bash
python scripts/annotate_hwpx.py 제안요청서.hwpx numeric_findings.json review_①.json review_②.json … --doc 제안요청서 -o 제안요청서_검토메모.hwpx
python scripts/annotate_hwpx.py 입찰공고문.hwpx numeric_findings.json review_①.json review_②.json … --doc 공고문 -o 입찰공고문_검토메모.hwpx
```
- A `.hwp` can be passed directly; it is converted first (needs 한/글). `-o` must differ from the input.
- Do not pass `items/review_external.json` to annotate: those checks are internal.
- Author `수정필요` gets a yellow highlight and a memo. Author `확인필요` with `"질의": true` gets a blue one; purchaser/external actions never become author memos, including with `--include-check`. Avoid that flag in ordinary review.
- If the output reports many `요약 메모로` or `부분 일치`, recheck quotes and regenerate to a **fresh private output path**. Preserve the failed attempt for diagnosis.
- If 한/글 shows a damage warning or cannot open the result, copy that staged memo to a fresh repair path under `work/`; run `strip_scripts.py` and `resave_hwpx.py` on the repair copy only. If still unsuccessful, invoke `safe_annotate.py` with the original source/findings and a **new, nonexistent `-o` path**. Never reuse an existing destination or modify originals/published files. Checkpoint only the validated replacement, invalidating dependent artifacts.
- Excel report: only when the user asks for it or memos are impossible (PDF/DOCX, no 한/글):
  `python scripts/make_report.py numeric_findings.json items/review_external.json review_…json -o "수정요청표_<사업명>.xlsx"`

### 7a. Publish validated final files
Check the generated file's ZIP/XML integrity and annotation placement; real 한/글 opening is separate evidence. Do not claim a COM check ran when it did not. Complete repairs on staged copies, never on originals or already published files.
```bash
python <skill-dir>/scripts/review_workspace.py checkpoint "<workspace>" memo work/제안요청서_검토메모.hwpx --depends-on numeric
python <skill-dir>/scripts/review_workspace.py publish "<workspace>" "memo=제안요청서_검토메모.hwpx"
```
Record every model-review artifact as a dependency too, not only numeric findings. Publish **all requested final files in one command** using `NAME=FILENAME` entries. A partial failure is retried with the identical list; the receipt prevents duplicates. Only final HWPX and requested/necessary XLSX/TXT are published, never facts, extracted text or JSON.
The publisher verifies a private, ownership-bound transaction stage on the output filesystem before atomic no-replace publication. It verifies the destination bytes before recording success and removes verified staging. Unsupported atomic publication fails closed; interrupted or ownership-ambiguous files are preserved with diagnostics, never treated as final deliverables or deleted by filename alone.
If a manifest write stops before its ownership header is committed, `status` preserves and reports that transaction under `manifest_temporaries`. A valid prior manifest can resume through a fresh exclusive transaction; an empty file is never assumed owned. Malformed committed state still fails closed, and unresolved temporary-file diagnostics prevent cleanup.

### 8. Answer and handoff (in Korean)
Take every count from the `validate_review.py` and `annotate_hwpx.py` outputs, not from your own tally.
1. One line: 수정필요 n건(필수 n건), 확인필요 n건.
2. Up to 5 필수 수정필요 items, one line each (id, problem, location).
3. Not covered: missing documents, extraction failures, coverage gaps, items left 확인필요 because a value was absent.
4. **구매팀 확인사항:** every unresolved purchaser/external action, with reason/evidence and responsible party. Do not reduce this list to counts or the top five. Split long lists into visible messages. This is separate from the author's draft and is required even when neither Excel nor TXT is generated.
5. Reply draft for the author, **in chat by default**. Create TXT only on explicit request:
```
제목: [구매팀] <사업명> 입찰서류 검토 결과 회신

<작성자>님, 요청하신 <사업명> 제안요청서와 공고문(안)을 검토했습니다(AI 1차 검토 후 구매팀 확인).
수정이 필요한 사항은 n건(필수 n건)입니다.

주요 수정사항
1. ...
2. ...

첨부한 한/글 파일의 형광펜·메모 자리를 고쳐 주세요. 반영한 메모는 지우고, 반영하지 않은 메모에는 사유를 적어 <회신기한>까지 회신 부탁드립니다.
위치를 특정하기 어려운 항목은 문서 맨 앞 '검토 요약' 메모에 있습니다.
```
Mention an Excel attachment only if you made one.
Only name documents actually reviewed. Omit an unknown recipient or reply deadline rather than inventing it. List the exact final `output` paths. Filename conventions: `<원본stem>_검토메모.hwpx`, collision `<원본stem>_2_검토메모.hwpx`; optional `수정요청표_<주입력stem>.xlsx`, optional `<주입력stem>_검토회신.txt`.

Do not clean internal state until final files are validated and published **and** both the complete purchaser list and the separate author reply draft have been visibly delivered. If the harness cannot run tools after its final response, deliver both in a visible message before the handoff checkpoint/cleanup, and retain them in the final answer. A stored checkpoint is not proof of visible delivery. On failure, preserve this run's internal workspace and report the failing stage and resume location; never delete existing user work or old `rfp-run` folders.
After that visible handoff:
```bash
python <skill-dir>/scripts/review_workspace.py checkpoint "<workspace>" handoff
python <skill-dir>/scripts/review_workspace.py cleanup "<workspace>"
```
Cleanup removes this helper's owned temporary content only. Report cleanup failure separately rather than claiming complete cleanup.
