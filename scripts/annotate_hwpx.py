#!/usr/bin/env python3
import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HP = "{%s}" % HP_NS
MEMO_FIELD_ID = str(int.from_bytes(b"%%me", "big"))  # 한/글이 메모 필드에 쓰는 값
VERDICTS = ("필수수정", "수정필요", "확인필요")  # 위급한 순서. 메모를 다는 순서로 쓴다
# 형광펜: 고칠 곳은 노랑, 확인할 곳은 하늘. 위급한 정도는 메모 풍선 색으로 나눈다
HIGHLIGHT = {"필수수정": "#FFFF00", "수정필요": "#FFFF00", "확인필요": "#9FE2FF"}
# (배경, 테두리, 선택했을 때 배경)
MEMO_COLOR = {"필수수정": ("#FFE1E1", "#E04848", "#FFC2C2"),
              "수정필요": ("#FFF4C2", "#D9A400", "#FFE88A"),
              "확인필요": ("#E1EFFF", "#4A86D9", "#C2DCFF"),
              "요약": ("#F2F2F2", "#8C8C8C", "#E0E0E0")}
DEFAULT_SHAPE = "65535"  # 한/글 기본 메모 모양
LABEL = {"필수수정": "필수 수정", "수정필요": "수정 필요", "확인필요": "확인 요청"}
SELF = "문서 자체 오류"
MEMO_SEP = "─" * 16
WS = re.compile(r"\s+")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def load_findings(paths, doc):
    """(이 문서의 지적, 다른 문서의 지적). 다른 문서는 메모를 달 HWPX가 없으므로 요약 메모에 싣는다."""
    every = []
    for p in paths:
        with open(p, encoding="utf-8") as fp:
            every += [f for f in json.load(fp)["findings"] if f["판정"] in VERDICTS]
    return [f for f in every if f["문서"] == doc], [f for f in every if f["문서"] != doc]


def para_hint(f):
    """위치의 [문단 n] 번호들. 같은 인용이 여러 문단에 있을 때 이 문단을 먼저 찾는다."""
    return [int(n) for n in re.findall(r"문단\s*(\d+)", f["위치"])]


def strip_scripts(names, read):
    """문서 스크립트와 content.hpf의 item·itemref를 뺀다. 스크립트가 있으면 한/글이 메모 단 파일을 '손상' 경고로 막는다.
    (뺄 파일, {이름: 바뀐 바이트})"""
    scripts = {n for n in names if n.startswith("Scripts/") and not n.endswith("/")}
    hpf_name = "Contents/content.hpf"
    if not scripts or hpf_name not in names:
        return scripts, {}
    hpf = read(hpf_name).decode("utf-8")
    item = r"""<(?:\w+:)?item\b[^>]*\bhref=["']Scripts/[^"']+["'][^>]*/>"""
    for tag in re.findall(item, hpf):
        rid = re.search(r"""\bid=["']([^"']+)["']""", tag)
        if rid:
            ref = r"""<(?:\w+:)?itemref\b[^>]*\bidref=["']%s["'][^>]*/>""" % re.escape(rid.group(1))
            hpf = re.sub(ref, "", hpf)
    return scripts, {hpf_name: re.sub(item, "", hpf).encode("utf-8")}


def publish(data, path):
    """덮어쓰지 않고 path, path_2, path_3… 중 빈 이름에 쓴다. 실제 경로를 돌려준다."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    for n in range(1, 1000):
        dest = os.path.join(folder, f"{stem}_{n}{ext}" if n > 1 else stem + ext)
        try:
            fp = open(dest, "xb")
        except FileExistsError:
            continue
        try:
            with fp:
                fp.write(data)
        except BaseException:
            os.remove(dest)  # 쓰다 실패한 반쪽 파일을 결과로 남기지 않는다
            raise
        return dest
    raise FileExistsError(f"빈 이름을 찾지 못했습니다: {path}")


class Para:
    """문단의 직계 run들을 (char | sub | ctrl) 토큰 열로 펼친다."""

    def __init__(self, p):
        self.p = p
        self.runs = [r for r in p if local(r.tag) == "run"]
        self.tokens = []
        self.chars = []   # 전역 문자 → (run idx, token idx)
        for ri, r in enumerate(self.runs):
            toks = []
            for c in r:
                if local(c.tag) == "t":
                    attrib = dict(c.attrib)
                    if c.text:
                        for ch in c.text:
                            toks.append(("char", ch, attrib))
                    for sub in c:  # 하위 요소 뒤 글자(tail)는 토큰으로만 옮긴다. 트리는 rebuild()에서만 바꾼다
                        toks.append(("sub", sub, attrib))
                        for ch in sub.tail or "":
                            toks.append(("char", ch, attrib))
                else:
                    toks.append(("ctrl", c, None))
            for ti, t in enumerate(toks):
                if t[0] == "char":
                    self.chars.append((ri, ti))
            self.tokens.append(toks)
        self.text = "".join(self.tokens[ri][ti][1] for ri, ti in self.chars)
        # 공백을 뺀 글자와 원래 위치: 지적마다 여러 문단을 찾으므로 한 번만 만든다
        self.idx = [i for i, ch in enumerate(self.text) if not ch.isspace()]
        self.norm = "".join(self.text[i] for i in self.idx)
        # 기존 필드(메모·누름틀 등)의 문자 범위: 새 메모가 이 범위와 엇갈리지 않게 한다
        self.fields, opened, pos = [], {}, 0
        for toks in self.tokens:
            for kind, val, _ in toks:
                if kind == "char":
                    pos += 1
                elif kind == "ctrl":
                    for x in val:
                        if local(x.tag) == "fieldBegin":
                            opened[x.get("id")] = pos
                        elif local(x.tag) == "fieldEnd" and x.get("beginIDRef") in opened:
                            self.fields.append((opened.pop(x.get("beginIDRef")), pos))
        self.inserts = []  # (char pos, 0=before/1=after, order, token)
        self.ranges = []   # 이미 메모를 단 (s, e, memo paragraphs list)

    def find(self, quote):
        """공백 무시 매칭. '…'로 생략된 인용은 앞부분~뒷부분 범위. (s, e) 문자 범위.
        생략 뒤 부분 중 하나라도 못 찾으면 None(다른 문단에서 완전히 맞는 자리를 계속 찾는다)."""
        norm, idx = self.norm, self.idx
        parts = [WS.sub("", x) for x in re.split(r"…|\.{3,}", quote)]
        parts = [x for x in parts if x]
        if not parts or not norm:
            return None
        a = norm.find(parts[0])
        if a < 0:
            return None
        b = a + len(parts[0])
        for part in parts[1:]:
            k = norm.find(part, b)
            if k < 0:
                return None
            b = k + len(part)
        return idx[a], idx[b - 1] + 1

    def fit(self, s, e):
        """기존 필드와 범위가 엇갈리지 않게 줄인다.

        같은 문자 사이(gap)에서는 [새 메모 끝] < [기존 필드 ctrl] < [새 메모 시작] 순서로 들어가므로
        새 메모의 시작을 s+0.4, 끝을 e-0.4로 보고 구간이 한쪽만 겹치는지 판단한다.
        """
        for _ in range(len(self.fields) + 1):
            moved = False
            for fs, fe in self.fields:
                a0, a1 = s + 0.4, e - 0.4
                if a0 < fs < a1 < fe:      # 필드 시작이 새 범위 안 → 필드 앞에서 끝낸다
                    e, moved = fs, True
                elif fs < a0 < fe < a1:    # 필드 끝이 새 범위 안 → 필드 뒤에서 시작한다
                    s, moved = fe, True
                if e <= s:                  # 줄이다 비면 필드 안쪽에 같은 경계로 넣는다(중첩)
                    return (fs, fe) if fe > fs else (s, s + 1)
            if not moved:
                break
        return s, e

    def overlapping(self, s, e):
        for r in self.ranges:
            if s < r[1] and r[0] < e:
                return r
        return None

    def rebuild(self):
        if not self.inserts:
            return
        by_pos = {}
        for pos, side, order, tok in self.inserts:
            by_pos.setdefault((pos, side), []).append((order, tok))
        g = 0
        for ri, r in enumerate(self.runs):
            new = []
            for tok in self.tokens[ri]:
                if tok[0] == "char":
                    # 끼워 넣는 하위 요소(형광펜)는 옆 글자의 글자 속성을 따른다
                    for _, t in sorted(by_pos.get((g, 0), []), key=lambda x: x[0]):
                        new.append(t if t[0] == "ctrl" else (t[0], t[1], tok[2]))
                    new.append(tok)
                    for _, t in sorted(by_pos.get((g, 1), []), key=lambda x: x[0]):
                        new.append(t if t[0] == "ctrl" else (t[0], t[1], tok[2]))
                    g += 1
                else:
                    new.append(tok)
            tail = r.tail
            attrib = dict(r.attrib)
            r.clear()
            r.attrib.update(attrib)
            r.tail = tail
            cur, cur_attr, last_sub = None, None, None
            for kind, val, attr in new:
                if kind == "ctrl":
                    r.append(val)
                    cur = None
                    continue
                if cur is None or attr != cur_attr:
                    cur = ET.SubElement(r, HP + "t", attr or {})
                    cur_attr, last_sub = attr, None
                if kind == "char":
                    if last_sub is None:
                        cur.text = (cur.text or "") + val
                    else:
                        last_sub.tail = (last_sub.tail or "") + val
                else:
                    val.tail = None
                    cur.append(val)
                    last_sub = val
        # 레이아웃 캐시 제거: 한/글이 열 때 다시 계산한다
        for c in [c for c in self.p if local(c.tag).lower() == "linesegarray"]:
            self.p.remove(c)


class MemoFactory:
    def __init__(self, author, start_number):
        self.author = author
        self.n = start_number
        now_utc = datetime.now(timezone.utc)
        # 한/글 파일: CreateDateTime은 현지 시각 + 'Z', Command의 FILETIME은 UTC
        self.created = now_utc.astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")
        ft = int((now_utc.timestamp() + 11644473600) * 10_000_000)
        self.ft_lo, self.ft_hi = ft & 0xFFFFFFFF, ft >> 32
        self.seq = 0
        self.used_ids = set()

    def renumber(self, records):
        """메모 번호를 문서 순서(문단 번호, 시작 위치)대로 다시 매긴다. records: [(정렬키, fieldBegin)]"""
        base = self.n - len(records)
        for i, (_, fb) in enumerate(sorted(records, key=lambda r: r[0]), 1):
            num = base + i
            fb.set("zorder", str(num))
            for prm in fb.find(HP + "parameters"):
                name = prm.get("name")
                if name == "Number":
                    prm.text = str(num)
                elif name == "ID":
                    prm.text = f"rfpreview{num}"
                elif name == "Command":
                    shape = prm.text.split("/")[1]
                    prm.text = f"MEMO/{shape}/{num}/{self.ft_lo}/{self.ft_hi}//\\;;"

    SHAPE = {}  # 판정 → memoPr id. annotate()에서 header.xml에 추가한 뒤 채운다

    def make(self, lines, kind):
        shape = self.SHAPE.get(kind, DEFAULT_SHAPE)
        self.n += 1
        while True:  # 문서에 이미 있는 필드 id와 겹치면 fieldEnd가 엉뚱한 필드를 닫는다
            self.seq += 1
            fid = str(1_900_000_000 + self.seq * 7919 % 99_999_999)
            if fid not in self.used_ids:
                break
        self.used_ids.add(fid)
        begin_ctrl = ET.Element(HP + "ctrl")
        fb = ET.SubElement(begin_ctrl, HP + "fieldBegin", {
            "id": fid, "type": "MEMO", "name": "", "editable": "1", "dirty": "0",
            "zorder": str(self.n), "fieldid": MEMO_FIELD_ID, "metaTag": ""})
        ps = ET.SubElement(fb, HP + "parameters", {"cnt": "7", "name": ""})
        ET.SubElement(ps, HP + "integerParam", {"name": "Prop"}).text = "0"
        ET.SubElement(ps, HP + "stringParam", {"name": "Command"}).text = \
            f"MEMO/{shape}/{self.n}/{self.ft_lo}/{self.ft_hi}//\\;;"
        ET.SubElement(ps, HP + "stringParam", {"name": "ID"}).text = f"rfpreview{self.n}"
        ET.SubElement(ps, HP + "integerParam", {"name": "Number"}).text = str(self.n)
        ET.SubElement(ps, HP + "stringParam", {"name": "Author"}).text = self.author
        ET.SubElement(ps, HP + "stringParam", {"name": "MemoShapeIDRef"}).text = shape
        ET.SubElement(ps, HP + "stringParam", {"name": "CreateDateTime"}).text = self.created
        sl = ET.SubElement(fb, HP + "subList", {
            "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "TOP",
            "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
            "hasTextRef": "0", "hasNumRef": "0"})
        self.add_lines(sl, lines)
        end_ctrl = ET.Element(HP + "ctrl")
        ET.SubElement(end_ctrl, HP + "fieldEnd", {"beginIDRef": fid, "fieldid": MEMO_FIELD_ID})
        return begin_ctrl, end_ctrl, sl

    PARA_PR = "0"  # 메모 문단 모양(왼쪽 정렬). annotate()에서 header.xml에 추가한 id로 바꾼다
    STYLE, CHAR_PR = "0", "0"  # 문서에 '메모' 스타일이 있으면 그 스타일·글자 모양

    @staticmethod
    def add_lines(sublist, lines):
        for line in lines:
            p = ET.SubElement(sublist, HP + "p", {
                "id": "0", "paraPrIDRef": MemoFactory.PARA_PR, "styleIDRef": MemoFactory.STYLE, "pageBreak": "0",
                "columnBreak": "0", "merged": "0"})
            run = ET.SubElement(p, HP + "run", {"charPrIDRef": MemoFactory.CHAR_PR})
            ET.SubElement(run, HP + "t").text = line


def bullets(text, limit):
    """문장·줄 단위로 끊어 개조식 항목으로(최대 limit개)."""
    out = []
    for line in text.splitlines():
        # '있습니다. ' 같은 문장 끝에서만 끊는다. '다. 성능 요구사항' 같은 항목 기호는 끊지 않는다
        for s in re.split(r"(?<=[가-힣][다요음함])\.\s+", line.strip()):
            s = s.strip().rstrip(".").strip()
            if s:
                out.append(re.sub(r"^[-·•]\s*", "", s))
    return out[:limit]


def clip(text, limit):
    text = WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def title(f):
    return WS.sub(" ", f["요약"]).strip()


def memo_lines(f):
    """짧은 메모: 제목 + 문제·수정·근거 각 한 줄. 지적한 문구는 형광펜으로 보이므로 다시 싣지 않는다."""
    lines = [f"[{LABEL[f['판정']]}] {title(f)}"]
    probs = [s for s in bullets(f["문제점"], 2) if WS.sub("", s) != WS.sub("", title(f))]
    if probs:
        lines.append("문제: " + clip(" ".join(probs), 80))
    lines.append(("확인: " if f["판정"] == "확인필요" else "수정: ") + clip(" ".join(bullets(f["수정안"], 3)), 100))
    basis = f["근거"].strip()
    first = re.split(r"\s+/\s+", basis)[0]
    lines.append("근거: " + ("문서 내용 대조" if basis == SELF else f'"{clip(first, 60)}"'))
    return lines


def memo_style(header):
    """문서의 '메모' 스타일(한/글이 메모 글자에 쓰는 9pt 모양). (스타일 id, paraPr id, charPr id) 또는 None.
    본문 글자(charPr 0)는 보통 10pt 이상이라 풍선이 커져 잘린다."""
    for tag in re.findall(r'<hh:style\b[^>]*>', header):
        if re.search(r'\bengName="Memo"', tag) or re.search(r'\bname="메모"', tag):
            got = [re.search(r'\b%s="(\d+)"' % k, tag) for k in ("id", "paraPrIDRef", "charPrIDRef")]
            if all(got):
                return tuple(g.group(1) for g in got)
    return None


def add_memo_para_pr(header, base="0"):
    """paraPr id=base를 복제해 왼쪽 정렬·줄간격 130%·어절 단위 줄바꿈으로 바꾼 문단 모양을 추가한다.
    header 텍스트를 직접 고쳐 나머지 부분은 바이트 그대로 둔다. 실패하면 (원문, None)."""
    m_props = re.search(r'(<hh:paraProperties\b[^>]*\bitemCnt=")(\d+)("[^>]*>)', header)
    m_p0 = re.search(r'<hh:paraPr id="%s"[\s\S]*?</hh:paraPr>' % base, header)
    m_end = header.find("</hh:paraProperties>")
    if not (m_props and m_p0 and m_end > 0):
        return header, None
    ids = [int(x) for x in re.findall(r'<hh:paraPr id="(\d+)"', header)]
    new_id = str(max(ids) + 1)
    p = m_p0.group(0).replace(f'<hh:paraPr id="{base}"', f'<hh:paraPr id="{new_id}"', 1)
    p = re.sub(r'(<hh:align\b[^>]*\bhorizontal=")\w+', r"\g<1>LEFT", p, count=1)
    p = re.sub(r'(<hh:lineSpacing type="PERCENT" value=")\d+', r"\g<1>130", p)
    p = p.replace('breakNonLatinWord="BREAK_WORD"', 'breakNonLatinWord="KEEP_WORD"')
    out = header[:m_end] + p + header[m_end:]  # m_end가 itemCnt보다 뒤라 m_props 위치는 그대로다
    out = out[:m_props.start(2)] + str(int(m_props.group(2)) + 1) + out[m_props.end(2):]
    return out, new_id


def add_memo_shapes(header):
    """중요도별 메모 모양(hh:memoPr)을 header의 hh:memoProperties에 더한다(없으면 refList 끝에 만든다).
    header 텍스트를 직접 고쳐 나머지는 바이트 그대로 둔다. (새 header, {판정: id}) 또는 (원문, {})."""
    ref_end = header.find("</hh:refList>")
    if ref_end < 0:
        return header, {}
    ids = [int(x) for x in re.findall(r'<hh:memoPr\b[^>]*\bid="(\d+)"', header)]
    start = max(ids) + 1 if ids else 0
    shapes, items = {}, ""
    for i, (kind, (fill, line, active)) in enumerate(MEMO_COLOR.items()):
        shapes[kind] = str(start + i)
        items += (f'<hh:memoPr id="{start + i}" width="15591" lineWidth="0.6mm" lineType="SOLID" '
                  f'lineColor="{line}" fillColor="{fill}" activeColor="{active}" memoType="NOMAL"/>')
    m = re.search(r'(<hh:memoProperties\b[^>]*\bitemCnt=")(\d+)("[^>]*>)', header)
    if m:
        end = header.index("</hh:memoProperties>", m.end())
        out = header[:end] + items + header[end:]
        return out[:m.start(2)] + str(int(m.group(2)) + len(MEMO_COLOR)) + out[m.end(2):], shapes
    block = f'<hh:memoProperties itemCnt="{len(MEMO_COLOR)}">{items}</hh:memoProperties>'
    return header[:ref_end] + block + header[ref_end:], shapes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("findings", nargs="+")
    ap.add_argument("--doc", required=True, help="이 파일에 해당하는 findings의 '문서' 값")
    ap.add_argument("-o", "--out", required=True, help="출력 경로. 이미 있으면 _2, _3…을 붙인다")
    ap.add_argument("--author", default="RFP 검토")
    a = ap.parse_args()
    if not a.hwpx.lower().endswith(".hwpx"):
        print("[중단] HWPX 파일만 메모를 달 수 있습니다. .hwp는 hancom.py convert로 먼저 변환하세요.")
        return 2
    findings, others = load_findings(a.findings, a.doc)
    # 같은 범위에 지적이 겹치면 먼저 단 지적의 색이 남는다: 위급한 것부터 단다
    findings.sort(key=lambda f: VERDICTS.index(f["판정"]))
    if others and not findings:
        print(f"[중단] --doc '{a.doc}'의 지적이 없습니다. findings의 문서 값: {', '.join(sorted({f['문서'] for f in others}))}")
        return 2
    try:
        zin = zipfile.ZipFile(a.hwpx)
    except (OSError, zipfile.BadZipFile) as e:
        print(f"[중단] HWPX를 열지 못했습니다: {a.hwpx} ({e})")
        return 2
    with zin:
        return annotate(a, findings, others, zin)


def annotate(a, findings, others, zin):
    sec_names = sorted([n for n in zin.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
    if not sec_names:
        print("[중단] HWPX 본문(Contents/section*.xml)을 찾지 못했습니다.")
        return 2

    changed = {}
    if "Contents/header.xml" in zin.namelist():
        hdr = zin.read("Contents/header.xml").decode("utf-8")
        style = memo_style(hdr)
        if style:
            MemoFactory.STYLE, MemoFactory.CHAR_PR = style[0], style[2]
        hdr, pid = add_memo_para_pr(hdr, style[1] if style else "0")
        if pid is not None:
            MemoFactory.PARA_PR = pid
        hdr, shapes = add_memo_shapes(hdr)
        if shapes:
            MemoFactory.SHAPE = shapes
        if pid is not None or shapes:
            changed["Contents/header.xml"] = hdr.encode("utf-8")

    # 섹션 파싱 (네임스페이스 접두어와 루트 선언을 보존한다)
    sections = []
    for name in sec_names:
        raw = zin.read(name).decode("utf-8")
        for pfx, uri in re.findall(r'xmlns:(\w+)="([^"]+)"', raw):
            ET.register_namespace(pfx, uri)
        m = re.search(r"<(?!\?)[^>]+>", raw)
        prolog, root_tag = raw[:m.start()], m.group(0)
        sections.append({"name": name, "root": ET.fromstring(raw), "prolog": prolog, "root_tag": root_tag})

    # extract_text.py와 같은 순서로 문단 번호를 매긴다
    paras, n = [], 0
    fields = [fb for s in sections for fb in s["root"].iter(HP + "fieldBegin")]
    # 기존 메모·머리말·꼬리말·각주 안 문단: 번호는 매기되 메모는 달지 않는다
    nested = fields + [el for s in sections for el in s["root"].iter()
                       if local(el.tag) in ("header", "footer", "footNote", "endNote")]
    in_memo = {id(q) for el in nested for q in el.iter(HP + "p")}
    max_z = max([int(fb.get("zorder")) for fb in fields
                 if fb.get("type") == "MEMO" and (fb.get("zorder") or "").isdigit()] or [0])
    for s in sections:
        for el in s["root"].iter():
            if local(el.tag) != "p":
                continue
            txt = "".join("".join(t.itertext()) for run in el if local(run.tag) == "run"
                          for t in run if local(t.tag) == "t")
            if WS.sub(" ", txt).strip():
                n += 1
                if id(el) not in in_memo:
                    paras.append((n, s, el))
    para_obj = {}

    def get_para(el):
        if id(el) not in para_obj:
            para_obj[id(el)] = Para(el)
        return para_obj[id(el)]

    factory = MemoFactory(a.author, max_z)
    factory.used_ids = {fb.get("id") for fb in fields}
    anchored, unanchored = [], []
    records = []  # 번호 재정렬용 (문서 위치, fieldBegin)

    for f in findings:
        if re.search(r"머리말|꼬리말|각주|미주", f["위치"]):  # 메모를 달 수 없는 영역: 본문의 같은 문구에 잘못 달지 않는다
            unanchored.append(f)
            continue
        hints = para_hint(f)
        order = [x for x in paras if x[0] in hints] + [x for x in paras if x[0] not in hints]
        hit = None
        for num, _, el in order:
            P = get_para(el)
            rng = P.find(f["원문"])
            if rng:
                hit = (num, P, rng)
                break
        if hit is None:
            unanchored.append(f)
            continue
        num, P, (s, e) = hit
        s, e = P.fit(s, e)
        lines = memo_lines(f)
        prev = P.overlapping(s, e)
        if prev:  # 같은 범위에 이미 메모가 있으면 내용을 이어 붙인다
            MemoFactory.add_lines(prev[2], ["", MEMO_SEP] + lines)
        else:
            begin, end, sl = factory.make(lines, f["판정"])
            records.append(((num, s), begin[0]))
            color = HIGHLIGHT[f["판정"]]
            P.inserts += [(s, 0, 0, ("ctrl", begin, None)), (e - 1, 1, 9, ("ctrl", end, None))]
            # 형광펜: run마다 따로 열고 닫는다
            runs_hit = {}
            for gi in range(s, e):
                ri, _ = P.chars[gi]
                runs_hit.setdefault(ri, [gi, gi])[1] = gi
            for a0, a1 in runs_hit.values():
                P.inserts.append((a0, 0, 1, ("sub", ET.Element(HP + "markpenBegin", {"color": color}), None)))
                P.inserts.append((a1, 1, 0, ("sub", ET.Element(HP + "markpenEnd"), None)))
            P.ranges.append((s, e, sl))
        anchored.append((f, num))

    # 검토 요약 메모: 첫 문단 앞부분에 단다
    every = [f for f, _ in anchored] + unanchored + others
    count = {v: sum(1 for f in every if f["판정"] == v) for v in VERDICTS}
    head = ", ".join(f"{LABEL[v]} {n}건" for v, n in count.items() if n) or "지적 0건"
    head += "입니다."
    if len(every) > len(anchored):
        head += f" 이 중 {len(every) - len(anchored)}건은 본문 위치에 표시하지 않고 아래에 따로 적었습니다."
    # 요약 메모는 짧게 둔다. 길면 한/글이 풍선을 잘라 보여 준다. 본문에 단 지적은 각 메모에 있으므로
    # 제목을 다시 나열하지 않고, 본문에 못 단 지적과 다른 문서의 지적만 싣는다.
    summary = ["[검토 요약] AI 1차 검토입니다. 최종 판단은 담당자가 합니다.", head,
               "노란 형광펜은 고친 뒤, 하늘색은 확인해 메모에 답한 뒤 메모를 지워 주세요."]
    if unanchored:
        summary += ["", f"■ 본문에 표시하지 못한 지적 {len(unanchored)}건"]
        for f in unanchored:
            lines = memo_lines(f)
            summary += [f" ({f['위치']}) {lines[0]}"] + [" " + x for x in lines[1:]]
    if others:
        summary += ["", f"■ 다른 문서의 지적 {len(others)}건 (해당 문서에서 고쳐 주세요)"]
        for f in others:
            lines = memo_lines(f)
            summary += [f" ({f['문서']} {f['위치']}) {lines[0]}"] + [" " + x for x in lines[1:]]
    if paras:
        P = get_para(paras[0][2])
        body = P.text.rstrip()
        k = max(1, min(len(body), 15))
        starts = [fs for fs, fe in P.fields if 0 < fs < k] + [r[0] for r in P.ranges if 0 < r[0] < k]
        if starts:
            k = min(starts)
        s0, k = P.fit(0, k)
        overlap = P.overlapping(s0, k)
        if overlap:  # 첫 글자부터 지적 메모가 있으면 그 메모 앞쪽에 요약을 넣는다
            first = list(overlap[2])
            for c in first:
                overlap[2].remove(c)
            MemoFactory.add_lines(overlap[2], summary + ["", MEMO_SEP])
            for c in first:
                overlap[2].append(c)
        else:
            begin, end, sl = factory.make(summary, "요약")
            records.append(((0, -1), begin[0]))
            P.inserts += [(s0, 0, -1, ("ctrl", begin, None)), (k - 1, 1, 10, ("ctrl", end, None))]
            P.ranges.append((s0, k, sl))
    factory.renumber(records)

    for P in para_obj.values():
        P.rebuild()

    # 섹션은 다시 직렬화하고, 나머지 엔트리는 원본 순서·압축방식 그대로 복사한다
    for s in sections:
        body = ET.tostring(s["root"], encoding="unicode")
        body = s["root_tag"] + body[body.index(">") + 1:]
        changed[s["name"]] = (s["prolog"] + body).encode("utf-8")
    scripts, hpf = strip_scripts(zin.namelist(), zin.read)
    changed.update(hpf)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            if info.filename in scripts:
                continue
            data = changed.get(info.filename, zin.read(info.filename))
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    try:
        out = publish(buf.getvalue(), a.out)
    except OSError as e:
        print(f"[중단] 결과 파일을 저장하지 못했습니다: {a.out} ({e})")
        return 2

    print(f"저장: {out}")
    print(f"메모 {len(anchored)}건 + 요약 메모 1건 (본문 표시 못 함 {len(unanchored)}건, 다른 문서 {len(others)}건)")
    print("합계: " + ", ".join(f"{v} {n}건" for v, n in count.items()))
    if scripts:
        print(f"문서 스크립트 {len(scripts)}개를 검토본에서 뺐습니다.")
    # 위치를 못 찾은 것을 먼저, 정상 메모는 20건까지만(하네스 출력 잘림 방지)
    for f in unanchored:
        print(f"- [요약 메모로] {f['id']} {title(f)}")
    for f, num in anchored[:20]:
        print(f"- [문단 {num}] {f['id']} {title(f)}")
    if len(anchored) > 20:
        print(f"- … {len(anchored) - 20}건 더")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # 하네스가 파이프로 읽어도 UTF-8로 나가게
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

