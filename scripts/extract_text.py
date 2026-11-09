#!/usr/bin/env python3
"""검토 대상 문서를 위치 표시가 붙은 텍스트로 변환한다.

지원: .hwpx .hwp(HWP 5.x, 배포용/암호 문서 제외) .pdf .docx .xlsx .txt .md
출력: <출력폴더>/<파일명>.txt  — 각 줄 앞에 [p.쪽] 또는 [문단 n] / [시트!셀] 위치 표시

사용법:
  python extract_text.py 파일1 [파일2 ...] -o extracted/
"""
import argparse
import json
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
def from_hwpx(path, objects=None):
    out = []
    with zipfile.ZipFile(path) as z:
        secs = sorted([n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                      key=lambda n: int(re.findall(r"\d+", n)[-1]))
        state = {"n": 0, "tbl": 0}

        def walk(el, cell):
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "tbl":
                state["tbl"] += 1
                tno = state["tbl"]
                for ch in el:
                    walk(ch, (tno, None))
                return
            if tag == "tc" and cell:
                addr = next((c for c in el if c.tag.endswith("}cellAddr")), None)
                rc = (int(addr.get("rowAddr", 0)) + 1, int(addr.get("colAddr", 0)) + 1) if addr is not None else None
                for ch in el:
                    walk(ch, (cell[0], rc))
                return
            if tag == "p":
                # 직계 run 안의 텍스트만 모아 중첩 표 문단이 중복되지 않게 한다
                parts, objs = [], []
                for run in el:
                    if not run.tag.endswith("}run"):
                        continue
                    for t in run:
                        kind = t.tag.rsplit("}", 1)[-1]
                        if kind == "t":
                            parts.append("".join(t.itertext()))
                        elif kind == "equation":
                            # 수식은 본문 글자가 아니라 개체다. 빼면 평점산식 등이 '공란'으로 보여 허위 지적이 나온다.
                            sc = next((x for x in t if x.tag.endswith("}script")), None)
                            objs.append(f"[수식: {clean(sc.text or '')}]" if sc is not None else "[수식]")
                        elif kind in ("pic", "ole"):
                            objs.append("[그림]" if kind == "pic" else "[개체]")
                txt = clean("".join(parts))
                where = f" 표{cell[0]} {cell[1][0]}-{cell[1][1]}" if cell and cell[1] else ""
                if txt:
                    state["n"] += 1
                    # 표 안 문단에는 표 번호와 행-열을 붙인다. 없으면 모델이 배점·등급을 다른 항목에 잘못 붙인다.
                    out.append(f"[문단 {state['n']}{where}] {' '.join([txt] + objs)}")
                elif objs:
                    # 글자 없는 문단은 번호를 매기지 않는다(annotate_hwpx와 번호를 맞춘다). 개체만 알린다.
                    out.append(f"[문단 {state['n']} 뒤{where}] {' '.join(objs)}")
                if objs and objects is not None:
                    location = f"[문단 {state['n']}{'' if txt else ' 뒤'}{where}]"
                    for marker in objs:
                        objects.append({
                            "id": f"object-{len(objects) + 1}",
                            "위치": location,
                            "종류": "수식" if marker.startswith("[수식") else "그림" if marker == "[그림]" else "개체",
                            "추출표시": marker,
                            "증거상태": "미판독",
                        })
            for ch in el:
                walk(ch, cell)

        for s in secs:
            walk(ET.fromstring(z.read(s)), None)
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
            if tag == 88 and len(rec) >= 6:  # HWPTAG_EQEDIT: 수식 스크립트. 직전 문단에 붙인다(빼면 '공란'으로 보인다)
                ln = struct.unpack("<H", rec[4:6])[0]
                script = clean(rec[6:6 + ln * 2].decode("utf-16-le", "ignore"))
                mark = f"[수식: {script}]"
                if out:
                    out[-1] += " " + mark
                else:
                    out.append(f"[문단 0 뒤] {mark}")
                continue
            if tag != 67:  # HWPTAG_PARA_TEXT
                continue
            chars, j = [], 0
            while j + 2 <= len(rec):
                c = struct.unpack("<H", rec[j:j + 2])[0]
                if c < 32:
                    if c in (0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31):
                        if c in (10, 30, 31):  # 줄바꿈·묶음빈칸·고정폭빈칸: 버리면 양쪽 단어가 붙는다
                            chars.append(" ")
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
            # read_only 모드의 빈 칸은 EmptyCell(좌표·행 번호 없음)이다. 값 있는 칸에서만 좌표를 읽는다.
            filled = [c for c in row if c.value not in (None, "")]
            if filled:
                out.append(f"[{ws.title}!{filled[0].row}행] " + " | ".join(f"{c.coordinate}={c.value}" for c in filled))
    wb.close()
    return out


def from_txt(path):
    with open(path, encoding="utf-8", errors="replace") as fp:
        return [f"[줄 {i}] {clean(ln)}" for i, ln in enumerate(fp, 1) if clean(ln)]


READERS = {".hwpx": from_hwpx, ".hwp": from_hwp, ".pdf": from_pdf, ".docx": from_docx,
           ".xlsx": from_xlsx, ".xlsm": from_xlsx, ".txt": from_txt, ".md": from_txt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--outdir", default="extracted")
    a = ap.parse_args()
    stems = [os.path.normcase(os.path.splitext(os.path.basename(f))[0]) for f in a.files]
    if len(set(stems)) != len(stems):
        ap.error("동명 입력은 내부 작업공간에서 서로 다른 이름으로 복사한 뒤 추출하세요.")
    os.makedirs(a.outdir, exist_ok=True)
    ok = True
    for f in a.files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in READERS:
            print(f"[건너뜀] {f}: 지원하지 않는 형식({ext}). HWPX/PDF/DOCX로 변환해 주세요.")
            ok = False
            continue
        try:
            objects = []
            lines = from_hwpx(f, objects) if ext == ".hwpx" else READERS[ext](f)
        except Exception as e:  # noqa: BLE001
            print(f"[실패] {f}: {e}")
            ok = False
            continue
        out = os.path.join(a.outdir, os.path.splitext(os.path.basename(f))[0] + ".txt")
        with open(out, "w", encoding="utf-8") as fp:
            fp.write(f"# 원본: {os.path.basename(f)}\n" + "\n".join(lines) + "\n")
        with open(os.path.splitext(out)[0] + ".objects.json", "w", encoding="utf-8") as fp:
            json.dump({"원본": os.path.basename(f), "개체목록": objects,
                       "개체조사": "완료" if ext == ".hwpx" else "미지원",
                       "주의": "수식 문자열 추출은 판독·적용 기준 확인을 대신하지 않습니다."},
                      fp, ensure_ascii=False, indent=2)
        chars = sum(len(ln) for ln in lines)
        pages = len({ln.split("]")[0] for ln in lines})
        warn = "  ※ 텍스트가 거의 없음: 스캔 PDF일 수 있습니다." if (ext == ".pdf" and chars < 200 * max(1, pages)) else ""
        print(f"[완료] {f} → {out} ({len(lines)}줄, {chars:,}자){warn}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # 하네스가 파이프로 읽어도 UTF-8로 나가게
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

