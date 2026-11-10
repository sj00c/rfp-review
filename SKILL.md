---
name: rfp-review
description: "제안요청서(RFP) 검토: 사용자가 준 검토 지침 파일(엑셀·한글·워드·텍스트)만을 근거로 작성 중인 RFP를 점검하고, 문제 위치에 형광펜·메모·수정안을 단 한글(HWPX) 검토본을 돌려줍니다. 예산·수치 불일치, 오타·빈칸, 문서 간 모순도 확인합니다. 제안요청서 검토, RFP 점검, 발주 전 사전검토에 사용합니다."
---

# RFP 검토

Goal: the author opens the returned 한/글 file and finds a highlight and a short memo on every spot that must change or be confirmed, colored by urgency. This is a first-pass AI review; say so in the reply.

Scripts are in `scripts/` next to this file (`<skill-dir>`); always run them by that absolute path. They need only Python 3.10+ (no packages to install); use `python3` or `py -3` if `python` is missing. On Windows Git Bash write paths as `C:/Users/...`, not `/c/Users/...`. Every value you write into JSON is Korean; keys are fixed.

**Do not write your own scripts.** Write JSON and notes with your file-editing tool, not with generated Python or long heredocs; count and list results from the scripts' own output. The only scripts you run are the ones in `scripts/`.

## Inputs and paths
- **지침** (required): the review guideline file the user gives — XLSX, HWPX/HWP, DOCX, TXT/MD. If none is given, ask for it. There is no built-in checklist.
- **RFP** (required): the draft 제안요청서, `.hwpx` or `.hwp`. Memos can only be written into HWPX, so a `.hwp` RFP is converted first (step 1).
- PDF and scanned images are not read. Ask for the original file (HWPX/DOCX/XLSX) or the text pasted into a `.txt`.
- Optional related documents (공고문, 원가계산서, 과업내용서 …): used only for cross-checks.
- Output: `<RFP folder>/output/`, or the folder the user names. Never the skill folder or the shell cwd.
- Work folder: `<output>/.rfp-review/<RFP stem>/`. All intermediates live there; run the commands below from that folder (relative paths below are inside it). Never modify the user's files.

## Rules (they prevent wrong findings)
1. **Only the guideline and the documents are evidence.** Do not use your own knowledge of laws, thresholds, article numbers or practice. If the guideline does not say it, do not write a memo — not even 확인필요.
2. **Exception — objective document errors:** typos, wrong project name, leftover placeholders (`OOO`, `202O년`, empty `□`, empty scope/schedule/budget/evaluation cells), contradictions inside one document or between the given documents, arithmetic errors. Their `근거` is `문서 자체 오류`. A contradiction needs both quotes in hand.
3. **Write only problems.** No 적합 records, no per-item coverage. Fewer, certain findings beat many weak ones.
4. **판정 = urgency** (memo color):
   - **필수수정** (red): a clear violation or objective error that bidders act on — eligibility/참가자격, evaluation items and scores, budget/price/amounts, submission method and deadline, contract terms — or a violation of a guideline item the guideline itself marks as 필수/필수 확인. Leaving it can void or dispute the notice.
   - **수정필요** (yellow): any other clear violation or objective error (typos, numbering, wording, wrong attachment numbers).
   - **확인필요** (blue): a guideline item applies but the documents do not settle it; say what to confirm. Never red.
   If you are unsure whether something is a problem at all, drop it. If unsure between red and yellow, use yellow.
5. **Quote verbatim.** `원문` is copied from the extracted text of that document; `근거` is copied from the extracted guideline text. Never paraphrase.
6. **Absence needs a search.** Before saying something is missing, search all extracted files for at least two keywords/synonyms. `[그림]`/`[수식]`/`[개체]` may hold the content: that is 확인필요, never a fix.
7. **Do not compute in your head.** Every amount, period or score comparison goes through `check_numbers.py`.
8. Compare like with like: same budget scope and VAT basis, same period meaning and start point. A 100-point rubric converted to a final weight (e.g. 90) is not a mismatch. Shared words in two evaluation items do not prove double scoring. "별도 통보" alone is not a defect. Past joint-contract evidence is not removed because current joint bids are disallowed.

## Context budget
- Never print a whole file. `python <skill-dir>/scripts/show_lines.py <file> <start>` stops at 8KB and prints `[next: N of M]`; continue from N.
- Read each document once. Write findings straight into `review.json` as you go (step 3); there is no separate notes pass. After compaction or on resume, reload from `guide_items.md` and the JSON files, not memory.

## Steps

### 0. Start or resume
If the work folder exists, run `python <skill-dir>/scripts/extract_text.py --check -o <work>/extracted`. Exit 0: continue from the existing files. Exit 1 (an input changed or files missing): delete that work folder and start over — never reuse old notes or findings.

### 1. Convert and extract
- RFP is `.hwp`: `python <skill-dir>/scripts/convert_to_hwpx.py <rfp.hwp> -o <work>/<stem>.hwpx` (Windows + 한/글; no packages), then use that HWPX everywhere below. If it prints `[변환 실패]`, ask the user to save the RFP as HWPX in 한/글 (파일 → 다른 이름으로 저장 → HWPX). Other `.hwp` documents are read directly; do not convert them.
- `python <skill-dir>/scripts/extract_text.py <guideline> <rfp.hwpx> [<other docs>] -o <work>/extracted`
- Lines carry location tags: `[문단 41]`, `[문단 52 표3 2-4]` (table 3, row 2, col 4), `[문단 3 머리말]` (also 꼬리말/각주/미주), `[시트!12행]`, `[줄 7]`. Put the tag in `위치`. Pair table values by row.
- `읽은 내용이 없습니다` or `[실패]` means the file was not read: say so; do not review it as empty.
- An Excel cell shown as `=…(계산값 없음)` is a formula whose result was never saved: ask for the file saved once in Excel, or treat that value as unknown. Excel dates appear as serial numbers (e.g. `45930`); do not guess the date.
- DOCX tables have no row/column tags; pair DOCX table values only when the line itself makes the pairing clear.

### 2. Read the guideline
Read the whole extracted guideline once. In `<work>/guide_items.md` copy only the lines that can be judged from documents (verbatim, with their tag), marking ones the guideline calls 필수. Skip internal approvals and procedures outside the documents.

### 3. Read the documents once and write findings as you go
Read every extracted document chunk by chunk. After each chunk:
- add any problem straight to `<work>/review.json` (format below), and
- add amounts, periods and scores you will need to compare to `<work>/facts.json` (step 4).
At the end of each chunk append one line `<file> <start>-<end> ✓` to `guide_items.md` so a resume knows where to continue.

### 4. Numbers
`facts.json` (format in the `check_numbers.py` header): `일치` groups for values that must be equal across places, `합계` for parts that must add up to a stated total; add `"필수": true` to a group for budget, price or score totals (red). Values may be expressions (`"300000000*1.1"`) to align VAT basis — only use a rate the documents or guideline state. Then:
`python <skill-dir>/scripts/check_numbers.py facts.json -o numeric_findings.json`
It outputs only mismatches. If a result contradicts the source (a value read wrongly), fix `facts.json` and rerun.

### 5. Findings format
`<work>/review.json`:
```json
{"findings": [
  {"id": "R1", "판정": "필수수정", "문서": "제안요청서", "위치": "[문단 61]",
   "원문": "제안서 인쇄본 10부와 USB 1개를 밀봉하여 제출",
   "요약": "인쇄본 제출 요구 삭제",
   "문제점": "지침은 전자 제출을 원칙으로 합니다.",
   "수정안": "\"제안서는 전자 파일로 제출한다\"로 바꿔 주세요.",
   "근거": "<지침 문구 그대로 | 문서 자체 오류>"}
]}
```
- `id`: `R1`, `R2` … (`N…` is used by check_numbers). `문서` is the document name used with `--doc` below. Put findings on the RFP whenever the problem is in the RFP; for a contradiction with another document, quote the RFP side and name the other side in `문제점`. Findings on other documents are listed in the RFP's summary memo. One finding per location; the same problem in two places is two findings.
- `요약`: one short line, the memo title. `수정안`: text the author can paste, or for 확인필요 what to confirm. Do not invent legal wording.
- Quote at least 4 characters next to the problem; never quote `[수식…]`/`[그림]` markers.

### 6. Validate (repeat until 0 errors)
```bash
python <skill-dir>/scripts/validate_review.py numeric_findings.json review.json --guide extracted/<지침>.txt --doc 제안요청서=extracted/<rfp>.txt [--doc 공고문=extracted/<notice>.txt]
```
Fix the cause (re-copy the quote, drop an unsupported finding). Never weaken a finding just to pass, and never delete one without a reason.

### 7. Annotate
On the RFP:
```bash
python <skill-dir>/scripts/annotate_hwpx.py <rfp.hwpx> numeric_findings.json review.json --doc 제안요청서 -o "<output>/<원본stem>_검토메모.hwpx"
```
- Red = 필수수정, yellow = 수정필요, blue = 확인필요. The summary memo on the first paragraph also carries findings it cannot place and findings on other documents, with their location.
- If an existing file has that name, it writes `_2`, `_3` … and prints the real path. It never overwrites.
- Findings whose `위치` has 머리말/꼬리말/각주/미주 always go to the summary memo (`요약 메모로`); that is final. Any other `요약 메모로` line means the quote was not matched in the HWPX: shorten it to text inside one body paragraph, validate, and annotate again. Delete only the bad file you just created; never an older result.
- The review copy drops document scripts (`Scripts/`); with them 한/글 may refuse to open a file with added memos. Nothing here opens the file in 한/글 — do not claim it was checked in 한/글.

### 8. Reply (Korean, short)
- One line: 필수수정 n건, 수정필요 n건, 확인필요 n건 (from annotate's `합계:` line), noting it is an AI first-pass review. Then the 필수수정 titles, one per line.
- The output file path(s).
- What was not covered: missing documents, unreadable files or images, guideline items left 확인필요 for lack of data.
Then delete the work folder. If something failed, keep the work folder and say where to resume.
