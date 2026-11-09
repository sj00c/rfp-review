#!/usr/bin/env python3
"""[계산] 항목 판정기.

모델이 문서에서 뽑은 값(facts.json, 형식은 references/facts-schema.md)을 받아
체크리스트의 수치·일치 항목을 결정적으로 판정한다. 같은 입력이면 항상 같은 결과가 나온다.

사용법:
  python check_numbers.py facts.json -o numeric_findings.json [--thresholds ../references/thresholds.json]
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import date
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TH = os.path.join(HERE, "..", "references", "thresholds.json")

findings = []

# 이 스크립트가 판정하는 체크리스트 항목과 그 범위. checklist_items.py가 이 표를 보여 주고, 모델은 범위 밖만 판정한다.
# add()로 내는 id는 모두 여기에 있어야 한다(테스트가 검사). 값이 "전부"면 항목 전체를 스크립트가 본다.
SCRIPT_SCOPE = {
    "①-15": "제공된 추정가격과 정확한 출처·범위로 적용 확인된 공식 지역제한 기준 비교; 지역 제한 유무·시도 범위는 모델/담당자가 확인",
    "①-17": "현재 공동계약 조건의 구성원 수·최소지분율; 공식 임계값은 해당 meta.공식기준 항목이 적용일 때만 비교",
    "①-19": "물품·용역 공고기간 날짜 계산; 공식 일수·고시금액 기준은 해당 meta.공식기준 적용 확인 후 비교",
    "②-1": "사업기간은 동일 역할·기산점만 비교; 미판독·미제출은 확인필요",
    "②-2": "동일 역할·범위를 비교; VAT 포함·제외 환산은 적용이 확인된 부가세율 공식 메타가 있을 때만 수행, 추정가격은 명시값만 사용",
    "②-3": "현재 공동계약·하도급 조건의 문서 간 일치; 과거 공동실적은 제외",
    "②-7": "명시 추정가격과 적용 확인된 고시금액 기준의 참가자격 실적제한 비교",
    "②-12": "기술·가격 최종 가중치 합계 산술 및 적용 확인된 가격 0점 기준",
    "②-13": "적용 확인된 공식 가격 범위와 별도 출처·범위가 확인된 기관 배점 프로필 비교; 범위 이탈만으로 위반 단정 안 함",
    "②-14": "평가항목 상한의 공식 적용 확인 및 정량·정성 원점수 합계·명시된 환산 산술",
    "②-17": "문서의 가격산식 하한과 정확히 적용 확인된 공식 수치 비교; 산식 문구·동일성은 모델이 검토",
    "②-18": "협상적격 기준값과 정확히 적용 확인된 공식 수치 비교; 동점·차순위 문구는 모델이 검토",
    "③-2": "협상 공고기간 날짜 계산; 분기 기준과 최소일수는 각 공식 meta 항목 적용 확인 후 비교",
    "③-7": "기관 출처·사업 적용성이 확인된 정량 최저평점 프로필만 비교; 70% 법적 일반화 없음",
    "③-8": "건수평가 한도는 정확히 적용 확인된 공식 기준으로만 계산; 미제공 값은 확인필요",
    "⑥-5": "공사 실적제한의 업종·규모·적용범위 구매팀 확인만",
}


def won(n):
    return f"{int(round(n)):,}원"


def is_number(value):
    """Accept finite JSON numbers while excluding bool, which is an int subclass."""
    return ((isinstance(value, int) and not isinstance(value, bool)) or
            (isinstance(value, float) and math.isfinite(value)))


def add(id_, 항목, 중요도, 판정, 문제점="", 근거="", 수정안="", 문서="", 위치="", 원문="", 연계="",
        *, 적용성=None, 증거상태=None, 기준유형=None, 대상=None,
        기준참조=None, 프로필참조=None, 검색어=None, 검색범위=None, 조치=None):
    # annotate_hwpx·make_report는 (id, 항목)으로 finding을 병합한다. 같은 키가 두 번 나오면 앞의 판정이 사라진다.
    if any(x["id"] == id_ and x["항목"] == 항목 for x in findings):
        raise ValueError(f"중복 finding 키: ({id_}, {항목})")
    if 판정 == "수정필요" and not all(isinstance(value, str) and value.strip()
                                         for value in (문서, 위치, 원문)):
        판정 = "확인필요"
        적용성 = "미확인"
        증거상태 = "미판독" if 문서 else "미제출"
        대상 = "구매팀"
        조치 = "원문 인용·문서명·위치를 확인해 판정 근거를 보완한 뒤 필요한 경우 정정하세요."
        수정안 = ""
        문제점 = (f"{문제점} 원문 인용·문서명·위치가 모두 확인되지 않아 작성자 수정 지시로 확정하지 않았습니다.").strip()
    if 적용성 is None:
        적용성 = {"적합": "적용", "해당없음": "비적용", "수정필요": "적용", "확인필요": "미확인"}[판정]
    if 증거상태 is None:
        증거상태 = "미판독" if 판정 == "확인필요" else "판독완료"
    if 기준유형 is None:
        if id_ in ("②-1", "②-2", "②-3"):
            기준유형 = ["사업요건"]
        elif id_ == "③-7":
            기준유형 = ["기관운영"]
        else:
            기준유형 = ["법령·공식기준"]
    finding = {
        "id": id_, "항목": 항목, "중요도": 중요도, "판정": 판정, "판정방식": "계산",
        "문서": 문서, "위치": 위치, "원문": 원문, "문제점": 문제점,
        "근거": 근거, "수정안": 수정안, "연계": 연계,
        "적용성": 적용성, "증거상태": 증거상태, "기준유형": 기준유형,
    }
    if 판정 == "확인필요":
        finding["대상"] = 대상 or "구매팀"
        finding["조치"] = 조치 or 수정안 or confirmation_action(id_, 항목)
        if 증거상태 == "미판독":
            finding["미판독사유"] = 문제점
    elif 판정 == "수정필요":
        finding["대상"] = 대상 or "작성자"
    if 조치 and 판정 != "확인필요":
        finding["조치"] = 조치
    if 기준참조:
        finding["기준참조"] = 기준참조 if isinstance(기준참조, list) else [기준참조]
    if 프로필참조:
        finding["프로필참조"] = 프로필참조
    if 증거상태 == "전수검색없음":
        finding["검색어"] = 검색어 or []
        finding["검색범위"] = 검색범위 or ""
    findings.append(finding)


def confirmation_action(id_, 항목):
    """Actionable next step for an unresolved numeric evidence or applicability check."""
    actions = {
        "①-15": "지역제한 문구·명시 추정가격·적용 공식 상한을 확인하세요.",
        "①-17": "현재 공동계약 조건과 해당 구성원 기준의 적용 출처·범위를 확인하세요.",
        "①-19": "공고일·제출마감일과 적용 공고기간 기준을 확인하세요.",
        "②-1": "비교할 문서를 확보하고 기간의 역할·기산점을 확인해 같은 조건끼리 대조하세요.",
        "②-2": "금액별 역할·범위·부가세 기준과 적용 세율을 확인해 비교 자료를 보완하세요.",
        "②-3": "현재 참가조건이 적힌 문서와 판독·검색 상태를 확인한 뒤 공고문과 제안요청서를 대조하세요.",
        "②-7": "명시 추정가격과 적용 공식 고시금액 기준, 참가자격 실적제한 근거를 확인하세요.",
        "②-12": "최종 기술·가격 가중치와 적용 공식기준을 확인하고 누락된 값을 확정하세요.",
        "②-13": "최종 가격 가중치와 적용 공식 범위 또는 기관 프로필의 출처·범위를 확인하세요.",
        "②-14": "평가항목 배점·원점수 만점·환산식을 원문과 대조해 확인하세요.",
        "②-17": "공고문·제안요청서의 원문 산식과 해당 공고일 기준 적용 공식기준을 확인하세요.",
        "②-18": "공고문·제안요청서의 협상적격 기준 원문과 적용 공식기준을 확인하세요.",
        "③-2": "공고일·제출마감일과 가격분기 및 적용 공식 공고기간을 확인하세요.",
        "③-7": "정량평가 점수표와 기관 프로필의 출처·사업 적용범위를 확인하세요.",
        "③-8": "건수평가 적용 여부·계산값과 적용 공식한도의 출처·범위를 확인하세요.",
        "⑥-5": "공사 종류·실적제한 업종과 규모·적용 근거를 구매팀에서 확인하세요.",
    }
    if id_ == "①-17" and "최소지분율" in 항목:
        return "현재 공동계약 최소지분율과 그 기준의 적용 공식 출처·범위를 확인하세요."
    if id_ == "①-17" and "구성원" in 항목:
        return "현재 공동계약 구성원 수와 그 기준의 적용 공식 출처·범위를 확인하세요."
    if id_ == "②-12" and "100점" in 항목:
        return "최종 기술·가격 가중치 원문을 확인해 합계가 100점인지 대조하세요."
    return actions.get(id_, f"{항목}의 미확인 사실과 적용 기준을 확인해 필요한 자료를 보완하세요.")


def summ(text, 조치=None):
    """직전에 추가한 finding에 메모용 한 줄 요약(제목)과 짧은 조치(▶ 줄)를 단다.
    한/글 메모 폭이 좁아 메모에는 수정안 대신 조치를 쓴다(수정안은 수정요청표에 남는다)."""
    findings[-1]["요약"] = text
    if 조치 and findings[-1]["판정"] != "확인필요":
        findings[-1]["조치"] = 조치


def add_refs(main, items, label):
    """같은 지적이 걸린 나머지 위치마다 참조용 finding을 단다(output-format.md 참조 규칙)."""
    for i in items:
        if not all(isinstance(i.get(field), str) and i[field].strip() for field in ("문서", "원문", "위치")):
            continue
        findings.append({
            "id": main["id"], "항목": f"{main['항목']} — {i.get('항목', '')}({main['id']} 참조)",
            "중요도": "참고", "판정": main["판정"], "판정방식": "계산", "참조": True,
            "문서": i["문서"], "위치": i["위치"], "원문": i["원문"],
            "문제점": main["문제점"], "근거": main["근거"], "수정안": main["수정안"], "연계": main["id"],
            "조치": main.get("조치", ""),
            "요약": label(i),
            "적용성": main["적용성"], "증거상태": main["증거상태"], "기준유형": main["기준유형"],
        })
        if main.get("대상"):
            findings[-1]["대상"] = main["대상"]
        if main.get("기준참조"):
            findings[-1]["기준참조"] = main["기준참조"]
        if main.get("프로필참조"):
            findings[-1]["프로필참조"] = main["프로필참조"]


def threshold_value(th, key):
    """Read one exact leaf/dotted path from thresholds.json's official section."""
    value = th.get("공식기준", {})
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def official_rule(f, th, key):
    """Return (threshold, source-record, applicability); missing metadata stays unknown."""
    value = threshold_value(th, key)
    meta = f.get("meta") or {}
    records = meta.get("공식기준") or {}
    record = records.get(key) if isinstance(records, dict) else None
    if not isinstance(record, dict):
        return value, None, "미확인"
    required = ("출처", "적용범위", "원문", "위치")
    if any(not record.get(field) for field in required):
        return value, record, "미확인"
    applicability = record.get("적용성")
    if applicability not in ("적용", "비적용", "미확인"):
        applicability = "미확인"
    return value, record, applicability


def official_reference_exists(f, key):
    record = ((f.get("meta") or {}).get("공식기준") or {}).get(key)
    return isinstance(record, dict) and all(record.get(field) for field in ("출처", "적용범위", "원문", "위치"))


def institution_profile(f, th, profile_id):
    records = (f.get("meta") or {}).get("기관프로필") or []
    record = next((p for p in records if isinstance(p, dict) and p.get("프로필ID") == profile_id), None)
    profile = ((th.get("기관운영프로필") or {}).get("프로필") or {}).get(profile_id)
    if not isinstance(record, dict) or not isinstance(profile, dict):
        return profile, record, "미확인"
    required = ("기관", "적용범위", "출처", "원문", "위치")
    if any(not record.get(field) for field in required):
        return profile, record, "미확인"
    applicability = record.get("적용성")
    if applicability not in ("적용", "비적용", "미확인"):
        applicability = "미확인"
    return profile, record, applicability


def profile_reference_exists(f, profile_id):
    records = (f.get("meta") or {}).get("기관프로필") or []
    record = next((p for p in records if isinstance(p, dict) and p.get("프로필ID") == profile_id), None)
    return isinstance(record, dict) and all(record.get(field) for field in ("기관", "적용범위", "출처", "원문", "위치"))


def source_reference(record):
    if not isinstance(record, dict):
        return ""
    if not all(record.get(field) for field in ("출처", "적용범위", "원문", "위치")):
        return ""
    source = record.get("출처", "")
    quote = record.get("원문", "")
    return f"{source}: {quote}" if source and quote else source


def period_role(entry):
    return entry.get("역할") if isinstance(entry, dict) else None


def amount_dimensions(entry):
    if not isinstance(entry, dict):
        return None
    role, scope = entry.get("역할"), entry.get("범위")
    if not role or role == "기타" or not scope or scope in ("기타", "미확인"):
        return None
    return role, scope


def absence_is_proven(f, entry, document):
    """True only with explicit search evidence and a completed object inventory for its input."""
    if not isinstance(entry, dict) or entry.get("증거상태") != "전수검색없음":
        return False
    if not entry.get("검색어") or not entry.get("검색범위"):
        return False
    sources = ((f.get("meta") or {}).get("문서목록") or [])
    document_id = entry.get("문서ID")
    matching = [source for source in sources if isinstance(source, dict) and
                ((document_id and source.get("문서ID") == document_id) or
                 (not document_id and (source.get("문서") == document or source.get("파일명") == document)))]
    return bool(matching) and all(source.get("개체조사") == "완료" for source in matching)


SHORT_DOC = {"원가계산보고서": "원가계산서", "제안요청서": "제안요청서", "공고문": "공고문"}


def sdoc(k):
    return SHORT_DOC.get(k, k)


def sval(v):
    m = re.search(r"(\d+)\s*개월", str(v))
    return f"{m.group(1)}개월" if m else str(v)


def eok(n):
    """200000000 -> '2억', 230000000 -> '2.3억'"""
    x = n / 100_000_000
    return (f"{x:.2f}".rstrip("0").rstrip(".") + "억") if x >= 1 else f"{int(round(n / 10_000)):,}만"


def loc(d):
    """{'문서명': {'위치':..}} 형태에서 '문서: 위치' 문자열 생성"""
    parts = []
    for doc, v in d.items():
        if isinstance(v, dict) and v.get("위치"):
            parts.append(f"{doc}: {v['위치']}")
    return " / ".join(parts)


def quotes(d):
    parts = []
    for doc, v in d.items():
        if isinstance(v, dict) and v.get("원문"):
            parts.append(f"[{doc}] {v['원문']}")
    return "\n".join(parts)


def source_evidence(items):
    """Return document, location, and quote fields without inventing missing source anchors."""
    records = items.items() if isinstance(items, dict) else ((None, item) for item in items)
    rows = list(records)
    if not rows:
        return "", "", ""
    documents, locations, quotes_ = [], [], []
    for key, row in rows:
        if not isinstance(row, dict):
            return "", "", ""
        document = row.get("문서") or key
        quote, location = row.get("원문"), row.get("위치")
        if not all(isinstance(value, str) and value.strip() for value in (document, quote, location)):
            return "", "", ""
        if document not in documents:
            documents.append(document)
        locations.append(f"{document}: {location}")
        quotes_.append(f"[{document}] {quote}")
    return ", ".join(documents), " / ".join(locations), "\n".join(quotes_)


def parse_date(s):
    if not s:
        return None
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(s).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def sourced_fact(record):
    return (isinstance(record, dict) and record.get("증거상태") == "판독완료" and
            all(isinstance(record.get(field), str) and record[field].strip()
                for field in ("문서", "원문", "위치")))


def norm_period(s):
    return re.sub(r"\s+", "", str(s or "")).replace("부터", "~").replace("까지", "")


# ---------------------------------------------------------------- checks

def check_period(f):
    d = f.get("사업기간") or {}
    docs = {k: v for k, v in d.items() if isinstance(v, dict)}
    known = {k: v for k, v in docs.items() if v.get("값") is not None and v.get("증거상태", "판독완료") == "판독완료"}
    groups = {}
    incomparable = []
    for key, entry in known.items():
        role = period_role(entry)
        start = norm_period(entry.get("기산점")) if entry.get("기산점") else None
        if not role or not start:
            incomparable.append(key)
            continue
        groups.setdefault((role, start), {})[key] = entry
    pairs = [group for group in groups.values() if len(group) >= 2]
    unresolved = [k for k, v in docs.items()
                  if v.get("증거상태") in ("미제출", "미판독", "충돌") or not v.get("값")]
    if not pairs:
        add("②-1", "사업기간 일치", "★필수", "확인필요",
            "같은 역할·기산점의 사업기간을 비교할 자료가 둘 이상 없습니다. 미제출 자료나 역할·기산점이 다른 기간을 구분해 확인하세요.",
            "협상에 의한 계약체결기준 제4조 제2항", "", ", ".join(known) or "공고문",
            loc(d), quotes(d), 적용성="미확인", 증거상태="미제출" if unresolved or not known else "미판독",
            대상="구매팀")
        return
    for group in pairs:
        values = {k: norm_period(v["값"]) for k, v in group.items()}
        if len(set(values.values())) > 1:
            diff = "; ".join(f"{k}={group[k]['값']}" for k in group)
            source_docs, source_locations, source_quotes = source_evidence(group)
            add("②-1", "사업기간 일치", "★필수", "수정필요",
                f"같은 역할·기산점의 문서 기간이 다릅니다: {diff}",
                "협상에 의한 계약체결기준 제4조 제2항 / 감사원 공공계약 실무가이드(2024) p.256",
                "비교 가능한 기간과 기산점을 확인해 관련 문서를 정합화하세요.",
                source_docs, source_locations, source_quotes, "①-1",
                적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
            groups_by_value = {}
            for key, entry in group.items():
                groups_by_value.setdefault(sval(entry["값"]), []).append(sdoc(key))
            summ("사업기간 불일치(" + " / ".join(f"{'·'.join(ds)} {val}" for val, ds in groups_by_value.items()) + ")",
                 "비교 가능한 기간과 기산점 정합화")
            return
    if unresolved or incomparable or len(pairs) != len(groups):
        why = "일부 문서가 미제출·미판독이거나 역할·기산점이 달라 전체 대조를 완료할 수 없습니다."
        add("②-1", "사업기간 일치", "★필수", "확인필요", why,
            "협상에 의한 계약체결기준 제4조 제2항", "", ", ".join(docs), loc(d), quotes(d),
            적용성="미확인", 증거상태="미제출" if any(v.get("증거상태") == "미제출" for v in docs.values()) else "미판독",
            대상="구매팀")
        return
    compared = {k: v for group in pairs for k, v in group.items()}
    add("②-1", "사업기간 일치", "★필수", "적합", "비교 가능한 문서의 사업기간과 기산점이 일치합니다.",
        "협상에 의한 계약체결기준 제4조 제2항", "", ", ".join(compared), loc(compared), quotes(compared),
        적용성="적용", 증거상태="판독완료", 기준유형=["사업요건"])


def check_amount(f, th):
    """사업금액 일치 + 부가세 표기 혼용. 반환값: 추정가격(VAT 제외) 또는 None"""
    d = f.get("사업금액") or {}
    docs = {k: v for k, v in d.items() if isinstance(v, dict)}
    est_fact = f.get("추정가격")
    if isinstance(est_fact, dict):
        est = est_fact.get("금액", est_fact.get("값"))
    else:
        est = est_fact
    est = int(est) if is_number(est) else None
    entries = {k: v for k, v in docs.items()
               if is_number(v.get("금액")) and v.get("증거상태", "판독완료") == "판독완료"}
    unresolved = [k for k, v in docs.items() if v.get("증거상태") in ("미제출", "미판독", "충돌")
                  or not is_number(v.get("금액"))]
    comparable = {}
    skipped = []
    rate, rate_record, rate_applies = official_rule(f, th, "부가세율")
    can_normalize_vat = rate_applies == "적용" and is_number(rate) and rate >= 0
    normalization_unknown = []
    for key, value in entries.items():
        dims = amount_dimensions(value)
        vat = value.get("부가세")
        if not dims or vat not in ("포함", "제외"):
            skipped.append(key)
            continue
        comparable.setdefault(dims, {})[key] = value
    pairs = []
    for dims, group in comparable.items():
        if len(group) < 2:
            continue
        vat_bases = {value["부가세"] for value in group.values()}
        if len(vat_bases) > 1 and not can_normalize_vat:
            normalization_unknown.append(dims)
            continue
        normalized = {}
        for doc, value in group.items():
            amount = Decimal(str(value["금액"]))
            if value["부가세"] == "포함" and len(vat_bases) > 1:
                amount /= Decimal("1") + Decimal(str(rate))
            normalized[doc] = amount
        pairs.append({"entries": group, "normalized": normalized, "vat_normalized": len(vat_bases) > 1})
    mismatch = next((pair for pair in pairs
                     if max(pair["normalized"].values()) - min(pair["normalized"].values()) > Decimal("1")), None)
    if mismatch:
        group = mismatch["entries"]
        source_docs, source_locations, source_quotes = source_evidence(group)
        details = "; ".join(
            f"{doc}={won(value['금액'])}({value['부가세']} VAT)" +
            (f" → VAT 제외 환산 {amount:,.2f}원" if mismatch["vat_normalized"] else "")
            for doc, value in group.items() for amount in [mismatch["normalized"][doc]])
        add("②-2", "사업금액 일치", "★필수", "수정필요",
            "같은 역할·범위의 문서 금액이 다릅니다: " + details,
            "국가계약법 시행령 제7조 / 감사원 공공계약 실무가이드(2024) p.256 (사업예산 명시)" +
            (f" / {source_reference(rate_record)}" if mismatch["vat_normalized"] else ""),
            "같은 역할·범위의 사업금액을 확인해 문서를 정합화하세요.",
            source_docs, source_locations, source_quotes, "①-8, ①-10",
            적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"],
            기준참조="부가세율" if mismatch["vat_normalized"] else None)
        summ("같은 역할·범위의 사업금액 불일치", "비교 가능한 사업금액 정합화")
    elif unresolved or skipped or normalization_unknown or not pairs or \
            len({doc for pair in pairs for doc in pair["entries"]}) != len(entries):
        details = []
        if unresolved:
            details.append("미제출·미판독 또는 금액 미기재 문서 " + ", ".join(unresolved))
        if skipped:
            details.append("역할·범위 또는 부가세 기준이 불명확해 비교하지 않은 문서 " + ", ".join(skipped))
        if normalization_unknown:
            scopes = ", ".join(f"{role}/{scope}" for role, scope in normalization_unknown)
            details.append(f"부가세 포함·제외가 혼재한 동일 범위({scopes})를 환산할 적용 부가세율의 출처·범위가 확인되지 않았습니다")
        if not pairs:
            details.append("같은 역할·범위에서 비교 가능한 문서가 둘 이상 없습니다")
        normalized_used = any(pair["vat_normalized"] for pair in pairs)
        vat_source = source_reference(rate_record) if (normalization_unknown or normalized_used) and \
            official_reference_exists(f, "부가세율") else ""
        add("②-2", "사업금액 일치", "★필수", "확인필요",
            "사업금액을 완전히 대조할 수 없습니다: " + "; ".join(details),
            "국가계약법 시행령 제7조 / 감사원 공공계약 실무가이드(2024) p.256 (사업예산 명시)" +
            (f" / {vat_source}" if vat_source else ""),
            "누락된 금액의 역할·범위·부가세 기준과 적용 세율을 확인한 뒤 비교하세요.",
            ", ".join(docs), loc(docs), quotes(docs), 적용성="미확인",
            증거상태="미제출" if any(v.get("증거상태") == "미제출" for v in docs.values()) else "미판독",
            기준유형=["사업요건"], 대상="구매팀",
            기준참조="부가세율" if vat_source else None)
    else:
        matched = {doc: value for pair in pairs for doc, value in pair["entries"].items()}
        normalized_pairs = [pair for pair in pairs if pair["vat_normalized"]]
        normalized_refs = ["부가세율"] if normalized_pairs and official_reference_exists(f, "부가세율") else None
        add("②-2", "사업금액 일치", "★필수", "적합",
            "비교 가능한 문서의 사업금액이 역할·범위별로 일치합니다." +
            (" 부가세 포함·제외 금액은 적용 확인된 세율로 VAT 제외 환산했습니다." if normalized_pairs else ""),
            "국가계약법 시행령 제7조", "", ", ".join(matched), loc(matched), quotes(matched),
            적용성="적용", 증거상태="판독완료", 기준유형=["사업요건"], 기준참조=normalized_refs)
    return est


def check_restrictions(f, th, est):
    kind = f.get("계약유형", "")
    r = f.get("실적제한") or {}
    if kind in ("용역", "물품"):
        threshold, record, applies = official_rule(f, th, "고시금액_물품용역")
        if r.get("있음") is True:
            if r.get("증거상태", "판독완료") != "판독완료":
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "확인필요",
                    "실적제한 여부가 미판독 상태라 추정가격 기준과 비교하지 않았습니다.",
                    "국가계약법 시행령 제21조 제1항 제1호", "실적제한 문구와 위치를 확인하세요.",
                    r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13",
                    적용성="미확인", 증거상태="미판독", 대상="구매팀")
            elif est is None:
                verdict, status, why = "확인필요", "미제출", "실적제한이 확인됐지만 문서에 표시된 추정가격을 확인하지 못했습니다."
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", verdict, why,
                    "국가계약법 시행령 제21조 제1항 제1호", "추정가격과 적용 기준을 확인하세요.",
                    r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13",
                    적용성="미확인", 증거상태=status, 대상="구매팀",
                    기준참조="고시금액_물품용역" if official_reference_exists(f, "고시금액_물품용역") else None)
            elif applies != "적용" or not is_number(threshold):
                why = ("실적제한과 추정가격은 확인됐지만 고시금액 기준의 공식 출처·이번 사업 적용성이 확인되지 않았습니다."
                       if applies != "비적용" else "기록된 공식 기준이 이번 사업에 비적용입니다. 다른 참가자격 기준에 따른 확인이 필요합니다.")
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "확인필요", why,
                    "국가계약법 시행령 제21조 제1항 제1호", "적용 기준을 확인하세요.", r.get("문서", ""),
                    r.get("위치", ""), r.get("원문", ""), "①-13", 적용성="미확인", 증거상태="미판독",
                    대상="구매팀", 기준참조="고시금액_물품용역" if official_reference_exists(f, "고시금액_물품용역") else None)
            elif est < threshold:
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "수정필요",
                    f"확인된 적용기준의 고시금액 {won(threshold)}보다 추정가격 {won(est)}이 낮지만 수행실적으로 참가자격을 제한합니다.",
                    "국가계약법 시행령 제21조 제1항 제1호 / 감사원 공공계약 실무가이드(2024) p.119",
                    "적용 기준을 확인해 참가자격 제한을 정정하세요.", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13",
                    적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조="고시금액_물품용역")
                summ(f"추정가격 {eok(est)}가 적용 고시금액 {eok(threshold)} 미만", "참가자격 제한 정정")
            else:
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "적합",
                    f"추정가격 {won(est)}이 확인된 적용기준의 고시금액 {won(threshold)} 이상입니다. 다른 참가제한 요건은 별도 검토가 필요합니다.",
                    "국가계약법 시행령 제21조 제1항 제1호", "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13",
                    적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조="고시금액_물품용역")
        elif r.get("있음") is False and absence_is_proven(f, r, r.get("문서", "")):
            add("②-7", "고시금액 미만 실적제한 불가", "★필수", "해당없음",
                "제공된 참가자격 문서와 관련 개체를 전수검색했으며 수행실적 제한이 없습니다.",
                "국가계약법 시행령 제21조 제1항 제1호 / 감사원 공공계약 실무가이드(2024) p.119",
                문서=r.get("문서", ""), 위치=r.get("위치", ""), 원문="해당 내용 없음",
                적용성="비적용", 증거상태="전수검색없음", 기준유형=["법령·공식기준"],
                검색어=r.get("검색어"), 검색범위=r.get("검색범위"))
        else:
            why = "수행실적 제한 여부가 확인되지 않았습니다. 사실 여부와 제공문서의 검색 범위를 확인하세요."
            add("②-7", "고시금액 미만 실적제한 불가", "★필수", "확인필요", why,
                "국가계약법 시행령 제21조 제1항 제1호", "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""),
                적용성="미확인", 증거상태="미판독" if r else "미제출", 대상="구매팀")
    elif kind == "공사" and r.get("있음") is True:
        add("⑥-5", "참가자격(건설업 등록)·실적제한 기준", "★필수", "확인필요",
            "공사 실적제한의 업종·규모별 기준 및 이번 사업 적용성을 확인해야 합니다.",
            "건설산업기본법 제9조·제16조, 시행령 제21조 / 감사원 공공계약 실무가이드(2024) p.103~108",
            "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "②-7",
            적용성="미확인", 증거상태="미판독", 대상="구매팀")
    g = f.get("지역제한") or {}
    if kind in ("용역", "물품"):
        threshold, record, applies = official_rule(f, th, "지역제한_상한_물품용역")
        if g.get("있음") is True:
            if g.get("증거상태", "판독완료") != "판독완료":
                add("①-15", "지역제한 적용 시 기준", "확인", "확인필요",
                    "지역제한 여부가 미판독 상태라 금액 기준과 비교하지 않았습니다.", "국가계약법 시행규칙 제24조",
                    "지역제한 문구와 위치를 확인하세요.", g.get("문서", ""), g.get("위치", ""), g.get("원문", ""),
                    적용성="미확인", 증거상태="미판독", 대상="구매팀")
            elif est is None or applies != "적용" or not is_number(threshold):
                state = "미제출" if est is None else "미판독"
                why = ("지역제한이 확인됐지만 문서에 표시된 추정가격이 없습니다." if est is None else
                       "지역제한과 추정가격은 확인됐지만 적용 상한의 공식 출처·사업 적용성이 확인되지 않았습니다.")
                add("①-15", "지역제한 적용 시 기준", "확인", "확인필요", why,
                    "국가계약법 시행규칙 제24조", "", g.get("문서", ""), g.get("위치", ""), g.get("원문", ""),
                    적용성="미확인", 증거상태=state, 대상="구매팀",
                    기준참조="지역제한_상한_물품용역" if official_reference_exists(f, "지역제한_상한_물품용역") else None)
            else:
                ok = est < threshold
                add("①-15", "지역제한 적용 시 기준", "확인", "적합" if ok else "수정필요",
                    (f"추정가격 {won(est)}이 확인된 적용기준 상한 {won(threshold)} 미만입니다. 이행 현장·납품지 기준은 별도 확인하세요." if ok
                     else f"추정가격 {won(est)}이 확인된 적용기준 상한 {won(threshold)} 이상입니다."),
                    "국가계약법 시행규칙 제24조 / 감사원 공공계약 실무가이드(2024) p.119~120",
                    "지역제한 조건을 적용 기준에 맞게 정정하세요." if not ok else "",
                    g.get("문서", ""), g.get("위치", ""), g.get("원문", ""),
                    적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조="지역제한_상한_물품용역")
                if not ok:
                    summ(f"추정가격 {eok(est)}가 적용 지역제한 상한 이상", "지역제한 조건 정정")
        elif g.get("있음") is False and absence_is_proven(f, g, g.get("문서", "")):
            add("①-15", "지역제한 적용 시 기준", "확인", "해당없음", "제공된 참가자격 문서와 관련 개체를 전수검색했으며 지역제한이 없습니다.",
                "국가계약법 시행규칙 제24조 / 감사원 공공계약 실무가이드(2024) p.119~120",
                문서=g.get("문서", ""), 위치=g.get("위치", ""), 원문="해당 내용 없음", 적용성="비적용",
                증거상태="전수검색없음", 기준유형=["법령·공식기준"], 검색어=g.get("검색어"),
                검색범위=g.get("검색범위"))
        else:
            add("①-15", "지역제한 적용 시 기준", "확인", "확인필요",
                "지역제한 여부가 확인되지 않았습니다. 문서와 개체의 검색 범위를 확인하세요.",
                "국가계약법 시행규칙 제24조", "", g.get("문서", ""), g.get("위치", ""), g.get("원문", ""),
                적용성="미확인", 증거상태="미판독" if g else "미제출", 대상="구매팀")


def check_notice(f, th, est):
    notice_fact, deadline_fact = f.get("공고일"), f.get("제출마감일")
    date_facts = [notice_fact, deadline_fact]
    n = parse_date(notice_fact.get("값")) if isinstance(notice_fact, dict) else None
    dl = parse_date(deadline_fact.get("값")) if isinstance(deadline_fact, dict) else None
    source_rows = [fact for fact in date_facts if isinstance(fact, dict) and
                   all(isinstance(fact.get(field), str) and fact[field].strip()
                       for field in ("문서", "원문", "위치"))]
    source_docs, source_locations, source_quotes = source_evidence(source_rows)
    dates_sourced = all(sourced_fact(fact) and parsed is not None
                        for fact, parsed in zip(date_facts, (n, dl)))
    method, kind, urgent = f.get("낙찰방식", ""), f.get("계약유형", ""), bool(f.get("긴급"))
    if method == "협상":
        # 협상 공고기간은 ③-2에서 판정한다. ①-19는 해당 방식에 비적용이다.
        add("①-19", "공고기간 산정(달력 계산)", "★필수", "해당없음", "협상에 의한 계약이라 ③-2에서 판정합니다.",
            "국가계약법 시행령 제35조 / 감사원 공공계약 실무가이드(2024) p.296~297 [표91]", "", "공고문", 연계="③-2",
            적용성="비적용", 증거상태="판독완료", 기준유형=["법령·공식기준"])
    if method == "협상":
        id_, name = "③-2", "공고기간(40일/10일)·기산점"
        basis = "국가계약법 시행령 제35조 제4항·제43조 제3항 / 감사원 공공계약 실무가이드(2024) p.297 [표91]"
        if not (n and dl):
            unavailable = any(not isinstance(fact, dict) or fact.get("증거상태") == "미제출" for fact in date_facts)
            add(id_, name, "★필수", "확인필요",
                "공고일·제출마감일이 아직 확인되지 않아 공고기간을 계산할 수 없습니다.", basis,
                "", source_docs, source_locations, source_quotes,
                적용성="미확인", 증거상태="미제출" if unavailable else "미판독", 대상="구매팀")
            summ("공고일·마감일 미정 → 게시 시 공고기간 확인", "게시 때 공고기간 계산")
            return
        if not dates_sourced:
            states = {fact.get("증거상태") for fact in date_facts if isinstance(fact, dict)}
            state = next((candidate for candidate in ("미제출", "충돌", "미판독") if candidate in states), "미판독")
            add(id_, name, "★필수", "확인필요",
                "공고일·제출마감일 수치는 있으나 원문 인용·문서 위치·판독 상태가 갖춰지지 않아 계산 판정을 보류합니다.",
                basis, "날짜별 실제 원문 인용·문서명·위치를 기록하고 충돌 여부를 확인하세요.",
                source_docs, source_locations, source_quotes,
                적용성="미확인", 증거상태=state, 대상="구매팀")
            return
        short_key = "공고기간_일.협상_긴급또는고시금액미만"
        base_key = "공고기간_일.협상"
        if urgent:
            selected_key = short_key
            need, record, applies = official_rule(f, th, selected_key)
            refs = [selected_key]
        else:
            if est is None:
                short, short_record, short_applies = official_rule(f, th, short_key)
                basic, basic_record, basic_applies = official_rule(f, th, base_key)
                add(id_, name, "★필수", "확인필요",
                    "협상 공고기간의 적용일수는 추정가격의 고시금액 해당 여부에 따라 달라지나, 명시된 추정가격이 없습니다.", basis,
                    "추정가격과 적용 공고기간 기준을 확인하세요.", "공고문", 적용성="미확인", 증거상태="미제출", 대상="구매팀",
                    기준참조=[key for key in (short_key, base_key) if official_reference_exists(f, key)])
                return
            cutoff, cutoff_record, cutoff_applies = official_rule(f, th, "고시금액_물품용역")
            if not is_number(cutoff) or cutoff_applies != "적용":
                add(id_, name, "★필수", "확인필요",
                    "추정가격은 확인됐지만 고시금액 기준의 출처·이번 사업 적용성이 확인되지 않아 공고기간 분기를 정할 수 없습니다.",
                    basis, "공식 고시금액 기준과 적용범위를 확인하세요.", "공고문", 적용성="미확인", 증거상태="미판독", 대상="구매팀",
                    기준참조="고시금액_물품용역" if official_reference_exists(f, "고시금액_물품용역") else None)
                return
            selected_key = short_key if est < cutoff else base_key
            need, record, applies = official_rule(f, th, selected_key)
            refs = ["고시금액_물품용역", selected_key]
    elif kind in ("용역", "물품"):
        id_, name = "①-19", "공고기간 산정(달력 계산)"
        basis = "국가계약법 시행령 제35조 / 감사원 공공계약 실무가이드(2024) p.296~297 [표91]"
        if not (n and dl):
            unavailable = any(not isinstance(fact, dict) or fact.get("증거상태") == "미제출" for fact in date_facts)
            add(id_, name, "★필수", "확인필요", "공고일·제출마감일이 아직 확인되지 않아 공고기간을 계산할 수 없습니다.",
                basis, "", source_docs, source_locations, source_quotes,
                적용성="미확인", 증거상태="미제출" if unavailable else "미판독", 대상="구매팀")
            summ("공고일·마감일 미정 → 게시 시 공고기간 확인", "게시 때 공고기간 계산")
            return
        if not dates_sourced:
            states = {fact.get("증거상태") for fact in date_facts if isinstance(fact, dict)}
            state = next((candidate for candidate in ("미제출", "충돌", "미판독") if candidate in states), "미판독")
            add(id_, name, "★필수", "확인필요",
                "공고일·제출마감일 수치는 있으나 원문 인용·문서 위치·판독 상태가 갖춰지지 않아 계산 판정을 보류합니다.",
                basis, "날짜별 실제 원문 인용·문서명·위치를 기록하고 충돌 여부를 확인하세요.",
                source_docs, source_locations, source_quotes,
                적용성="미확인", 증거상태=state, 대상="구매팀")
            return
        selected_key = "공고기간_일.물품용역_긴급" if urgent else "공고기간_일.물품용역"
        need, record, applies = official_rule(f, th, selected_key)
        refs = [selected_key]
    else:
        why = ("공사는 현장설명 유무·규모별 공고기간 기준을 확인해야 합니다." if kind == "공사"
               else f"계약유형('{kind}')을 알 수 없어 공고기간 기준을 확인해야 합니다.")
        add("①-19", "공고기간 산정(달력 계산)", "★필수", "확인필요", why,
            "국가계약법 시행령 제35조", "", "공고문", 적용성="미확인", 증거상태="미판독", 대상="구매팀")
        return
    if applies != "적용" or not is_number(need):
        add(id_, name, "★필수", "확인필요",
            "공고기간의 숫자 기준을 확인했지만 공식 출처·이번 사업 적용성이 확인되지 않아 계산 결과를 판정할 수 없습니다.",
            basis, "적용 가능한 공고기간 기준을 확인하세요.", source_docs, source_locations, source_quotes,
            적용성="미확인", 증거상태="미판독", 대상="구매팀",
            기준참조=[key for key in refs if official_reference_exists(f, key)])
        return
    gap = (dl - n).days
    msg = f"공고일 {n} ~ 제출마감일 {dl}: {gap}일 차이, 필요 {need}일(마감일 전일부터 기산)."
    link = "" if id_ == "①-19" else "①-19"
    refs = [key for key in refs if official_reference_exists(f, key)]
    if gap > need:
        add(id_, name, "★필수", "적합", msg, basis, "", source_docs, source_locations, source_quotes,
            적용성="적용", 증거상태="판독완료",
            기준유형=["법령·공식기준"], 기준참조=refs)
    elif gap == need:
        add(id_, name, "★필수", "확인필요", msg + " 경계값은 달력 계산을 재확인하세요.", basis, "",
            source_docs, source_locations, source_quotes,
            적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=refs)
    else:
        add(id_, name, "★필수", "수정필요", msg + " 공고기간이 부족합니다.", basis,
            f"제출마감일을 최소 {need + 1}일 이후로 조정하세요(공고일 기준).", source_docs, source_locations, source_quotes, link,
            적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조=refs)
        summ(f"공고기간 부족({gap}일, 필요 {need}일 초과)", f"마감일을 공고일+{need + 1}일 이후로")


def check_scores(f, th):
    if f.get("낙찰방식") != "협상":
        return
    b = f.get("배점") or {}
    t, p = b.get("기술"), b.get("가격")
    raw = f.get("기술평가") or {}
    where = {"문서": b.get("문서", ""), "위치": b.get("위치", ""), "원문": b.get("원문", "")}
    basis_212 = "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.259"
    basis_213 = "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.258"
    if not is_number(t) or not is_number(p):
        add("②-12", "기술·가격 배점 합계 100점", "★필수", "확인필요",
            "기술·가격 최종 가중치 중 하나 이상을 확인할 수 없어 합계를 계산하지 못했습니다.",
            basis_212, "", b.get("문서", "제안요청서"), b.get("위치", ""), b.get("원문", ""),
            적용성="미확인", 증거상태="미판독" if b else "미제출", 대상="구매팀", 기준유형=["사업요건"])
        add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "확인필요",
            "최종 가격 가중치를 확인할 수 없어 기술·가격 평가구조를 판단하지 못했습니다.",
            basis_212, "", b.get("문서", "제안요청서"), b.get("위치", ""), b.get("원문", ""),
            적용성="미확인", 증거상태="미판독" if b else "미제출", 대상="구매팀")
        add("②-13", "가격평가 비중 범위", "★필수", "확인필요",
            "기술·가격 최종 가중치가 미확인이라 공식 범위나 기관 프로필과 비교하지 않았습니다.",
            basis_213, "최종 가중치를 확인하세요.", b.get("문서", "제안요청서"), b.get("위치", ""), b.get("원문", ""),
            적용성="미확인", 증거상태="미판독" if b else "미제출", 대상="구매팀", 연계="③-4")
    else:
        total = t + p
        if not is_number(total):
            add("②-12", "기술·가격 배점 합계 100점", "★필수", "확인필요",
                "기술·가격 가중치의 합계가 유한한 숫자로 계산되지 않아 합계를 판정하지 않았습니다.",
                basis_212, "유한한 숫자의 최종 가중치를 확인하세요.", **where,
                적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준유형=["사업요건"])
            return
        if total != 100:
            add("②-12", "기술·가격 배점 합계 100점", "★필수", "수정필요",
                f"문서에 기재된 최종 기술 {t:g}점+가격 {p:g}점={total:g}점으로 합계 100점과 모순됩니다.",
                basis_212, "최종 기술·가격 가중치 합계를 확인해 정합화하세요.", **where,
                적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
            summ(f"최종 가중치 합계 {total:g}점 ≠ 100점", "최종 기술·가격 가중치 정합화")
        else:
            add("②-12", "기술·가격 배점 합계 100점", "★필수", "적합",
                f"최종 기술 {t:g}점+가격 {p:g}점이 100점입니다.", basis_212, **where,
                적용성="적용", 증거상태="판독완료", 기준유형=["사업요건"])

        min_price, min_record, min_applies = official_rule(f, th, "배점.원칙_가격_최소")
        if min_applies == "적용" and is_number(min_price):
            if p == 0 and min_price > 0:
                add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "수정필요",
                    f"가격평가 비중이 0점입니다. 확인된 적용 기준의 기본 최소 가격비중은 {min_price:g}점이며 승인된 예외 근거는 별도 확인되지 않았습니다.",
                    basis_212, "적용 기준 또는 확인된 예외 승인에 따라 가격 가중치를 정정하세요.", **where,
                    적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"],
                    기준참조="배점.원칙_가격_최소")
                summ("가격 평가비중 0점", "적용 기준과 예외 승인 확인")
            else:
                add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "적합",
                    f"가격평가 비중 {p:g}점이 반영되어 가격평가 0점은 아닙니다.",
                    basis_212, **where, 적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"],
                    기준참조="배점.원칙_가격_최소")
        else:
            add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "확인필요",
                "가격점수만으로 0점이 허용되지 않는지 판단할 적용 공식기준의 출처·범위가 확인되지 않았습니다.",
                basis_212, "적용 가능한 공식기준을 확인하세요.", **where, 적용성="미확인", 증거상태="미판독",
                대상="구매팀", 기준참조="배점.원칙_가격_최소" if official_reference_exists(f, "배점.원칙_가격_최소") else None)

        min_value, min_meta, min_app = official_rule(f, th, "배점.원칙_가격_최소")
        max_value, max_meta, max_app = official_rule(f, th, "배점.원칙_가격_최대")
        range_refs = [key for key in ("배점.원칙_가격_최소", "배점.원칙_가격_최대") if official_reference_exists(f, key)]
        if min_app == "적용" and max_app == "적용" and is_number(min_value) and is_number(max_value):
            if min_value <= p <= max_value:
                add("②-13", "가격평가 비중 범위", "★필수", "적합",
                    f"최종 가격 가중치 {p:g}점이 확인된 적용 공식기준 범위 {min_value:g}~{max_value:g}점 안입니다.",
                    basis_213, **where, 연계="③-4", 적용성="적용", 증거상태="판독완료",
                    기준유형=["법령·공식기준"], 기준참조=range_refs)
            else:
                add("②-13", "가격평가 비중 범위", "★필수", "확인필요",
                    f"최종 가격 가중치 {p:g}점이 확인된 기본 범위 {min_value:g}~{max_value:g}점 밖입니다. 조정 근거·승인 및 이번 사업 적용을 확인해야 하며, 범위 이탈만으로 위반을 단정하지 않습니다.",
                    basis_213, "조정 사유와 적용되는 승인·예외 근거를 확인하세요.", **where, 연계="③-4",
                    적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=range_refs)
        else:
            add("②-13", "가격평가 비중 범위", "★필수", "확인필요",
                "기술·가격 가중치가 확인됐지만 적용 가능한 공식 기본 범위의 출처·범위가 미확정입니다. 기관 프로필이나 예시비율을 법정 기준으로 대체하지 않았습니다.",
                basis_213, "이번 사업에 적용되는 공식 기준을 확인하세요.", **where, 연계="③-4",
                적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=range_refs)

        profiles = ((f.get("meta") or {}).get("기관프로필") or [])
        known_profile_ids = {"기관_기술강조_90_10", "기관_균형_80_20"}
        relevant_profiles = [entry for entry in profiles if isinstance(entry, dict) and entry.get("프로필ID") in known_profile_ids]
        for entry in relevant_profiles:
            profile_id = entry["프로필ID"]
            profile, record, state = institution_profile(f, th, profile_id)
            if state == "비적용":
                continue
            if state != "적용":
                add("②-13", f"기관 배점 프로필 확인({profile_id})", "확인", "확인필요",
                    "기관 배점 프로필의 적용성이 확인되지 않아 공식 기준과 별도로 비교할 수 없습니다.",
                    source_reference(record), "", b.get("문서", ""), b.get("위치", ""), b.get("원문", ""),
                    적용성="미확인", 증거상태="미판독", 기준유형=["기관운영"], 대상="구매팀", 프로필참조=profile_id)
            elif t != profile.get("기술배점") or p != profile.get("가격배점"):
                add("②-13", f"기관 배점 프로필({profile_id})", "확인", "수정필요",
                    f"확인된 기관 프로필은 기술 {profile['기술배점']}·가격 {profile['가격배점']}점이나 문서 기재는 기술 {t}·가격 {p}점입니다.",
                    source_reference(record), "기관의 적용 프로필과 문서 배점을 확인해 정합화하세요.", **where,
                    적용성="적용", 증거상태="충돌", 기준유형=["기관운영"], 대상="구매팀", 프로필참조=profile_id)
            else:
                add("②-13", f"기관 배점 프로필({profile_id})", "확인", "적합",
                    "기술·가격 가중치가 출처와 적용성이 확인된 기관 프로필과 일치합니다.", source_reference(record), **where,
                    적용성="적용", 증거상태="판독완료", 기준유형=["기관운영"], 프로필참조=profile_id)

    items = f.get("기술평가항목") or []
    q = f.get("정량평가항목") or []
    if items:
        cap, cap_record, cap_applies = official_rule(f, th, "배점.평가항목_최대")
        scored = [i for i in items if is_number(i.get("배점"))]
        unknown_scores = [i for i in items if not is_number(i.get("배점"))]
        if cap_applies == "적용" and is_number(cap):
            over = [i for i in scored if i["배점"] > cap]
        else:
            over = []
            add("②-14", "각 평가항목 배점한도", "★필수", "확인필요",
                "평가항목별 점수는 읽혔지만 각 항목 최대점수의 공식 출처·이번 사업 적용성이 확인되지 않았습니다.",
                "협상에 의한 계약체결기준 [별표] 비고 / 감사원 공공계약 실무가이드(2024) p.259",
                "적용 가능한 항목별 상한 기준을 확인하세요.", items[0].get("문서", "") or b.get("문서", ""),
                items[0].get("위치", ""), items[0].get("원문", ""), "③-5",
                적용성="미확인", 증거상태="미판독", 대상="구매팀",
                기준참조="배점.평가항목_최대" if official_reference_exists(f, "배점.평가항목_최대") else None)
        if cap_applies == "적용" and is_number(cap) and over:
            add("②-14", "각 평가항목 배점한도", "★필수", "수정필요",
                ", ".join(f"'{i['항목']}' {i['배점']:g}점" for i in over) + f"으로 적용 상한 {cap:g}점을 넘습니다. "
                f"확인된 적용기준의 항목별 상한은 {cap:g}점입니다.",
                "협상에 의한 계약체결기준 [별표] 비고 / 감사원 공공계약 실무가이드(2024) p.259",
                f"적용 기준에 맞게 평가항목 배점을 {cap:g}점 이하로 조정하세요.",
                over[0].get("문서", "") or b.get("문서", ""), over[0].get("위치", ""), over[0].get("원문", ""), "③-5",
                적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 대상="작성자",
                기준참조="배점.평가항목_최대")
            summ(", ".join(f"'{i['항목']}' {i['배점']:g}점" for i in over) + " — 항목별 적용 상한 초과", f"{cap:g}점 이하로 조정")
            # finding 하나에는 원문이 하나뿐이다. 두 번째 초과 항목부터는 참조 finding으로 그 자리에 메모를 단다.
            add_refs(findings[-1], over[1:], lambda i: f"{i['항목']} {i['배점']}점 → {cap:g}점 이하로")
        elif cap_applies == "적용" and is_number(cap) and not unknown_scores:
            add("②-14", "각 평가항목 배점한도", "★필수", "적합",
                f"평가항목 {len(items)}개 모두 확인된 적용 상한 {cap:g}점 이하입니다.",
                "협상에 의한 계약체결기준 [별표] 비고", 연계="③-5", **where,
                적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조="배점.평가항목_최대")
        typed_items = any(i.get("평가유형") in ("정량", "정성") for i in items)
        score_rows = list(items) if typed_items else list(items) + list(q)
        if typed_items and not any(i.get("평가유형") == "정량" for i in items):
            score_rows.extend(q)
        unknown_total = [i for i in score_rows if not is_number(i.get("배점"))]
        raw_max = raw.get("원점수만점")
        q_max, qual_max = raw.get("정량만점"), raw.get("정성만점")
        q_max = q_max if is_number(q_max) else None
        qual_max = qual_max if is_number(qual_max) else None
        raw_max = raw_max if is_number(raw_max) else None
        component_max = q_max + qual_max if q_max is not None and qual_max is not None else None
        if not is_number(component_max):
            component_max = None
        if raw_max is None:
            raw_max = component_max
        if unknown_total:
            add("②-14", "평가항목 배점 합계", "★필수", "확인필요",
                "일부 정량·정성 항목의 배점이 미확인이라 원점수 합계를 계산하지 않았습니다. null을 0점으로 보지 않습니다.",
                "협상에 의한 계약체결기준 [별표]", "", items[0].get("문서", "") or b.get("문서", ""),
                items[0].get("위치", ""), items[0].get("원문", ""), 적용성="미확인", 증거상태="미판독", 대상="구매팀")
        elif raw_max is None:
            add("②-14", "평가항목 원점수 합계", "★필수", "확인필요",
                "정량·정성 점수의 원점수 만점이 확인되지 않아 합계 또는 환산의 일치 여부를 판정하지 않았습니다.",
                "협상에 의한 계약체결기준 [별표]", "원점수 만점과 정량·정성별 만점을 확인하세요.",
                items[0].get("문서", "") or b.get("문서", ""), items[0].get("위치", ""), items[0].get("원문", ""),
                적용성="미확인", 증거상태="미판독", 대상="구매팀")
        else:
            s = sum(i["배점"] for i in score_rows)
            if not is_number(s):
                add("②-14", "평가항목 원점수 합계", "★필수", "확인필요",
                    "평가항목 원점수 합계가 유한한 숫자로 계산되지 않았습니다.",
                    "협상에 의한 계약체결기준 [별표]", "평가항목의 원점수 값과 만점을 확인하세요.",
                    items[0].get("문서", "") or b.get("문서", ""), items[0].get("위치", ""), items[0].get("원문", ""),
                    적용성="미확인", 증거상태="미판독", 대상="구매팀")
                s = None
            if s is not None and typed_items:
                for score_type, declared in (("정량", q_max), ("정성", qual_max)):
                    typed = [i for i in items if i.get("평가유형") == score_type]
                    if typed and is_number(declared) and all(is_number(i.get("배점")) for i in typed):
                        typed_sum = sum(i["배점"] for i in typed)
                        if not is_number(typed_sum):
                            source_docs, source_locations, source_quotes = source_evidence(typed)
                            add("②-14", f"{score_type} 원점수 합계", "★필수", "확인필요",
                                f"{score_type} 평가항목 합계가 유한한 숫자로 계산되지 않았습니다.",
                                "협상에 의한 계약체결기준 [별표]", f"{score_type} 평가항목의 수치와 만점을 확인하세요.",
                                source_docs, source_locations, source_quotes,
                                적용성="미확인", 증거상태="미판독", 대상="구매팀")
                        elif typed_sum != declared:
                            source_docs, source_locations, source_quotes = source_evidence(typed)
                            add("②-14", f"{score_type} 원점수 합계", "★필수", "수정필요",
                                f"{score_type} 평가항목 합계 {typed_sum:g}점이 문서의 {score_type} 원점수 만점 {declared:g}점과 다릅니다.",
                                "협상에 의한 계약체결기준 [별표]", f"{score_type} 평가항목 합계와 만점을 정합화하세요.",
                                source_docs, source_locations, source_quotes,
                                적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
                    elif score_type == "정량" and not typed and q and is_number(declared) and all(
                            is_number(i.get("배점")) for i in q):
                        quant_sum = sum(i["배점"] for i in q)
                        if not is_number(quant_sum):
                            source_docs, source_locations, source_quotes = source_evidence(q)
                            add("②-14", "정량 원점수 합계", "★필수", "확인필요",
                                "정량평가 항목 합계가 유한한 숫자로 계산되지 않았습니다.",
                                "협상에 의한 계약체결기준 [별표]", "정량평가 항목의 수치와 만점을 확인하세요.",
                                source_docs, source_locations, source_quotes,
                                적용성="미확인", 증거상태="미판독", 대상="구매팀")
                        elif quant_sum != declared:
                            source_docs, source_locations, source_quotes = source_evidence(q)
                            add("②-14", "정량 원점수 합계", "★필수", "수정필요",
                                f"정량평가 항목 합계 {quant_sum:g}점이 문서의 정량 원점수 만점 {declared:g}점과 다릅니다.",
                                "협상에 의한 계약체결기준 [별표]", "정량평가 항목 합계와 만점을 정합화하세요.",
                                source_docs, source_locations, source_quotes, 적용성="미확인", 증거상태="충돌",
                                기준유형=["사업요건"])
            if s is not None and raw_max is not None and s != raw_max:
                source_docs, source_locations, source_quotes = source_evidence(score_rows)
                add("②-14", "평가항목 원점수 합계", "★필수", "수정필요",
                    f"기술평가 항목 원점수 합계 {s:g}점이 문서의 원점수 만점 {raw_max:g}점과 다릅니다.",
                    "협상에 의한 계약체결기준 [별표]", "평가항목별 원점수와 원점수 만점을 정합화하세요.",
                    source_docs, source_locations, source_quotes,
                    적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
            elif s is not None and raw_max is not None and t is not None and raw_max != t:
                mode = raw.get("환산방식")
                normalized = raw.get("환산기술배점")
                expected = s / raw_max * t if raw_max else None
                if mode in ("명시산식", "비례환산") and raw.get("환산식원문"):
                    if not is_number(expected):
                        add("②-14", "기술 원점수 환산", "★필수", "확인필요",
                            "확인된 원점수·만점·기술 가중치로 유한한 환산점수를 계산하지 못했습니다.",
                            "협상에 의한 계약체결기준 [별표]", "원점수 만점과 환산식을 확인하세요.", **where,
                            적용성="미확인", 증거상태="미판독", 대상="구매팀")
                    elif not is_number(normalized):
                        add("②-14", "기술 원점수 환산", "★필수", "확인필요",
                            f"원점수 {s:g}/{raw_max:g}와 환산식은 확인됐지만 최종 환산점수가 미확인입니다.",
                            "협상에 의한 계약체결기준 [별표]", "문서에 기재된 최종 환산점수를 확인하세요.", **where,
                            적용성="미확인", 증거상태="미판독", 대상="구매팀")
                    elif abs(normalized - expected) > 0.001:
                        add("②-14", "기술 원점수 환산", "★필수", "수정필요",
                            f"원점수 {s:g}/{raw_max:g}를 기술 가중치 {t:g}점으로 환산한 값은 {expected:g}점이나 문서 기재 환산점수는 {normalized:g}점입니다.",
                            "협상에 의한 계약체결기준 [별표]", "명시된 환산식에 따라 기술점수를 정합화하세요.", **where,
                            적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
                    else:
                        add("②-14", "기술 원점수 환산", "★필수", "적합",
                            f"문서에 확인된 {mode}로 원점수 {s:g}/{raw_max:g}를 기술 가중치 {t:g}점에 환산하면 {expected:g}점입니다.",
                            "협상에 의한 계약체결기준 [별표]", **where, 적용성="적용", 증거상태="판독완료",
                            기준유형=["사업요건"])
                else:
                    add("②-14", "기술 원점수 환산", "★필수", "확인필요",
                        f"기술 원점수 만점 {raw_max:g}점과 최종 기술 가중치 {t:g}점은 서로 다른 척도입니다. 문서의 환산방식·산식을 확인하세요.",
                        "협상에 의한 계약체결기준 [별표]", "", b.get("문서", ""), b.get("위치", ""), raw.get("환산식원문") or b.get("원문", ""),
                        적용성="미확인", 증거상태="미판독", 대상="구매팀")
            elif s is not None and raw_max is not None:
                add("②-14", "평가항목 원점수 합계", "★필수", "적합",
                    f"기술평가 원점수 합계 {s:g}점이 원점수 만점 {raw_max:g}점과 일치합니다.",
                    "협상에 의한 계약체결기준 [별표]", **where, 적용성="적용", 증거상태="판독완료",
                    기준유형=["사업요건"])
    else:
        add("②-14", "각 평가항목 배점한도", "★필수", "확인필요",
            "제안요청서 평가항목별 배점표가 facts에서 확인되지 않았습니다. 평가표와 개체의 판독·검색 상태를 확인하세요.",
            "협상에 의한 계약체결기준 [별표] 비고 / 감사원 공공계약 실무가이드(2024) p.259",
            "", b.get("문서", "제안요청서"), b.get("위치", ""), b.get("원문", ""), "③-5",
            적용성="미확인", 증거상태="미제출", 대상="구매팀")

    if q:
        profile_id = "기관_정량최저평점_70"
        profile, record, applies = institution_profile(f, th, profile_id)
        if applies == "비적용":
            add("③-7", "정량평가 최저평점 기관기준", "★필수", "해당없음",
                "출처와 이번 사업 범위가 확인되어 이 기관 최저평점 프로필은 비적용입니다. 보편적 70% 법정 기준은 적용하지 않았습니다.",
                source_reference(record), 적용성="비적용", 증거상태="판독완료", 기준유형=["기관운영"],
                프로필참조=profile_id)
        elif applies == "적용":
            percent = profile.get("최저평점_배점대비퍼센트")
            complete = all(is_number(i.get("배점")) and is_number(i.get("최저등급평점")) for i in q)
            if not is_number(percent) or not complete:
                add("③-7", "정량평가 최저평점 기관기준", "★필수", "확인필요",
                    "출처가 확인된 기관 기준이 적용되지만 일부 최저등급 점수 또는 배점이 미확인입니다. null을 0으로 보지 않습니다.",
                    source_reference(record), "", b.get("문서", ""), b.get("위치", ""), b.get("원문", ""), "②-15, ②-16",
                    적용성="미확인", 증거상태="미판독", 기준유형=["기관운영"], 대상="구매팀", 프로필참조=profile_id)
            else:
                bad = [i for i in q if i["최저등급평점"] < i["배점"] * percent / 100 - 1e-9]
                if bad:
                    source_docs, source_locations, source_quotes = source_evidence([bad[0]])
                    add("③-7", "정량평가 최저평점 기관기준", "★필수", "수정필요",
                        f"적용 확인된 기관 프로필의 최저평점 {percent:g}%보다 낮은 항목: " + ", ".join(
                            f"{i['항목']}(배점 {i['배점']:g}, 최저 {i['최저등급평점']:g})" for i in bad),
                        source_reference(record), "적용된 기관 프로필에 따라 최저평점을 확인해 정합화하세요.",
                        source_docs, source_locations, source_quotes, "②-15, ②-16",
                        적용성="적용", 증거상태="판독완료", 기준유형=["기관운영"], 프로필참조=profile_id)
                    summ(f"기관 프로필 최저평점 {percent:g}% 미만", "적용 기관 기준에 따라 최저평점 정합화")
                    add_refs(findings[-1], bad[1:],
                             lambda item: f"{item['항목']} 최저 {item['최저등급평점']:g}/{item['배점']:g}점 → {percent:g}% 이상으로")
                else:
                    add("③-7", "정량평가 최저평점 기관기준", "★필수", "적합",
                        f"모든 정량평가 최저평점이 출처가 확인된 기관 프로필의 {percent:g}% 이상입니다.",
                        source_reference(record), 연계="②-15, ②-16", 적용성="적용", 증거상태="판독완료",
                        기준유형=["기관운영"], 프로필참조=profile_id)
        else:
            add("③-7", "정량평가 최저평점 기관기준", "★필수", "확인필요",
                "정량평가 점수표는 있으나 70%는 보편적 법정 하한으로 적용할 수 없습니다. 이번 기관·사업의 프로필 출처와 적용성을 확인하세요.",
                source_reference(record), "", b.get("문서", ""), b.get("위치", ""), b.get("원문", ""), "②-15, ②-16",
                적용성="미확인", 증거상태="미제출" if record is None else "미판독", 기준유형=["기관운영"],
                대상="구매팀", 프로필참조=profile_id if profile_reference_exists(f, profile_id) else None)
    else:
        add("③-7", "정량평가 최저평점 기관기준", "★필수", "확인필요",
            "정량평가 항목이 확인되지 않아 기관 최저평점 기준의 적용 여부를 판단하지 않았습니다. 비적용인지 자료 누락인지 확인하세요.",
            "기관운영 프로필 확인", "", b.get("문서", ""), b.get("위치", ""), b.get("원문", ""),
            적용성="미확인", 증거상태="미판독" if f.get("기술평가항목") or b else "미제출",
            기준유형=["기관운영"], 대상="구매팀")

    c = f.get("실적건수평가") or {}
    if c.get("적용성") == "비적용" and c.get("증거상태") == "판독완료":
        add("③-8", "수행실적 '건수' 평가 시 한도", "확인", "해당없음",
            "문서에서 실적 건수평가가 적용되지 않음을 확인했습니다.", "조달청 협상에 의한 계약 제안서평가 세부기준",
            적용성="비적용", 증거상태="판독완료", 기준유형=["법령·공식기준"])
    elif not all(is_number(c.get(k)) for k in ("기준금액", "최대인정건수", "사업예산")):
        add("③-8", "수행실적 '건수' 평가 시 한도", "확인", "확인필요",
            "수행실적 건수평가 적용 여부 또는 계산에 필요한 금액·인정건수가 미확인입니다.",
            "조달청 협상에 의한 계약 제안서평가 세부기준", "적용 여부와 자료를 확인하세요.",
            c.get("문서", ""), c.get("위치", ""), c.get("원문", ""),
            적용성="미확인", 증거상태="미판독" if c else "미제출", 대상="구매팀")
    else:
        max_base, base_record, base_applies = official_rule(f, th, "실적건수평가.기준금액_예산대비_최대")
        max_total, total_record, total_applies = official_rule(f, th, "실적건수평가.합계_예산대비_최대")
        refs = [key for key in ("실적건수평가.기준금액_예산대비_최대",
                                "실적건수평가.합계_예산대비_최대") if official_reference_exists(f, key)]
        if base_applies != "적용" or total_applies != "적용" or not is_number(max_base) or not is_number(max_total):
            add("③-8", "수행실적 '건수' 평가 시 한도", "확인", "확인필요",
                "건수 평가 금액은 추출됐지만 적용 공식한도의 출처·이번 사업 적용성이 확인되지 않았습니다.",
                "조달청 협상에 의한 계약 제안서평가 세부기준", "적용 기준을 확인하세요.",
                c.get("문서", ""), c.get("위치", ""), c.get("원문", ""),
                적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=refs)
        else:
            problems = []
            if c["기준금액"] > c["사업예산"] * max_base:
                problems.append(f"기준금액 {won(c['기준금액'])}이 사업예산의 {max_base:.0%}를 넘습니다.")
            if c["기준금액"] * c["최대인정건수"] > c["사업예산"] * max_total:
                problems.append("기준금액×최대인정건수가 사업예산 한도를 넘습니다.")
            add("③-8", "수행실적 '건수' 평가 시 한도", "확인", "수정필요" if problems else "적합",
                " ".join(problems) or "기준금액과 인정건수가 확인된 적용기준 한도 안입니다.",
                "조달청 협상에 의한 계약 제안서평가 세부기준",
                "적용 공식한도에 맞게 기준금액·인정건수를 조정하세요." if problems else "",
                c.get("문서", ""), c.get("위치", ""), c.get("원문", ""), 적용성="적용", 증거상태="판독완료",
                기준유형=["법령·공식기준"], 기준참조=refs)
            if problems:
                summ("실적 건수평가 기준금액·인정건수 한도 초과", "기준금액·인정건수를 한도에 맞춤")

    for key, id_, name, expect, basis, link in [
        ("협상적격자기준_퍼센트", "②-18", "협상적격자 기준(기술평가 배점한도의 85%)", "협상적격_기술점수_비율_퍼센트",
         "협상에 의한 계약체결기준 / 감사원 공공계약 실무가이드(2024) p.262~263", "③-10"),
        ("평점산식_하한_퍼센트", "②-17", "입찰가격 평점산식 하한", "입찰가격_평점산식_하한_퍼센트",
         "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.259~260", "③-9"),
    ]:
        v = f.get(key)
        if v is None:
            add(id_, name, "★필수", "확인필요",
                "문서에 적힌 기준값을 facts에서 확인할 수 없어 적용 기준과 대조하지 않았습니다.", basis,
                "공고문·제안요청서의 해당 기준값과 적용 공식 기준을 확인하세요.", "제안요청서", "", "",
                link, 적용성="미확인", 증거상태="미제출", 대상="구매팀",
                기준참조=_threshold_key_for_fact(key) if official_reference_exists(f, _threshold_key_for_fact(key)) else None)
            continue
        val = v.get("값") if isinstance(v, dict) else v
        meta = v if isinstance(v, dict) else {}
        expect, record, applies = official_rule(f, th, _threshold_key_for_fact(key))
        threshold_key = _threshold_key_for_fact(key)
        refs = [threshold_key] if official_reference_exists(f, threshold_key) else None
        if not is_number(val):
            add(id_, name, "★필수", "확인필요",
                "문서 기재 기준값이 유한한 숫자로 확인되지 않아 공식 기준과 대조하지 않았습니다.", basis,
                "원문에서 수치 기준값을 확인한 뒤 적용 공식 기준과 대조하세요.",
                meta.get("문서", ""), meta.get("위치", ""), meta.get("원문", ""), link,
                적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=refs)
            continue
        if not is_number(expect) or applies != "적용":
            add(id_, name, "★필수", "확인필요",
                f"문서 기재값 {val}%은 있으나 공식 기준의 출처·이번 사업 적용성이 확인되지 않았습니다.",
                basis, "적용 가능한 공식 기준과 문구를 확인하세요.",
                meta.get("문서", ""), meta.get("위치", ""), meta.get("원문", ""), link,
                적용성="미확인", 증거상태="미판독", 대상="구매팀", 기준참조=refs)
            continue
        ok = val == expect
        add(id_, name, "★필수", "적합" if ok else "수정필요",
            f"문서 기재값 {val}% / 확인된 적용 기준 {expect}%." + ("" if ok else " 값이 다릅니다."),
            basis, "" if ok else f"{expect}%로 고치고 공고문·제안요청서를 같은 문구로 통일하세요.",
            meta.get("문서", ""), meta.get("위치", ""), meta.get("원문", ""), link,
            적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 기준참조=refs)
        if not ok:
            label = "협상적격 기준" if id_ == "②-18" else "평점산식 하한"
            summ(f"{label} {val}% / 적용 기준 {expect}% 불일치", f"{expect}%로 통일")


def _threshold_key_for_fact(key):
    return {"협상적격자기준_퍼센트": "협상적격_기술점수_비율_퍼센트",
            "평점산식_하한_퍼센트": "입찰가격_평점산식_하한_퍼센트"}[key]


def check_joint(f, th):
    for key, name in (("공동계약", "공동도급 허용 여부 기재"), ("하도급", "하도급 허용 여부 기재")):
        d = f.get(key) or {}
        metadata_keys = {"구성원수", "최소지분율", "과거실적증빙"}
        entries = {doc: value for doc, value in d.items()
                   if doc not in metadata_keys and isinstance(value, dict) and "값" in value}
        current_candidates = {doc: value for doc, value in entries.items() if value.get("맥락") == "현재참가조건"}
        unread_current = {doc: value for doc, value in current_candidates.items()
                          if value.get("증거상태", "판독완료") != "판독완료"}
        current = {doc: value for doc, value in current_candidates.items() if doc not in unread_current}
        ambiguous = {doc: value for doc, value in entries.items()
                     if value.get("맥락") not in ("현재참가조건", "과거실적증빙")}
        if unread_current:
            state = "미제출" if any(value.get("증거상태") == "미제출" for value in unread_current.values()) else "미판독"
            add("②-3", name, "확인", "확인필요",
                f"현재 {key} 조건이 미판독 또는 미제출 상태여서 문서 간 비교를 완료하지 않았습니다.",
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91", "",
                ", ".join(unread_current), loc(unread_current), quotes(unread_current), "①-17, ①-18",
                적용성="미확인", 증거상태=state, 기준유형=["사업요건"], 대상="구매팀")
            continue
        if not current and not ambiguous:
            # 과거 실적 evidence is intentionally not a current participation condition.
            continue
        if ambiguous:
            add("②-3", name, "확인", "확인필요",
                f"{key} 사실에 현재 참가조건 맥락이 지정되지 않았습니다. 과거 실적 증빙과 구분해 확인하세요.",
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91", "",
                ", ".join(ambiguous), loc(ambiguous), quotes(ambiguous), "①-17, ①-18",
                적용성="미확인", 증거상태="미판독", 기준유형=["사업요건"], 대상="구매팀")
            continue
        vals = {doc: value.get("값") for doc, value in current.items()}
        missing = [doc for doc, value in current.items() if value.get("값") in ("미기재", "", None)]
        defined = {value for value in vals.values() if value not in ("미기재", "", None)}
        if len(current) < 2:
            add("②-3", name, "확인", "확인필요",
                f"현재 {key} 조건을 비교할 문서가 둘 미만입니다. 과거 실적 증빙은 현재 조건 비교에 포함하지 않았습니다.",
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91", "",
                ", ".join(current), loc(current), quotes(current), "①-17, ①-18",
                적용성="미확인", 증거상태="미제출", 기준유형=["사업요건"], 대상="구매팀")
        elif len(defined) > 1:
            source_docs, source_locations, source_quotes = source_evidence(current)
            add("②-3", name, "확인", "수정필요", f"현재 {key} 참가조건이 문서 간 다릅니다: " +
                ", ".join(f"{doc}={value}" for doc, value in vals.items()),
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91",
                f"현재 {key} 조건이 서로 같은 의미인지 확인해 문서를 정합화하세요.",
                source_docs, source_locations, source_quotes, "①-17, ①-18",
                적용성="미확인", 증거상태="충돌", 기준유형=["사업요건"])
            summ(f"현재 {key} 참가조건 불일치", f"현재 참가조건 정합화")
        elif missing:
            fully_searched = all(absence_is_proven(f, current[doc], doc) for doc in missing)
            if fully_searched:
                source_docs, source_locations, source_quotes = source_evidence(current)
                add("②-3", name, "확인", "수정필요", f"현재 {key} 조건이 전수검색 후 미기재인 문서: {', '.join(missing)}",
                    "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91",
                    f"현재 {key} 허용 여부를 적용 근거에 따라 명시하세요.", source_docs, source_locations, source_quotes,
                    "①-17, ①-18", 적용성="적용", 증거상태="전수검색없음", 기준유형=["사업요건"],
                    검색어=sum((current[doc].get("검색어", []) for doc in missing), []),
                    검색범위="; ".join(current[doc].get("검색범위", "") for doc in missing))
            else:
                add("②-3", name, "확인", "확인필요", f"현재 {key} 조건이 문서에서 확인되지 않았습니다: {', '.join(missing)}. 전체 텍스트·개체 검색을 확인하세요.",
                    "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91", "",
                    ", ".join(current), loc(current), quotes(current), "①-17, ①-18",
                    적용성="미확인", 증거상태="미판독", 기준유형=["사업요건"], 대상="구매팀")
        else:
            add("②-3", name, "확인", "적합", f"현재 {key} 참가조건이 제공된 문서 간 일치합니다({', '.join(defined)}).",
                "공동계약운용요령", "", ", ".join(current), loc(current), quotes(current),
                적용성="적용", 증거상태="판독완료", 기준유형=["사업요건"])

    joint = f.get("공동계약") or {}
    active_joint = any(doc not in {"구성원수", "최소지분율", "과거실적증빙"} and
                       isinstance(value, dict) and value.get("맥락") == "현재참가조건" and value.get("값") == "허용"
                       for doc, value in joint.items())
    if not active_joint and not any(k in joint for k in ("구성원수", "최소지분율")):
        return
    for fact_key, threshold_key, label, comparator in (
        ("구성원수", "공동계약.구성원_최대", "공동계약 구성원 수", lambda value, limit: value > limit),
        ("최소지분율", "공동계약.최소지분율_퍼센트", "공동계약 최소지분율", lambda value, limit: value < limit),
    ):
        fact = joint.get(fact_key)
        if fact is None and active_joint:
            add("①-17", label, "확인", "확인필요", f"현재 공동계약 허용 조건에서 {fact_key} 값이 미확인입니다.",
                "(계약예규) 공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90 [표31]",
                "문서의 구성원 수·최소지분율을 확인하세요.", 적용성="미확인", 증거상태="미판독", 대상="구매팀")
            continue
        if fact is None:
            continue
        if not isinstance(fact, dict):
            add("①-17", label, "확인", "확인필요",
                f"{fact_key}가 원문·문서·위치가 포함된 사실 레코드가 아니어서 출처를 확인하지 못했습니다.",
                "(계약예규) 공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90 [표31]",
                f"{fact_key}를 원문 인용·문서명·위치를 포함한 사실 레코드로 보완하세요.",
                적용성="미확인", 증거상태="미판독", 대상="구매팀")
            continue
        value = fact.get("값")
        if not sourced_fact(fact) or not is_number(value):
            state = fact.get("증거상태")
            if state not in ("미제출", "미판독", "충돌"):
                state = "미판독"
            add("①-17", label, "확인", "확인필요",
                f"{fact_key} 값이 있더라도 원문 인용·문서 위치·판독 상태가 갖춰진 유한한 수치가 아니어서 기준과 비교하지 않았습니다.",
                "(계약예규) 공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90 [표31]",
                f"{fact_key}의 수치와 실제 원문 인용·문서명·위치를 확인하세요.",
                fact.get("문서", ""), fact.get("위치", ""), fact.get("원문", ""),
                적용성="미확인", 증거상태=state, 대상="구매팀")
            continue
        limit, record, applies = official_rule(f, th, threshold_key)
        if applies != "적용" or not is_number(limit):
            add("①-17", label, "확인", "확인필요",
                f"문서의 {fact_key} 값은 있으나 기준의 공식 출처·이번 사업 적용성이 확인되지 않았습니다.",
                source_reference(record) or "(계약예규) 공동계약운용요령", "적용 기준과 범위를 확인하세요.",
                fact.get("문서", ""), fact.get("위치", ""), fact.get("원문", ""),
                적용성="미확인", 증거상태="미판독", 대상="구매팀",
                기준참조=threshold_key if official_reference_exists(f, threshold_key) else None)
        elif comparator(value, limit):
            unit = "인" if fact_key == "구성원수" else "%"
            add("①-17", label, "확인", "수정필요", f"{fact_key} {value:g}{unit}가 확인된 적용 기준 {limit:g}{unit}과 맞지 않습니다.",
                source_reference(record), f"적용 기준에 맞는 {fact_key}를 확인해 정합화하세요.",
                fact.get("문서", ""), fact.get("위치", ""), fact.get("원문", ""),
                적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"], 대상="작성자",
                기준참조=threshold_key)
            summ(f"{label} {value:g}{unit} / 적용기준 {limit:g}{unit} 불일치", f"적용 {fact_key} 기준에 맞춤")
        else:
            add("①-17", label, "확인", "적합", f"{fact_key} {value:g}가 확인된 적용 기준 범위입니다.",
                source_reference(record), fact.get("수정안", ""),
                fact.get("문서", ""), fact.get("위치", ""), fact.get("원문", ""),
                적용성="적용", 증거상태="판독완료", 기준유형=["법령·공식기준"],
                기준참조=threshold_key)


def main():
    global findings
    findings = []
    ap = argparse.ArgumentParser()
    ap.add_argument("facts")
    ap.add_argument("-o", "--out", default="numeric_findings.json")
    ap.add_argument("--thresholds", default=DEFAULT_TH)
    a = ap.parse_args()
    with open(a.facts, encoding="utf-8") as fp:
        f = json.load(fp)
    with open(a.thresholds, encoding="utf-8") as fp:
        th = json.load(fp)
    check_period(f)
    est = check_amount(f, th)
    check_restrictions(f, th, est)
    check_notice(f, th, est)
    check_scores(f, th)
    check_joint(f, th)
    with open(a.out, "w", encoding="utf-8") as fp:
        json.dump({"meta": f.get("meta") or {}, "추정가격": est, "기준": th.get("기준일"), "findings": findings}, fp,
                  ensure_ascii=False, indent=2)
    cnt = {}
    for x in findings:
        cnt[x["판정"]] = cnt.get(x["판정"], 0) + 1
    print(f"추정가격(VAT 제외): {won(est) if est is not None else '미확인'}")
    print("판정:", ", ".join(f"{k} {v}" for k, v in cnt.items()) or "없음")
    for x in findings:
        if x["판정"] != "적합":
            print(f"- [{x['판정']}] {x['id']} {x['항목']}: {x['문제점']}")
    print(f"저장: {a.out}")


if __name__ == "__main__":
    # 하네스(Claude Code·Codex 등)는 stdout을 파이프로 읽는다. Windows 기본(cp949)이면 글자가 깨지거나 죽는다.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
