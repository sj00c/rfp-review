#!/usr/bin/env python3
"""주석(메모) 삽입 후의 .hwpx를 한/글 COM으로 다시 열어 HWPX로 재저장한다.

annotate_hwpx가 파이썬으로 zip을 다시 묶으면 한/글이 "문서가 손상되었거나 변조되었을
가능성이 있습니다 … 문서 보안설정을 낮음으로" 경고를 띄우는 경우가 있다. 한/글이 자기
포맷으로 새로 저장하면 이 판정이 사라지므로, 메모본을 한/글로 열어 그대로 HWPX로
다시 저장한다(메모·형광펜은 그대로 보존).

전제: Windows + 한/글 설치(COM "HWPFrame.HwpObject") + pywin32.
사용법: python resave_hwpx.py 메모본.hwpx [-o 출력.hwpx]   (-o 생략 시 제자리 덮어쓰기)
"""
import argparse
import os
import sys

# convert_to_hwpx의 보안모듈 등록 재사용
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_to_hwpx import _create_hwp_instance, _ensure_security_module


def resave(src, dst=None):
    src = os.path.abspath(src)
    if not os.path.exists(src):
        raise RuntimeError(f"파일을 찾을 수 없습니다: {src}")
    if dst is None:
        dst = src
    dst = os.path.abspath(dst)
    inplace = (dst == src)
    tmp = dst + ".resave.hwpx" if inplace else dst

    try:
        import pythoncom
        import win32com.client as win32
    except ImportError as e:
        raise RuntimeError("pywin32가 없어 한/글 COM을 쓸 수 없습니다.") from e

    _ensure_security_module()
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = _create_hwp_instance(win32)
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        if not hwp.Open(src, "HWPX", "forceopen:true"):
            raise RuntimeError("한/글이 메모본을 열지 못했습니다.")
        if not hwp.SaveAs(tmp, "HWPX", ""):
            raise RuntimeError(f"한/글이 메모본 재저장에 실패했습니다: {tmp}")
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

    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        raise RuntimeError("재저장 결과 파일이 생성되지 않았습니다.")
    if inplace:
        os.replace(tmp, dst)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        out = resave(a.hwpx, a.out)
    except RuntimeError as e:
        print(f"[재저장 실패] {e}")
        return 2
    print(f"[재저장 완료] {out} ({os.path.getsize(out):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
