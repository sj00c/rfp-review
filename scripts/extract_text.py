#!/usr/bin/env python3
"""검토 대상 문서를 위치 표시가 붙은 텍스트로 변환한다.

지원: .hwpx .hwp(HWP 5.x, 배포용/암호 문서 제외) .pdf .docx .xlsx .txt .md
출력: <출력폴더>/<파일명>.txt  — 각 줄 앞에 [p.쪽] 또는 [문단 n] / [시트!셀] 위치 표시

사용법:
  python extract_text.py 파일1 [파일2 ...] -o extracted/
"""
import argparse
import os
import re
import struct
import sys
import zipfile
import zlib
import xml.etree.ElementTree as ET


def clean(s):
    return re.sub(r"[ \t\u00a0]+", " ", s).strip()


# ------------------------------------------------------------------ HWPX
def from_hwpx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        secs = sorted([n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                      key=lambda n: int(re.findall(r"\d+", n)[-1]))
        n = 0
        for s in secs:
            root = ET.fromstring(z.read(s))
            for el in root.iter():
                if el.tag.endswith("}p"):
                    # 직계 run 안의 텍스트만 모아 중첩 표 문단이 중복되지 않게 한다
                    parts = []
                    for run in el:
                        if not run.tag.endswith("}run"):
                            continue
                        for t in run:
                            if t.tag.endswith("}t"):
                                parts.append("".join(t.itertext()))
                    txt = clean("".join(parts))
                    if txt:
                        n += 1
                        out.append(f"[문단 {n}] {txt}")
    return out


# ------------------------------------------------------------------ OLE(CFB) 최소 리더 (olefile 없이 .hwp 읽기)
class MiniCFB:
    END = 0xFFFFFFFE

    def __init__(self, path):
        with open(path, "rb") as fp:
            self.d = d = fp.read()
        if d[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
            raise RuntimeError("HWP 5.x(OLE) 형식이 아닙니다.")
        self.ss = 1 << struct.unpack("<H", d[30:32])[0]
        self.mss = 1 << struct.unpack("<H", d[32:34])[0]
        dir_start, = struct.unpack("<I", d[48:52])
        self.cutoff, mf_start, _, difat_start, n_difat = struct.unpack("<IIIII", d[56:76])
        difat = list(struct.unpack("<109I", d[76:512]))
        s = difat_start
        for _ in range(n_difat):
            if s >= 0xFFFFFFFA:
                break
            ent = struct.unpack(f"<{self.ss // 4}I", self.sector(s))
            difat += ent[:-1]
            s = ent[-1]
        self.fat = []
        for s in difat:
            if s < 0xFFFFFFFA:
                self.fat += struct.unpack(f"<{self.ss // 4}I", self.sector(s))
        dirdata = self.chain(dir_start)
        self.entries = []
        for i in range(len(dirdata) // 128):
            e = dirdata[i * 128:(i + 1) * 128]
            nl = struct.unpack("<H", e[64:66])[0]
            name = e[:max(nl - 2, 0)].decode("utf-16-le", "ignore")
            left, right, child = struct.unpack("<III", e[68:80])
            start, size = struct.unpack("<II", e[116:124])
            self.entries.append(dict(name=name, type=e[66], left=left, right=right, child=child, start=start, size=size))
        root = self.entries[0]
        self.ministream = self.chain(root["start"]) if root["start"] < 0xFFFFFFFA else b""
        mf = self.chain(mf_start) if mf_start < 0xFFFFFFFA else b""
        self.minifat = list(struct.unpack(f"<{len(mf) // 4}I", mf)) if mf else []
        self.paths = {}
        self._walk(root["child"], ())

    def sector(self, n):
        o = (n + 1) * self.ss
        return self.d[o:o + self.ss]

    def chain(self, s):
        out, seen = [], set()
        while s < 0xFFFFFFFA and s not in seen and s < len(self.fat) + 1:
            seen.add(s)
            out.append(self.sector(s))
            s = self.fat[s] if s < len(self.fat) else self.END
        return b"".join(out)

    def _walk(self, i, parent):
        stack = [i]
        while stack:
            i = stack.pop()
            if i >= 0xFFFFFFFA or i >= len(self.entries):
                continue
            e = self.entries[i]
            stack += [e["left"], e["right"]]
            p = parent + (e["name"],)
            if e["type"] == 2:
                self.paths[p] = e
            elif e["type"] == 1:
                self._walk(e["child"], p)

    def listdir(self):
        return [list(p) for p in self.paths]

    def read(self, p):
        e = self.paths[tuple(p) if not isinstance(p, str) else (p,)]
        if e["size"] < self.cutoff:
            out, s = [], e["start"]
            while s < 0xFFFFFFFA and s < len(self.minifat):
                o = s * self.mss
                out.append(self.ministream[o:o + self.mss])
                s = self.minifat[s]
            return b"".join(out)[:e["size"]]
        return self.chain(e["start"])[:e["size"]]


# ------------------------------------------------------------------ HWP 5.x
def from_hwp(path):
    ole = MiniCFB(path)
    header = ole.read("FileHeader")
    flags = struct.unpack("<I", header[36:40])[0]
    compressed, encrypted, distributed = flags & 1, flags & 2, flags & 4
    if encrypted or distributed:
        raise RuntimeError("암호 또는 배포용 HWP 문서입니다. 일반 HWPX/PDF로 저장해 다시 올려주세요.")
    secs = sorted([e for e in ole.listdir() if e[0] == "BodyText"], key=lambda e: int(re.findall(r"\d+", e[1])[0]))
    out, n = [], 0
    for e in secs:
        data = ole.read(e)
        if compressed:
            data = zlib.decompress(data, -15)
        i = 0
        while i + 4 <= len(data):
            h = struct.unpack("<I", data[i:i + 4])[0]
            i += 4
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            if size == 0xFFF:
                size = struct.unpack("<I", data[i:i + 4])[0]
                i += 4
            rec = data[i:i + size]
            i += size
            if tag != 67:  # HWPTAG_PARA_TEXT
                continue
            chars, j = [], 0
            while j + 2 <= len(rec):
                c = struct.unpack("<H", rec[j:j + 2])[0]
                if c < 32:
                    if c in (0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31):
                        j += 2
                    else:  # 인라인/확장 컨트롤: 8 wchar
                        if c == 9:
                            chars.append("\t")
                        j += 16
                    continue
                if 0xD800 <= c <= 0xDBFF and j + 4 <= len(rec):  # UTF-16 서러게이트 쌍 결합
                    c2 = struct.unpack("<H", rec[j + 2:j + 4])[0]
                    if 0xDC00 <= c2 <= 0xDFFF:
                        chars.append(chr(0x10000 + ((c - 0xD800) << 10) + (c2 - 0xDC00)))
                        j += 4
                        continue
                if 0xD800 <= c <= 0xDFFF:  # 짝 없는 서러게이트: 건너뜀
                    j += 2
                    continue
                chars.append(chr(c))
                j += 2
            txt = clean("".join(chars))
            if txt:
                n += 1
                out.append(f"[문단 {n}] {txt}")
    return out


# ------------------------------------------------------------------ PDF
def from_pdf(path):
    out = []
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for p, page in enumerate(pdf.pages, 1):
                for line in (page.extract_text() or "").splitlines():
                    if clean(line):
                        out.append(f"[p.{p}] {clean(line)}")
        return out
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    for p, page in enumerate(PdfReader(path).pages, 1):
        for line in (page.extract_text() or "").splitlines():
            if clean(line):
                out.append(f"[p.{p}] {clean(line)}")
    return out


# ------------------------------------------------------------------ DOCX
def from_docx(path):
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out, n = [], 0
    for p in root.iter(W + "p"):
        txt = clean("".join(t.text or "" for t in p.iter(W + "t")))
        if txt:
            n += 1
            out.append(f"[문단 {n}] {txt}")
    return out


# ------------------------------------------------------------------ XLSX (원가계산보고서 등)
def from_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            cells = [f"{c.coordinate}={c.value}" for c in row if c.value not in (None, "")]
            if cells:
                out.append(f"[{ws.title}!{row[0].row}행] " + " | ".join(cells))
    return out


def from_txt(path):
    with open(path, encoding="utf-8", errors="replace") as fp:
        return [f"[줄 {i}] {clean(l)}" for i, l in enumerate(fp, 1) if clean(l)]


READERS = {".hwpx": from_hwpx, ".hwp": from_hwp, ".pdf": from_pdf, ".docx": from_docx,
           ".xlsx": from_xlsx, ".xlsm": from_xlsx, ".txt": from_txt, ".md": from_txt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--outdir", default="extracted")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    ok = True
    for f in a.files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in READERS:
            print(f"[건너뜀] {f}: 지원하지 않는 형식({ext}). HWPX/PDF/DOCX로 변환해 주세요.")
            ok = False
            continue
        try:
            lines = READERS[ext](f)
        except Exception as e:  # noqa: BLE001
            print(f"[실패] {f}: {e}")
            ok = False
            continue
        out = os.path.join(a.outdir, os.path.splitext(os.path.basename(f))[0] + ".txt")
        with open(out, "w", encoding="utf-8") as fp:
            fp.write(f"# 원본: {os.path.basename(f)}\n" + "\n".join(lines) + "\n")
        chars = sum(len(l) for l in lines)
        warn = "  ※ 텍스트가 거의 없음: 스캔 PDF일 수 있습니다." if (ext == ".pdf" and chars < 200 * max(1, len({l.split("]")[0] for l in lines}))) else ""
        print(f"[완료] {f} → {out} ({len(lines)}줄, {chars:,}자){warn}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

