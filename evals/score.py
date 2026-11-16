#!/usr/bin/env python3
import argparse
import collections
import glob
import json
import os
import re
import sys

E = os.path.dirname(os.path.abspath(__file__))
PARA = re.compile(r"문단\s*(\d+)")


def paras_of(spec):
    out = set()
    for x in spec:
        if isinstance(x, str) and "-" in x:
            a, b = (int(v) for v in x.split("-"))
            out.update(range(a, b + 1))
        else:
            out.add(int(x))
    return out


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError:
            return default


def findings(run):
    work = glob.glob(os.path.join(run, "**", ".rfp-review", "*"), recursive=True)
    out = []
    for w in work:
        for fn in ("numeric_findings.json", "review.json"):
            out += read_json(os.path.join(w, fn), {"findings": []})["findings"]
    return out, bool(work)


def items_coverage(run):
    for p in glob.glob(os.path.join(run, "**", ".rfp-review", "*", "items.json"), recursive=True):
        items = read_json(p)["items"]
        return sum(1 for x in items if x.get("판정")), len(items)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.path.join(E, "runs"))
    ap.add_argument("--show-fp", action="store_true", help="허위로 센 지적을 모두 보여 준다")
    a = ap.parse_args()
    rows, by_group = [], collections.defaultdict(list)
    for run in sorted(glob.glob(os.path.join(a.runs, "*-*-*"))):
        sample, model, rep = os.path.basename(run).rsplit("-", 2)
        ans = read_json(os.path.join(E, "data", sample, "answers.json"))
        if ans is None:
            continue
        fs, has_work = findings(run)
        paras = {}
        for f in fs:
            m = PARA.search(f.get("위치", ""))
            if m:
                paras.setdefault(int(m.group(1)), f)
        hit = {i["id"] for i in ans["issues"] if paras.keys() & paras_of(i["문단"])}
        known = {n for i in ans["issues"] + ans.get("neutral", []) for n in paras_of(i["문단"])}
        fp_paras = sorted(set(paras) - known)
        res = read_json(os.path.join(run, "result.json"), {})
        wall = 0
        if os.path.isfile(os.path.join(run, "wall.txt")):
            with open(os.path.join(run, "wall.txt")) as fp:
                wall = int(fp.read() or 0)
        row = dict(sample=sample, model=model, rep=rep, hit=hit, issues=[i["id"] for i in ans["issues"]],
                   must=[i["id"] for i in ans["issues"] if i["등급"] == "필수"],
                   fp=fp_paras, fp_detail=[paras[n] for n in fp_paras], ok=has_work,
                   wall=wall, cost=res.get("total_cost_usd", 0.0), cov=items_coverage(run))
        rows.append(row)
        by_group[(sample, model)].append(row)
    if not rows:
        print("채점할 실행이 없습니다.")
        return 1
    for r in rows:
        must_hit = len(set(r["must"]) & r["hit"])
        cov = f" 항목판정 {r['cov'][0]}/{r['cov'][1]}" if r["cov"] else ""
        miss = ",".join(sorted(set(r["must"]) - r["hit"], key=lambda x: int(x[1:])))
        print(f"{r['sample']} {r['model']:6} #{r['rep']} 잡음 {len(r['hit'])}/{len(r['issues'])} (필수 {must_hit}/{len(r['must'])}) "
              f"허위 {len(r['fp'])} {r['wall']}s ${r['cost']:.2f}{cov}{'' if r['ok'] else ' [작업 폴더 없음]'}"
              + (f" 놓친 필수: {miss}" if miss else ""))
        if a.show_fp:
            for f in r["fp_detail"]:
                print(f"    허위? {f['위치']} {f['요약']}")
    print()
    models = sorted({r["model"] for r in rows})
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        recall = sum(len(r["hit"]) / len(r["issues"]) for r in rs) / len(rs)
        must = sum(len(set(r["must"]) & r["hit"]) / max(1, len(r["must"])) for r in rs) / len(rs)
        cons = []
        for (_, mm), group in by_group.items():
            if mm != m:
                continue
            ids = group[0]["issues"]
            cons.append(sum(all(i in g["hit"] for g in group) for i in ids) / len(ids))
        print(f"METRIC recall_{m}={recall:.3f}")
        print(f"METRIC must_recall_{m}={must:.3f}")
        print(f"METRIC pass_all_reps_{m}={sum(cons) / len(cons):.3f}")
        print(f"METRIC fp_mean_{m}={sum(len(r['fp']) for r in rs) / len(rs):.1f}")
        print(f"METRIC wall_mean_{m}={sum(r['wall'] for r in rs) / len(rs):.0f}")
        print(f"METRIC cost_mean_{m}={sum(r['cost'] for r in rs) / len(rs):.2f}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
