#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_text import READERS, sha256

LIB = os.path.abspath(os.path.expanduser(os.environ.get("RFP_GUIDES") or "~/rfp-guides"))
INDEX_DIR = os.path.join(LIB, ".index")
INDEX = os.path.join(INDEX_DIR, "index.json")
WS = re.compile(r"\s+")


def load():
    if not os.path.isfile(INDEX):
        return {}
    with open(INDEX, encoding="utf-8") as fp:
        return json.load(fp)


def save(index):
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as fp:
        json.dump(index, fp, ensure_ascii=False, indent=1)


def show(index):
    if not index:
        print(f"[비어 있음] {LIB}에 지침 파일이 없습니다.")
        return
    for gid, g in sorted(index.items()):
        print(f"- {gid} | {g['설명'] or '(설명 없음: 앞부분을 읽고 describe로 적을 것)'}")
        print(f"  원본: {g['원본']} | 추출본: {g['추출본']} ({g['줄']}줄)")


def sync():
    if not os.path.isdir(LIB):
        print(f"[없음] 지침 라이브러리 폴더가 없습니다: {LIB}")
        return 1
    old, index, ok = load(), {}, True
    for root, dirs, files in os.walk(LIB):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in READERS or name.startswith(("~$", ".")):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, LIB)
            gid = re.sub(r"[\\/]+", "__", os.path.splitext(rel)[0])
            digest = sha256(path)
            prev = old.get(gid)
            if prev and prev["sha256"] == digest and os.path.isfile(prev["추출본"]):
                index[gid] = prev
                continue
            try:
                lines = READERS[ext](path)
            except Exception as e:
                print(f"[실패] {rel}: {e}")
                ok = False
                continue
            if not lines:
                print(f"[실패] {rel}: 읽은 내용이 없습니다")
                ok = False
                continue
            os.makedirs(INDEX_DIR, exist_ok=True)
            txt = os.path.join(INDEX_DIR, gid + ".txt")
            with open(txt, "w", encoding="utf-8") as fp:
                fp.write(f"# 원본: {name}\n" + "\n".join(lines) + "\n")
            index[gid] = {"원본": rel, "sha256": digest, "추출본": txt, "줄": len(lines), "설명": ""}
            print(f"[{'갱신' if prev else '추가'}] {rel} ({len(lines)}줄)")
    for gid in sorted(set(old) - set(index)):
        if os.path.isfile(old[gid]["추출본"]):
            os.remove(old[gid]["추출본"])
        print(f"[삭제] {old[gid]['원본']}")
    save(index)
    show(index)
    return 0 if ok else 1


def describe(gid, text):
    index = load()
    if gid not in index:
        print(f"[없음] {gid} — sync 결과의 id를 쓰세요.")
        return 1
    index[gid]["설명"] = WS.sub(" ", text).strip()
    save(index)
    print(f"- {gid} | {index[gid]['설명']}")
    return 0


def search(terms, gid, limit):
    index = load()
    if gid and gid not in index:
        print(f"[없음] {gid}")
        return 1
    targets = {gid: index[gid]} if gid else index
    keys = [WS.sub("", t) for t in terms if WS.sub("", t)]
    hits = 0
    for g, meta in sorted(targets.items()):
        with open(meta["추출본"], encoding="utf-8") as fp:
            for ln in fp:
                flat = WS.sub("", ln)
                if ln.startswith("# 원본:") or not all(k in flat for k in keys):
                    continue
                hits += 1
                if hits <= limit:
                    print(f"{g} {ln.rstrip()}")
    if hits > limit:
        print(f"… {hits - limit}건 더. 단어를 더 주거나 --id로 좁히세요.")
    print(f"[검색] {' '.join(terms)}: {hits}건")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    d = sub.add_parser("describe")
    d.add_argument("id")
    d.add_argument("text")
    s = sub.add_parser("search")
    s.add_argument("terms", nargs="+")
    s.add_argument("--id")
    s.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    if a.cmd == "sync":
        return sync()
    if a.cmd == "describe":
        return describe(a.id, a.text)
    return search(a.terms, a.id, a.limit)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
