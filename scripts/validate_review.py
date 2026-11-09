#!/usr/bin/env python3
"""Validate findings before annotating: catch hallucinated quotes, citations, ids and coverage gaps.

Checks (errors fail with exit code 1; warnings are printed only):
  - schema: 판정/중요도 values, required fields per 판정, (id, 항목) uniqueness, 참조 rules
  - id: must exist in references/checklist.md, or be 기타-n
  - 원문: every quoted part must appear in an extracted text line (whitespace-insensitive, '…' allowed)
  - 근거: every ' / '-separated source must appear in that item's 근거 line in checklist.md
          (기타-n: in any 근거 line). Prevents invented statutes and page numbers.
  - coverage (--sheets): every checklist item of the applicable sheets has at least one finding

Usage:
  python validate_review.py numeric_findings.json review.json --extracted extracted/ --sheets ①②③⑤
"""
import argparse
import glob
import json
import os
import re
import sys

from checklist_items import parse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHECKLIST = os.path.join(HERE, "..", "references", "checklist.md")
VERDICTS = {"수정필요", "확인필요", "적합", "해당없음"}
SEVERITIES = {"★필수", "확인", "참고"}
APPLICABILITY = {"적용", "비적용", "미확인"}
EVIDENCE = {"판독완료", "전수검색없음", "미제출", "미판독", "충돌"}
AUDIENCES = {"작성자", "구매팀", "외부확인"}
AUTHORITIES = {"법령·공식기준", "기관운영", "사업요건", "예시피드백"}
WS = re.compile(r"\s+")
ETC = re.compile(r"^기타-\d+$")


def nows(s):
    return WS.sub("", s or "")


def load_checklist(path):
    """{id: {'tag': '문서'|'계산'|'확인', 'basis': str}}"""
    return {item["id"]: {**item, "basis": item.get("근거", "")} for item in parse(path)}


def load_lines(extracted):
    lines = []
    for p in sorted(glob.glob(os.path.join(extracted, "*.txt"))):
        with open(p, encoding="utf-8") as fp:
            for ln in fp:
                body = re.sub(r"^\[[^\]]*\]\s*", "", ln.strip())
                lines.append(nows(body))
    return lines


def quote_parts(raw):
    """'[공고문] …' 형태(문서별 원문)는 문서 태그를 떼고 각각 돌려준다."""
    out = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^\[(공고문|제안요청서|원가계산보고서|과업내용서|용역계약의뢰서|기관운영자료|기타)\]\s*(.+)$", ln)
        out.append(m.group(2) if m else ln)
    return out


def found(quote, lines):
    """quote가 들어 있는 추출 줄 목록(공백 무시, '…' 생략 허용). 없으면 빈 목록."""
    parts = [nows(x) for x in re.split(r"…|\.{3,}", quote)]
    parts = [x for x in parts if x]
    if not parts:
        return ["(빈 인용)"]
    hits = []
    for ln in lines:
        k = ln.find(parts[0])
        if k < 0:
            continue
        b = k + len(parts[0])
        ok = True
        for part in parts[1:]:
            j = ln.find(part, b)
            if j < 0:
                ok = False
                break
            b = j + len(part)
        if ok:
            hits.append(ln)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings", nargs="+", help="numeric_findings.json, review.json (파일 간에도 finding 키는 고유해야 함)")
    ap.add_argument("--extracted", required=True, help="extract_text.py 출력 폴더")
    ap.add_argument("--sheets", default="", help="적용 시트(예: ①②③⑤). 주면 항목 누락을 검사한다")
    ap.add_argument("--checklist", default=DEFAULT_CHECKLIST)
    ap.add_argument("--coverage", help="checklist_items.py의 coverage.json (선택 항목 검증)")
    ap.add_argument("--show", type=int, default=30, help="화면에 보여 줄 오류·경고 수(나머지는 --report 파일로)")
    ap.add_argument("--report", default="validate_report.txt")
    a = ap.parse_args()

    checklist = load_checklist(a.checklist)
    all_basis = [nows(v["basis"]) for v in checklist.values()]
    lines = load_lines(a.extracted)
    if not lines:
        print(f"[오류] {a.extracted}에 추출 텍스트(*.txt)가 없습니다.")
        return 1

    merged, order, errors, warnings = {}, [], [], []
    profiles = {}
    official = {}
    with open(os.path.join(HERE, "..", "references", "thresholds.json"), encoding="utf-8") as fp:
        threshold_data = json.load(fp)
    thresholds = threshold_data["공식기준"]
    known_profiles = threshold_data["기관운영프로필"]["프로필"]
    for p in a.findings:
        with open(p, encoding="utf-8") as fp:
            data = json.load(fp)
        for profile in (data.get("meta") or {}).get("기관프로필", []):
            pid = profile.get("프로필ID")
            if pid in profiles and profiles[pid] != profile:
                errors.append(f"기관프로필 정의 충돌: {pid}")
            profiles[pid] = profile
        for rule, record in (data.get("meta") or {}).get("공식기준", {}).items():
            if rule in official and official[rule] != record:
                errors.append(f"공식기준 정의 충돌: {rule}")
            official[rule] = record
        for f in data.get("findings", []):
            key = (f.get("id"), f.get("항목"))
            if key in merged:
                errors.append(f"{p}: (id, 항목) 중복 {key} — 앞 finding이 덮어써져 사라집니다")
            if key not in merged:
                order.append(key)
            merged[key] = f

    for key in order:
        f = merged[key]
        fid, label = f.get("id") or "", f"{key[0]} {key[1]}"
        v, sev = f.get("판정"), f.get("중요도")
        if v not in VERDICTS:
            errors.append(f"{label}: 판정 '{v}'은 허용값이 아님({', '.join(sorted(VERDICTS))})")
        if sev not in SEVERITIES:
            errors.append(f"{label}: 중요도 '{sev}'은 허용값이 아님({', '.join(sorted(SEVERITIES))})")
        if fid not in checklist and not ETC.match(fid):
            errors.append(f"{label}: 체크리스트에 없는 id — 기존 id를 쓰거나 '기타-n'으로")
        applicability = f.get("적용성")
        evidence = f.get("증거상태")
        audience = f.get("대상")
        authority = f.get("기준유형")
        for field, value, allowed in (
            ("적용성", applicability, APPLICABILITY),
            ("증거상태", evidence, EVIDENCE),
            ("대상", audience, AUDIENCES),
        ):
            if value is not None and (not isinstance(value, str) or value not in allowed):
                errors.append(f"{label}: {field} 허용값이 아닙니다: {value}")
        if authority is not None and (
            not isinstance(authority, list) or not authority
            or any(not isinstance(x, str) or x not in AUTHORITIES for x in authority)
        ):
            errors.append(f"{label}: 기준유형은 허용된 출처 유형의 비어 있지 않은 배열이어야 합니다")
        if authority == ["예시피드백"] and v in ("적합", "수정필요"):
            errors.append(f"{label}: 예시피드백만으로 적합·수정필요를 판정할 수 없습니다")
        if authority is None and v in ("적합", "수정필요") and not checklist.get(fid, {}).get("기준유형"):
            errors.append(f"{label}: 확정 판정에는 명시적 기준유형 또는 체크리스트의 기준유형이 필요합니다")
        if v == "해당없음" and (applicability != "비적용" or not f.get("문제점")):
            errors.append(f"{label}: 해당없음에는 비적용과 사유가 필요합니다")
        if v == "적합" and (applicability != "적용" or evidence != "판독완료"):
            errors.append(f"{label}: 적합에는 적용 및 판독완료 증거가 필요합니다")
        if v == "수정필요":
            if evidence not in ("판독완료", "충돌", "전수검색없음"):
                errors.append(f"{label}: 수정필요에는 판독·충돌·전수검색 완료 증거가 필요합니다")
            if applicability != "적용" and not (
                applicability == "미확인" and evidence == "충돌" and authority == ["사업요건"]
            ):
                errors.append(f"{label}: 적용 미확인인 경우 독립적인 사업요건 충돌만 수정필요로 판정합니다")
        if v == "확인필요" and (
            not isinstance(audience, str) or audience not in AUDIENCES
            or not isinstance(evidence, str) or evidence not in EVIDENCE or not f.get("조치")
        ):
            errors.append(f"{label}: 확인필요에는 명시적인 대상·증거상태·조치가 필요합니다")
        if f.get("질의") is True and audience != "작성자":
            errors.append(f"{label}: 질의는 대상이 작성자인 경우에만 허용됩니다")
        if f.get("프로필참조"):
            if f["프로필참조"] not in known_profiles:
                errors.append(f"{label}: 기관프로필 참조가 기준 프로필 목록에 없습니다")
            profile = profiles.get(f["프로필참조"])
            if not profile:
                errors.append(f"{label}: 프로필참조가 meta.기관프로필에 없습니다")
            elif v in ("적합", "수정필요") and (
                profile.get("적용성") != "적용"
                or not all(profile.get(k) for k in ("기관", "적용범위", "출처", "원문", "위치"))
            ):
                errors.append(f"{label}: 기관프로필의 출처·범위·적용성이 확인되지 않았습니다")
        rule_refs = f.get("기준참조") or []
        if not isinstance(rule_refs, list) or any(not isinstance(x, str) for x in rule_refs):
            errors.append(f"{label}: 기준참조는 수치 기준 키의 배열이어야 합니다")
            rule_refs = []
        for rule in rule_refs:
            value = thresholds
            for part in rule.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{label}: 기준참조가 공식 수치 기준에 없습니다: {rule}")
            record = official.get(rule)
            if not record:
                errors.append(f"{label}: 기준참조가 meta.공식기준에 없습니다: {rule}")
            elif v in ("적합", "수정필요") and (
                record.get("적용성") != "적용"
                or not all(record.get(k) for k in ("출처", "적용범위", "원문", "위치"))
            ):
                errors.append(f"{label}: 공식기준의 출처·범위·적용성이 확인되지 않았습니다: {rule}")
        raw = (f.get("원문") or "").strip()
        if raw.startswith("해당 내용 없음") and v == "수정필요":
            if evidence != "전수검색없음" or "검색" not in (f.get("문제점") or ""):
                errors.append(f"{label}: 누락 판정에는 전수검색 완료와 검색 기록이 필요합니다")
        model = f.get("판정방식") != "계산"  # check_numbers 출력은 날짜·수치라 원문이 없을 수 있다
        if v == "수정필요":
            if not raw:
                errors.append(f"{label}: 수정필요인데 원문이 비어 있음(누락이면 '해당 내용 없음')")
            if not f.get("문서") or not f.get("위치"):
                errors.append(f"{label}: 수정필요에는 문서와 위치가 필요합니다")
            if not (f.get("수정안") or "").strip():
                errors.append(f"{label}: 수정필요인데 수정안이 없음")
            if not (f.get("조치") or "").strip():
                warnings.append(f"{label}: 조치 없음 — 메모에 수정안 전문이 들어가 길어짐")
            if model and len(f.get("요약") or "") > 40:
                warnings.append(f"{label}: 요약 {len(f['요약'])}자 — 메모 제목은 한 문장 25~35자")
        if model and (v == "수정필요" or f.get("질의") is True):
            # 문제점·수정안은 메모에 그대로 실린다. 작성자는 [문단 n]·S-nn 번호를 모른다.
            for k in ("문제점", "수정안"):
                t = re.sub(r"\([^()]*\)", "", f.get(k) or "")
                if re.search(r"\[문단 \d|(?<![(\w])S-\d", t):
                    warnings.append(f"{label}: {k}에 [문단 n]/S-nn이 본문으로 들어 있음 — 메모에 그대로 보인다. 제목·항목명으로 쓰거나 괄호 안에")
        if f.get("질의") is True:
            if v != "확인필요":
                errors.append(f"{label}: '질의'는 확인필요에만 씁니다")
            elif not raw or raw.startswith("해당 내용 없음") or not (f.get("조치") or "").strip():
                errors.append(f"{label}: 질의 메모에는 원문(메모 자리)과 조치(작성자에게 묻는 것)가 필요")
        if v in ("적합", "확인필요") and not (f.get("문제점") or "").strip():
            errors.append(f"{label}: {v}인데 문제점(판단 근거·확인할 내용)이 비어 있음")
        if raw and not raw.startswith("해당 내용 없음"):
            for q in quote_parts(raw):
                if re.search(r"\[(수식|그림|개체)", q):
                    errors.append(f"{label}: 원문에 개체 표시([수식…]/[그림]) 포함 — 본문에 없는 글자라 메모를 못 단다. 옆의 본문 문구를 인용")
                    continue
                if len(nows(q)) < 4:
                    errors.append(f"{label}: 원문 \"{q}\"이 너무 짧아 위치를 특정할 수 없음 — 앞뒤 문구를 포함해 4자 이상 인용")
                    continue
                hits = found(q, lines)
                if not hits:
                    errors.append(f"{label}: 원문이 추출 텍스트에 없음 → \"{q[:40]}\" (그대로 복사했는지 확인)")
                elif v == "수정필요" and any(re.search(r"\[(수식|그림|개체)", h) for h in hits):
                    if re.search(r"공란|누락|미기재|없", (f.get("문제점") or "") + (f.get("요약") or "")):
                        if not (f.get("개체판독근거") or "").strip():
                            errors.append(f"{label}: 수식·그림이 있는 위치의 누락 판정에는 개체판독근거가 필요합니다. 미판독이면 확인필요로 기록")
                    else:
                        warnings.append(f"{label}: 인용 위치에 수식·그림이 있습니다. 개체 내용의 판독 여부를 확인하세요")
        basis = (f.get("근거") or "").strip()
        if basis and basis != "-":
            own = nows(checklist.get(fid, {}).get("basis", ""))
            linked_sources = [official[k] for k in rule_refs if k in official]
            if f.get("프로필참조") in profiles:
                linked_sources.append(profiles[f["프로필참조"]])
            declared_basis = set()
            for record in linked_sources:
                source, quote = record.get("출처"), record.get("원문")
                if source and quote and record.get("적용범위") and record.get("위치"):
                    declared_basis.add(nows(source))
                    declared_basis.add(nows(f"{source}: {quote}"))
            for part in [x for x in re.split(r"\s+/\s+", basis) if x.strip()]:
                p = nows(part)
                if (own and p in own) or p in declared_basis:
                    continue
                if any(p in b for b in all_basis):
                    if not ETC.match(fid):
                        warnings.append(f"{label}: 근거 '{part}'는 다른 항목의 근거")
                    continue
                errors.append(f"{label}: 근거 '{part}'가 checklist.md 근거란에 없음 — 지어낸 조문·쪽수 금지")
        if f.get("참조"):
            mains = [g for k, g in merged.items() if k[0] == fid and not g.get("참조")]
            if not mains:
                errors.append(f"{label}: 참조 finding인데 같은 id의 본 항목이 없음")
            if sev != "참고":
                warnings.append(f"{label}: 참조 finding의 중요도는 '참고'")

    required = {i for i in checklist if i[0] in a.sheets}
    if a.coverage:
        with open(a.coverage, encoding="utf-8") as fp:
            coverage = json.load(fp)
        sheets = coverage.get("시트", "")
        expected = {i for i in checklist if i[0] in sheets}
        if coverage.get("SW사업") is False:
            expected -= {"⑤-5", "⑤-6"}
        if a.sheets and set(a.sheets) != set(sheets):
            errors.append("coverage의 시트와 --sheets가 다릅니다")
        if set(coverage.get("항목", [])) != expected:
            errors.append("coverage 항목이 체크리스트 선택 범위와 다릅니다")
        required = expected
    if a.sheets or a.coverage:
        have = {k[0] for k in merged}
        miss = sorted(required - have)
        for i in miss:
            hint = "확인필요로 기록" if checklist[i]["tag"] == "확인" else "판정 기록(적합·해당없음 포함)"
            errors.append(f"누락: {i} [{checklist[i]['tag']}] — {hint}")

    cnt = {}
    for f in merged.values():
        if f.get("참조"):
            continue
        cnt[f.get("판정")] = cnt.get(f.get("판정"), 0) + 1
    summary = f"검사: finding {len(merged)}건 {cnt} — 오류 {len(errors)}건, 경고 {len(warnings)}건"
    rows = ["[오류] " + e for e in errors] + ["[경고] " + w for w in warnings]
    # 하네스가 긴 출력을 잘라도 요약과 앞쪽 오류는 보이게: 요약 먼저, 화면에는 일부만, 전체는 파일로
    print(summary)
    for r in rows[:a.show]:
        print(r)
    if len(rows) > a.show:
        with open(a.report, "w", encoding="utf-8") as fp:
            fp.write(summary + "\n" + "\n".join(rows) + "\n")
        print(f"… {len(rows) - a.show}건 더 있음. 전체: {a.report} (고친 뒤 다시 실행)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
