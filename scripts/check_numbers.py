#!/usr/bin/env python3
"""[계산] 항목 판정기.

모델이 문서에서 뽑은 값(facts.json, 형식은 references/facts-schema.md)을 받아
체크리스트의 수치·일치 항목을 결정적으로 판정한다. 같은 입력이면 항상 같은 결과가 나온다.

사용법:
  python check_numbers.py facts.json -o numeric_findings.json [--thresholds ../references/thresholds.json]
"""
import argparse
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TH = os.path.join(HERE, "..", "references", "thresholds.json")

findings = []


def won(n):
    return f"{int(round(n)):,}원"


def add(id_, 항목, 중요도, 판정, 문제점="", 근거="", 수정안="", 문서="", 위치="", 원문="", 연계=""):
    findings.append({
        "id": id_, "항목": 항목, "중요도": 중요도, "판정": 판정, "판정방식": "계산",
        "문서": 문서, "위치": 위치, "원문": 원문, "문제점": 문제점,
        "근거": 근거, "수정안": 수정안, "연계": 연계,
    })


def summ(text):
    """직전에 추가한 finding에 한 줄 요약(메모 첫 줄)을 단다."""
    findings[-1]["요약"] = text


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


def parse_date(s):
    if not s:
        return None
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(s).strip())
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def norm_period(s):
    return re.sub(r"\s+", "", str(s or "")).replace("부터", "~").replace("까지", "")


# ---------------------------------------------------------------- checks

def check_period(f):
    d = f.get("사업기간") or {}
    docs = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("값")}
    if len(docs) < 2:
        add("②-1", "사업기간 일치", "★필수", "확인필요",
            "사업기간을 비교할 문서가 2개 미만입니다(공고문·제안요청서·원가계산보고서 중).",
            "협상에 의한 계약체결기준 제4조 제2항", "", "", loc(d), quotes(d))
        return
    vals = {k: norm_period(v["값"]) for k, v in docs.items()}
    if len(set(vals.values())) == 1:
        add("②-1", "사업기간 일치", "★필수", "적합", "문서 간 사업기간이 일치합니다.",
            "협상에 의한 계약체결기준 제4조 제2항", "", ", ".join(docs), loc(d), quotes(d))
    else:
        diff = "; ".join(f"{k}={v['값']}" for k, v in docs.items())
        add("②-1", "사업기간 일치", "★필수", "수정필요",
            f"문서 간 사업기간이 다릅니다: {diff}",
            "협상에 의한 계약체결기준 제4조 제2항 / 감사원 공공계약 실무가이드(2024) p.256",
            "원가계산보고서 기준기간과 같은 기간으로 공고문·제안요청서를 통일하세요.",
            ", ".join(docs), loc(d), quotes(d), "①-1")
        groups = {}
        for k, v in docs.items():
            groups.setdefault(sval(v["값"]), []).append(sdoc(k))
        summ("사업기간 불일치(" + " / ".join(f"{'·'.join(ds)} {val}" for val, ds in groups.items()) + ")")


def check_amount(f, th):
    """사업금액 일치 + 부가세 표기 혼용. 반환값: 추정가격(VAT 제외) 또는 None"""
    d = f.get("사업금액") or {}
    rate = th["부가세율"]
    docs = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("금액") is not None}
    est = f.get("추정가격")
    if not docs:
        add("②-2", "사업금액 일치(원가계산보고서 기준)", "★필수", "확인필요",
            "문서에서 사업금액을 찾지 못했습니다.", "국가계약법 시행령 제7조")
        return est
    ex_vat = {}
    labels = set()
    unknown = []
    for k, v in docs.items():
        vat = (v.get("부가세") or "불명").strip()
        if k != "원가계산보고서":  # 원가계산서는 보통 부가세 제외로 작성되므로 표기 혼용 판단에서 뺀다
            labels.add(vat)
        amt = float(v["금액"])
        if vat == "포함":
            ex_vat[k] = amt / (1 + rate)
        elif vat == "제외":
            ex_vat[k] = amt
        else:
            unknown.append(k)
            ex_vat[k] = None
    problems = []
    known = {k: x for k, x in ex_vat.items() if x is not None}
    if len(known) >= 2:
        vals = list(known.values())
        if max(vals) - min(vals) > 1:  # 원 단위 반올림 허용
            problems.append("부가세 기준을 맞춰도 금액이 다릅니다: " +
                            "; ".join(f"{k}={won(docs[k]['금액'])}(부가세 {docs[k].get('부가세','불명')})" for k in known))
    if unknown:
        problems.append(f"부가세 포함/제외 표기가 없는 문서: {', '.join(unknown)}")
    if "포함" in labels and "제외" in labels:
        problems.append("공고문과 제안요청서의 부가세 포함/제외 표기가 서로 다릅니다(혼용).")
    if problems:
        add("②-2", "사업금액 일치(원가계산보고서 기준)", "★필수", "수정필요", " ".join(problems),
            "국가계약법 시행령 제7조 / 감사원 공공계약 실무가이드(2024) p.256",
            "원가계산보고서 금액 기준으로 통일하고, 모든 문서에 '부가세 포함' 여부를 같은 방식으로 명시하세요.",
            ", ".join(docs), loc(d), quotes(d), "①-8, ①-10")
        if len(known) >= 2 and max(known.values()) - min(known.values()) > 1:
            summ("사업금액 불일치(" + " / ".join(f"{sdoc(k)} {eok(docs[k]['금액'])}" for k in known) + ")")
        elif unknown:
            summ("부가세 포함 여부 표기 누락(" + ", ".join(sdoc(k) for k in unknown) + ")")
        else:
            summ("부가세 포함/제외 표기 혼용")
    else:
        add("②-2", "사업금액 일치(원가계산보고서 기준)", "★필수", "적합",
            "문서 간 사업금액과 부가세 표기가 일치합니다.", "국가계약법 시행령 제7조",
            "", ", ".join(docs), loc(d), quotes(d))
    if est is None and known:
        est = round(min(known.values()))
    return est


def check_restrictions(f, th, est):
    kind = f.get("계약유형", "")
    r = f.get("실적제한") or {}
    if r.get("있음"):
        if kind in ("용역", "물품"):
            if est is None:
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "확인필요",
                    "실적제한이 있으나 추정가격을 확인하지 못해 판정할 수 없습니다.",
                    "국가계약법 시행령 제21조 제1항 제1호", "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""))
            elif est < th["고시금액_물품용역"]:
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "수정필요",
                    f"추정가격 {won(est)}이 고시금액 {won(th['고시금액_물품용역'])} 미만인데 수행실적으로 참가자격을 제한하고 있습니다. 위반 시 입찰 취소 사유입니다.",
                    "국가계약법 시행령 제21조 제1항 제1호 / 감사원 공공계약 실무가이드(2024) p.119",
                    "참가자격에서 실적 요건을 삭제하고, 실적은 정량평가 항목으로만 반영하세요.",
                    r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13")
                summ(f"추정가격 {eok(est)}(고시금액 {eok(th['고시금액_물품용역'])} 미만) → 실적으로 참가제한 불가")
            else:
                add("②-7", "고시금액 미만 실적제한 불가", "★필수", "적합",
                    f"추정가격 {won(est)}으로 고시금액 이상이라 실적제한이 가능합니다. 제한 범위가 계약금액 1배 이내인지는 ①-13에서 확인하세요.",
                    "국가계약법 시행령 제21조 제1항 제1호", "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "①-13")
        elif kind == "공사":
            add("⑥-5", "참가자격(건설업 등록)·실적제한 기준", "★필수", "확인필요",
                f"공사 실적제한은 종합 {won(th['공사_실적제한_종합'])}/전문 {won(th['공사_실적제한_전문'])} 이상에서만 가능합니다. 업종 구분 확인 후 판정하세요."
                + (f" (추정가격 {won(est)})" if est else ""),
                "건설산업기본법, 국가계약법 시행령 제21조", "", r.get("문서", ""), r.get("위치", ""), r.get("원문", ""), "②-7")
    g = f.get("지역제한") or {}
    if g.get("있음") and kind in ("용역", "물품") and est is not None:
        ok = est < th["지역제한_상한_물품용역"]
        add("①-15", "지역제한 적용 시 기준", "확인", "적합" if ok else "수정필요",
            (f"추정가격 {won(est)}으로 지역제한 가능 범위입니다. 이행 현장·납품지 관할 시·도 기준인지(시·군·구 세분 불가) 확인하세요." if ok
             else f"추정가격 {won(est)}이 {won(th['지역제한_상한_물품용역'])} 이상이라 지역제한을 할 수 없습니다."),
            "국가계약법 시행규칙 제24조 / 감사원 공공계약 실무가이드(2024) p.119~120",
            "" if ok else "지역제한 조건을 삭제하세요.", g.get("문서", ""), g.get("위치", ""), g.get("원문", ""))
        if not ok:
            summ(f"추정가격 {eok(est)} → 지역제한 불가(기준 {eok(th['지역제한_상한_물품용역'])} 미만)")


def check_notice(f, th, est):
    n, dl = parse_date(f.get("공고일")), parse_date(f.get("제출마감일"))
    if not (n and dl):
        return
    method, kind, urgent = f.get("낙찰방식", ""), f.get("계약유형", ""), bool(f.get("긴급"))
    days = th["공고기간_일"]
    if method == "협상":
        below = est is not None and est < th["고시금액_물품용역"]
        need = days["협상_긴급또는고시금액미만"] if (urgent or below) else days["협상"]
        id_, name = "③-2", "공고기간(40일/10일)·기산점"
    elif kind in ("용역", "물품"):
        need = days["물품용역_긴급"] if urgent else days["물품용역"]
        id_, name = "①-19", "공고기간 산정(달력 계산)"
    else:
        add("①-19", "공고기간 산정(달력 계산)", "★필수", "확인필요",
            "공사는 현장설명 유무·규모별로 공고기간이 달라 자동 판정하지 않습니다.", "국가계약법 시행령 제35조")
        return
    gap = (dl - n).days
    basis = "국가계약법 시행령 제35조 / 감사원 공공계약 실무가이드(2024) p.296~297 [표91]"
    msg = f"공고일 {n} ~ 제출마감일 {dl}: {gap}일 차이, 필요 {need}일(마감일 전일부터 기산)."
    if gap > need:
        add(id_, name, "★필수", "적합", msg, basis)
    elif gap == need:
        add(id_, name, "★필수", "확인필요", msg + " 경계값이라 달력으로 직접 다시 세어 확인하세요.", basis)
    else:
        add(id_, name, "★필수", "수정필요", msg + " 공고기간이 부족합니다.", basis,
            f"제출마감일을 최소 {need + 1}일 이후로 조정하세요(공고일 기준).", "", "", "", "①-19")
        summ(f"공고기간 부족({gap}일, 필요 {need}일 초과)")


def check_scores(f, th):
    if f.get("낙찰방식") != "협상":
        return
    b = f.get("배점") or {}
    t, p = b.get("기술"), b.get("가격")
    B = th["배점"]
    where = {"문서": b.get("문서", ""), "위치": b.get("위치", ""), "원문": b.get("원문", "")}
    if t is not None and p is not None:
        if t + p != 100:
            add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "수정필요",
                f"기술 {t} + 가격 {p} = {t + p}점으로 100점이 아닙니다.", "협상에 의한 계약체결기준 [별표]", **where)
            summ(f"배점 합계 {t + p}점(기술 {t} + 가격 {p}) ≠ 100점")
        if p == 0:
            add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "수정필요",
                "가격평가 배점이 0점입니다. 협상에 의한 계약은 기술과 가격을 합산 평가해야 합니다.",
                "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.259",
                "배점표에 가격평가 비중을 반영하세요.", **where)
            summ("가격평가 0점 → 가격 배점 필수")
        else:
            add("②-12", "기술평가 100% 불가, 가격평가 필수", "★필수", "적합", f"가격평가 {p}점이 반영되어 있습니다.",
                "협상에 의한 계약체결기준 [별표]", **where)
        reason = b.get("배점조정사유기재")
        if p > B["가격중시_최대"]:
            add("②-13", "가격평가 비중 범위", "★필수", "수정필요",
                f"가격 {p}점은 가격 중시형 최대 {B['가격중시_최대']}점을 넘습니다.",
                "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.258", "", **where, 연계="③-4")
            summ(f"가격 {p}점 → 최대 {B['가격중시_최대']}점 초과")
        elif B["원칙_가격_최소"] <= p <= B["원칙_가격_최대"]:
            add("②-13", "가격평가 비중 범위", "★필수", "적합",
                f"기술 {t} : 가격 {p}로 원칙 범위(가격 {B['원칙_가격_최소']}~{B['원칙_가격_최대']}) 안입니다.",
                "협상에 의한 계약체결기준 [별표]", **where, 연계="③-4")
        elif reason:
            add("②-13", "가격평가 비중 범위", "★필수", "적합",
                f"기술 {t} : 가격 {p}로 원칙 범위 밖이지만 조정 사유가 기재되어 있습니다. 사유가 결재문서에도 있는지 확인하세요.",
                "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.258", **where, 연계="③-4")
        else:
            add("②-13", "가격평가 비중 범위", "★필수", "수정필요",
                f"기술 {t} : 가격 {p}로 원칙 범위(가격 {B['원칙_가격_최소']}~{B['원칙_가격_최대']}) 밖인데 배점 조정 사유가 없습니다.",
                "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.258",
                "공고문에 배점 조정 사유(예: SW사업 등 근거)를 명시하고 결재문서에도 같은 사유를 기재하세요.", **where, 연계="③-4")
            summ(f"가격 {p}점(원칙 {B['원칙_가격_최소']}~{B['원칙_가격_최대']}점) → 조정 사유 필요")

    items = f.get("기술평가항목") or []
    if items:
        over = [i for i in items if (i.get("배점") or 0) > B["평가항목_최대"]]
        if over:
            add("②-14", "각 평가항목 배점한도 30점 이하", "★필수", "수정필요",
                "30점을 넘는 평가항목: " + ", ".join(f"{i['항목']}({i['배점']}점)" for i in over),
                "협상에 의한 계약체결기준 [별표] 비고 / 감사원 공공계약 실무가이드(2024) p.259",
                "해당 항목을 쪼개거나 배점을 30점 이하로 조정하세요.",
                over[0].get("문서", ""), "; ".join(i.get("위치", "") for i in over if i.get("위치")),
                "\n".join(i.get("원문", "") for i in over if i.get("원문")), "③-5")
            summ("30점 초과 항목: " + ", ".join(f"{i['항목']} {i['배점']}점" for i in over))
        else:
            add("②-14", "각 평가항목 배점한도 30점 이하", "★필수", "적합",
                f"평가항목 {len(items)}개 모두 30점 이하입니다.", "협상에 의한 계약체결기준 [별표] 비고", 연계="③-5")
        s = sum((i.get("배점") or 0) for i in items)
        if t is not None and abs(s - t) > 0.001:
            first = next((i for i in items if i.get("위치") or i.get("원문")), {})
            add("②-14", "평가항목 배점 합계", "★필수", "수정필요",
                f"기술평가 세부항목 합계 {s}점이 기술평가 배점 {t}점과 다릅니다.", "협상에 의한 계약체결기준 [별표]",
                "세부항목 배점 합계를 기술평가 배점과 맞추세요.",
                first.get("문서", "") or b.get("문서", ""), first.get("위치", ""), first.get("원문", ""))
            summ(f"세부항목 합계 {s:g}점 ≠ 기술평가 {t:g}점")

    q = f.get("정량평가항목") or []
    bad = [i for i in q if i.get("최저등급평점") is not None and i.get("배점")
           and i["최저등급평점"] < i["배점"] * th["정량평가_최저평점_비율"] - 1e-9]
    if q:
        if bad:
            add("③-7", "정량평가 최저평점 하한(배점의 70%)", "★필수", "수정필요",
                "최하등급 평점이 배점의 70% 미만: " + ", ".join(
                    f"{i['항목']}(배점 {i['배점']}, 최저 {i['최저등급평점']}, 하한 {round(i['배점'] * th['정량평가_최저평점_비율'], 2)})" for i in bad),
                "협상에 의한 계약체결기준 [별표]", "최하등급 평점을 배점의 70% 이상으로 조정하세요.",
                bad[0].get("문서", ""), "; ".join(i.get("위치", "") for i in bad if i.get("위치")), "", "②-15, ②-16")
            summ("최저등급 평점 70% 미만: " + ", ".join(f"{i['항목']} {i['최저등급평점']:g}/{i['배점']:g}점" for i in bad))
        else:
            add("③-7", "정량평가 최저평점 하한(배점의 70%)", "★필수", "적합",
                "정량평가 최하등급 평점이 모두 배점의 70% 이상입니다.", "협상에 의한 계약체결기준 [별표]", 연계="②-15, ②-16")

    c = f.get("실적건수평가") or {}
    if c.get("기준금액") and c.get("사업예산"):
        R = th["실적건수평가"]
        probs = []
        if c["기준금액"] > c["사업예산"] * R["기준금액_예산대비_최대"]:
            probs.append(f"기준금액 {won(c['기준금액'])}이 사업예산의 50%({won(c['사업예산'] * 0.5)})를 넘습니다.")
        if c.get("최대인정건수") and c["기준금액"] * c["최대인정건수"] > c["사업예산"] * R["합계_예산대비_최대"]:
            probs.append(f"기준금액×최대인정건수 {won(c['기준금액'] * c['최대인정건수'])}이 사업예산을 넘습니다.")
        add("③-8", "수행실적 '건수' 평가 시 한도", "확인", "수정필요" if probs else "적합",
            " ".join(probs) or "건수 평가 한도 안입니다.", "조달청 협상에 의한 계약 제안서평가 세부기준",
            "기준금액·인정건수를 한도 안으로 조정하세요." if probs else "",
            c.get("문서", ""), c.get("위치", ""), c.get("원문", ""))
        if probs:
            summ("실적 건수평가 기준금액·인정건수 한도 초과")

    for key, id_, name, expect, basis, link in [
        ("협상적격자기준_퍼센트", "②-18", "협상적격자 기준(기술평가 배점한도의 85%)", th["협상적격_기술점수_비율_퍼센트"],
         "협상에 의한 계약체결기준 / 감사원 공공계약 실무가이드(2024) p.262", "③-10"),
        ("평점산식_하한_퍼센트", "②-17", "입찰가격 평점산식 하한(추정가격의 70%)", th["입찰가격_평점산식_하한_퍼센트"],
         "협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.259~260", "③-9"),
    ]:
        v = f.get(key)
        if v is None:
            continue
        val = v.get("값") if isinstance(v, dict) else v
        meta = v if isinstance(v, dict) else {}
        ok = val == expect
        add(id_, name, "★필수", "적합" if ok else "수정필요",
            f"문서 기재값 {val}%, 현행 기준 {expect}%." + ("" if ok else " 구 기준이 남아 있을 수 있습니다."),
            basis, "" if ok else f"{expect}%로 고치고 공고문·제안요청서를 같은 문구로 통일하세요.",
            meta.get("문서", ""), meta.get("위치", ""), meta.get("원문", ""), link)
        if not ok:
            label = "협상적격 기준" if id_ == "②-18" else "평점산식 하한"
            summ(f"{label} {val}% → {expect}%로 수정(구 기준)")


def check_joint(f, th):
    for key, id_, name in [("공동계약", "②-3", "공동도급 허용 여부 기재"), ("하도급", "②-3", "하도급 허용 여부 기재")]:
        d = f.get(key) or {}
        docs = {k: v for k, v in d.items() if isinstance(v, dict) and "값" in v}
        if not docs:
            continue
        vals = {k: v["값"] for k, v in docs.items()}
        missing = [k for k, v in vals.items() if v in ("미기재", "", None)]
        set_vals = {v for v in vals.values() if v not in ("미기재", "", None)}
        if len(set_vals) > 1:
            add(id_, name, "확인", "수정필요", f"문서 간 {key} 허용 여부가 다릅니다: " + ", ".join(f"{k}={v}" for k, v in vals.items()),
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91",
                f"공고문과 제안요청서에 {key} 허용/불허를 같은 내용으로 기재하세요.", ", ".join(docs), loc(docs), quotes(docs), "①-17, ①-18")
            summ(f"{key} 허용 여부 불일치(" + " / ".join(f"{sdoc(k)} {v}" for k, v in vals.items()) + ")")
        elif missing:
            add(id_, name, "확인", "수정필요", f"{key} 허용 여부가 기재되지 않은 문서: {', '.join(missing)}",
                "공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90~91",
                f"{key} 허용/불허를 양쪽 문서에 동일하게 기재하세요(불허 시 사유 권장).", ", ".join(docs), loc(docs), quotes(docs), "①-17, ①-18")
            summ(f"{key} 허용 여부 미기재(" + ", ".join(sdoc(k) for k in missing) + ")")
        else:
            add(id_, name, "확인", "적합", f"{key} 허용 여부가 문서 간 일치합니다({', '.join(set_vals)}).",
                "공동계약운용요령", "", ", ".join(docs), loc(docs), quotes(docs))
    d = f.get("공동계약") or {}
    C = th["공동계약"]
    if d.get("구성원수") and d["구성원수"] > C["구성원_최대"]:
        add("①-17", "공동계약 구성원 수", "확인", "수정필요", f"구성원 {d['구성원수']}인으로 {C['구성원_최대']}인을 넘습니다.",
            "(계약예규) 공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90 [표31]", f"구성원 수를 {C['구성원_최대']}인 이하로 하세요.")
        summ(f"공동계약 구성원 {d['구성원수']}인 → {C['구성원_최대']}인 이하로")
    if d.get("최소지분율") is not None and d["최소지분율"] < C["최소지분율_퍼센트"]:
        add("①-17", "공동계약 최소지분율", "확인", "수정필요", f"최소지분율 {d['최소지분율']}%가 {C['최소지분율_퍼센트']}% 미만입니다.",
            "(계약예규) 공동계약운용요령 / 감사원 공공계약 실무가이드(2024) p.90 [표31]", f"최소지분율을 {C['최소지분율_퍼센트']}% 이상으로 하세요.")
        summ(f"최소지분율 {d['최소지분율']}% → {C['최소지분율_퍼센트']}% 이상으로")


def main():
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
        json.dump({"추정가격": est, "기준": th.get("기준일"), "findings": findings}, fp, ensure_ascii=False, indent=2)
    cnt = {}
    for x in findings:
        cnt[x["판정"]] = cnt.get(x["판정"], 0) + 1
    print(f"추정가격(VAT 제외): {won(est) if est else '미확인'}")
    print("판정:", ", ".join(f"{k} {v}" for k, v in cnt.items()) or "없음")
    for x in findings:
        if x["판정"] != "적합":
            print(f"- [{x['판정']}] {x['id']} {x['항목']}: {x['문제점']}")
    print(f"저장: {a.out}")


if __name__ == "__main__":
    sys.exit(main())
