#!/usr/bin/env python3
"""annotate_hwpx로 메모를 달되, 한/글이 열지 못하게 만드는 인라인 메모를 자동으로 가려낸다.

일부 문서에서 특정 위치에 인라인 메모(형광펜+메모필드)를 넣으면 한/글이
"문서가 손상되었거나 변조되었을 가능성이 있습니다" 경고를 내며 열지 못하는 경우가 있다.
이 드라이버는 findings를 하나씩 인라인으로 누적하면서 그때마다 한/글 COM으로 열어보고,
열리면 인라인 유지, 열리지 않으면 그 finding을 '검토 요약'으로 돌린다(원문='해당 내용 없음').
결과적으로 한/글이 확실히 여는, 인라인을 최대한 살린 메모본을 만든다.

사용법:
  python safe_annotate.py 문서.hwpx numeric_findings.json review.json --doc 제안요청서 \
      [--include-check] -o 결과.hwpx
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load_merged(paths):
    """annotate_hwpx.load_findings와 같은 방식으로 (id,항목) 기준 병합(뒤 파일 우선), 순서 보존."""
    merged = {}
    order = []
    for p in paths:
        for f in json.load(open(p, encoding="utf-8")).get("findings", []):
            key = (f.get("id"), f.get("항목"))
            if key not in merged:
                order.append(key)
            merged[key] = f
    return [merged[k] for k in order]


def run_annotate(hwpx, findings, doc, include_check, out):
    tmp = out + ".findings.json"
    json.dump({"meta": {}, "findings": findings}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    cmd = [sys.executable, os.path.join(HERE, "annotate_hwpx.py"), hwpx, tmp, "--doc", doc, "-o", out]
    if include_check:
        cmd.append("--include-check")
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return os.path.exists(out)


class HwpOpener:
    """한/글 COM 인스턴스 하나를 재사용해 파일이 열리는지만 확인한다."""

    def __init__(self):
        from convert_to_hwpx import _ensure_security_module
        import pythoncom
        import win32com.client as win32
        _ensure_security_module()
        pythoncom.CoInitialize()
        try:
            self.hwp = win32.gencache.EnsureDispatch("HWPFrame.HwpObject")
        except Exception:
            self.hwp = win32.Dispatch("HWPFrame.HwpObject")
        try:
            self.hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            self.hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass

    def opens(self, path):
        ok = False
        try:
            ok = bool(self.hwp.Open(os.path.abspath(path), "HWPX", "forceopen:true"))
        except Exception:
            ok = False
        try:
            self.hwp.Clear(1)
        except Exception:
            pass
        return ok

    def close(self):
        import pythoncom
        try:
            self.hwp.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def to_summary(f):
    g = dict(f)
    g["원문"] = "해당 내용 없음"
    g.pop("참조", None)  # 참조 메모는 요약으로 가면 의미 없음
    loc = f.get("위치", "")
    summ = f.get("요약") or f.get("항목", "")
    if loc and loc not in summ:
        g["요약"] = f"[{loc.split(']')[0].lstrip('[')}] {summ}"
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("findings", nargs="+")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--include-check", action="store_true")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    allf = load_merged(a.findings)
    opener = HwpOpener()
    trial = a.out + ".trial.hwpx"
    inline_keep = []   # 그대로 인라인
    forced = []        # 요약으로 돌린 finding
    try:
        # 먼저 전체 인라인으로 한 번: 열리면 그대로 끝
        if run_annotate(a.hwpx, allf, a.doc, a.include_check, trial) and opener.opens(trial):
            os.replace(trial, a.out)
            print(f"[safe-annotate] 전체 인라인 OK → {a.out}")
            return 0
        # 누적 추가: 안전한 것만 인라인 유지
        for i, f in enumerate(allf):
            cand = []
            keyset = {(x.get("id"), x.get("항목")) for x in inline_keep}
            keyset.add((f.get("id"), f.get("항목")))
            for g in allf:
                k = (g.get("id"), g.get("항목"))
                cand.append(g if k in keyset else to_summary(g))
            ok = run_annotate(a.hwpx, cand, a.doc, a.include_check, trial) and opener.opens(trial)
            label = f"{f.get('id')} {f.get('항목')}"
            if ok:
                inline_keep.append(f)
                print(f"  [인라인 OK] {label}")
            else:
                forced.append(f)
                print(f"  [요약으로] {label}")
        # 최종본 생성
        keyset = {(x.get("id"), x.get("항목")) for x in inline_keep}
        final = [g if (g.get("id"), g.get("항목")) in keyset else to_summary(g) for g in allf]
        run_annotate(a.hwpx, final, a.doc, a.include_check, a.out)
        okf = opener.opens(a.out)
        print(f"[safe-annotate] 인라인 {len(inline_keep)}건, 요약으로 {len(forced)}건, 최종 오픈={'OK' if okf else '실패'} → {a.out}")
        if forced:
            print("  요약으로 돌린 항목: " + ", ".join(f"{x.get('id')}" for x in forced))
    finally:
        try:
            if os.path.exists(trial):
                os.remove(trial)
        except OSError:
            pass
        opener.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
