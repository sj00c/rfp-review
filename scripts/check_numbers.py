#!/usr/bin/env python3
"""숫자 대조: 문서끼리 같아야 하는 값과 합계를 계산해 어긋난 곳만 지적한다.

모델은 문서에서 읽은 숫자를 facts.json에 옮겨 적고, 계산은 이 스크립트가 한다(암산 금지).
값은 숫자 또는 사칙연산 식이다. 예: "330,000,000", "300000000*1.1", "20+30+30".

facts.json:
{
  "일치": [
    {"항목": "사업금액(부가세 포함)", "근거": "<지침 원문 또는 '문서 자체 오류'>",
     "값": [{"문서": "제안요청서", "위치": "[문단 8]", "원문": "금330,000,000원", "값": "330,000,000"},
            {"문서": "공고문", "위치": "[문단 3]", "원문": "300,000,000원(부가세 별도)", "값": "300000000*1.1"}]}
  ],
  "합계": [
    {"항목": "기술평가 배점 합계", "근거": "...",
     "부분": [{"문서": "제안요청서", "위치": "[문단 52 표3 2-3]", "원문": "20", "값": 20}, ...],
     "합계": {"문서": "제안요청서", "위치": "[문단 52 표3 9-3]", "원문": "합계 90", "값": 90}}
  ]
}
선택: "허용오차"(기본 0). 근거를 비우면 '문서 자체 오류'로 기록한다.

사용법:
  python check_numbers.py facts.json -o numeric_findings.json
"""
import argparse
import ast
import json
import sys
from fractions import Fraction

SELF = "문서 자체 오류"
OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
       ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def evaluate(value):
    """숫자 또는 사칙연산 식을 정확한 분수로 계산한다. 그 밖의 식은 ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"숫자가 아님: {value!r}")
    if isinstance(value, (int, float)):
        return Fraction(str(value))
    if not isinstance(value, str):
        raise ValueError(f"숫자가 아님: {value!r}")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return Fraction(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            x = ev(node.operand)
            return -x if isinstance(node.op, ast.USub) else x
        raise ValueError(f"사칙연산 식이 아님: {value!r}")

    try:
        return ev(ast.parse(value.replace(",", "").strip(), mode="eval"))
    except (SyntaxError, ZeroDivisionError) as e:
        raise ValueError(f"계산할 수 없는 값: {value!r} ({e})") from e


def show(x):
    """정수는 천 단위 쉼표, 아니면 소수 둘째 자리까지."""
    if x.denominator == 1:
        return f"{x.numerator:,}"
    return f"{float(x):,.2f}"


def entry_text(e, x):
    return f"{e['문서']} {e['위치']} {show(x)}"


def finding(n, entry, 항목, 근거, 문제점, 수정안, 요약):
    return {"id": f"N{n}", "판정": "수정필요", "문서": entry["문서"], "위치": entry["위치"],
            "원문": entry["원문"], "요약": 요약, "문제점": 문제점, "수정안": 수정안, "근거": 근거, "항목": 항목}


def check(facts):
    out, errors = [], []
    for c in facts.get("일치", []):
        name, basis = c.get("항목", "값 일치"), (c.get("근거") or SELF)
        try:
            vals = [(e, evaluate(e["값"])) for e in c["값"]]
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        if len(vals) < 2:
            errors.append(f"{name}: 비교할 값이 2개 이상 필요합니다")
            continue
        tol = evaluate(c.get("허용오차", 0))
        lo, hi = min(x for _, x in vals), max(x for _, x in vals)
        if hi - lo <= tol:
            continue
        listing = "; ".join(entry_text(e, x) for e, x in vals)
        for e, x in vals:
            others = "; ".join(entry_text(o, y) for o, y in vals if o is not e)
            out.append(finding(len(out) + 1, e, name, basis,
                               f"같아야 할 {name} 값이 문서마다 다릅니다. 이곳 {show(x)}, 다른 곳: {others}",
                               f"맞는 값을 확인해 모든 곳({listing})을 같은 값으로 맞춰 주세요.",
                               f"{name} 불일치"))
    for c in facts.get("합계", []):
        name, basis = c.get("항목", "합계"), (c.get("근거") or SELF)
        try:
            parts = [evaluate(e["값"]) for e in c["부분"]]
            total_entry = c["합계"]
            stated = evaluate(total_entry["값"])
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        computed = sum(parts, Fraction(0))
        if abs(computed - stated) <= evaluate(c.get("허용오차", 0)):
            continue
        out.append(finding(len(out) + 1, total_entry, name, basis,
                           f"{name}: 세부 값 {len(parts)}개의 합은 {show(computed)}인데 {show(stated)}로 적혀 있습니다.",
                           f"세부 값과 합계를 확인해 맞춰 주세요(계산 합계 {show(computed)}).",
                           f"{name} 계산 오류"))
    return out, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("facts")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    with open(a.facts, encoding="utf-8") as fp:
        facts = json.load(fp)
    found, errors = check(facts)
    for e in errors:
        print(f"[오류] {e}")
    if errors:
        print("facts.json을 고친 뒤 다시 실행하세요. 결과 파일은 만들지 않았습니다.")
        return 1
    with open(a.out, "w", encoding="utf-8") as fp:
        json.dump({"findings": found}, fp, ensure_ascii=False, indent=2)
    n_eq, n_sum = len(facts.get("일치", [])), len(facts.get("합계", []))
    print(f"검사: 일치 {n_eq}건, 합계 {n_sum}건 → 지적 {len(found)}건")
    for f in found:
        print(f"- {f['id']} {f['문서']} {f['위치']} {f['요약']}")
    print(f"저장: {a.out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
