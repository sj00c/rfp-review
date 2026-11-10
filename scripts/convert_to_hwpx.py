#!/usr/bin/env python3
"""설치된 한/글로 .hwp를 .hwpx로 변환한다(메모는 HWPX에만 달 수 있다).

Windows + 한/글 필요. Python 패키지 없이 Windows PowerShell로 한/글(HWPFrame.HwpObject)을 부른다.
원본은 건드리지 않고, 출력 파일이 이미 있으면 덮어쓰지 않고 중단한다.

한/글은 외부 프로그램이 파일을 열 때 보안 확인 창을 띄울 수 있다. 승인 모듈(FilePathCheckerModule)이
레지스트리에 등록돼 있으면 창 없이 변환한다. pyhwpx가 설치돼 있으면 그 DLL을 찾아 등록한다(설치는 필수 아님).
창이 뜨면 '모두 허용'을 누르면 된다. 제한 시간 안에 끝나지 않으면 실패로 보고 HWPX 저장을 요청한다.

사용법:
  python convert_to_hwpx.py 제안요청서.hwp -o 작업폴더/제안요청서.hwpx
"""
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
  if (-not $hwp.Open($env:RFP_SRC, 'HWP', 'forceopen:true')) { Write-Output 'OPEN_FAIL'; exit 3 }
  if (-not $hwp.SaveAs($env:RFP_DST, 'HWPX', '')) { Write-Output 'SAVE_FAIL'; exit 4 }
  try { [void]$hwp.Clear(1) } catch {}
} finally {
  try { $hwp.Quit() } catch {}
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($hwp)
}
"""
REASON = {3: "한/글이 원본을 열지 못했습니다(암호·손상·배포용 문서일 수 있음).",
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
    spec = importlib.util.find_spec("pyhwpx")  # import하지 않고 위치만 찾는다
    dll = os.path.join(os.path.dirname(spec.origin), MODULE + ".dll") if spec and spec.origin else ""
    if not os.path.isfile(dll):
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, MODULE, 0, winreg.REG_SZ, dll)
    return True


def convert(src, dst, timeout):
    if os.name != "nt":
        raise RuntimeError("Windows가 아니라 한/글로 변환할 수 없습니다.")
    if not os.path.isfile(src):
        raise RuntimeError(f"원본이 없습니다: {src}")
    if os.path.lexists(dst):
        raise RuntimeError(f"출력 파일이 이미 있습니다: {dst} — 다른 이름을 주세요.")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not register_security_module():
        print("[안내] 한/글 보안 확인 창이 뜰 수 있습니다. 뜨면 '모두 허용'을 눌러 주세요.")
    env = dict(os.environ, RFP_SRC=src, RFP_DST=dst)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                           env=env, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise RuntimeError("PowerShell을 찾지 못했습니다.") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{timeout}초 안에 끝나지 않았습니다(보안 확인 창이 떠 있을 수 있음). "
                           "작업 관리자에서 남은 Hwp.exe를 닫아 주세요.") from e
    if p.returncode != 0:
        msg = (p.stdout + p.stderr).decode(locale.getpreferredencoding(False), "replace").strip()
        raise RuntimeError(REASON.get(p.returncode) or f"한/글을 실행하지 못했습니다(설치 확인): {msg[-300:]}")
    if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError("변환 결과 파일이 생기지 않았습니다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="변환할 .hwp")
    ap.add_argument("-o", "--out", required=True, help="출력 .hwpx 경로(작업 폴더 안)")
    ap.add_argument("--timeout", type=int, default=180, help="초")
    a = ap.parse_args()
    if not a.src.lower().endswith(".hwp"):
        print(f"[중단] .hwp 파일이 아닙니다: {a.src}")
        return 2
    src, dst = os.path.abspath(a.src), os.path.abspath(a.out)
    try:
        convert(src, dst, a.timeout)
    except RuntimeError as e:
        print(f"[변환 실패] {e}")
        print("→ 한/글에서 '다른 이름으로 저장 → HWPX'로 저장해 다시 주세요.")
        return 2
    print(f"[변환 완료] {src} → {dst} ({os.path.getsize(dst):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
