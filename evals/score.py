#!/usr/bin/env python3
"""평가 채점: evals/runs/<샘플>-<모델>-<회차>/ 의 지적을 evals/data/<샘플>/answers.json 과 문단 번호로 맞춘다.

- 잡음: 정답 issue의 문단 중 하나에 지적이 있으면 그 issue를 잡은 것으로 본다.
- 허위: issue·neutral 어느 문단에도 없는 지적 위치(문단) 수. 정답지가 초안이면 실제 오류일 수도 있으니 목록을 읽어 볼 것.
- 일관성: 같은 샘플·모델의 회차들 중 issue마다 모두 잡았는지(pass^k 방식, k=회차 수).
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

E = os.path.dirname(os.path.abspath(__file__))
PARA = re.compile(r"문단\s*(\d+)")


def findings(run):
    work = glob.glob(os.path.join(run, "output", ".rfp-review", "*"))
    out = []
    for w in work:
        for fn in ("numeric_findings.json", "review.json"):
            p = os.path.join(w, fn)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fp:
                    out += json.load(fp)["findings"]
    return out, bool(work)


def items_coverage(run):
    """items.json이 있으면 (판정한 항목 수, 전체 항목 수)."""
    for p in glob.glob(os.path.join(run, "output", ".rfp-review", "*", "items.json")):
        with open(p, encoding="utf-8") as fp:
            items = json.load(fp)["items"]
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
        ans_path = os.path.join(E, "data", sample, "answers.json")
        if not os.path.isfile(ans_path):
            continue
        with open(ans_path, encoding="utf-8") as fp:
            ans = json.load(fp)
        fs, has_work = findings(run)
        paras = {}
        for f in fs:
            m = PARA.search(f.get("위치", ""))
            if m:
                paras.setdefault(int(m.group(1)), f)
        hit = {i["id"] for i in ans["issues"] if paras.keys() & set(i["문단"])}
        known = {n for i in ans["issues"] + ans.get("neutral", []) for n in i["문단"]}
        fp_paras = sorted(set(paras) - known)
        res = {}
        if os.path.isfile(os.path.join(run, "result.json")):
            with open(os.path.join(run, "result.json"), encoding="utf-8") as fp:
                try:
                    res = json.load(fp)
                except json.JSONDecodeError:
                    res = {}
        row = dict(sample=sample, model=model, rep=rep, hit=hit, total=len(ans["issues"]),
                   must=[i["id"] for i in ans["issues"] if i["등급"] == "필수"],
                   fp=fp_paras, fp_detail=[paras[n] for n in fp_paras], ok=has_work,
                   wall=int(open(os.path.join(run, "wall.txt")).read() or 0) if os.path.isfile(os.path.join(run, "wall.txt")) else 0,
                   cost=res.get("total_cost_usd", 0.0), cov=items_coverage(run))
        rows.append(row)
        by_group[(sample, model)].append(row)
    if not rows:
        print("채점할 실행이 없습니다.")
        return 1
    for r in rows:
        must_hit = len(set(r["must"]) & r["hit"])
        cov = f" 항목판정 {r['cov'][0]}/{r['cov'][1]}" if r["cov"] else ""
        miss = ",".join(sorted({i for i in r["must"]} - r["hit"], key=lambda x: int(x[1:])))
        print(f"{r['sample']} {r['model']:6} #{r['rep']} 잡음 {len(r['hit'])}/{r['total']} (필수 {must_hit}/{len(r['must'])}) "
              f"허위 {len(r['fp'])} {r['wall']}s ${r['cost']:.2f}{cov}{'' if r['ok'] else ' [작업 폴더 없음]'}"
              + (f" 놓친 필수: {miss}" if miss else ""))
        if a.show_fp:
            for f in r["fp_detail"]:
                print(f"    허위? {f['위치']} {f['요약']}")
    print()
    models = sorted({r["model"] for r in rows})
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        recall = sum(len(r["hit"]) / r["total"] for r in rs) / len(rs)
        must = sum(len(set(r["must"]) & r["hit"]) / max(1, len(r["must"])) for r in rs) / len(rs)
        # pass^k: 샘플·모델 묶음마다, issue를 모든 회차에서 잡은 비율
        cons = []
        for (s, mm), group in by_group.items():
            if mm != m:
                continue
            ids = [i for i in json.load(open(os.path.join(E, "data", s, "answers.json"), encoding="utf-8"))["issues"]]
            cons.append(sum(all(i["id"] in g["hit"] for g in group) for i in ids) / len(ids))
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
