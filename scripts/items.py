#!/usr/bin/env python3
"""지침(체크리스트) 항목별 판정 파일.

init: 지침 추출본의 줄 하나를 항목 하나로 삼아 판정이 빈 items.json을 만든다(위치 태그가 id).
todo: 판정이 빈 항목을 8KB씩 보여 준다. 지침을 읽는 것도 이 명령으로 한다.
set:  항목에 판정을 적는다. id 대신 접두어(예: '[공사_특화!')로 여러 항목을 한 번에 적을 수 있다.
"""
import argparse
import json
import os
import re
import sys

VERDICTS = ("위반", "확인필요", "적합", "해당없음")
TAG = re.compile(r"^(\[[^\]]+\])\s*(.*)$")
MIN_CHARS = 15  # 태그를 뺀 글자(공백 제외)가 이보다 적은 줄은 제목·번호 줄로 보고 항목에서 뺀다
TOO_MANY = 300


def load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def init(guides, out):
    old = {x["id"]: x for x in load(out)["items"]} if os.path.isfile(out) else {}
    items, kept = [], 0
    for g in guides:
        name = os.path.splitext(os.path.basename(g))[0]
        seen = {}
        n = 0
        with open(g, encoding="utf-8") as fp:
            for line in fp:
                m = TAG.match(line.strip())
                if not m or len(re.sub(r"\s", "", m.group(2))) < MIN_CHARS:
                    continue
                n += 1
                tag = m.group(1)
                seen[tag] = seen.get(tag, 0) + 1
                if seen[tag] > 1:  # PDF는 한 쪽의 여러 줄이 같은 [p.쪽] 태그라 순번을 붙인다
                    tag = f"{tag}#{seen[tag]}"
                iid = f"{name} {tag}"
                item = {"id": iid, "내용": m.group(2), "판정": ""}
                prev = old.get(iid)
                if prev and prev["내용"] == item["내용"] and prev.get("판정"):
                    item, kept = prev, kept + 1  # 이어서 할 때 같은 항목의 판정은 살린다
                items.append(item)
        if n == 0:
            print(f"[중단] {g}에서 항목을 하나도 찾지 못했습니다(빈 추출본이거나 스캔 문서). 원본 파일을 다시 받으세요.")
            return 2
    ids = [x["id"] for x in items]
    if len(set(ids)) != len(ids):
        print("[중단] 같은 항목 id가 두 번 나옵니다. 같은 이름의 지침 추출본을 두 번 주었는지 확인하세요.")
        return 2
    save(out, {"items": items})
    print(f"[항목] {len(items)}개 → {out}" + (f" (이전 판정 {kept}개 유지)" if kept else ""))
    if len(items) > TOO_MANY:
        print(f"[주의] 항목이 {TOO_MANY}개를 넘습니다. 법령·해설서처럼 긴 지침은 항목으로 만들지 말고 "
              "guides.py search로 찾아 근거로만 쓰세요. 점검표(체크리스트)만 항목으로 만듭니다.")
    return 0


def todo(path, max_bytes):
    items = load(path)["items"]
    left = [x for x in items if not x.get("판정")]
    used, shown = 0, 0
    for x in left:
        row = f"{x['id']} {x['내용']}"
        cost = len(row.encode("utf-8")) + 1
        if shown and used + cost > max_bytes:
            break
        print(row)
        used, shown = used + cost, shown + 1
    print(f"[남은 항목] {len(left) - shown}개 더 / 전체 {len(items)}개 중 판정 {len(items) - len(left)}개")
    return 0


def set_verdict(path, keys, verdict, finding, quote, reason):
    data = load(path)
    if verdict in ("위반", "확인필요") and not finding:
        print(f"[중단] {verdict}에는 --finding <review.json의 id>가 필요합니다.")
        return 2
    if verdict == "적합" and not quote:
        print("[중단] 적합에는 --quote <RFP 원문>이 필요합니다.")
        return 2
    if verdict == "해당없음" and not reason:
        print("[중단] 해당없음에는 --reason <이유>가 필요합니다.")
        return 2
    def match(x, k):
        """id나 위치 태그가 정확히 같거나, '!'로 끝나는 시트 접두어('[공사_특화!')로 시작하면 해당.
        그 밖의 앞부분 일치는 받지 않는다('[시트!1'이 10~19행까지 잡히는 실수를 막는다)."""
        tag = x["id"].split(" ", 1)[-1]
        if k in (x["id"], tag):
            return True
        return k.endswith("!") and (x["id"].startswith(k) or tag.startswith(k))

    hit = [x for x in data["items"] if any(match(x, k) for k in keys)]
    if not hit:
        print(f"[없음] {', '.join(keys)} — todo에 보이는 위치 태그 그대로, 또는 시트 전체는 '[시트!'로 쓰세요.")
        return 1
    for x in hit:
        x["판정"] = verdict
        for k in ("지적", "원문", "이유"):
            x.pop(k, None)
        if finding:
            x["지적"] = [f.strip() for f in finding.split(",") if f.strip()]
        if quote:
            x["원문"] = quote
        if reason:
            x["이유"] = reason
    save(path, data)
    left = sum(1 for x in data["items"] if not x.get("판정"))
    print(f"[판정] {verdict} {len(hit)}개 (남은 항목 {left}개)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("guides", nargs="+", help="항목으로 만들 지침 추출본(점검표)")
    i.add_argument("-o", "--out", default="items.json")
    t = sub.add_parser("todo")
    t.add_argument("items", nargs="?", default="items.json")
    t.add_argument("--max-bytes", type=int, default=8000)
    s = sub.add_parser("set")
    s.add_argument("items")
    s.add_argument("verdict", choices=VERDICTS)
    s.add_argument("ids", nargs="+", help="항목 id·위치 태그, 또는 시트 전체는 '[시트!'(여러 개 가능)")
    s.add_argument("--finding", help="위반·확인필요: review.json/numeric_findings.json의 지적 id(쉼표로 여러 개)")
    s.add_argument("--quote", help="적합: 그렇게 본 RFP 원문")
    s.add_argument("--reason", help="해당없음: 이유 한 줄")
    a = ap.parse_args()
    if a.cmd == "init":
        return init(a.guides, a.out)
    if a.cmd == "todo":
        return todo(a.items, a.max_bytes)
    return set_verdict(a.items, a.ids, a.verdict, a.finding, a.quote, a.reason)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
