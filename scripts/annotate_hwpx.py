#!/usr/bin/env python3
"""검토 결과를 원본 HWPX 문서에 한글 '메모'와 형광펜으로 단다.

- 지적한 원문 위치에 형광펜을 칠하고, 그 범위에 메모(점검ID·문제·수정안·근거)를 단다.
- 위치를 못 찾은 지적과 전체 요약은 문서 첫 문단에 '검토 요약' 메모로 단다.
- 원본 파일은 건드리지 않고 새 파일로 저장한다. 메모가 달린 문단 외에는 그대로 둔다.

메모 구조는 한/글이 저장한 파일과 같다: 본문 run 안의
  <hp:ctrl><hp:fieldBegin type="MEMO" ...><hp:parameters/><hp:subList>메모 내용</hp:subList></hp:fieldBegin></hp:ctrl>
  지적한 텍스트
  <hp:ctrl><hp:fieldEnd .../></hp:ctrl>
형광펜: <hp:t>…<hp:markpenBegin color="#FFFF00"/>지적한 텍스트<hp:markpenEnd/>…</hp:t>

사용법:
  python annotate_hwpx.py 제안요청서.hwpx --doc 제안요청서 numeric_findings.json review.json -o 제안요청서_검토메모.hwpx
  옵션: --include-check  확인필요 항목도 메모로 단다(기본: 수정필요만)
        --author 구매팀   메모 작성자
"""
import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HP = "{%s}" % HP_NS
MEMO_FIELD_ID = str(int.from_bytes(b"%%me", "big"))  # 623209829, 한/글이 메모 필드에 쓰는 값
COLOR = {"수정필요": "#FFFF00", "확인필요": "#9FE2FF"}
SEV = {"★필수": 0, "확인": 1, "참고": 2}
WS = re.compile(r"\s+")


def local(tag):
    return tag.rsplit("}", 1)[-1]


# ------------------------------------------------------------------ 입력
def load_findings(paths, include_check):
    merged = {}
    for p in paths:
        with open(p, encoding="utf-8") as fp:
            d = json.load(fp)
        for f in d.get("findings", []):
            merged[(f.get("id"), f.get("항목"))] = f
    keep = {"수정필요"} | ({"확인필요"} if include_check else set())
    out = [f for f in merged.values() if f.get("판정") in keep]
    out.sort(key=lambda f: (SEV.get(f.get("중요도"), 3), f.get("id", "")))
    return out, list(merged.values())


def quote_for_doc(f, doc):
    """finding의 원문 중 이 문서에 해당하는 부분. 없으면 None."""
    raw = (f.get("원문") or "").strip()
    if not raw or raw.startswith("해당 내용 없음"):
        return None
    tagged = re.findall(r"^\[([^\]]+)\]\s*(.+)$", raw, re.M)
    if tagged:
        for d, q in tagged:
            if d.strip() == doc:
                return q.strip()
        return None
    docs = [x.strip() for x in re.split(r"[,/]", f.get("문서") or "") if x.strip()]
    if docs and doc not in docs:
        return None
    return raw


def para_hint(f):
    """위치에서 [문단 n] 번호를 모두 뽑는다."""
    return [int(n) for n in re.findall(r"문단\s*(\d+)", f.get("위치") or "")]


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
        """공백 무시 매칭. '…'로 생략된 인용은 앞부분~뒷부분 범위. (s, e) 문자 범위."""
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
                break
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
        self.seq += 1
        fid = str(1_900_000_000 + self.seq * 7919 % 99_999_999)
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
    """메모 첫 줄용 한 줄 요약. finding의 '요약'이 있으면 그것을, 없으면 문제점 첫 문장을 줄여 쓴다."""
    s = WS.sub(" ", f.get("요약") or "").strip()
    if s:  # 직접 쓴 요약은 자르지 않는다
        return s
    s = WS.sub(" ", f.get("문제점") or f.get("항목") or "").strip()
    s = re.split(r"(?<=[다요음])\.\s|\.\s*$", s)[0].rstrip(".")
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def memo_lines(f):
    """첫 줄만 보고도 무엇을 고칠지 알 수 있게: 요약 → 수정안 → 상세 → 근거 순."""
    tag = f"{f.get('id', '')} {f.get('중요도', '')}".strip()
    if f.get("판정") == "확인필요":
        tag += " 확인요청"
    lines = [f"{tag} | {short_summary(f)}"]
    if f.get("수정안"):
        lines.append("▶ 수정: " + f["수정안"])
    detail = f.get("문제점") or ""
    if detail and WS.sub("", detail) != WS.sub("", short_summary(f, 10**6)):
        lines.append("상세: " + detail)
    if f.get("항목"):
        lines.append("점검항목: " + f["항목"])
    if f.get("근거") and f["근거"].strip() not in ("-", ""):
        lines.append("근거: " + f["근거"])
    if f.get("연계"):
        lines.append("연계: " + f["연계"])
    return [WS.sub(" ", x).strip() for x in lines]


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
    ap.add_argument("--doc", required=True, help="이 파일의 문서 구분: 제안요청서 | 공고문 | 과업내용서 ...")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--author", default="구매팀")
    ap.add_argument("--include-check", action="store_true")
    a = ap.parse_args()

    if a.hwpx.lower().endswith(".hwp"):
        # .hwp(바이너리)에는 메모를 직접 못 쓴다. 설치된 한/글로 HWPX로 변환해 진행한다.
        try:
            from convert_to_hwpx import convert_hwp_to_hwpx
        except ImportError:
            import os
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from convert_to_hwpx import convert_hwp_to_hwpx
        try:
            converted = convert_hwp_to_hwpx(a.hwpx)
        except RuntimeError as e:
            print(f"[중단] .hwp를 HWPX로 변환하지 못했습니다: {e}")
            print("→ 한/글에서 '다른 이름으로 저장 → HWPX'로 저장해 다시 올려주세요.")
            return 2
        print(f"[변환] {a.hwpx} → {converted} (이 HWPX에 메모를 답니다)")
        a.hwpx = converted

    findings, all_findings = load_findings(a.findings, a.include_check)
    zin = zipfile.ZipFile(a.hwpx)
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
    anchored, unanchored, partial = [], [], []
    records = []  # 번호 재정렬용 (문서 위치, fieldBegin)

    for f in findings:
        q = quote_for_doc(f, a.doc)
        hints = para_hint(f)
        docs = f.get("문서") or ""
        mine = a.doc in docs or not docs
        if q is None:
            # 원문은 없지만 [문단 n] 위치가 있으면 그 문단 전체에 단다
            if mine and hints and not (f.get("원문") or "").startswith("해당 내용 없음"):
                for num, s, el in paras:
                    if num == hints[0]:
                        q = get_para(el).text.strip()
                        break
            if q is None:
                if mine or (f.get("원문") or "").startswith("해당 내용 없음"):
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
            short = WS.sub("", q)[:20]
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
            MemoFactory.add_lines(prev[2], [""] + lines)
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
    # 참조 메모(같은 지적을 다른 위치에도 단 포인터)는 그려주되 건수에는 세지 않는다.
    ref_cnt = sum(1 for f, _ in anchored if f.get("참조"))
    req = [x for x in all_findings if x.get("판정") == "수정필요" and not x.get("참조")]
    must = [x for x in req if x.get("중요도") == "★필수"]
    chk = [x for x in all_findings if x.get("판정") == "확인필요" and not x.get("참조")]
    summary = [f"검토 요약 | 이 문서 수정 요청 {len(anchored) + len(unanchored) - ref_cnt}건",
               "노란 형광펜과 메모가 달린 곳을 고쳐 주세요. 고친 메모는 지우고, 반영하지 않은 메모에는 사유를 덧붙여 회신해 주세요.",
               f"전체 검토 결과(공고문·원가계산서 포함): 수정필요 {len(req)}건(★필수 {len(must)}건), 확인필요 {len(chk)}건"]
    if unanchored:
        summary.append("")
        summary.append(f"※ 위치를 특정하지 못했거나 내용이 빠진 항목 {len(unanchored)}건")
        for f in unanchored:
            ls = memo_lines(f)
            summary.append("- " + ls[0])
            summary += ["   " + x for x in ls[1:2]]  # 수정안까지
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
            MemoFactory.add_lines(overlap[2], summary + [""])
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
    with zipfile.ZipFile(a.out, "w") as zout:
        for info in zin.infolist():
            data = changed.get(info.filename, zin.read(info.filename))
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)

    print(f"저장: {a.out}")
    print(f"메모 {len(anchored)}건 + 요약 메모 1건 (위치 못 찾음 {len(unanchored)}건, 부분 일치 {len(partial)}건)")
    for f, num in anchored:
        mark = " (부분 일치: 앞부분만 표시)" if (f, num) in partial else ""
        print(f"- [문단 {num}] {f.get('id')} {f.get('항목')}{mark}")
    for f in unanchored:
        print(f"- [요약 메모로] {f.get('id')} {f.get('항목')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
