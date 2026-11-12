#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import zipfile
import zlib
import xml.etree.ElementTree as ET


def clean(s):
    """공백·줄바꿈을 한 칸으로. 셀 안 줄바꿈이 남으면 위치 표시 없는 줄이 생겨 인용 검사가 깨진다."""
    return re.sub(r"\s+", " ", s).strip()


AREA = {"header": "머리말", "footer": "꼬리말", "footNote": "각주", "endNote": "미주"}


def from_hwpx(path):
    out = []
    with zipfile.ZipFile(path) as z:
        secs = sorted([n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                      key=lambda n: int(re.findall(r"\d+", n)[-1]))
        state = {"n": 0, "tbl": 0, "memo": 0, "area": ""}

        def walk(el, cell):
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "tbl":
                state["tbl"] += 1
                tno = state["tbl"]
                for ch in el:
                    walk(ch, (tno, None))
                return
            if tag in AREA:
                # 머리말·꼬리말·각주·미주: annotate_hwpx는 여기에 메모를 달지 않으므로 위치 표시에 밝힌다
                outer, state["area"] = state["area"], " " + AREA[tag]
                for ch in el:
                    walk(ch, cell)
                state["area"] = outer
                return
            if tag == "fieldBegin":
                # 기존 메모·누름틀 안 문단: 번호는 annotate_hwpx와 맞춰 세되 RFP 본문으로 내보내지 않는다
                state["memo"] += 1
                for ch in el:
                    walk(ch, cell)
                state["memo"] -= 1
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
                            parts.append(t.text or "")
                            for sub in t:  # 탭·줄바꿈 표시는 글자가 없다. 빼면 앞뒤 단어가 붙는다
                                parts.append(" " if sub.tag.rsplit("}", 1)[-1] in ("tab", "lineBreak", "nbSpace", "fwSpace") else "")
                                parts.append(sub.tail or "")
                        elif kind == "equation":
                            # 수식은 본문 글자가 아니라 개체다. 빼면 평점산식 등이 '공란'으로 보여 허위 지적이 나온다.
                            sc = next((x for x in t if x.tag.endswith("}script")), None)
                            objs.append(f"[수식: {clean(sc.text or '')}]" if sc is not None else "[수식]")
                        elif kind in ("pic", "ole"):
                            objs.append("[그림]" if kind == "pic" else "[개체]")
                txt = clean("".join(parts))
                where = state["area"] + (f" 표{cell[0]} {cell[1][0]}-{cell[1][1]}" if cell and cell[1] else "")
                if txt:
                    state["n"] += 1
                    # 표 안 문단에는 표 번호와 행-열을 붙인다. 없으면 모델이 배점·등급을 다른 항목에 잘못 붙인다.
                    if not state["memo"]:
                        out.append(f"[문단 {state['n']}{where}] {' '.join([txt] + objs)}")
                elif objs and not state["memo"]:
                    # 글자 없는 문단은 번호를 매기지 않는다(annotate_hwpx와 번호를 맞춘다). 개체만 알린다.
                    out.append(f"[문단 {state['n']} 뒤{where}] {' '.join(objs)}")
            for ch in el:
                walk(ch, cell)

        for s in secs:
            walk(ET.fromstring(z.read(s)), None)
    return out


class MiniCFB:
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
        while s < len(self.fat) and s not in seen:  # 끝 표시(0xFFFFFFFE 등)는 FAT 길이보다 크다
            seen.add(s)
            out.append(self.sector(s))
            s = self.fat[s]
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


def from_hwp(path):
    ole = MiniCFB(path)
    header = ole.read("FileHeader")
    flags = struct.unpack("<I", header[36:40])[0]
    compressed, encrypted, distributed = flags & 1, flags & 2, flags & 4
    if encrypted or distributed:
        raise RuntimeError("암호 또는 배포용 HWP 문서입니다. 한/글에서 HWPX로 저장해 주세요.")
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
                if 0xD800 <= c <= 0xDBFF and j + 4 <= len(rec):
                    c2 = struct.unpack("<H", rec[j + 2:j + 4])[0]
                    if 0xDC00 <= c2 <= 0xDFFF:
                        chars.append(chr(0x10000 + ((c - 0xD800) << 10) + (c2 - 0xDC00)))
                        j += 4
                        continue
                if 0xD800 <= c <= 0xDFFF:
                    j += 2
                    continue
                chars.append(chr(c))
                j += 2
            txt = clean("".join(chars))
            if txt:
                n += 1
                out.append(f"[문단 {n}] {txt}")
    return out


def from_pdf(path):
    try:
        import pdfplumber  # 표·줄 순서를 더 잘 지킨다
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except ImportError:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("PDF를 읽으려면 `pip install pypdf`가 필요합니다. "
                               "아니면 원본(HWPX·DOCX·XLSX)이나 텍스트(.txt)를 받으세요.") from e
        pages = [page.extract_text() or "" for page in PdfReader(path).pages]
    return [f"[p.{n}] {clean(ln)}" for n, text in enumerate(pages, 1) for ln in text.splitlines() if clean(ln)]


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


X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def from_xlsx(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            # 서식이 섞인 글자(r/t)도 합친다. 읽기 표시(rPh)는 본문이 아니므로 뺀다.
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(X + "si"):
                ts = si.findall(X + "t") + si.findall(f"{X}r/{X}t")
                shared.append("".join(t.text or "" for t in ts))
        rels = {r.get("Id"): r.get("Target") for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PKG + "Relationship")}
        out = []
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(X + "sheet"):
            target = rels[sheet.get(REL)].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            for row in ET.fromstring(z.read(target)).iter(X + "row"):
                cells = []
                for c in row.iter(X + "c"):
                    kind, v, f = c.get("t"), c.find(X + "v"), c.find(X + "f")
                    if kind == "inlineStr":
                        text = "".join(t.text or "" for t in c.findall(f"{X}is/{X}t") + c.findall(f"{X}is/{X}r/{X}t"))
                    elif v is None:
                        # 계산값이 저장되지 않은 수식은 빈 칸이 아니다. 수식을 그대로 보여 준다.
                        text = f"={f.text}(계산값 없음)" if f is not None and f.text else ""
                    elif kind == "s":
                        text = shared[int(v.text)]
                    elif kind == "b":
                        text = "TRUE" if v.text == "1" else "FALSE"
                    else:
                        text = v.text or ""
                    if clean(text):
                        cells.append(f"{c.get('r')}={clean(text)}")
                if cells:
                    out.append(f"[{sheet.get('name')}!{row.get('r')}행] " + " | ".join(cells))
    return out


def from_txt(path):
    with open(path, encoding="utf-8", errors="replace") as fp:
        return [f"[줄 {i}] {clean(ln)}" for i, ln in enumerate(fp, 1) if clean(ln)]


READERS = {".hwpx": from_hwpx, ".hwp": from_hwp, ".pdf": from_pdf, ".docx": from_docx,
           ".xlsx": from_xlsx, ".xlsm": from_xlsx, ".txt": from_txt, ".md": from_txt}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for block in iter(lambda: fp.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_sources(outdir):
    """_sources.json의 원본이 그대로인지. 바뀌었거나 없으면 1."""
    path = os.path.join(outdir, "_sources.json")
    if not os.path.isfile(path):
        print(f"[재시작] {path} 없음 — 처음부터 추출하세요.")
        return 1
    with open(path, encoding="utf-8") as fp:
        sources = json.load(fp)
    stale = [s for s in sources.values()
             if not os.path.isfile(s["원본"]) or sha256(s["원본"]) != s["sha256"]]
    for s in stale:
        print(f"[바뀜] {s['원본']}")
    if stale:
        print("[재시작] 입력이 바뀌었습니다. 이전 추출·메모·판정을 쓰지 말고 새로 검토하세요.")
        return 1
    print(f"[이어서] 원본 {len(sources)}개 모두 추출 때와 같습니다.")
    return 0


def clean_work(outdir):
    """작업 폴더(<output>/.rfp-review/<stem>)를 지운다. 에이전트 하네스가 rm -rf를 막아도 지울 수 있게 한다.
    .rfp-review 바로 아래 폴더가 아니면 지우지 않는다(사용자 폴더 보호)."""
    work = os.path.dirname(os.path.abspath(outdir))
    root = os.path.dirname(work)
    if os.path.basename(root) != ".rfp-review":
        print(f"[중단] 작업 폴더(.rfp-review/<이름>)가 아닙니다: {work}")
        return 2
    if os.path.isdir(work):
        shutil.rmtree(work)
    if os.path.isdir(root) and not os.listdir(root):
        os.rmdir(root)
    print(f"[삭제] {work}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("-o", "--outdir", default="extracted")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="원본이 추출 때와 같은지만 확인")
    mode.add_argument("--clean", action="store_true", help="-o 위의 작업 폴더를 지움")
    a = ap.parse_args()
    if a.check:
        return check_sources(a.outdir)
    if a.clean:
        return clean_work(a.outdir)
    if not a.files:
        ap.error("추출할 파일을 주세요.")
    stems = [os.path.normcase(os.path.splitext(os.path.basename(f))[0]) for f in a.files]
    if len(set(stems)) != len(stems):
        ap.error("파일 이름(확장자 제외)이 같은 입력이 있습니다. 따로 추출하거나 작업 폴더에 다른 이름으로 복사하세요.")
    os.makedirs(a.outdir, exist_ok=True)
    manifest = os.path.join(a.outdir, "_sources.json")
    sources = {}
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as fp:
            sources = json.load(fp)
    ok = True
    for f in a.files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in READERS:
            print(f"[건너뜀] {f}: 지원하지 않는 형식({ext}). HWPX·DOCX·XLSX·PDF·TXT로 주세요.")
            ok = False
            continue
        try:
            lines = READERS[ext](f)
        except Exception as e:
            print(f"[실패] {f}: {e}")
            ok = False
            continue
        name = os.path.splitext(os.path.basename(f))[0] + ".txt"
        out = os.path.join(a.outdir, name)
        with open(out, "w", encoding="utf-8") as fp:
            fp.write(f"# 원본: {os.path.basename(f)}\n" + "\n".join(lines) + "\n")
        sources[name] = {"원본": os.path.abspath(f), "sha256": sha256(f)}
        chars = sum(len(ln) for ln in lines)
        pages = len({ln.split("]")[0] for ln in lines})
        warn = "  ※ 글자가 거의 없음: 스캔 PDF일 수 있습니다." if ext == ".pdf" and chars < 200 * max(1, pages) else ""
        if not lines:
            warn = "  ※ 읽은 내용이 없습니다. 빈 문서로 보고 검토하지 마세요."
            ok = False
        print(f"[완료] {f} → {out} ({len(lines)}줄, {chars:,}자){warn}")
    with open(manifest, "w", encoding="utf-8") as fp:
        json.dump(sources, fp, ensure_ascii=False, indent=2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # 하네스가 파이프로 읽어도 UTF-8로 나가게
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

