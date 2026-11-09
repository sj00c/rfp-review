"""추출 텍스트의 목차(본문 제목 번호)를 뽑고 번호 건너뜀·중복을 표시한다.

사용: python outline.py extracted/제안요청서.txt [--gaps]
  --gaps  번호 문제만 출력

'3. 입찰 및 낙찰 방식' 다음이 '5. 입찰절차'처럼 4가 빠진 오류는 통독으로 놓치기 쉽다.
표 안 문단(목차 표·서식)은 제외한다. 상위 제목(Ⅰ., 1.)이 바뀌면 하위 번호를 새로 센다.
"""
import argparse
import re
import sys

ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
HANGUL = "가나다라마바사아자차카타파하"
LEVELS = [  # (수준, 패턴, 순서값 함수)
    (0, re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\s*\.\s*(.*)"), lambda m: ROMAN.index(m.group(1)) + 1),
    (1, re.compile(r"^(\d{1,2})\.\s+(.*)"), lambda m: int(m.group(1))),
    (2, re.compile(r"^([가-하])\.\s+(.*)"), lambda m: HANGUL.index(m.group(1)) + 1 if m.group(1) in HANGUL else 0),
]
TAG = re.compile(r"^\[문단 (\d+)([^\]]*)\]\s*(.*)")


def outline(lines):
    out, last = [], {}
    for line in lines:
        m = TAG.match(line)
        if not m or "표" in m.group(2) or "뒤" in m.group(2):
            continue
        num, text = m.group(1), m.group(3).strip()
        for lvl, pat, val in LEVELS:
            h = pat.match(text)
            if not h:
                continue
            v = val(h)
            prev = last.get(lvl)
            note = ""
            if prev is not None and v != prev + 1 and v != 1:
                note = f"  << 번호 {'중복' if v == prev else '건너뜀'}: 앞 번호 {prev}"
            last[lvl] = v
            for deeper in [k for k in last if k > lvl]:
                del last[deeper]
            out.append((note != "", f"{'  ' * lvl}[문단 {num}] {text[:40]}{note}"))
            break
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--gaps", action="store_true")
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as fp:
        rows = outline(fp.read().splitlines())
    bad = [t for flag, t in rows if flag]
    for flag, t in rows:
        if flag or not a.gaps:
            print(t)
    print(f"제목 {len(rows)}개, 번호 문제 {len(bad)}건")


if __name__ == "__main__":
    main()
