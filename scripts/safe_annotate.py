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
import shutil
import stat
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
    log = out + ".log"
    if os.path.lexists(out) or os.path.lexists(tmp) or os.path.lexists(log):
        raise RuntimeError(f"임시 annotate 경로가 이미 있습니다: {out}")
    with open(tmp, "x", encoding="utf-8") as fp:
        json.dump({"meta": {}, "findings": findings}, fp, ensure_ascii=False)
    cmd = [sys.executable, os.path.join(HERE, "annotate_hwpx.py"), hwpx, tmp, "--doc", doc, "-o", out]
    if include_check:
        cmd.append("--include-check")
    try:
        with open(log, "x", encoding="utf-8") as fp:
            try:
                rc = subprocess.run(cmd, stdout=fp, stderr=subprocess.STDOUT).returncode
            except OSError as exc:
                fp.write(f"\nannotate_hwpx 실행 실패: {exc}\n")
                return False
    except OSError as exc:
        raise RuntimeError(f"annotate 진단 파일을 생성하지 못했습니다: {exc}") from exc
    return rc == 0 and os.path.isfile(out)


def _paths_alias(first, second):
    try:
        if os.path.exists(first) and os.path.exists(second) and os.path.samefile(first, second):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def _author_actionable(finding, include_check):
    from annotate_hwpx import finding_target

    if finding_target(finding) != "작성자":
        return False
    verdict = finding.get("판정")
    return verdict == "수정필요" or (
        verdict == "확인필요" and (include_check or finding.get("질의") is True))


def _publish_exclusive(source, destination):
    """Atomically link a same-directory private trial without replacing user data."""
    try:
        info = os.lstat(source)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"최종 게시 trial이 일반 파일이 아닙니다: {source}")
        os.link(source, destination)
    except FileExistsError as exc:
        raise FileExistsError(f"출력 파일이 이미 있습니다: {destination}") from exc


def _private_trial_dir(output):
    output_dir = os.path.dirname(os.path.abspath(output))
    os.makedirs(output_dir, exist_ok=True)
    path = tempfile.mkdtemp(prefix=".safe-annotate-", dir=output_dir)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


class HwpOpener:
    """한/글 COM 인스턴스 하나를 재사용해 파일이 열리는지만 확인한다."""

    def __init__(self):
        from convert_to_hwpx import _create_hwp_instance, _ensure_security_module
        import pythoncom
        import win32com.client as win32
        self._pythoncom = pythoncom
        self._initialized = False
        self.hwp = None
        _ensure_security_module()
        pythoncom.CoInitialize()
        self._initialized = True
        try:
            self.hwp = _create_hwp_instance(win32)
        except RuntimeError:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            self._initialized = False
            raise
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
        if self.hwp is not None:
            try:
                self.hwp.Quit()
            except Exception:
                pass
            self.hwp = None
        if self._initialized:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass
            self._initialized = False


def to_summary(f):
    """인라인으로 못 단 finding을 검토 요약용으로 바꾼다. 참조 finding은 본 항목과 중복이므로 None(빼기)."""
    if f.get("참조"):
        return None
    g = dict(f)
    g["원문"] = "해당 내용 없음"
    loc = f.get("위치", "")
    summ = f.get("요약") or f.get("항목", "")
    if loc and loc not in summ:
        g["요약"] = f"[{loc.split(']')[0].lstrip('[')}] {summ}"
    return g


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("findings", nargs="+")
    ap.add_argument("--doc", required=True)
    ap.add_argument("--include-check", action="store_true")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    output = os.path.abspath(a.out)
    sources = [a.hwpx, *a.findings]
    if any(_paths_alias(output, source) for source in sources):
        print(f"[safe-annotate] 입력과 출력 경로가 같거나 alias입니다: {output}", file=sys.stderr)
        return 2
    if os.path.lexists(output):
        print(f"[safe-annotate] 출력 파일이 이미 있습니다: {output}", file=sys.stderr)
        return 2

    allf = load_merged(a.findings)
    author_findings = [f for f in allf if _author_actionable(f, a.include_check)]

    def key(x):
        return x.get("id"), x.get("항목")

    def build(inline_keys):
        """inline_keys에 없는 메모 대상은 요약으로 돌린 finding 목록. 적합 등은 건수 계산용으로 그대로 둔다."""
        out = []
        for g in allf:
            if not _author_actionable(g, a.include_check) or key(g) in inline_keys:
                out.append(g)
            else:
                s = to_summary(g)
                if s is not None:
                    out.append(s)
        return out

    try:
        trial_dir = _private_trial_dir(output)
    except OSError as e:
        print(f"[safe-annotate] 임시 작업 디렉터리를 만들지 못했습니다: {e}", file=sys.stderr)
        return 2
    try:
        opener = HwpOpener()
    except RuntimeError as e:
        shutil.rmtree(trial_dir, ignore_errors=True)
        print(f"[safe-annotate] 한/글 독립 인스턴스 시작 실패: {e}", file=sys.stderr)
        return 2

    attempt = 0

    def next_trial():
        nonlocal attempt
        attempt += 1
        return os.path.join(trial_dir, f"trial-{attempt:04d}.hwpx")

    inline_keep = []   # 그대로 인라인
    forced = []        # 요약으로 돌린 finding
    success = False
    try:
        # 먼저 전체 인라인으로 한 번: 열리면 그대로 끝
        trial = next_trial()
        all_inline = build({key(f) for f in author_findings})
        if not run_annotate(a.hwpx, all_inline, a.doc, a.include_check, trial):
            # 메모 삽입 자체가 실패하면 finding별 시험도 전부 실패한다. 원인을 보려면 annotate_hwpx.py를 직접 실행한다.
            print("[safe-annotate] annotate_hwpx.py 실행 실패 — 같은 인자로 annotate_hwpx.py를 직접 실행해 오류를 확인하세요.")
            return 2
        if opener.opens(trial):
            try:
                _publish_exclusive(trial, output)
            except OSError as e:
                print(f"[safe-annotate] 최종 파일을 게시하지 못했습니다: {e}", file=sys.stderr)
                return 2
            success = True
            print(f"[safe-annotate] 전체 인라인 OK → {output}")
            return 0
        # 누적 추가: 안전한 것만 인라인 유지 (메모가 달리는 판정만 시험한다)
        for f in author_findings:
            keyset = {key(x) for x in inline_keep} | {key(f)}
            trial = next_trial()
            ok = run_annotate(a.hwpx, build(keyset), a.doc, a.include_check, trial) and opener.opens(trial)
            label = f"{f.get('id')} {f.get('항목')}"
            if ok:
                inline_keep.append(f)
                print(f"  [인라인 OK] {label}")
            else:
                forced.append(f)
                print(f"  [요약으로] {label}")
        # 최종본 생성
        final = build({key(x) for x in inline_keep})
        final_trial = next_trial()
        okf = run_annotate(a.hwpx, final, a.doc, a.include_check, final_trial) and opener.opens(final_trial)
        if okf:
            try:
                _publish_exclusive(final_trial, output)
            except OSError as e:
                print(f"[safe-annotate] 최종 파일을 게시하지 못했습니다: {e}", file=sys.stderr)
                return 2
            success = True
        print(f"[safe-annotate] 인라인 {len(inline_keep)}건, 요약으로 {len(forced)}건, 최종 오픈={'OK' if okf else '실패'} → {output}")
        if forced:
            print("  요약으로 돌린 항목: " + ", ".join(f"{x.get('id')}" for x in forced))
        if not okf:
            return 2
    except (OSError, RuntimeError) as e:
        print(f"[safe-annotate] 작업 실패: {e}", file=sys.stderr)
        return 2
    finally:
        opener.close()
        if success:
            shutil.rmtree(trial_dir, ignore_errors=True)
        else:
            print(f"[safe-annotate] 실패 진단을 보존했습니다: {trial_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
