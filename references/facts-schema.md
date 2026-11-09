# `facts.json` format (input to `check_numbers.py`)

Put in **only values you found in the documents**. Omit a field or set it to `null` when the documents do not state it. Never estimate, infer or carry over values from examples. Unknown applicability or evidence is not `해당없음`, `적합`, or zero. A missing value makes the script skip or flag the check, which is correct; an invented value produces a wrong verdict.

Every value that came from a document carries:
- `원문`: verbatim text (a table cell's text for table values). The memo is attached here.
- `위치`: location tag from the extracted text plus heading, e.g. `[문단 12] 1. 입찰에 부치는 사항`.
- `문서`: `공고문` | `제안요청서` | `원가계산보고서` | `과업내용서` | `용역계약의뢰서` | `기관운영자료` | `기타` (for per-document records).
- `문서ID`: optional stable ID into `meta.문서목록`; use it when two inputs share a filename or a finding compares multiple files.
- `증거상태`: `판독완료` | `전수검색없음` | `미제출` | `미판독` | `충돌`. State the evidence status rather than turning unavailable evidence into a negative fact.

`meta.문서목록` is the shared input-to-role mapping. `meta.공식기준` is a sparse applicability map keyed by the exact leaf/dotted key in `thresholds.json.공식기준`; missing means `미확인`. `meta.기관프로필` contains only identified institutional operating profiles; findings refer to `프로필ID` rather than repeating the source and scope. Do not create a generic catalog of criteria.

For HWPX inputs, `<stem>.objects.json` is discovery evidence only: `{원본: <basename>, 개체목록: [{id: "object-N", 위치: "[문단 N]" | "[문단 N 뒤]", 종류: "수식" | "그림" | "개체", 추출표시: <marker>, 증거상태: "미판독"}], 개체조사: "완료" | "미지원", 주의: ...}`. An entry with `증거상태: "미판독"` means an equation/image/object was found, not that its contents were semantically read. `개체조사: "완료"` confirms the inventory pass only; `"미지원"` does not establish absence. If a reviewer manually reads an object, record that interpretation separately with its object ID/anchor and actual interpreted text. Never infer true absence from an unread marker or unsupported inventory.

The block below shows the shape only. `<…>` marks values you must take from the documents.

```json
{
  "meta": {
    "문서목록": [
      {"문서ID": "D1", "역할": "주입력", "문서": "제안요청서", "파일명": "<파일명>", "경로": "<내부 입력 매핑>", "개체조사": "완료"},
      {"문서ID": "D2", "역할": "보조입력", "문서": "용역계약의뢰서", "파일명": "<파일명>", "경로": "<내부 입력 매핑>"},
      {"문서ID": "D3", "역할": "기준자료", "문서": "기타", "파일명": "<공식 기준 판본>", "경로": "<내부 입력 매핑>"},
      {"문서ID": "D4", "역할": "기준자료", "문서": "기관운영자료", "파일명": "<기관 자료>", "경로": "<내부 입력 매핑>"}
    ],
    "공식기준": {
      "협상적격_기술점수_비율_퍼센트": {"적용성": "미확인", "출처": "<공식 문서·판본>", "적용범위": "<이번 계약·사업>", "문서ID": "D3", "원문": "<원문>", "위치": "<위치>"}
    },
    "기관프로필": [
      {"프로필ID": "기관_기술강조_90_10", "기관": "<확인된 기관>", "적용성": "미확인", "적용범위": "<이번 사업/기준기간>", "출처": "<기관 자료 또는 확인된 담당자 기록>", "문서ID": "D4", "원문": "<원문>", "위치": "<위치>"}
    ]
  },
  "계약유형": "용역",
  "낙찰방식": "협상",
  "SW사업": true,
  "긴급": false,
  "공고일": {"값": "<ISO 날짜>", "문서": "공고문", "원문": "<실제 원문>", "위치": "<문서 위치>", "증거상태": "판독완료"},
  "제출마감일": {"값": "<ISO 날짜>", "문서": "공고문", "원문": "<실제 원문>", "위치": "<문서 위치>", "증거상태": "판독완료"},

  "사업기간": {
    "공고문": {"값": "<정규화한 기간>", "역할": "계약이행기간", "기산점": "<문서 표현 또는 null>", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "제안요청서": {"값": "<정규화한 기간>", "역할": "서비스운영기간", "기산점": "<문서 표현 또는 null>", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "용역계약의뢰서": {"값": null, "역할": "사업기간", "기산점": null, "원문": null, "위치": null, "증거상태": "미제출"},
    "원가계산보고서": {"값": "<정규화한 기간>", "역할": "원가계산기간", "기산점": "<문서 표현 또는 null>", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"}
  },
  "사업금액": {
    "공고문": {"금액": null, "역할": "사업예산", "범위": "총사업", "부가세": "포함", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "제안요청서": {"금액": null, "역할": "사업예산", "범위": "총사업", "부가세": "불명", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "원가계산보고서": {"금액": null, "역할": "원가산정액", "범위": "총사업", "부가세": "제외", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"}
  },
  "추정가격": null,

  "실적제한": {"있음": true, "문서": "공고문", "원문": "<원문>", "위치": "<위치>"},
  "지역제한": {"있음": false},

  "공동계약": {
    "공고문": {"값": "불허", "맥락": "현재참가조건", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "제안요청서": {"값": "불허", "맥락": "현재참가조건", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"},
    "구성원수": {"값": "<정수>", "문서": "공고문", "원문": "<실제 원문>", "위치": "<문서 위치>", "증거상태": "판독완료"},
    "최소지분율": {"값": "<숫자>", "문서": "공고문", "원문": "<실제 원문>", "위치": "<문서 위치>", "증거상태": "판독완료"},
    "과거실적증빙": {
      "제안요청서": {"요구여부": "요구", "요구내용": "<과거 공동수행 실적 증빙>", "원문": "<원문>", "위치": "<위치>", "증거상태": "판독완료"}
    }
  },
  "하도급": {
    "공고문":     {"값": "미기재", "증거상태": "전수검색없음", "검색어": ["하도급", "재하청"], "검색범위": "공고문 본문·표 및 완료된 개체조사"},
    "제안요청서": {"값": "허용", "원문": "<원문>", "위치": "<위치>"}
  },

  "배점": {"기술": null, "가격": null, "배점조정사유기재": null, "문서": "제안요청서", "원문": "<원문>", "위치": "<위치>"},
  "기술평가": {"원점수만점": null, "정량만점": null, "정성만점": null, "환산기술배점": null, "환산방식": "미확인", "환산식원문": null},
  "기술평가항목": [
    {"항목": "<항목명>", "평가유형": "정성", "배점": null, "측정대상": "<무엇을 평가하는지>", "측정기간": null, "증빙범위": null, "측정방법": "<평가척도 또는 판정방법>", "설명원문": "<평가기준 설명>", "문서": "제안요청서", "원문": "<셀 문구>", "위치": "<위치>", "증거상태": "판독완료"}
  ],
  "정량평가항목": [
    {"항목": "신용평가", "배점": null, "최저등급평점": null, "문서": "제안요청서", "원문": "<최저등급 셀 문구>", "위치": "<위치>", "증거상태": "판독완료"}
  ],
  "실적건수평가": {"기준금액": null, "최대인정건수": null, "사업예산": null},

  "협상적격자기준_퍼센트": {"값": null, "문서": "제안요청서", "원문": "<원문>", "위치": "<위치>"},
  "평점산식_하한_퍼센트":   {"값": null, "문서": "공고문", "원문": "<원문>", "위치": "<위치>"}
}
```
The values above are shape examples only. Replace them with document evidence or leave them `null`; never write 0 for unknown. A documented zero is a real value. `meta.기관프로필` is populated only from an identified source; a missing profile is not a default profile.

## Value rules

- `계약유형`: `용역` | `물품` | `공사`. `낙찰방식`: `협상` | `적격심사` | `기타`. `SW사업`, `긴급`: `true` only when the documents say so.
- `공고일`, `제출마감일`: each is a source-bearing record `{값: ISO 날짜, 문서, 원문, 위치, 증거상태}` or `null` when unavailable. A date without its actual document quote and location cannot support a notice-period verdict; never pass a scalar date as if sourced.
- `meta.문서목록`: `문서ID` is stable within the review; `역할` is `주입력` | `보조입력` | `기준자료`. `경로` is an internal input mapping and is never rendered. `문서` identifies the content type, not the actor who supplied it. HWPX `개체조사` is `완료` | `미지원`; `미지원` does not establish that no embedded object exists.
- `meta.공식기준`: sparse map keyed by the exact threshold key in `thresholds.json.공식기준`; for nested keys use dot notation (for example `배점.원칙_기술`). Each consulted rule has `{적용성, 출처, 적용범위, 문서ID, 원문, 위치}`. `적용성` is `적용` | `비적용` | `미확인`; absent entry means `미확인`, never auto-apply the number. Use the exact official source/edition and the contract, subject, estimated-price, and announcement-date scope that determines applicability.
- `meta.기관프로필`: an entry is `{프로필ID, 기관, 적용성, 적용범위, 출처, 문서ID, 원문, 위치}`. `프로필ID` is one of the source-scoped IDs in `thresholds.json`; `적용성` is `적용` | `비적용` | `미확인`. Include only a source actually supplied or a recorded buyer confirmation. The profile's institution, scope, source, and applicability must match this procurement before its threshold is used. `예시피드백` is not authority.
- `증거상태`: `판독완료` | `전수검색없음` | `미제출` | `미판독` | `충돌`. `미제출` means the input document was not supplied; `미판독` means evidence/object was found but unread or the relevant search is incomplete (include `미판독사유`, a string); `충돌` means comparable evidence conflicts. `전수검색없음` means a complete search confirms absence. For this state, include `검색어` (array of strings) and `검색범위` (string), and confirm relevant object coverage in `meta.문서목록.개체조사`; `미지원` cannot establish absence where objects could contain the evidence. `미기재` is allowed only after supplied material, relevant text, and embedded-object evidence were completely searched.
- `사업기간.<문서>` keeps the existing per-document map; add `역할`, `기산점`, and `증거상태`. `역할` is `사업기간` | `계약이행기간` | `서비스운영기간` | `산정기간` | `원가계산기간` | `기타`. Record `기산점` as written or `null`. Compare only periods with the same role and start-point meaning. A missing contract request is not a match.
- `사업금액.<문서>` keeps the existing per-document map; add `역할`, `범위`, and `증거상태`. `역할` is `사업예산` | `연차예산` | `원가산정액` | `계약금액` | `단가` | `기타`; `범위` is `총사업` | `연차별` | `단가` | `기타` | `미확인`; `금액` is integer won or `null`; `부가세` is `포함` | `제외` | `불명`. Compare only like roles/scopes and VAT bases. `추정가격` stays the existing separate top-level fact. Do not treat the cost report as an automatic controlling value or derive VAT from amount size.
- `추정가격`: keep the existing top-level value; enter it only when explicitly labelled. Any computed estimate requires an applicable source rule and complete matching inputs; the cost report is not automatically controlling.
- `공동계약.<문서>` keeps the current document map. Add `맥락: "현재참가조건"` to current participation clauses; `값` is `허용` | `불허` | `미기재`. Keep historical performance evidence in the separate `과거실적증빙.<문서>` map with `요구여부` `요구` | `미기재`; it never determines current participation eligibility.
- `공동계약.구성원수` and `공동계약.최소지분율`: each is a source-bearing record `{값: number, 문서, 원문, 위치, 증거상태}` or `null`. They are numeric facts, not document-map entries. Only a finite number with a read, quoted, located source can support a correction; missing, unread, or unanchored values remain `확인필요`.
- `배점` keeps the existing `{기술, 가격, 배점조정사유기재, 문서, 원문, 위치}` contract for final scoring weights. `기술평가` separately records raw points `{원점수만점, 정량만점, 정성만점}` and final normalized technology `{환산기술배점, 환산방식, 환산식원문}`. `환산방식` is `명시산식` | `비례환산` | `미환산` | `미확인`; use `비례환산` only when the document states or fully establishes it. A 100-point raw technical table is not automatically a 100-point final technology weight.
- `기술평가항목`: one entry per scored item, with `평가유형` `정량` | `정성`, `측정대상`, `측정기간`, `증빙범위`, `측정방법`, `설명원문`, and source location. Use null for absent/unread information; do not infer duplicate scoring from matching words alone. A blank is established only after checking text and discovered objects; an unread object remains `미판독`.
- `정량평가항목.최저등급평점`: record the actual lowest score cell. Applying any lower-bound threshold requires the matching source/profile and confirmed scope; do not assume a universal 70% legal rule.
- Institution profile values are not activated by the numbers alone. To apply one, capture the exact institution/source, profile, scope, and applicability in `meta.기관프로필`. Unknown applicability affects that criterion only; an independently proven contradiction in comparable document values remains a finding.
- Not a negotiated contract → omit `배점`, `기술평가`, `기술평가항목`, `정량평가항목`, `협상적격자기준_퍼센트`, `평점산식_하한_퍼센트`.
