# Review file format (`review_<sheet>.json`)

Input to `validate_review.py`, `annotate_hwpx.py`, `make_report.py`. One file per checklist sheet. Keys are Korean and fixed. Values are Korean.

Final files go in `<주입력 부모>/output` by default; an explicit user output override wins. Do not place final files beside the input or use the working directory as a fallback. Intermediate facts, extraction, and review JSON stay private to the run.

The example below is an illustration of shape only. Never reuse its values.

```json
{
  "meta": {
    "사업명": "<문서의 사업명>", "검토문서": ["<파일명>"], "낙찰방식": "협상", "계약유형": "용역",
    "문서목록": [{"문서ID": "D1", "역할": "주입력", "문서": "제안요청서", "파일명": "<파일명>", "개체조사": "완료"}],
    "공식기준": {"협상적격_기술점수_비율_퍼센트": {"적용성": "미확인", "출처": "<공식 문서·판본>", "적용범위": "<이번 계약·사업>", "문서ID": "D2", "원문": "<원문>", "위치": "<위치>"}},
    "기관프로필": [{"프로필ID": "기관_기술강조_90_10", "기관": "<확인된 기관>", "적용성": "미확인", "적용범위": "<이번 사업>", "출처": "<기관 자료 또는 담당자 확인>", "문서ID": "D2", "원문": "<원문>", "위치": "<위치>"}]
  },
  "findings": [
    {
      "id": "②-20",
      "항목": "전자입찰 기준 현행화",
      "중요도": "★필수",
      "판정": "수정필요",
      "판정방식": "문서",
      "문서": "제안요청서",
      "문서ID": "D1",
      "위치": "[문단 212] Ⅴ.3 제안서 제출",
      "적용성": "적용",
      "증거상태": "판독완료",
      "기준유형": ["법령·공식기준"],
      "대상": "작성자",
      "원문": "제안서 인쇄본 10부와 USB 1개를 밀봉하여 제출",
      "요약": "비전자 제출 문구 잔존(인쇄본·USB)",
      "조치": "나라장터 전자제출로 변경(S-07)",
      "문제점": "비전자 제출 문구(인쇄본·USB·밀봉)가 남아 있습니다.",
      "근거": "전자조달법 제11조, 조달청 제안서평가 세부기준 제6조의2",
      "수정안": "제안서와 가격입찰서는 국가종합전자조달시스템(나라장터)을 통해 전자적으로 제출하며 … (S-07)",
      "연계": ""
    }
  ]
}
```

## Fields

| Key | Rule |
|---|---|
| `id` | Checklist id exactly as printed by `checklist_items.py`, or `기타-n`. |
| `항목` | Item name. `(id, 항목)` must be unique across all files; validation rejects duplicates before a renderer can replace an earlier finding. Name distinct subchecks distinctly. |
| `중요도` | `★필수` \| `확인` \| `참고`, copied from the checklist. `기타-n` → `확인`. Reference findings → `참고`. |
| `판정` | See verdicts below. |
| `판정방식` | `문서` for your findings (the script writes `계산`). |
| `문서` | `공고문` \| `제안요청서` \| `원가계산보고서` \| `과업내용서` \| `용역계약의뢰서` \| `기관운영자료` \| `기타`. Several: `"공고문, 제안요청서"`. Required for 수정필요 and author memo questions. Purchaser/external confirmations may leave it empty when no document was supplied. |
| `문서ID` | Optional ID into `meta.문서목록`; include it when names collide or evidence comes from several inputs. |
| `개체ID` | Optional sidecar ID such as `object-1`; it proves discovery/location only, not semantic reading. |
| `위치` | Location tag from the extracted text plus heading, e.g. `[문단 41] 3. 평가방법`. For several documents: `공고문: [문단 3] / 제안요청서: [문단 9]`. |
| `원문` | Verbatim quote of only the problematic part. Long quotes: `앞부분…뒷부분` (both parts verbatim; the highlight spans them). Several documents: one line each, `[공고문] …`. Use `해당 내용 없음` only after full text and discovered-object search confirms absence. |
| `적용성` | Optional `적용` \| `비적용` \| `미확인`; omitted values inherit the checklist item rule, never an assumed global pass. |
| `증거상태` | Optional `판독완료` \| `전수검색없음` \| `미제출` \| `미판독` \| `충돌`; cite an unread object's `개체ID` when relevant. `전수검색없음` means full search confirms absence; `미판독` means unread evidence or incomplete search. |
| `기준유형` | Optional array of `법령·공식기준` \| `기관운영` \| `사업요건` \| `예시피드백`; omitted values inherit the checklist item. `예시피드백` is context only, never authority by itself. |
| `기준참조` | Optional array of exact leaf/dotted keys in `meta.공식기준` and `thresholds.json.공식기준`; missing applicability metadata means `미확인`. |
| `프로필참조` | Optional `프로필ID` into `meta.기관프로필`; use only for a source-scoped institution profile whose applicability is established or explicitly unknown. |
| `개체판독근거` | When claiming a blank/omission beside a discovered equation/image, record the object ID/location, actual interpreted content, and why it does not supply the missing requirement. An extracted marker or an unchecked claim of “확인 완료” is not enough. Unread objects remain 확인필요. |
| `대상` | Optional `작성자` \| `구매팀` \| `외부확인`; action owner/output audience, not a legal authority label. |
| `요약` | Memo title: one plain sentence, about 25–35 characters (see below). |
| `조치` | Short action. Shown in the memo when `수정안` is empty, and for `확인필요` as the question to answer. Required for 수정필요. |
| `문제점` | For the reader (see below): what is wrong and why it matters. For 적합: why it passes. For 확인필요: what to check and why. Absence: search terms in parentheses with `검색`. |
| `근거` | Only sources from the item's 근거 line, ` / ` between sources. Empty 근거 line → `-`. |
| `수정안` | Paste-ready text (Excel only), standard phrase id in parentheses when used. Required for 수정필요. |
| `연계` | Other checklist ids covered by this finding. |
| `참조` | `true` only on reference findings (below). |
| `질의` | `true` only on a `확인필요` with `대상: "작성자"` that the document author must answer. It gets a blue highlight and a memo; needs `원문` and `조치`. Leave it out for internal checks or external confirmation. |

The shared schema stays compact: put document mappings and source/scope once in `meta`; include finding overrides only where they differ from the checklist default or explain an unknown. `meta.공식기준` is a sparse map keyed by the exact leaf or dotted key in `thresholds.json.공식기준` (for example `배점.원칙_기술`). Each used entry is `{적용성, 출처, 적용범위, 문서ID, 원문, 위치}`; only `적용성: "적용"` activates that numeric rule. `meta.기관프로필` entries are `{프로필ID, 기관, 적용성, 적용범위, 출처, 원문, 위치}` (plus `문서ID` when needed), with profile IDs from `thresholds.json.기관운영프로필.프로필`. A profile is active only for the named institution and confirmed procurement scope.

### Conditional requirements

- Keep exactly the four verdicts below; unknown evidence is not `해당없음`.
- `적합` requires `적용성: "적용"` and complete, relevant evidence (`증거상태: "판독완료"`).
- `해당없음` requires `적용성: "비적용"` and a reason.
- `수정필요` requires `적용성: "적용"` and `증거상태: "판독완료"`, `"충돌"`, or `"전수검색없음"`. For a confirmed omission, use `원문: "해당 내용 없음"`; `문제점` must state the search terms/scope and checked object coverage. A directly proven, comparable document-to-document contradiction may instead use `적용성: "미확인"`, `증거상태: "충돌"`, and `기준유형: ["사업요건"]`.
- `확인필요` requires `조치`, explicit `대상`, `증거상태`, and a reason preventing decision. For author questions set `질의: true`; for internal or external actions leave `질의` out. Missing files use `미제출`; found but unread objects or incomplete search use `미판독`, with the reason stated in `문제점`.
- `대상` defaults to `작성자` for `수정필요` unless the checklist item says otherwise. It is omitted for `적합` and `해당없음`. Every `확인필요` must explicitly name `작성자`, `구매팀`, or `외부확인`.
- `기준유형` inherits the checklist item type when available. A direct, independently proven document contradiction defaults to `사업요건`; otherwise specify all applicable types. Do not let an unknown official profile demote an independently established contradiction.
- For `적합` or `수정필요`, if the checklist item has no explicit `기준유형`, write the source type array explicitly. A citation alone is not a source classification.
- `기준참조` must resolve to `meta.공식기준` and a threshold key; `프로필참조` must resolve to `meta.기관프로필`. Each source, applicability, institution (profile only), and scope must be checked before using its numeric threshold. An unknown profile affects only that rule.

## Verdicts (exactly four)

| 판정 | Use when |
|---|---|
| `수정필요` | Certain violation, omission or inconsistency in the documents. Needs `원문`, `수정안`, `조치`. |
| `확인필요` | Cannot be decided from the documents: `external` items, values missing, unread text, or doubt. `문제점` says what to check and where. |
| `적합` | The documents meet the item. `문제점` gives the one-line reason. Nothing to fix may hide here. |
| `해당없음` | The item does not apply to this case (e.g. joint-contract details when joint contracts are not allowed). `문제점` gives the reason. |

## What the memo shows (write for the reader)

The reader is the requesting researcher or administrator, not a contract expert. They must understand the memo without the checklist, without paragraph numbers, and without asking anyone. The memo is built from your fields:
```
[반드시 수정] 협상적격자를 종합점수로 정하고 있음
■ 현재 문구
 "종합평가점수(기술평가+가격평가)가 85% 이상인 업체를 협상적격자로 선정"
■ 왜 고쳐야 하나
 - 협상적격자는 기술평가 점수만으로 정해야 합니다
 - 가격점수를 더하면 기술능력이 기준에 못 미치는 업체도 협상 대상이 될 수 있습니다
■ 이렇게 고쳐 주세요
 - "기술능력평가 점수가 기술능력평가 배점한도의 85% 이상인 자를 협상적격자로 선정"
■ 근거
 - 협상에 의한 계약체결기준
 - 감사원 공공계약 실무가이드(2024) p.262
(점검번호 ②-18)
```
- Head label from the verdict and 중요도: `반드시 수정` (★필수), `수정 요청` (확인), `수정 권장` (참고), `답변 요청` (확인필요 with `질의`), `같은 문제(다른 위치)` (reference findings).
- `요약` → title: one plain sentence saying what is wrong, about 25–35 characters. No ids, no internal shorthand (`S-07`, `②-9`, `SW사업자` is fine).
- `원문` → 현재 문구 (long quotes are cut at about 90 characters).
- `문제점` → 왜 고쳐야 하나: 2–3 short sentences, one point each: what is wrong, then the consequence (who is harmed, what can go wrong: bid cancelled, protest, audit finding). No `[문단 n]`; name places by heading or form name (`붙임 3 보안서약서`, `Ⅳ. 입찰 일반사항`). Put search notes in parentheses with `검색` (they are dropped from the memo, kept in Excel).
- `수정안` → 이렇게 고쳐 주세요: the replacement text in quotes, ready to paste, or a concrete instruction ("○○ 문장을 삭제"). Several changes → one per line. `(S-nn)` is removed. For `확인필요` this block is 답변해 주세요 from `조치`: the question the author must answer.
- `근거` → every source on its own line, full names (up to 3).
- Findings on the same span are merged into one memo, separated by a rule line.
- The first paragraph gets a 검토 요약 memo listing every memo title by group, in document order, plus how to respond.

## Same problem at several places (reference findings)

A finding has one `원문`, so it gets one memo. When the same problem recurs elsewhere (the same blank, the same wrong figure, the same outdated phrase), keep the main finding at the first place and add one reference finding per extra place:
- same `id`; a different `항목`, e.g. `"과업 범위 기재(②-5 참조)"`;
- `"참조": true`, `중요도: "참고"`, same `판정` as the main finding (same highlight colour);
- `요약` describes this place in plain words (e.g. `"제출서류 목록에도 폐지된 신고필증"`); the memo head says `같은 문제(다른 위치)`;
- `원문` = the text at that place; `위치` = that place's paragraph tag (give the body paragraph, not the TOC line, when both contain the text);
- `연계` = the main id.

Reference findings get memos but are not counted as separate requests.

## Correcting a script verdict

Correct the sourced facts and rerun the calculator. Never replace a computed finding using the same `(id, 항목)` in another file: validation rejects duplicate keys. If the facts cannot express an unresolved contextual limitation, record it as a distinctly named subcheck with its reason and responsible audience.
