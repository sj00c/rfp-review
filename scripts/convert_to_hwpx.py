#!/usr/bin/env python3
"""설치된 한/글(Hancom Office)로 .hwp(바이너리)를 .hwpx(OWPML)로 변환한다.

바이너리 .hwp에는 메모·형광펜을 안정적으로 쓸 수 없으므로, 주석 전에 한 번 HWPX로 바꾼다.
변환 후에는 extract_text·annotate_hwpx가 모두 같은 .hwpx를 기준으로 동작한다.

전제: Windows + 한/글 설치(COM ProgID "HWPFrame.HwpObject") + pywin32.
한/글이 없으면 2번 종료코드와 안내 메시지를 내고, 호출부는 기존 방식(HWPX 요청/엑셀)으로 되돌아간다.

사용법:
  python convert_to_hwpx.py "제안요청서.hwp" [-o "제안요청서.hwpx"]
"""
import argparse
import os
import sys


def _ensure_security_module():
    """한/글 자동화 보안 경고창을 없애기 위해 승인 모듈(FilePathCheckerModule)을 레지스트리에 등록한다.

    pyhwpx가 번들한 FilePathCheckerModule.dll을 찾아 HKCU의 HwpAutomation\\Modules에 등록한다.
    이미 등록돼 있거나 Windows가 아니면 조용히 넘어간다. 등록된 DLL 경로를 반환(없으면 None)."""
    try:
        import os
        import pyhwpx  # 번들 DLL 제공
        dll = os.path.join(os.path.dirname(pyhwpx.__file__), "FilePathCheckerModule.dll")
        if not os.path.exists(dll):
            return None
    except Exception:
        return None
    try:
        import winreg
    except ImportError:
        return None
    for root in (r"Software\HNC\HwpAutomation\Modules", r"Software\Hnc\HwpAutomation\Modules"):
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, root)
            try:
                cur, _ = winreg.QueryValueEx(key, "FilePathCheckerModule")
            except FileNotFoundError:
                cur = None
            if cur != dll:
                winreg.SetValueEx(key, "FilePathCheckerModule", 0, winreg.REG_SZ, dll)
            winreg.CloseKey(key)
        except OSError:
            pass
    return dll


def _create_hwp_instance(win32):
    """Start a dedicated Hancom process; never attach to a user's running instance."""
    try:
        return win32.DispatchEx("HWPFrame.HwpObject")
    except Exception as exc:
        raise RuntimeError(f"한/글 독립 인스턴스를 시작하지 못했습니다: {exc}") from exc


def convert_hwp_to_hwpx(src, dst=None):
    """src(.hwp)를 dst(.hwpx)로 변환하고 dst 경로를 반환한다. 실패 시 RuntimeError."""
    src = os.path.abspath(src)
    if not os.path.exists(src):
        raise RuntimeError(f"원본을 찾을 수 없습니다: {src}")
    if dst is None:
        dst = os.path.splitext(src)[0] + ".hwpx"
    dst = os.path.abspath(dst)
    if os.path.lexists(dst):
        # 기존 HWPX는 사용자가 따로 만든 판본일 수 있다. mtime으로 재사용 여부를 추측하지 않는다.
        raise RuntimeError(f"출력 파일이 이미 있습니다: {dst} — -o로 다른 이름을 지정하세요.")
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    try:
        import pythoncom
        import win32com.client as win32
    except ImportError as e:
        raise RuntimeError(
            "pywin32가 없어 한/글 COM을 쓸 수 없습니다. `pip install pywin32` 후 다시 시도하세요.") from e

    _ensure_security_module()  # 보안 경고창 억제 모듈을 미리 레지스트리에 등록

    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = _create_hwp_instance(win32)
        # 파일 접근 보안 대화상자 억제(위에서 등록한 승인 모듈 사용)
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        if not hwp.Open(src, "HWP", "forceopen:true"):
            raise RuntimeError("한/글이 원본을 열지 못했습니다(암호·손상·배포용 문서일 수 있음).")
        if not hwp.SaveAs(dst, "HWPX", ""):
            raise RuntimeError(f"한/글이 변환 결과 저장에 실패했습니다: {dst}")
        try:
            hwp.Clear(1)
        except Exception:
            pass
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError("변환 결과 파일이 생성되지 않았습니다.")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="변환할 .hwp 파일")
    ap.add_argument("-o", "--out", default=None, help="출력 .hwpx 경로(기본: 원본과 같은 이름)")
    a = ap.parse_args()
    if not a.src.lower().endswith(".hwp"):
        print(f"[건너뜀] .hwp 파일이 아닙니다: {a.src}")
        return 1
    try:
        out = convert_hwp_to_hwpx(a.src, a.out)
    except RuntimeError as e:
        print(f"[변환 실패] {e}")
        print("→ 한/글에서 '다른 이름으로 저장 → 파일 형식 HWPX'로 저장해 다시 올려주세요.")
        return 2
    print(f"[변환 완료] {a.src} → {out} ({os.path.getsize(out):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # 하네스가 파이프로 읽어도 UTF-8로 나가게
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
