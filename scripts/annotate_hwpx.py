#!/usr/bin/env python3
"""검토 결과를 원본 HWPX 문서에 한글 '메모'와 형광펜으로 단다.

- 지적한 원문 위치에 형광펜을 칠하고, 그 범위에 메모(문제·수정안·근거)를 단다.
- 위치를 못 찾은 지적과 전체 요약은 문서 첫 문단에 요약 메모로 단다.
- 원본은 건드리지 않고 새 파일로 저장한다. 같은 이름이 있으면 _2, _3…을 붙인다(덮어쓰지 않음).

메모 구조는 한/글이 저장한 파일과 같다: 본문 run 안의
  <hp:ctrl><hp:fieldBegin type="MEMO" ...><hp:parameters/><hp:subList>메모 내용</hp:subList></hp:fieldBegin></hp:ctrl>
  지적한 텍스트
  <hp:ctrl><hp:fieldEnd .../></hp:ctrl>
형광펜: <hp:t>…<hp:markpenBegin color="#FFFF00"/>지적한 텍스트<hp:markpenEnd/>…</hp:t>

사용법:
  python annotate_hwpx.py 제안요청서.hwpx numeric_findings.json review.json --doc 제안요청서 -o output/제안요청서_검토메모.hwpx
  --doc: findings의 '문서' 값 중 이 파일에 해당하는 것. --author: 메모 작성자(기본 'RFP 검토').
"""
import argparse
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HP = "{%s}" % HP_NS
MEMO_FIELD_ID = str(int.from_bytes(b"%%me", "big"))  # 623209829, 한/글이 메모 필드에 쓰는 값
COLOR = {"수정필요": "#FFFF00", "확인필요": "#9FE2FF"}
LABEL = {"수정필요": "수정 필요", "확인필요": "확인 요청"}
SELF = "문서 자체 오류"
NO_QUOTE = "해당 내용 없음"  # safe_annotate가 인라인을 포기한 지적에 쓴다 → 요약 메모로
MEMO_SEP = "─" * 16  # 한 메모에 합친 지적 사이 구분선
WS = re.compile(r"\s+")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def paths_alias(first, second):
    """Existing hard-link/symlink aliases and normalized path aliases are unsafe outputs."""
    try:
        if os.path.exists(first) and os.path.exists(second) and os.path.samefile(first, second):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


# ------------------------------------------------------------------ 입력
def load_findings(paths, doc):
    """이 문서(--doc)의 수정필요·확인필요 지적을 파일 순서대로."""
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as fp:
            out += [f for f in json.load(fp).get("findings", [])
                    if f.get("문서") == doc and f.get("판정") in COLOR]
    return out


def quote_of(f):
    raw = (f.get("원문") or "").strip()
    return None if not raw or raw.startswith(NO_QUOTE) else raw


def para_hint(f):
    """위치의 [문단 n] 번호들. 같은 인용이 여러 문단에 있을 때 이 문단을 먼저 찾는다."""
    return [int(n) for n in re.findall(r"문단\s*(\d+)", f.get("위치") or "")]


def publish(data, path):
    """path가 없으면 그 이름, 있으면 _2, _3…으로 새로 만든다. 기존 파일은 덮어쓰지 않는다. 실제 경로를 돌려준다."""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    fd, tmp = tempfile.mkstemp(prefix=".annotate-", suffix=ext, dir=folder)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
        for n in range(1, 1000):
            dest = os.path.join(folder, f"{stem}{'' if n == 1 else f'_{n}'}{ext}")
            try:
                os.link(tmp, dest)  # 이미 있으면 실패한다: 원자적 no-clobber
                return dest
            except FileExistsError:
                continue
        raise FileExistsError(f"빈 이름을 찾지 못했습니다: {path}")
    finally:
        os.unlink(tmp)


# ------------------------------------------------------------------ 문단 토큰화
class Para:
    """문단의 직계 run들을 (char | sub | ctrl) 토큰 열로 펼친다."""

    def __init__(self, p):
        self.p = p
        self.runs = [r for r in p if local(r.tag) == "run"]
        self.tokens = []  # run별 토큰 리스트
        self.chars = []   # 전역 문자 → (run idx, token idx)
        for ri, r in enumerate(self.runs):
            toks = []
            for c in r:
                if local(c.tag) == "t":
                    attrib = dict(c.attrib)
                    if c.text:
                        for ch in c.text:
                            toks.append(("char", ch, attrib))
                    for sub in c:
                        tail = sub.tail
                        sub.tail = None
                        toks.append(("sub", sub, attrib))
                        if tail:
                            for ch in tail:
                                toks.append(("char", ch, attrib))
                else:
                    toks.append(("ctrl", c, None))
            for ti, t in enumerate(toks):
                if t[0] == "char":
                    self.chars.append((ri, ti))
            self.tokens.append(toks)
        self.text = "".join(self.tokens[ri][ti][1] for ri, ti in self.chars)
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
        norm, idx = [], []
        for i, ch in enumerate(self.text):
            if not ch.isspace():
                norm.append(ch)
                idx.append(i)
        norm = "".join(norm)
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
                    for _, t in sorted(by_pos.get((g, 0), []), key=lambda x: x[0]):
                        new.append(t if t[2] is not None or t[0] == "ctrl" else (t[0], t[1], tok[2]))
                    new.append(tok)
                    for _, t in sorted(by_pos.get((g, 1), []), key=lambda x: x[0]):
                        new.append(t if t[2] is not None or t[0] == "ctrl" else (t[0], t[1], tok[2]))
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
                    cur.append(val)
                    last_sub = val
        # 레이아웃 캐시 제거: 한/글이 열 때 다시 계산한다
        for c in [c for c in self.p if local(c.tag).lower() == "linesegarray"]:
            self.p.remove(c)


# ------------------------------------------------------------------ 메모 요소
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
                    prm.text = f"MEMO/65535/{num}/{self.ft_lo}/{self.ft_hi}//\\;;"

    def make(self, lines, char_ref="0"):
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
            f"MEMO/65535/{self.n}/{self.ft_lo}/{self.ft_hi}//\\;;"
        ET.SubElement(ps, HP + "stringParam", {"name": "ID"}).text = f"rfpreview{self.n}"
        ET.SubElement(ps, HP + "integerParam", {"name": "Number"}).text = str(self.n)
        ET.SubElement(ps, HP + "stringParam", {"name": "Author"}).text = self.author
        ET.SubElement(ps, HP + "stringParam", {"name": "MemoShapeIDRef"}).text = "65535"
        ET.SubElement(ps, HP + "stringParam", {"name": "CreateDateTime"}).text = self.created
        sl = ET.SubElement(fb, HP + "subList", {
            "id": "", "textDirection": "HORIZONTAL", "lineWrap": "BREAK", "vertAlign": "TOP",
            "linkListIDRef": "0", "linkListNextIDRef": "0", "textWidth": "0", "textHeight": "0",
            "hasTextRef": "0", "hasNumRef": "0"})
        self.add_lines(sl, lines, char_ref)
        end_ctrl = ET.Element(HP + "ctrl")
        ET.SubElement(end_ctrl, HP + "fieldEnd", {"beginIDRef": fid, "fieldid": MEMO_FIELD_ID})
        return begin_ctrl, end_ctrl, sl

    PARA_PR = "0"  # 메모 문단 모양(왼쪽 정렬). main()에서 header에 추가한 id로 바꾼다

    @staticmethod
    def add_lines(sublist, lines, char_ref="0"):
        for line in lines:
            p = ET.SubElement(sublist, HP + "p", {
                "id": "0", "paraPrIDRef": MemoFactory.PARA_PR, "styleIDRef": "0", "pageBreak": "0",
                "columnBreak": "0", "merged": "0"})
            run = ET.SubElement(p, HP + "run", {"charPrIDRef": char_ref})
            ET.SubElement(run, HP + "t").text = line




def short_summary(f, limit=38):
    """메모 첫 줄용 한 줄 요약. '요약'이 있으면 그대로, 없으면 문제점 첫 문장을 줄인다."""
    s = WS.sub(" ", f.get("요약") or "").strip()
    if s:
        return s
    s = WS.sub(" ", f.get("문제점") or "").strip()
    s = re.split(r"(?<=[다요음])\.\s|\.\s*$", s)[0].rstrip(".")
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def bullets(text, limit=4):
    """문장·줄 단위로 끊어 개조식 항목으로(최대 limit개)."""
    out = []
    for line in str(text or "").splitlines():
        # '있습니다. ' 같은 문장 끝에서만 끊는다. '다. 성능 요구사항' 같은 항목 기호는 끊지 않는다
        for s in re.split(r"(?<=[가-힣][다요음함])\.\s+", line.strip()):
            s = s.strip().rstrip(".").strip()
            if s:
                out.append(re.sub(r"^[-·•]\s*", "", s))
    return out[:limit]


def clip(text, limit):
    text = WS.sub(" ", text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def memo_lines(f):
    """메모 본문. 작성자가 메모만 보고 고치거나 답할 수 있어야 한다:
      [수정 필요] 요약
      ■ 현재 문구 / ■ 문제(확인이 필요한 이유) / ■ 이렇게 고쳐 주세요(확인해 주세요) / ■ 근거"""
    check = f.get("판정") == "확인필요"
    title = short_summary(f)
    lines = [f"[{LABEL[f['판정']]}] {title}"]
    cur = quote_of(f)
    if cur:
        lines += ["■ 현재 문구", f' "{clip(cur, 90)}"']
    probs = [s for s in bullets(f.get("문제점")) if WS.sub("", s) != WS.sub("", title)]
    if probs:
        lines += ["■ 확인이 필요한 이유" if check else "■ 문제"] + [f" - {s}" for s in probs]
    todo = bullets(f.get("수정안"), limit=6)
    if todo:
        lines += ["■ 확인해 주세요" if check else "■ 이렇게 고쳐 주세요"] + [f" - {s}" for s in todo]
    basis = (f.get("근거") or "").strip()
    if basis == SELF:
        lines += ["■ 근거", " - 문서 내용 대조(오타·빈칸·불일치)"]
    elif basis:
        lines += ["■ 근거(검토 지침)"] + [f' - "{clip(b, 120)}"' for b in re.split(r"\s+/\s+", basis)[:3]]
    return lines


def add_memo_para_pr(header):
    """paraPr id=0을 복제해 왼쪽 정렬·줄간격 130%·어절 단위 줄바꿈으로 바꾼 문단 모양을 추가한다.
    header 텍스트를 직접 고쳐 나머지 부분은 바이트 그대로 둔다. 실패하면 (원문, None)."""
    m_props = re.search(r'(<hh:paraProperties\b[^>]*\bitemCnt=")(\d+)("[^>]*>)', header)
    m_p0 = re.search(r'<hh:paraPr id="0"[\s\S]*?</hh:paraPr>', header)
    m_end = header.find("</hh:paraProperties>")
    if not (m_props and m_p0 and m_end > 0):
        return header, None
    ids = [int(x) for x in re.findall(r'<hh:paraPr id="(\d+)"', header)]
    new_id = str(max(ids) + 1)
    p = m_p0.group(0).replace('<hh:paraPr id="0"', f'<hh:paraPr id="{new_id}"', 1)
    p = re.sub(r'(<hh:align\b[^>]*\bhorizontal=")\w+', r"\g<1>LEFT", p, count=1)
    p = re.sub(r'(<hh:lineSpacing type="PERCENT" value=")\d+', r"\g<1>130", p)
    p = p.replace('breakNonLatinWord="BREAK_WORD"', 'breakNonLatinWord="KEEP_WORD"')
    out = header[:m_end] + p + header[m_end:]
    m_props = re.search(r'(<hh:paraProperties\b[^>]*\bitemCnt=")(\d+)(")', out)
    out = out[:m_props.start(2)] + str(int(m_props.group(2)) + 1) + out[m_props.end(2):]
    return out, new_id




# ------------------------------------------------------------------ 메인
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hwpx")
    ap.add_argument("findings", nargs="+")
    ap.add_argument("--doc", required=True, help="이 파일에 해당하는 findings의 '문서' 값")
    ap.add_argument("-o", "--out", required=True, help="출력 경로. 이미 있으면 _2, _3…을 붙인다")
    ap.add_argument("--author", default="RFP 검토")
    a = ap.parse_args()
    source = os.path.abspath(a.hwpx)
    if paths_alias(a.out, source):
        print("[중단] 출력 파일(-o)이 원본과 같습니다. 다른 이름을 주세요.")
        return 2
    try:
        if source.lower().endswith(".hwp"):
            # 바이너리 원본은 OS 임시 폴더의 사본으로 변환해 주석한다(한/글 필요).
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from convert_to_hwpx import convert_hwp_to_hwpx
            with tempfile.TemporaryDirectory(prefix="rfp-review-annotate-") as temp_dir:
                try:
                    converted = convert_hwp_to_hwpx(source, os.path.join(temp_dir, "converted.hwpx"))
                except Exception as e:
                    print(f"[중단] .hwp를 HWPX로 변환하지 못했습니다: {e}")
                    print("→ 한/글에서 '다른 이름으로 저장 → HWPX'로 저장해 다시 주세요.")
                    return 2
                print(f"[변환] {source} → 임시 HWPX 사본에 메모를 답니다")
                return _annotate(a, converted)
        return _annotate(a, source)
    except Exception as e:
        print(f"[중단] HWPX 주석을 생성하지 못했습니다: {e}")
        return 2


def _annotate(a, hwpx):
    findings = load_findings(a.findings, a.doc)
    with zipfile.ZipFile(hwpx) as zin:
        return _annotate_archive(a, findings, zin)


def _annotate_archive(a, findings, zin):
    sec_names = sorted([n for n in zin.namelist() if re.match(r"Contents/section\d+\.xml$", n)],
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
    if not sec_names:
        print("[중단] HWPX 본문(Contents/section*.xml)을 찾지 못했습니다.")
        return 2

    # 메모 문단용 문단 모양(왼쪽 정렬)을 header에 추가한다
    changed = {}
    if "Contents/header.xml" in zin.namelist():
        hdr, pid = add_memo_para_pr(zin.read("Contents/header.xml").decode("utf-8"))
        if pid is not None:
            changed["Contents/header.xml"] = hdr.encode("utf-8")
            MemoFactory.PARA_PR = pid

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
    max_z = 0
    in_memo = set()  # 기존 메모 내용 문단: 번호는 매기되 메모는 달지 않는다
    for s in sections:
        for fb in s["root"].iter(HP + "fieldBegin"):
            for q in fb.iter(HP + "p"):
                in_memo.add(id(q))
        for el in s["root"].iter():
            if local(el.tag) == "fieldBegin" and el.get("type") == "MEMO":
                try:
                    max_z = max(max_z, int(el.get("zorder", "0")))
                except ValueError:
                    pass
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
    factory.used_ids = {fb.get("id") for s in sections for fb in s["root"].iter(HP + "fieldBegin")}
    anchored, unanchored, partial = [], [], []
    records = []  # 번호 재정렬용 (문서 위치, fieldBegin)

    for f in findings:
        q = quote_of(f)
        hints = para_hint(f)
        if q is None:
            unanchored.append(f)
            continue
        order = [x for x in paras if x[0] in hints] + [x for x in paras if x[0] not in hints]
        hit = None
        for num, s, el in order:
            P = get_para(el)
            rng = P.find(q)
            if rng:
                hit = (num, P, rng, False)
                break
        if hit is None:  # 앞 20자만으로 다시 시도
            short = WS.sub("", re.split(r"…|\.{3,}", q)[0])[:20]
            if len(short) >= 8:
                for num, s, el in order:
                    P = get_para(el)
                    rng = P.find(short)
                    if rng:
                        hit = (num, P, rng, True)
                        break
        if hit is None:
            unanchored.append(f)
            continue
        num, P, (s, e), is_partial = hit
        s, e = P.fit(s, e)
        lines = memo_lines(f)
        prev = P.overlapping(s, e)
        if prev:  # 같은 범위에 이미 메모가 있으면 내용을 이어 붙인다
            MemoFactory.add_lines(prev[2], ["", MEMO_SEP] + lines)
        else:
            begin, end, sl = factory.make(lines)
            records.append(((num, s), begin[0]))
            color = COLOR.get(f.get("판정"), "#FFFF00")
            P.inserts += [(s, 0, 0, ("ctrl", begin, None)), (e - 1, 1, 9, ("ctrl", end, None))]
            # 형광펜: run마다 따로 열고 닫는다
            runs_hit = {}
            for gi in range(s, e):
                ri, _ = P.chars[gi]
                runs_hit.setdefault(ri, [gi, gi])[1] = gi
            for ri, (a0, a1) in runs_hit.items():
                P.inserts.append((a0, 0, 1, ("sub", ET.Element(HP + "markpenBegin", {"color": color}), None)))
                P.inserts.append((a1, 1, 0, ("sub", ET.Element(HP + "markpenEnd"), None)))
            P.ranges.append((s, e, sl))
        anchored.append((f, num))
        if is_partial:
            partial.append((f, num))

    # 검토 요약 메모: 첫 문단 앞부분에 단다
    every = [f for f, _ in anchored] + unanchored
    n_req = sum(1 for f in every if f.get("판정") == "수정필요")
    n_chk = len(every) - n_req
    head = f"이 문서에 고칠 곳 {n_req}건" + (f", 확인이 필요한 곳 {n_chk}건" if n_chk else "") + "에 메모를 달았습니다."
    summary = ["[RFP 검토 요약] AI 1차 검토 결과입니다. 최종 판단은 담당자가 합니다.", head]
    # 문서 순서대로 제목만 모아 한눈에 보이게 한다. 위치를 못 찾은 지적은 본문까지 여기 싣는다.
    ordered = [f for f, _ in sorted(anchored, key=lambda x: x[1])]
    for verdict in ("수정필요", "확인필요"):
        group = [f for f in ordered if f.get("판정") == verdict]
        if group:
            summary += ["", f"■ {LABEL[verdict]} {len(group)}건"]
            summary += [f" {i}. {short_summary(f, 60)}" for i, f in enumerate(group, 1)]
    if unanchored:
        summary += ["", f"■ 위치를 특정하지 못한 지적 {len(unanchored)}건"]
        for f in unanchored:
            where = f"({f['위치']}) " if f.get("위치") else ""
            lines = memo_lines(f)
            summary += [" " + where + lines[0]] + [" " + x for x in lines[1:]]
    summary += ["", "■ 처리 방법",
                " - 노란 형광펜: 고친 뒤 메모 삭제",
                " - 파란 형광펜: 확인한 내용을 메모에 답변",
                " - 고치지 않을 곳: 메모에 사유 작성"]
    if paras:
        P = get_para(paras[0][2])
        body = P.text.rstrip()
        k = max(1, min(len(body), 15))
        starts = [fs for fs, fe in P.fields if 0 < fs < k] + [r[0] for r in P.ranges if 0 < r[0] < k]
        if starts:
            k = min(starts)
        _, k = P.fit(0, k)
        overlap = P.overlapping(0, k)
        if overlap:  # 첫 글자부터 지적 메모가 있으면 그 메모 앞쪽에 요약을 넣는다
            first = list(overlap[2])
            for c in first:
                overlap[2].remove(c)
            MemoFactory.add_lines(overlap[2], summary + ["", MEMO_SEP])
            for c in first:
                overlap[2].append(c)
        else:
            begin, end, sl = factory.make(summary)
            records.append(((0, -1), begin[0]))
            P.inserts += [(0, 0, -1, ("ctrl", begin, None)), (k - 1, 1, 10, ("ctrl", end, None))]
            P.ranges.append((0, k, sl))
    factory.renumber(records)

    for P in para_obj.values():
        P.rebuild()

    # 저장: 원본 엔트리 순서·압축방식 유지, 바뀐 섹션만 교체
    for s in sections:
        body = ET.tostring(s["root"], encoding="unicode")
        body = s["root_tag"] + body[body.index(">") + 1:]
        changed[s["name"]] = (s["prolog"] + body).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            data = changed.get(info.filename, zin.read(info.filename))
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    out = publish(buf.getvalue(), a.out)

    print(f"저장: {out}")
    print(f"메모 {len(anchored)}건 + 요약 메모 1건 (위치 못 찾음 {len(unanchored)}건, 부분 일치 {len(partial)}건)")
    # 고쳐야 할 것(요약 메모로·부분 일치)을 먼저, 정상 메모는 건수가 많으면 줄여서 출력한다(하네스 출력 잘림 방지)
    for f in unanchored:
        print(f"- [요약 메모로] {f.get('id')} {short_summary(f)}")
    for f, num in anchored:
        if (f, num) in partial:
            print(f"- [부분 일치: 앞부분만 표시] [문단 {num}] {f.get('id')} {short_summary(f)}")
    ok = [(f, num) for f, num in anchored if (f, num) not in partial]
    for f, num in ok[:20]:
        print(f"- [문단 {num}] {f.get('id')} {short_summary(f)}")
    if len(ok) > 20:
        print(f"- … 정상 메모 {len(ok) - 20}건 더")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # 하네스가 파이프로 읽어도 UTF-8로 나가게
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())

