#!/usr/bin/env python3
"""메모를 달기 전에 지적을 검사한다: 지어낸 인용·근거, 빠진 필드, 중복 id.

- 원문: 해당 문서의 추출 텍스트에 그대로 있어야 한다(공백 무시, '…' 생략 허용).
- 근거: 지침 추출 텍스트에 그대로 있는 문구이거나 '문서 자체 오류'(오타·빈칸·문서 안/문서 간 모순).
- 판정: 필수수정 | 수정필요 | 확인필요. 문제없는 항목은 기록하지 않는다.
- 고칠 곳에는 수정안, 확인필요에는 확인할 내용(수정안 칸)이 필요하다.

사용법:
  python validate_review.py numeric_findings.json review.json \
      --guide extracted/지침.txt --doc 제안요청서=extracted/제안요청서.txt [--doc 공고문=extracted/공고문.txt]
"""
import argparse
import json
import re
import sys

SELF = "문서 자체 오류"
VERDICTS = ("필수수정", "수정필요", "확인필요")
WS = re.compile(r"\s+")
TAG = re.compile(r"^\s*\[[^\]]*\]\s*")
OBJECT = re.compile(r"\[(수식|그림|개체)")


def nows(s):
    return WS.sub("", s or "")


def load_lines(path):
    with open(path, encoding="utf-8") as fp:
        return [nows(TAG.sub("", ln)) for ln in fp if not ln.startswith("# 원본:")]


def found(quote, lines):
    """quote가 한 줄 안에 있으면 True. '…'/'...'로 생략한 인용은 조각이 순서대로 있어야 한다."""
    parts = [nows(x) for x in re.split(r"…|\.{3,}", quote)]
    parts = [x for x in parts if x]
    if not parts:
        return False
    for ln in lines:
        k = ln.find(parts[0])
        if k < 0:
            continue
        b, ok = k + len(parts[0]), True
        for part in parts[1:]:
            j = ln.find(part, b)
            if j < 0:
                ok = False
                break
            b = j + len(part)
        if ok:
            return True
    return False


def check(findings, guide, docs):
    """findings: [(파일, finding)], guide: 지침 줄 목록, docs: {문서명: 줄 목록}. 오류 목록을 돌려준다."""
    errors, seen = [], set()
    for path, f in findings:
        fid = f.get("id")
        label = f"{path}: {fid or '(id 없음)'}"
        if not fid:
            errors.append(f"{label}: id가 필요합니다")
        elif fid in seen:
            errors.append(f"{label}: id 중복 — 파일 간에도 고유해야 합니다")
        seen.add(fid)
        v = f.get("판정")
        if v not in VERDICTS:
            errors.append(f"{label}: 판정 '{v}' — 필수수정/수정필요/확인필요만 기록합니다(문제없는 항목은 쓰지 않음)")
        for field in ("위치", "요약", "문제점", "수정안"):
            if not str(f.get(field) or "").strip():
                errors.append(f"{label}: {field}이(가) 비어 있습니다")
        doc = f.get("문서")
        if doc not in docs:
            errors.append(f"{label}: 문서 '{doc}'은(는) --doc으로 준 문서가 아닙니다({', '.join(docs)})")
        quote = str(f.get("원문") or "").strip()
        if OBJECT.search(quote):
            errors.append(f"{label}: 원문에 [수식]/[그림] 표시가 있습니다 — 옆의 본문 글자를 인용하세요")
        elif len(nows(quote)) < 4:
            errors.append(f"{label}: 원문이 4자 미만이라 위치를 특정할 수 없습니다")
        elif doc in docs and not found(quote, docs[doc]):
            errors.append(f"{label}: 원문이 {doc} 텍스트에 없습니다 → \"{quote[:40]}\" (그대로 복사)")
        basis = str(f.get("근거") or "").strip()
        if not basis:
            errors.append(f"{label}: 근거가 비어 있습니다 — 지침 원문 또는 '{SELF}'")
        elif basis != SELF:
            for part in [x for x in re.split(r"\s+/\s+", basis) if x.strip()]:
                if not found(TAG.sub("", part), guide):
                    errors.append(f"{label}: 근거가 지침에 없습니다 → \"{part[:40]}\" (지침 문구를 그대로 복사)")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings", nargs="+")
    ap.add_argument("--guide", action="append", required=True, help="지침 추출 텍스트(여러 개 가능)")
    ap.add_argument("--doc", action="append", required=True, metavar="문서명=추출텍스트")
    a = ap.parse_args()

    guide = [ln for p in a.guide for ln in load_lines(p)]
    docs = {}
    for spec in a.doc:
        name, sep, path = spec.partition("=")
        if not sep:
            ap.error(f"--doc은 문서명=경로 형식입니다: {spec}")
        docs[name.strip()] = load_lines(path)
    findings = []
    for p in a.findings:
        with open(p, encoding="utf-8") as fp:
            findings += [(p, f) for f in json.load(fp)["findings"]]

    errors = check(findings, guide, docs)
    counts = {v: sum(1 for _, f in findings if f.get("판정") == v) for v in VERDICTS}
    print(f"검사: 지적 {len(findings)}건 {counts} — 오류 {len(errors)}건")
    for e in errors[:40]:
        print(f"[오류] {e}")
    if len(errors) > 40:
        print(f"… {len(errors) - 40}건 더. 앞의 오류부터 고치고 다시 실행하세요.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
