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
MEMO_FIELD_ID = str(int.from_bytes(b"%%me", "big"))
VERDICTS = ("필수수정", "수정필요", "확인필요")
HIGHLIGHT = {"필수수정": "#FFFF00", "수정필요": "#FFFF00", "확인필요": "#9FE2FF"}
MEMO_COLOR = {"필수수정": ("#FFE1E1", "#E04848", "#FFC2C2"),
              "수정필요": ("#FFF4C2", "#D9A400", "#FFE88A"),
              "확인필요": ("#E1EFFF", "#4A86D9", "#C2DCFF"),
              "요약": ("#F2F2F2", "#8C8C8C", "#E0E0E0")}
DEFAULT_SHAPE = "65535"
LABEL = {"필수수정": "필수 수정", "수정필요": "수정 필요", "확인필요": "확인 요청"}
SELF = "문서 자체 오류"
MEMO_SEP = "─" * 16
SUMMARY_LINES = 5
WS = re.compile(r"\s+")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def load_findings(paths, doc):
    every = []
    for p in paths:
        with open(p, encoding="utf-8") as fp:
            every += [f for f in json.load(fp)["findings"] if f["판정"] in VERDICTS]
    return [f for f in every if f["문서"] == doc], [f for f in every if f["문서"] != doc]


def para_hint(f):
    return [int(n) for n in re.findall(r"문단\s*(\d+)", f["위치"])]


def strip_scripts(names, read):
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
            os.remove(dest)
            raise
        return dest
    raise FileExistsError(f"빈 이름을 찾지 못했습니다: {path}")


class Para:
    def __init__(self, p):
        self.p = p
        self.runs = [r for r in p if local(r.tag) == "run"]
        self.tokens = []
        self.chars = []
        for ri, r in enumerate(self.runs):
            toks = []
            for c in r:
                if local(c.tag) == "t":
                    attrib = dict(c.attrib)
                    if c.text:
                        for ch in c.text:
                            toks.append(("char", ch, attrib))
                    for sub in c:
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
        self.idx = [i for i, ch in enumerate(self.text) if not ch.isspace()]
        self.norm = "".join(self.text[i] for i in self.idx)
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
        self.inserts = []
        self.ranges = []

    def find(self, quote):
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
        for _ in range(len(self.fields) + 1):
            moved = False
            for fs, fe in self.fields:
                a0, a1 = s + 0.4, e - 0.4
                if a0 < fs < a1 < fe:
                    e, moved = fs, True
                elif fs < a0 < fe < a1:
                    s, moved = fe, True
                if e <= s:
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
        for c in [c for c in self.p if local(c.tag).lower() == "linesegarray"]:
            self.p.remove(c)


class MemoFactory:
    def __init__(self, author, start_number, used_ids, shapes, para_pr, style, char_pr):
        self.author = author
        self.n = start_number
        self.used_ids = used_ids
        self.shapes, self.para_pr, self.style, self.char_pr = shapes, para_pr, style, char_pr
        now_utc = datetime.now(timezone.utc)
        self.created = now_utc.astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")
        ft = int((now_utc.timestamp() + 11644473600) * 10_000_000)
        self.ft_lo, self.ft_hi = ft & 0xFFFFFFFF, ft >> 32

    def renumber(self, records):
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

    def make(self, lines, kind):
        shape = self.shapes.get(kind, DEFAULT_SHAPE)
        self.n += 1
        fid = 1_900_000_000 + len(self.used_ids)
        while str(fid) in self.used_ids:
            fid += 1
        fid = str(fid)
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

    def add_lines(self, sublist, lines):
        for line in lines:
            p = ET.SubElement(sublist, HP + "p", {
                "id": "0", "paraPrIDRef": self.para_pr, "styleIDRef": self.style, "pageBreak": "0",
                "columnBreak": "0", "merged": "0"})
            run = ET.SubElement(p, HP + "run", {"charPrIDRef": self.char_pr})
            ET.SubElement(run, HP + "t").text = line


def clip(text, limit):
    text = WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def title(f):
    return WS.sub(" ", f["요약"]).strip()


def memo_lines(f):
    lines = [f"[{LABEL[f['판정']]}] {title(f)}",
             "- 문제: " + clip(f["문제점"], 80),
             ("- 확인: " if f["판정"] == "확인필요" else "- 수정: ") + clip(f["수정안"], 100)]
    basis = f["근거"].strip()
    if basis != SELF:
        first = re.split(r"\s+/\s+", basis)[0]
        lines.append(f'- 근거: "{clip(first, 60)}"')
    return lines


def summary_lines(fixes, unplaced, checks):
    n = {v: sum(1 for f, _ in fixes + unplaced if f["판정"] == v) for v in VERDICTS[:2]}
    head = "[수정할 곳] " + ", ".join(f"{LABEL[v]} {c}건" for v, c in n.items())
    if not fixes and not unplaced:
        return ["[수정할 곳] 없음" + (f", 확인 요청 {checks}건(파란 메모)" if checks else "")]
    lines = [f"- ({LABEL[f['판정']]}) {title(f)} {where} → {clip(f['수정안'], 60)}" for f, where in unplaced]
    places = {}
    for f, _ in fixes:
        places.setdefault((f["판정"], title(f)), []).append(f)
    groups = [f"- ({LABEL[v]}) {t}" + (f" ({len(fs)}곳)" if len(fs) > 1 else "") for (v, t), fs in places.items()]
    room = SUMMARY_LINES - 1 - len(lines)
    keep = len(groups) if len(groups) <= room else max(room - 1, 0)
    lines += groups[:keep]
    if keep < len(groups) and room > 0:
        rest = sum(len(fs) for fs in list(places.values())[keep:])
        lines.append(f"- 외 {rest}건: 본문 메모 참조")
    return [head] + lines


def memo_style(header):
    for tag in re.findall(r'<hh:style\b[^>]*>', header):
        if re.search(r'\bengName="Memo"', tag) or re.search(r'\bname="메모"', tag):
            got = [re.search(r'\b%s="(\d+)"' % k, tag) for k in ("id", "paraPrIDRef", "charPrIDRef")]
            if all(got):
                return tuple(g.group(1) for g in got)
    return None


def add_memo_para_pr(header, base="0"):
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
    out = header[:m_end] + p + header[m_end:]
    out = out[:m_props.start(2)] + str(int(m_props.group(2)) + 1) + out[m_props.end(2):]
    return out, new_id


def add_memo_shapes(header):
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
    style_id, char_pr, para_pr, shapes = "0", "0", "0", {}
    if "Contents/header.xml" in zin.namelist():
        hdr = zin.read("Contents/header.xml").decode("utf-8")
        style = memo_style(hdr)
        if style:
            style_id, char_pr = style[0], style[2]
        hdr, pid = add_memo_para_pr(hdr, style[1] if style else "0")
        if pid is not None:
            para_pr = pid
        hdr, shapes = add_memo_shapes(hdr)
        if pid is not None or shapes:
            changed["Contents/header.xml"] = hdr.encode("utf-8")

    sections = []
    for name in sec_names:
        raw = zin.read(name).decode("utf-8")
        for pfx, uri in re.findall(r'xmlns:(\w+)="([^"]+)"', raw):
            ET.register_namespace(pfx, uri)
        m = re.search(r"<(?!\?)[^>]+>", raw)
        prolog, root_tag = raw[:m.start()], m.group(0)
        sections.append({"name": name, "root": ET.fromstring(raw), "prolog": prolog, "root_tag": root_tag})

    paras, n = [], 0
    fields = [fb for s in sections for fb in s["root"].iter(HP + "fieldBegin")]
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

    factory = MemoFactory(a.author, max_z, {fb.get("id") for fb in fields}, shapes, para_pr, style_id, char_pr)
    anchored, unanchored = [], []
    records = []

    for f in findings:
        if re.search(r"머리말|꼬리말|각주|미주", f["위치"]):
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
        if prev:
            factory.add_lines(prev[2], ["", MEMO_SEP] + lines)
        else:
            begin, end, sl = factory.make(lines, f["판정"])
            records.append(((num, s), begin[0]))
            color = HIGHLIGHT[f["판정"]]
            P.inserts += [(s, 0, 0, ("ctrl", begin, None)), (e - 1, 1, 9, ("ctrl", end, None))]
            runs_hit = {}
            for gi in range(s, e):
                ri, _ = P.chars[gi]
                runs_hit.setdefault(ri, [gi, gi])[1] = gi
            for a0, a1 in runs_hit.values():
                P.inserts.append((a0, 0, 1, ("sub", ET.Element(HP + "markpenBegin", {"color": color}), None)))
                P.inserts.append((a1, 1, 0, ("sub", ET.Element(HP + "markpenEnd"), None)))
            P.ranges.append((s, e, sl))
        anchored.append((f, num))

    every = [f for f, _ in anchored] + unanchored + others
    count = {v: sum(1 for f in every if f["판정"] == v) for v in VERDICTS}
    fixes = sorted(((f, num) for f, num in anchored if f["판정"] != "확인필요"),
                   key=lambda x: (VERDICTS.index(x[0]["판정"]), x[1]))
    unplaced = [(f, f["위치"]) for f in unanchored] + [(f, f"{f['문서']} {f['위치']}") for f in others]
    summary = summary_lines(fixes, unplaced, count["확인필요"])
    if paras:
        P = get_para(paras[0][2])
        body = P.text.rstrip()
        k = max(1, min(len(body), 15))
        starts = [fs for fs, fe in P.fields if 0 < fs < k] + [r[0] for r in P.ranges if 0 < r[0] < k]
        if starts:
            k = min(starts)
        s0, k = P.fit(0, k)
        overlap = P.overlapping(s0, k)
        if overlap:
            first = list(overlap[2])
            for c in first:
                overlap[2].remove(c)
            factory.add_lines(overlap[2], summary + ["", MEMO_SEP])
            overlap[2].extend(first)
        else:
            begin, end, sl = factory.make(summary, "요약")
            records.append(((0, -1), begin[0]))
            P.inserts += [(s0, 0, -1, ("ctrl", begin, None)), (k - 1, 1, 10, ("ctrl", end, None))]
            P.ranges.append((s0, k, sl))
    factory.renumber(records)

    for P in para_obj.values():
        P.rebuild()

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
    for f in unanchored:
        print(f"- [요약 메모로] {f['id']} {title(f)}")
    for f, num in anchored[:20]:
        print(f"- [문단 {num}] {f['id']} {title(f)}")
    if len(anchored) > 20:
        print(f"- … {len(anchored) - 20}건 더")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

