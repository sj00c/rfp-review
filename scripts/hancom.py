#!/usr/bin/env python3
import argparse
import importlib.util
import locale
import os
import subprocess
import sys

MODULE = "FilePathCheckerModule"
PS = r"""
$ErrorActionPreference = 'Stop'
$hwp = New-Object -ComObject HWPFrame.HwpObject
try {
  try { [void]$hwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule') } catch {}
  try { $hwp.XHwpWindows.Item(0).Visible = $false } catch {}
  if (-not $hwp.Open($env:RFP_SRC, $env:RFP_FMT, 'forceopen:true')) { Write-Output 'OPEN_FAIL'; exit 3 }
  Write-Output ('PAGES=' + $hwp.PageCount)
  if ($env:RFP_DST -and -not $hwp.SaveAs($env:RFP_DST, 'HWPX', '')) { Write-Output 'SAVE_FAIL'; exit 4 }
  try { [void]$hwp.Clear(1) } catch {}
} finally {
  try { $hwp.Quit() } catch {}
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($hwp)
}
"""
REASON = {3: "한/글이 파일을 열지 못했습니다(암호·손상·배포용 문서일 수 있음).",
          4: "한/글이 HWPX 저장에 실패했습니다."}


def register_security_module():
    """보안 확인 창을 없애는 승인 모듈을 HKCU에 등록한다. 이미 등록됐거나 DLL이 없으면 그대로 둔다."""
    import winreg
    key_path = r"Software\HNC\HwpAutomation\Modules"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            if os.path.isfile(winreg.QueryValueEx(key, MODULE)[0]):
                return True
    except OSError:
        pass
    spec = importlib.util.find_spec("pyhwpx")  # 설치돼 있으면 그 DLL만 빌린다(import·설치 불필요)
    dll = os.path.join(os.path.dirname(spec.origin), MODULE + ".dll") if spec and spec.origin else ""
    if not os.path.isfile(dll):
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, MODULE, 0, winreg.REG_SZ, dll)
    return True


def run(src, dst, timeout):
    """한/글로 src를 연다. dst가 있으면 HWPX로 저장한다. 쪽수를 돌려준다."""
    if os.name != "nt":
        raise RuntimeError("Windows가 아니라 한/글을 쓸 수 없습니다.")
    if not os.path.isfile(src):
        raise RuntimeError(f"파일이 없습니다: {src}")
    if dst:
        if os.path.lexists(dst):
            raise RuntimeError(f"출력 파일이 이미 있습니다: {dst} — 다른 이름을 주세요.")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not register_security_module():
        print("[안내] 한/글 보안 확인 창이 뜰 수 있습니다. 뜨면 '모두 허용'을 눌러 주세요.")
    fmt = "HWP" if src.lower().endswith(".hwp") else "HWPX"
    env = dict(os.environ, RFP_SRC=src, RFP_DST=dst or "", RFP_FMT=fmt)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                           env=env, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError("PowerShell을 찾지 못했습니다.") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{timeout}초 안에 끝나지 않았습니다(보안 확인 창이 떠 있을 수 있음). "
                           "작업 관리자에서 남은 Hwp.exe를 닫아 주세요.") from e
    out = (p.stdout + p.stderr).decode(locale.getpreferredencoding(False), "replace")
    if p.returncode != 0:
        raise RuntimeError(REASON.get(p.returncode) or f"한/글을 실행하지 못했습니다(설치 확인): {out.strip()[-300:]}")
    if dst and (not os.path.isfile(dst) or os.path.getsize(dst) == 0):
        raise RuntimeError("결과 파일이 생기지 않았습니다.")
    return next((ln.split("=", 1)[1].strip() for ln in out.splitlines() if ln.startswith("PAGES=")), "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["convert", "check", "resave"])
    ap.add_argument("src")
    ap.add_argument("-o", "--out", help="convert·resave의 출력 .hwpx 경로")
    ap.add_argument("--timeout", type=int, default=180, help="초")
    a = ap.parse_args()
    want = ".hwp" if a.action == "convert" else ".hwpx"
    if not a.src.lower().endswith(want):
        print(f"[중단] {a.action}에는 {want} 파일을 주세요: {a.src}")
        return 2
    if (a.action == "check") == bool(a.out):
        print("[중단] convert·resave는 -o가 필요하고, check는 -o를 받지 않습니다.")
        return 2
    src = os.path.abspath(a.src)
    dst = os.path.abspath(a.out) if a.out else None
    try:
        pages = run(src, dst, a.timeout)
    except RuntimeError as e:
        print(f"[실패] {e}")
        if a.action == "convert":
            print("→ 한/글에서 '다른 이름으로 저장 → HWPX'로 저장해 다시 주세요.")
        return 2
    if a.action == "check":
        print(f"[열림] {src} ({pages}쪽)")
    else:
        print(f"[완료] {src} → {dst} ({pages}쪽, {os.path.getsize(dst):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
