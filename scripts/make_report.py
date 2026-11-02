#!/usr/bin/env python3
"""검토 결과(JSON)를 작성자 회신용 '수정요청표' 엑셀로 만든다.

입력 JSON 형식(references/output-format.md):
  {"meta": {...}, "findings": [{"id","항목","중요도","판정","판정방식","문서","위치","원문","문제점","근거","수정안","연계"}]}
여러 파일을 넣으면 합친다. 같은 (id, 항목)은 뒤에 넣은 파일이 앞의 것을 덮어쓴다.
  → numeric_findings.json 을 먼저, 모델 검토 결과(review.json)를 나중에 넣는다.

사용법:
  python make_report.py numeric_findings.json review.json -o 수정요청표.xlsx
"""
import argparse
import json
import re
import sys
from datetime import date

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "맑은 고딕"
HDR_FILL = PatternFill("solid", fgColor="1F3864")
TITLE = Font(name=FONT, size=14, bold=True)
HDR = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="top", wrap_text=True)
RED_FILL = PatternFill("solid", fgColor="FDE9E7")
YEL_FILL = PatternFill("solid", fgColor="FFF4CE")
GRN_FILL = PatternFill("solid", fgColor="E8F3E8")

SEV = {"★필수": 0, "확인": 1, "참고": 2}
SHEET_ORDER = "①②③④⑤⑥"


def id_key(i):
    m = re.match(r"([①②③④⑤⑥])-(\d+)", i or "")
    return (SHEET_ORDER.index(m.group(1)), int(m.group(2))) if m else (9, 999)


def load(paths):
    meta, merged = {}, {}
    for p in paths:
        with open(p, encoding="utf-8") as fp:
            d = json.load(fp)
        meta.update(d.get("meta") or {})
        for f in d.get("findings", []):
            merged[(f.get("id"), f.get("항목"))] = f
    rows = sorted(merged.values(), key=lambda f: (SEV.get(f.get("중요도"), 3), id_key(f.get("id"))))
    return meta, rows


def table(ws, start_row, headers, widths, rows, center_cols=()):
    for c, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(start_row, c, h)
        cell.font, cell.fill, cell.border, cell.alignment = HDR, HDR_FILL, BOX, CENTER
        ws.column_dimensions[get_column_letter(c)].width = w
    for r, vals in enumerate(rows, start_row + 1):
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.font, cell.border = BODY, BOX
            cell.alignment = CENTER if c in center_cols else WRAP
    end = start_row + max(len(rows), 1)
    ws.freeze_panes = ws.cell(start_row + 1, 1)
    ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{end}"
    return end


def sev_format(ws, col_letter, first, last, ncols):
    rng = f"A{first}:{get_column_letter(ncols)}{last}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'${col_letter}{first}="★필수"'], fill=RED_FILL))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", default="수정요청표.xlsx")
    a = ap.parse_args()
    meta, rows = load(a.inputs)

    wb = Workbook()
    # ---------------------------------------------------------------- 1. 수정요청 (작성자 회신용)
    ws = wb.active
    ws.title = "수정요청"
    ws["A1"] = f"제안요청서·공고문 수정요청표 — {meta.get('사업명', '')}"
    ws["A1"].font = TITLE
    ws["A2"] = (f"검토일 {meta.get('검토일', date.today().isoformat())} · 검토 {meta.get('검토자', '구매팀')} · "
                f"낙찰방식 {meta.get('낙찰방식', '-')} · 계약유형 {meta.get('계약유형', '-')}")
    ws["A2"].font = BODY
    ws["A3"] = "아래 항목을 수정한 뒤 '작성자 조치'와 '작성자 의견'을 채워 회신해 주세요. ★필수 항목은 법령·계약예규상 필수 사항입니다."
    ws["A3"].font = BODY
    req = [f for f in rows if f.get("판정") == "수정필요"]
    H = ["No", "점검ID", "중요도", "점검항목", "문서", "위치", "현재 문구", "문제점", "근거", "수정안", "작성자 조치", "작성자 의견"]
    W = [5, 9, 8, 20, 12, 16, 36, 36, 26, 40, 13, 24]
    data = [[i, f.get("id"), f.get("중요도"), f.get("항목"), f.get("문서"), f.get("위치"), f.get("원문"),
             f.get("문제점"), f.get("근거") + (f"\n(연계 {f['연계']})" if f.get("연계") else "") if f.get("근거") else f.get("연계", ""),
             f.get("수정안"), "", ""] for i, f in enumerate(req, 1)]
    end = table(ws, 5, H, W, data, center_cols=(1, 2, 3, 11))
    dv = DataValidation(type="list", formula1='"반영,미반영(사유 기재),협의 요청"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"K6:K{max(end, 6)}")
    sev_format(ws, "C", 6, max(end, 6), len(H))

    # ---------------------------------------------------------------- 2. 확인필요 (구매팀·요청부서 확인)
    ws2 = wb.create_sheet("확인필요")
    ws2["A1"] = "문서만으로 판정할 수 없는 항목 — 담당자 확인 필요"
    ws2["A1"].font = TITLE
    chk = [f for f in rows if f.get("판정") == "확인필요"]
    H2 = ["No", "점검ID", "중요도", "점검항목", "확인할 내용", "관련 문서·위치", "근거", "확인 주체", "확인 결과", "확인일/비고"]
    W2 = [5, 9, 8, 22, 50, 22, 28, 12, 11, 20]
    data2 = [[i, f.get("id"), f.get("중요도"), f.get("항목"), f.get("문제점"),
              " ".join(x for x in [f.get("문서", ""), f.get("위치", "")] if x), f.get("근거"),
              f.get("확인주체", "구매팀"), "", ""] for i, f in enumerate(chk, 1)]
    end2 = table(ws2, 3, H2, W2, data2, center_cols=(1, 2, 3, 8, 9))
    dv2 = DataValidation(type="list", formula1='"완료,미확인,해당없음"', allow_blank=True)
    ws2.add_data_validation(dv2)
    dv2.add(f"I4:I{max(end2, 4)}")
    sev_format(ws2, "C", 4, max(end2, 4), len(H2))

    # ---------------------------------------------------------------- 3. 전체 점검결과
    ws3 = wb.create_sheet("전체결과")
    ws3["A1"] = "전체 점검결과 (판정을 바꾸면 요약이 다시 계산됩니다)"
    ws3["A1"].font = TITLE
    H3 = ["점검ID", "중요도", "점검항목", "판정", "판정방식", "문서", "위치", "원문", "문제점·판단 근거", "근거", "수정안", "연계"]
    W3 = [9, 8, 22, 10, 9, 12, 16, 34, 40, 26, 34, 12]
    data3 = [[f.get("id"), f.get("중요도"), f.get("항목"), f.get("판정"), f.get("판정방식"), f.get("문서"), f.get("위치"),
              f.get("원문"), f.get("문제점"), f.get("근거"), f.get("수정안"), f.get("연계")] for f in rows]
    end3 = table(ws3, 3, H3, W3, data3, center_cols=(1, 2, 4, 5))
    dv3 = DataValidation(type="list", formula1='"수정필요,확인필요,적합,해당없음"', allow_blank=False)
    ws3.add_data_validation(dv3)
    dv3.add(f"D4:D{max(end3, 4)}")
    last3 = max(end3, 4)
    for txt, fill in [("수정필요", RED_FILL), ("확인필요", YEL_FILL), ("적합", GRN_FILL)]:
        ws3.conditional_formatting.add(f"D4:D{last3}", FormulaRule(formula=[f'$D4="{txt}"'], fill=fill))

    # ---------------------------------------------------------------- 4. 요약 (맨 앞으로)
    ws0 = wb.create_sheet("요약", 0)
    ws0.column_dimensions["A"].width = 16
    for col in "BCDE":
        ws0.column_dimensions[col].width = 12
    ws0["A1"] = "제안요청서·공고문 검토 요약"
    ws0["A1"].font = TITLE
    info = [("사업명", meta.get("사업명", "")), ("검토일", meta.get("검토일", date.today().isoformat())),
            ("검토자", meta.get("검토자", "구매팀")), ("검토 문서", ", ".join(meta.get("검토문서", []))),
            ("낙찰방식", meta.get("낙찰방식", "")), ("계약유형", meta.get("계약유형", "")),
            ("추정가격(VAT 제외)", meta.get("추정가격", "")), ("체크리스트 기준", meta.get("체크리스트기준", "v4 (26.8. 기준)"))]
    for r, (k, v) in enumerate(info, 3):
        ws0.cell(r, 1, k).font = BOLD
        c = ws0.cell(r, 2, v)
        c.font = BODY
        if isinstance(v, (int, float)):
            c.number_format = '#,##0"원"'
        ws0.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
    r0 = 3 + len(info) + 1
    heads = ["판정", "★필수", "확인", "참고", "합계"]
    for c, h in enumerate(heads, 1):
        cell = ws0.cell(r0, c, h)
        cell.font, cell.fill, cell.border, cell.alignment = HDR, HDR_FILL, BOX, CENTER
    rng_d, rng_b = f"전체결과!$D$4:$D${last3}", f"전체결과!$B$4:$B${last3}"
    for i, v in enumerate(["수정필요", "확인필요", "적합", "해당없음"], 1):
        r = r0 + i
        ws0.cell(r, 1, v)
        for c, s in enumerate(["★필수", "확인", "참고"], 2):
            ws0.cell(r, c, f'=COUNTIFS({rng_d},$A{r},{rng_b},"{s}")')
        ws0.cell(r, 5, f"=SUM(B{r}:D{r})")
        for c in range(1, 6):
            ws0.cell(r, c).font, ws0.cell(r, c).border = (BOLD if c in (1, 5) else BODY), BOX
            ws0.cell(r, c).alignment = CENTER
    r = r0 + 5
    ws0.cell(r, 1, "합계").font = BOLD
    for c in range(2, 6):
        L = get_column_letter(c)
        ws0.cell(r, c, f"=SUM({L}{r0 + 1}:{L}{r0 + 4})")
    for c in range(1, 6):
        ws0.cell(r, c).border, ws0.cell(r, c).alignment = BOX, CENTER
        ws0.cell(r, c).font = BOLD
    ws0.cell(r + 2, 1, "시트 안내").font = BOLD
    for k, t in enumerate(["수정요청: 작성자에게 그대로 회신하는 표 (작성자 조치·의견 칸 포함)",
                           "확인필요: 문서만으로 판정 불가 — 구매팀·요청부서가 확인할 항목",
                           "전체결과: 적합 항목까지 포함한 전체 판정 (판정을 바꾸면 이 요약이 갱신됨)",
                           "AI 1차 검토 결과입니다. 최종 판단은 구매팀 담당자가 합니다."], r + 3):
        ws0.cell(k, 1, "· " + t).font = BODY

    for w in wb.worksheets:
        w.sheet_view.zoomScale = 90
        w.page_setup.orientation = "landscape"
        w.page_setup.fitToWidth = 1
        w.page_setup.fitToHeight = 0
        w.sheet_properties.pageSetUpPr.fitToPage = True
    wb.save(a.out)
    cnt = {}
    for f in rows:
        cnt[f.get("판정")] = cnt.get(f.get("판정"), 0) + 1
    print(f"저장: {a.out}  (수정요청 {len(req)}건, 확인필요 {len(chk)}건, 전체 {len(rows)}건: {cnt})")


if __name__ == "__main__":
    sys.exit(main())
