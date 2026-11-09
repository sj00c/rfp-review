#!/usr/bin/env python3
"""Write the checklist items that apply to this review, one small file per sheet.

The whole checklist (~39KB) and even the applicable subset (~25KB) exceed what harness shells print
(often ~10KB, silently truncated). So this writes files and prints only a short summary:

  <out>/<sheet>.md            items to judge, compact: id | 중요도 | owner | name, 점검, 근거
  <out>/review_external.json  ready-made 확인필요 findings for every 'external' item

owner:
  script   - check_numbers.py judges it fully; not written to the sheet files
  script+  - check_numbers.py judges part of it; you judge the rest (shown)
  model    - you judge it from the documents
  external - needs information outside the documents; covered by review_external.json.
             Preserve that confirmation; document evidence can resolve a separately named subcheck,
             not establish that an outside approval or procedure actually happened.

Usage: python checklist_items.py ①②③⑤ [--sw | --non-sw] [-o items]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_numbers import SCRIPT_SCOPE  # noqa: E402

CHECKLIST = os.path.join(HERE, "..", "references", "checklist.md")


def parse(path=CHECKLIST):
    with open(path, encoding="utf-8") as fp:
        text = fp.read()
    out = []
    for block in re.split(r"\n(?=### )", text):
        m = re.match(r"### (\S+) (.+?)\s+`([^`]+)` `\[([^\]]+)\]`", block)
        if not m:
            continue
        field = {k: v.strip() for k, v in re.findall(r"^- ([^:\n]+): (.*)$", block, re.M)}
        out.append({"id": m.group(1), "name": m.group(2).strip(), "sev": m.group(3), "tag": m.group(4), **field})
    return out


def owner(item):
    scope = SCRIPT_SCOPE.get(item["id"])
    if scope:
        return ("script", scope) if scope.startswith("전부") else ("script+", scope)
    if item["tag"] == "확인":
        return ("external", "")
    return ("model", "")


def basis_of(item):
    b = item.get("근거", "")
    return b if b and b.strip() != "-" else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheets", help="적용 시트 기호를 붙여 쓴다. 예: ①②③⑤")
    sw = ap.add_mutually_exclusive_group()
    sw.add_argument("--sw", action="store_true", help="SW사업임이 확인됨")
    sw.add_argument("--non-sw", action="store_true", help="SW사업이 아님이 확인됨")
    ap.add_argument("-o", "--out", default="items", help="출력 폴더(작업 폴더 안)")
    a = ap.parse_args()
    items = [i for i in parse() if i["id"][0] in a.sheets]
    if a.non_sw:
        items = [i for i in items if i["id"] not in ("⑤-5", "⑤-6")]
    os.makedirs(a.out, exist_ok=True)

    sheets, external, counts = {}, [], {}
    for i in items:
        who, scope = owner(i)
        counts[who] = counts.get(who, 0) + 1
        if who == "script":
            continue
        if who == "external":
            external.append({
                "id": i["id"], "항목": i["name"], "중요도": i["sev"], "판정": "확인필요", "판정방식": "확인",
                "문서": "", "위치": "", "원문": "", "요약": f"{i['name']} 확인",
                "문제점": f"문서 밖 확인 필요: {i.get('점검', '')}", "근거": basis_of(i), "수정안": "", "연계": "",
                "대상": "구매팀", "적용성": "미확인", "증거상태": "미제출",
                "조치": f"{i['name']}의 담당자와 확인 자료를 확인하세요.",
            })
            continue
        lines = [f"{i['id']} | {i['sev']} | {who} | {i['name']}"]
        if who == "script+":
            lines.append(f"  script judges: {scope} — you judge the rest")
        lines.append(f"  점검: {i.get('점검', '')}")
        lines.append(f"  근거: {basis_of(i)}")
        for field in ("적용조건", "필요증거", "맥락", "판정규칙", "미확인처리", "대상", "기준유형", "적용성", "증거상태"):
            if field in i:
                lines.append(f"  {field}: {i[field]}")
        sheets.setdefault(i["id"][0], []).append("\n".join(lines))

    print(f"{len(items)} items: {counts}")
    sheet_files = []
    for s, blocks in sheets.items():
        chunks, current = [], ""
        for block in blocks:
            if current and len((current + block + "\n").encode("utf-8")) >= 9500:
                chunks.append(current)
                current = ""
            current += block + "\n"
        if current:
            chunks.append(current)
        for index, text in enumerate(chunks, 1):
            name = f"{s}.md" if index == 1 else f"{s}-{index}.md"
            path = os.path.join(a.out, name)
            sheet_files.append(name)
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(text)
            print(f"- {path}: {len(text.encode('utf-8')):,} bytes")
    ext = os.path.join(a.out, "review_external.json")
    with open(ext, "w", encoding="utf-8") as fp:
        json.dump({"findings": external}, fp, ensure_ascii=False, indent=1)
    coverage = {"시트": a.sheets, "SW사업": True if a.sw else False if a.non_sw else None,
                "항목": [i["id"] for i in items], "파일": sheet_files}
    with open(os.path.join(a.out, "coverage.json"), "w", encoding="utf-8") as fp:
        json.dump(coverage, fp, ensure_ascii=False, indent=2)
    print(f"- {ext}: {len(external)} external items prefilled as 확인필요")
    print(f"- script-only items ({counts.get('script', 0)}) come from numeric_findings.json")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
