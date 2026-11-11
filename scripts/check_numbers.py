#!/usr/bin/env python3
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

    src = value.replace(",", "").strip()

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Fraction(node.value)
        if isinstance(node, ast.Constant) and type(node.value) is float:
            # float을 거치지 않고 적힌 숫자 그대로 분수로 만든다(17자리 이상도 정확)
            return Fraction(ast.get_source_segment(src, node).replace("_", ""))
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            x = ev(node.operand)
            return -x if isinstance(node.op, ast.USub) else x
        raise ValueError(f"사칙연산 식이 아님: {value!r}")

    try:
        return ev(ast.parse(src, mode="eval"))
    except (SyntaxError, ZeroDivisionError) as e:
        raise ValueError(f"계산할 수 없는 값: {value!r} ({e})") from e


def show(x):
    if x.denominator == 1:
        return f"{x.numerator:,}"
    return f"{float(x):,.2f}".rstrip("0").rstrip(".")


def entry_text(e, x):
    return f"{e['문서']} {e['위치']} {show(x)}"


def finding(n, c, entry, 요약, 문제점, 수정안, 근거):
    verdict = "필수수정" if c.get("필수") is True else "수정필요"
    return {"id": f"N{n}", "판정": verdict, "문서": entry["문서"], "위치": entry["위치"],
            "원문": entry["원문"], "요약": 요약, "문제점": 문제점, "수정안": 수정안, "근거": 근거}


ENTRY = ("문서", "위치", "원문", "값")
# 기준 그룹의 조건: 키 → (만족 판정, 문구)
BOUNDS = {"이상": (lambda x, b: x >= b, "이상"), "이하": (lambda x, b: x <= b, "이하"),
          "초과": (lambda x, b: x > b, "초과"), "미만": (lambda x, b: x < b, "미만")}


def entries(c, key):
    """c[key]의 항목들. 문서·위치·원문·값이 모두 있어야 한다(KeyError로 알린다)."""
    items = c[key] if isinstance(c[key], list) else [c[key]]
    if not items:
        raise KeyError(f"{key}이(가) 비어 있음")
    for e in items:
        missing = [k for k in ENTRY if k not in e]
        if missing:
            raise KeyError(f"{key} 항목에 {', '.join(missing)} 없음")
    return items


def check(facts):
    out, errors = [], []
    for c in facts.get("일치", []):
        name, basis = c.get("항목", "값 일치"), (c.get("근거") or SELF)
        try:
            vals = [(e, evaluate(e["값"])) for e in entries(c, "값")]
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        if len(vals) < 2:
            errors.append(f"{name}: 비교할 값이 2개 이상 필요합니다")
            continue
        if len({x for _, x in vals}) == 1:
            continue
        for e, x in vals:
            others = ", ".join(entry_text(o, y) for o, y in vals if o is not e)
            out.append(finding(len(out) + 1, c, e, f"{name} 불일치",
                               f"이곳 {show(x)}, 다른 곳 {others}",
                               "맞는 값으로 모든 곳을 통일", basis))
    for c in facts.get("합계", []):
        name, basis = c.get("항목", "합계"), (c.get("근거") or SELF)
        try:
            parts = [evaluate(e["값"]) for e in entries(c, "부분")]
            total_entry = entries(c, "합계")[0]
            stated = evaluate(total_entry["값"])
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        computed = sum(parts, Fraction(0))
        if computed == stated:
            continue
        out.append(finding(len(out) + 1, c, total_entry, f"{name} 계산 오류",
                           f"세부 {len(parts)}개 합 {show(computed)}, 적힌 합계 {show(stated)}",
                           f"세부 값과 합계를 맞춤(계산 합계 {show(computed)})", basis))
    for c in facts.get("기준", []):
        name, basis = c.get("항목", "기준"), (c.get("근거") or SELF)
        try:
            items = [(e, evaluate(e["값"])) for e in entries(c, "값")]
            bounds = [(k, evaluate(c[k])) for k in BOUNDS if k in c]
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"{name}: {e}")
            continue
        if not bounds:
            errors.append(f"{name}: 이상·이하·초과·미만 중 하나 이상이 필요합니다")
            continue
        rule = ", ".join(f"{show(b)} {BOUNDS[k][1]}" for k, b in bounds)
        for e, x in items:
            if all(BOUNDS[k][0](x, b) for k, b in bounds):
                continue
            out.append(finding(len(out) + 1, c, e, f"{name} 기준 위반",
                               f"이곳 {show(x)}, 기준 {rule}",
                               f"기준({rule})에 맞게 수정", basis))
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
    n = {k: len(facts.get(k, [])) for k in ("일치", "합계", "기준")}
    print(f"검사: 일치 {n['일치']}건, 합계 {n['합계']}건, 기준 {n['기준']}건 → 지적 {len(found)}건")
    for f in found:
        print(f"- {f['id']} {f['문서']} {f['위치']} {f['요약']}")
    print(f"저장: {a.out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
