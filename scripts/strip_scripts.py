# -*- coding: utf-8 -*-
"""HWPX에서 문서 스크립트(Scripts/*.js)를 제거해 '손상/변조' 보안 경고를 없앤다.

한/글은 문서 보안설정이 '높음'일 때 스크립트(JScript)가 든 HWPX를 열면
"문서가 손상되었거나 변조되었을 가능성이 있습니다" 경고를 띄운다. 원본 템플릿에서
딸려온 기본 스텁(var Documents = XHwpDocuments; ...)이라 검토본에선 불필요하므로
① zip의 Scripts/ 파일 ② Contents/content.hpf의 <opf:item href="Scripts/...">
③ 같은 id를 가리키는 <opf:spine>의 <opf:itemref> 를 일관되게 제거한다.

사용법: python scripts/strip_scripts.py 입력.hwpx [-o 출력.hwpx]
-o 생략 시 입력 파일을 제자리에서 덮어쓴다.
"""
import argparse
import re
import sys
import zipfile


def strip(in_path, out_path):
    zin = zipfile.ZipFile(in_path)
    names = zin.namelist()
    script_files = [n for n in names if re.match(r"Scripts/.*\.js$", n, re.I)]
    hpf_name = "Contents/content.hpf"
    changed = {}
    removed_ids = []

    if hpf_name in names and script_files:
        hpf = zin.read(hpf_name).decode("utf-8")
        # Scripts/ 를 href로 가진 item의 id 수집
        for m in re.finditer(r'<opf:item\b[^>]*href="(Scripts/[^"]+)"[^>]*/>', hpf):
            idm = re.search(r'id="([^"]+)"', m.group(0))
            if idm:
                removed_ids.append(idm.group(1))
        # item 제거
        hpf = re.sub(r'<opf:item\b[^>]*href="Scripts/[^"]+"[^>]*/>', "", hpf)
        # 해당 id를 가리키는 spine itemref 제거
        for rid in removed_ids:
            hpf = re.sub(r'<opf:itemref\b[^>]*idref="%s"[^>]*/>' % re.escape(rid), "", hpf)
        changed[hpf_name] = hpf.encode("utf-8")

    drop = set(script_files)
    with zipfile.ZipFile(out_path, "w") as zout:
        for info in zin.infolist():
            if info.filename in drop:
                continue
            data = changed.get(info.filename, zin.read(info.filename))
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    zin.close()
    return script_files, removed_ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    out = a.out or a.hwpx
    tmp = out + ".tmp" if out == a.hwpx else out
    files, ids = strip(a.hwpx, tmp)
    if tmp != out:
        import os
        os.replace(tmp, out)
    sys.stdout.reconfigure(encoding="utf-8")
    if files:
        print(f"스크립트 제거: {files} (item id {ids}) → {out}")
    else:
        print(f"제거할 스크립트 없음 → {out}")


if __name__ == "__main__":
    main()
