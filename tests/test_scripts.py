"""scripts/ 회귀 테스트. 실행: python -m unittest discover -s tests

한/글 없이 돌아가도록 HWPX는 최소 구조(zip + section XML)로 직접 만든다.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def run(script, *args, cwd):
    """하네스처럼 파이프로 실행한다(PYTHONIOENCODING 없이). stdout은 UTF-8이어야 한다."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args], cwd=cwd,
                       capture_output=True, env=env)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

def sourced_value(value, quote, location):
    return {"값": value, "문서": "공고문", "원문": quote, "위치": location, "증거상태": "판독완료"}


def make_hwpx(path, paragraphs):
    body = "".join(f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{t}</hp:t>'
                   f"</hp:run></hp:p>" for i, t in enumerate(paragraphs))
    sec = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
           f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)


def memos(path):
    """(메모 첫 줄, 메모가 감싼 문단 텍스트) 목록."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("Contents/section0.xml"))
    out = []
    for p in root.findall("{%s}p" % HP):  # 본문 문단만(메모 안 문단 제외)
        ts = [t for run in p for t in run if t.tag == "{%s}t" % HP]
        text = "".join((t.text or "") + "".join(x.tail or "" for x in t) for t in ts)
        for fb in p.iter("{%s}fieldBegin" % HP):
            lines = ["".join(x.itertext()) for x in fb.find("{%s}subList" % HP).findall("{%s}p" % HP)]
            ids = [m.group(1) for m in (re.match(r"\(점검번호 (.+)\)$", x) for x in lines) if m]
            key = "요약" if lines[0].startswith("[입찰서류 검토 요약]") else (ids[0] if ids else "")
            out.append((key, text, lines))
    return out


FACTS = {
    "meta": {
        "공식기준": {
            key: {"적용성": "적용", "출처": "합성 공식기준", "적용범위": "합성 회귀 사업",
                  "원문": "회귀 검증용 적용 기준", "위치": "[기준 1]"}
            for key in ("배점.평가항목_최대", "배점.원칙_가격_최소", "부가세율")
        },
        "기관프로필": [{
            "프로필ID": "기관_정량최저평점_70", "기관": "합성 기관", "적용성": "적용",
            "적용범위": "합성 회귀 사업", "출처": "합성 기관 운영자료",
            "원문": "정량평가 최저점은 배점의 70%", "위치": "[운영 1]",
        }],
    },
    "계약유형": "용역", "낙찰방식": "협상", "긴급": False,
    "사업금액": {
        "공고문": {"금액": 220000000, "역할": "사업예산", "범위": "총사업", "증거상태": "판독완료", "부가세": "포함", "원문": "금220,000,000원(부가세 포함)", "위치": "[문단 2]"},
        "원가계산보고서": {"금액": 210000000, "역할": "사업예산", "범위": "총사업", "증거상태": "판독완료", "부가세": "제외", "원문": "합계 210,000,000", "위치": "[원가!9행]"},
    },
    "지역제한": {"있음": True, "문서": "공고문", "원문": "서울특별시 소재 업체", "위치": "[문단 3]"},
    "하도급": {"공고문": {"값": "미기재"}, "제안요청서": {"값": "허용", "원문": "하도급 허용", "위치": "[문단 4]"}},
    "배점": {"기술": 80, "가격": 10, "문서": "제안요청서", "원문": "기술평가 80점, 가격평가 10점", "위치": "[문단 1]"},
    "기술평가항목": [
        {"항목": "사업 이해도", "배점": 35, "문서": "제안요청서", "원문": "사업이해도 35점", "위치": "[문단 2]"},
        {"항목": "수행 방법론", "배점": 45, "문서": "제안요청서", "원문": "수행방법론 45점", "위치": "[문단 3]"},
    ],
    "정량평가항목": [
        {"항목": "신용평가", "배점": 5, "최저등급평점": 3.0, "문서": "제안요청서", "원문": "CCC+ 이하 3.0", "위치": "[문단 5]"},
        {"항목": "수행실적", "배점": 5, "최저등급평점": 2.0, "문서": "제안요청서", "원문": "실적 없음 2.0", "위치": "[문단 6]"},
    ],
}


class CheckNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        with open(os.path.join(cls.tmp, "facts.json"), "w", encoding="utf-8") as fp:
            json.dump(FACTS, fp, ensure_ascii=False)
        cls.rc, cls.out, cls.err = run("check_numbers.py", "facts.json", "-o", "nf.json", cwd=cls.tmp)
        with open(os.path.join(cls.tmp, "nf.json"), encoding="utf-8") as fp:
            cls.nf = json.load(fp)
        cls.f = cls.nf["findings"]

    def test_runs_with_utf8_stdout(self):
        self.assertEqual(self.rc, 0, self.err)
        self.assertIn("추정가격", self.out)

    def test_keys_unique(self):
        keys = [(x["id"], x["항목"]) for x in self.f]
        self.assertEqual(len(keys), len(set(keys)))

    def test_score_sum_not_overwritten(self):
        # 합계 90점 지적이 '가격평가 반영' 적합에 덮이지 않아야 한다
        by = {(x["id"], x["항목"]): x["판정"] for x in self.f}
        self.assertEqual(by[("②-12", "기술·가격 배점 합계 100점")], "수정필요")
        self.assertEqual(by[("②-12", "기술평가 100% 불가, 가격평가 필수")], "적합")

    def test_every_correction_has_short_action(self):
        # 메모의 ▶ 줄은 조치(짧은 문구)를 쓴다. 수정필요인데 조치가 없으면 긴 수정안이 메모에 들어간다
        for x in self.f:
            if x["판정"] == "수정필요":
                self.assertTrue(x.get("조치"), x["항목"])
                self.assertLessEqual(len(x["조치"]), 25, x["조치"])

    def test_estimate_does_not_prefer_conflicting_cost_report(self):
        # 상충하는 금액 중 원가계산서를 임의로 추정가격의 정답으로 선택하지 않는다.
        self.assertIsNone(self.nf["추정가격"])

    def test_over_30_each_item_anchored(self):
        rows = [x for x in self.f if x["id"] == "②-14" and x["항목"].startswith("각 평가항목")]
        main = [x for x in rows if not x.get("참조")]
        refs = [x for x in rows if x.get("참조")]
        self.assertEqual(main[0]["원문"], "사업이해도 35점")
        self.assertEqual([r["원문"] for r in refs], ["수행방법론 45점"])

    def test_quant_min_has_document(self):
        rows = [x for x in self.f if x["id"] == "③-7"]
        self.assertTrue(all(x["문서"] == "제안요청서" for x in rows))
        self.assertEqual(rows[0]["원문"], "[제안요청서] CCC+ 이하 3.0")
        self.assertEqual(len(rows), 2)


class CheckNumbersRegion(unittest.TestCase):
    def test_region_without_estimate_is_flagged(self):
        tmp = tempfile.mkdtemp()
        facts = {"계약유형": "용역", "낙찰방식": "적격심사",
                 "지역제한": {"있음": True, "문서": "공고문", "원문": "서울 소재", "위치": "[문단 1]"}}
        with open(os.path.join(tmp, "f.json"), "w", encoding="utf-8") as fp:
            json.dump(facts, fp, ensure_ascii=False)
        rc, _, err = run("check_numbers.py", "f.json", "-o", "n.json", cwd=tmp)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(tmp, "n.json"), encoding="utf-8") as fp:
            f = json.load(fp)["findings"]
        self.assertIn(("①-15", "확인필요"), [(x["id"], x["판정"]) for x in f])

    def test_negotiation_notice_without_estimate(self):
        # 추정가격 미확인 + 20일: 고시금액 미만(10일)이면 충족이므로 수정필요가 아니라 확인필요
        tmp = tempfile.mkdtemp()
        facts = {"계약유형": "용역", "낙찰방식": "협상",
                 "공고일": sourced_value("2026-11-03", "공고일 2026-11-03", "[문단 10]"),
                 "제출마감일": sourced_value("2026-11-23", "제출마감일 2026-11-23", "[문단 11]")}
        with open(os.path.join(tmp, "f.json"), "w", encoding="utf-8") as fp:
            json.dump(facts, fp, ensure_ascii=False)
        rc, _, err = run("check_numbers.py", "f.json", "-o", "n.json", cwd=tmp)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(tmp, "n.json"), encoding="utf-8") as fp:
            f = json.load(fp)["findings"]
        self.assertIn(("③-2", "확인필요", "공고문"), [(x["id"], x["판정"], x["문서"]) for x in f])

    def test_unknown_item_points_skip_sum(self):
        # 배점을 못 읽은(null) 항목이 있으면 합계 불일치를 만들어내지 않는다
        tmp = tempfile.mkdtemp()
        facts = {"계약유형": "용역", "낙찰방식": "협상", "배점": {"기술": 80, "가격": 20},
                 "기술평가항목": [{"항목": "A", "배점": 30}, {"항목": "B", "배점": None}]}
        write_json(os.path.join(tmp, "f.json"), facts)
        rc, _, err = run("check_numbers.py", "f.json", "-o", "n.json", cwd=tmp)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(tmp, "n.json"), encoding="utf-8") as fp:
            rows = json.load(fp)["findings"]
        totals = [x for x in rows if x["항목"] == "평가항목 배점 합계"]
        self.assertTrue(totals)
        self.assertTrue(all(x["판정"] == "확인필요" for x in totals))

    def numbers(self, facts):
        tmp = tempfile.mkdtemp()
        write_json(os.path.join(tmp, "f.json"), facts)
        rc, _, err = run("check_numbers.py", "f.json", "-o", "n.json", cwd=tmp)
        self.assertEqual(rc, 0, err)
        with open(os.path.join(tmp, "n.json"), encoding="utf-8") as fp:
            return {(x["id"], x["항목"]): x["판정"] for x in json.load(fp)["findings"]}

    def test_script_items_recorded_when_condition_absent(self):
        # 스크립트 전담 항목은 모델 항목표에 없다. 조건(제한·날짜)이 없어도 판정을 남겨야 검증기의 누락 오류가 안 난다(KIST 초안 실측)
        by = self.numbers({"계약유형": "용역", "낙찰방식": "협상"})
        ids = {k[0]: v for k, v in by.items()}
        self.assertEqual(ids["②-7"], "확인필요")
        self.assertEqual(ids["①-15"], "확인필요")
        self.assertEqual(ids["③-8"], "확인필요")
        self.assertEqual(ids["③-2"], "확인필요")
        self.assertEqual(ids["①-19"], "해당없음")  # 협상은 ③-2가 본다
        by = self.numbers({"계약유형": "용역", "낙찰방식": "적격심사"})
        self.assertIn(("①-19", "공고기간 산정(달력 계산)"), by)
        self.assertNotIn("③-2", {k[0] for k in by})

    def test_hundred_point_table_is_not_a_mismatch(self):
        # 평가표 100점 + '기술평가(90%)' 환산은 흔한 서식이다. 단정(수정필요)하지 않는다
        items = [{"항목": n, "배점": 25, "문서": "제안요청서",
                  "원문": f"{n} 평가항목 25점", "위치": f"[문단 {i}]"} for i, n in enumerate("ABCD", 1)]
        by = self.numbers({"계약유형": "용역", "낙찰방식": "협상", "배점": {"기술": 90, "가격": 10},
                           "기술평가항목": items})
        self.assertEqual(by[("②-14", "평가항목 원점수 합계")], "확인필요")
        by = self.numbers({"계약유형": "용역", "낙찰방식": "협상", "배점": {"기술": 90, "가격": 10},
                           "기술평가": {"원점수만점": 100}, "기술평가항목": items[:3]})
        self.assertEqual(by[("②-14", "평가항목 원점수 합계")], "수정필요")


class ExtractTable(unittest.TestCase):
    def test_table_cells_tagged_with_row_col(self):
        tmp = tempfile.mkdtemp()
        cell = ('<hp:tc><hp:subList><hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p></hp:subList>'
                '<hp:cellAddr colAddr="{c}" rowAddr="{r}"/></hp:tc>')
        rows = "".join("<hp:tr>" + "".join(cell.format(t=t, r=r, c=c) for c, t in enumerate(row)) + "</hp:tr>"
                       for r, row in enumerate([["항목", "배점"], ["사업이해도", "10"]]))
        body = (f'<hp:p><hp:run><hp:t>평가표</hp:t></hp:run><hp:run><hp:tbl>{rows}</hp:tbl></hp:run></hp:p>'
                f'<hp:p><hp:run><hp:t>끝</hp:t></hp:run></hp:p>')
        sec = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>'
        with zipfile.ZipFile(os.path.join(tmp, "t.hwpx"), "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/section0.xml", sec)
        rc, out, err = run("extract_text.py", "t.hwpx", "-o", "ex", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        with open(os.path.join(tmp, "ex", "t.txt"), encoding="utf-8") as fp:
            lines = fp.read().splitlines()[1:]
        self.assertEqual(lines, ["[문단 1] 평가표", "[문단 2 표1 1-1] 항목", "[문단 3 표1 1-2] 배점",
                                 "[문단 4 표1 2-1] 사업이해도", "[문단 5 표1 2-2] 10", "[문단 6] 끝"])


class ExtractObjects(unittest.TestCase):
    def test_equation_kept_and_numbering_unchanged(self):
        # 실제 KIST 제안요청서: 평점산식이 수식 개체라 '-'만 추출돼 '산식 공란' 허위 지적이 나왔다
        tmp = tempfile.mkdtemp()
        eq = '<hp:equation><hp:script>평점=A over B</hp:script></hp:equation>'
        body = (f'<hp:p><hp:run><hp:t>-</hp:t>{eq}</hp:run></hp:p>'
                f'<hp:p><hp:run>{eq}</hp:run></hp:p>'
                f'<hp:p><hp:run><hp:t>다음</hp:t></hp:run></hp:p>')
        sec = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>'
        with zipfile.ZipFile(os.path.join(tmp, "e.hwpx"), "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/section0.xml", sec)
        rc, out, err = run("extract_text.py", "e.hwpx", "-o", "ex", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        with open(os.path.join(tmp, "ex", "e.txt"), encoding="utf-8") as fp:
            lines = fp.read().splitlines()[1:]
        self.assertEqual(lines, ["[문단 1] - [수식: 평점=A over B]", "[문단 1 뒤] [수식: 평점=A over B]", "[문단 2] 다음"])


class ExtractText(unittest.TestCase):
    def test_xlsx_with_blank_first_column(self):
        import openpyxl
        tmp = tempfile.mkdtemp()
        wb = openpyxl.Workbook()
        wb.active["C2"] = "직접인건비"
        wb.active["D2"] = 1000
        wb.save(os.path.join(tmp, "cost.xlsx"))
        rc, out, err = run("extract_text.py", "cost.xlsx", "-o", "ex", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        with open(os.path.join(tmp, "ex", "cost.txt"), encoding="utf-8") as fp:
            self.assertIn("[Sheet!2행] C2=직접인건비 | D2=1000", fp.read())


class Annotate(unittest.TestCase):
    def annotate(self, paragraphs, findings, doc):
        tmp = tempfile.mkdtemp()
        make_hwpx(os.path.join(tmp, "d.hwpx"), paragraphs)
        with open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as fp:
            json.dump({"findings": findings}, fp, ensure_ascii=False)
        rc, out, err = run("annotate_hwpx.py", "d.hwpx", "r.json", "--doc", doc, "-o", "o.hwpx", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        return memos(os.path.join(tmp, "o.hwpx")), out

    def test_other_document_paragraph_hint_not_used(self):
        # 공고문에 '미기재'인 하도급: 제안요청서의 [문단 4] 번호로 공고문 4번째 문단에 달리면 안 된다
        f = {"id": "②-3", "항목": "하도급 허용 여부 기재", "중요도": "확인", "판정": "수정필요",
             "문서": "공고문, 제안요청서", "위치": "제안요청서: [문단 4]", "원문": "[제안요청서] 하도급 허용",
             "요약": "하도급 미기재"}
        m, _ = self.annotate(["입찰공고문", "가", "나", "무관한 문단"], [f], "공고문")
        self.assertEqual([x[0] for x in m], ["요약"])  # 검토 요약 메모 하나뿐

    def test_document_less_finding_hint_not_used(self):
        f = {"id": "③-7", "항목": "정량평가", "중요도": "★필수", "판정": "수정필요", "문서": "",
             "위치": "[문단 3]", "원문": "", "요약": "최저평점"}
        m, _ = self.annotate(["공고문", "가", "무관한 문단"], [f], "공고문")
        self.assertEqual([x[1] for x in m if x[0] != "요약"], [])

    def test_bracket_in_quote_is_not_doc_tag(self):
        f = {"id": "②-17", "항목": "평점산식", "중요도": "★필수", "판정": "수정필요", "문서": "제안요청서",
             "위치": "[문단 2]", "원문": "[별표] 추정가격의 100분의 60", "요약": "60% → 70%"}
        m, _ = self.annotate(["제안요청서", "[별표] 추정가격의 100분의 60"], [f], "제안요청서")
        hit = [x for x in m if x[0] == "②-17"]
        self.assertEqual([(x[1], x[2][0]) for x in hit], [("[별표] 추정가격의 100분의 60", "[반드시 수정] 60% → 70%")])

    def test_memo_layout(self):
        # 쉬운 머리표 / 현재 문구 / 왜(문장별) / 고칠 문구(줄별, S-nn·검색 기록 제외) / 근거 전문 / 점검번호, 합친 지적은 구분선
        base = {"중요도": "★필수", "판정": "수정필요", "문서": "제안요청서", "위치": "", "원문": "제출서류"}
        fs = [dict(base, id="②-23", 항목="제출서류 목록", 요약="제출서류 표준화",
                   수정안="표준 목록으로 정비 (S-10)\n1. 입찰참가신청서", 조치="표준 12종으로",
                   문제점="목록이 다릅니다. 가격제안서가 없습니다('가격제안' 검색 결과 없음).",
                   근거="협상에 의한 계약체결기준 [별표] / 감사원 공공계약 실무가이드(2024) p.1 / 세번째",
                   연계="②-24"),
              dict(base, id="②-24", 항목="서식 대조", 중요도="확인", 요약="서식 번호 불일치",
                   문제점="서식 3호가 목록에 없습니다.")]
        tmp = tempfile.mkdtemp()
        make_hwpx(os.path.join(tmp, "d.hwpx"), ["제안요청서", "제출서류"])
        with open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as fp:
            json.dump({"findings": fs}, fp, ensure_ascii=False)
        rc, out, err = run("annotate_hwpx.py", "d.hwpx", "r.json", "--doc", "제안요청서", "-o", "o.hwpx", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        with zipfile.ZipFile(os.path.join(tmp, "o.hwpx")) as z:
            root = ET.fromstring(z.read("Contents/section0.xml"))
        memo = [fb for fb in root.iter("{%s}fieldBegin" % HP)
                if "②-23" in "".join(fb.find("{%s}subList" % HP).itertext())][0]
        lines = ["".join(p.itertext()) for p in memo.find("{%s}subList" % HP).findall("{%s}p" % HP)]
        self.assertEqual(lines, [
            "[반드시 수정] 제출서류 표준화",
            "■ 현재 문구", ' "제출서류"',
            "■ 왜 고쳐야 하나", " - 목록이 다릅니다", " - 가격제안서가 없습니다",
            "■ 이렇게 고쳐 주세요", " - 표준 목록으로 정비", " - 1. 입찰참가신청서",
            "■ 근거", " - 협상에 의한 계약체결기준 [별표]", " - 감사원 공공계약 실무가이드(2024) p.1", " - 세번째",
            "(점검번호 ②-23)",
            "", "─" * 16,
            "[수정 요청] 서식 번호 불일치", "■ 현재 문구", ' "제출서류"',
            "■ 왜 고쳐야 하나", " - 서식 3호가 목록에 없습니다", "(점검번호 ②-24)"])

    def test_ellipsis_tail_must_match(self):
        # '…' 뒷부분이 이 문단에 없으면 앞부분만 칠하지 말고 뒷부분까지 맞는 문단을 찾는다
        f = {"id": "②-20", "항목": "전자입찰", "중요도": "★필수", "판정": "수정필요", "문서": "제안요청서",
             "위치": "", "원문": "제안서는…밀봉하여 제출", "요약": "비전자 제출"}
        m, _ = self.annotate(["제안서는 PDF로 낸다", "제안서는 인쇄본을 밀봉하여 제출"], [f], "제안요청서")
        self.assertEqual([x[1] for x in m if x[0] == "②-20"], ["제안서는 인쇄본을 밀봉하여 제출"])

    def test_reference_not_counted(self):
        base = {"id": "②-5", "중요도": "★필수", "판정": "수정필요", "문서": "제안요청서", "위치": ""}
        fs = [dict(base, 항목="과업명", 원문="1. 과업명", 요약="과업명 공란"),
              dict(base, 항목="과업명(②-5 참조)", 원문="2. 과업명", 요약="②-5 참조", 중요도="참고", 참조=True)]
        m, _ = self.annotate(["제안요청서", "1. 과업명", "2. 과업명"], fs, "제안요청서")
        summary = [x[2] for x in m if x[0] == "요약"][0]
        self.assertIn("이 문서에 고칠 곳 1건에 메모를 달았습니다.", summary)
        self.assertIn(" 1. 과업명 공란", summary)
        self.assertNotIn("②-5 참조", " ".join(summary))

    def test_memo_keeps_item_marker_and_drops_internal_notes(self):
        # '다. 성능 요구사항'의 '다.'는 문장 끝이 아니다. 괄호 안 [문단 n]·검색 기록은 메모에서 빠진다
        f = {"id": "기타-1", "항목": "분류 오기", "중요도": "확인", "판정": "수정필요", "문서": "제안요청서",
             "위치": "", "원문": "성능 요구사항(SFR)", "요약": "분류 오기",
             "문제점": "영문 분류가 SFR입니다(목록 [문단 9]은 PER). 다른 항목은 없습니다('PER' 검색 1건).",
             "수정안": "다. 성능 요구사항(PER, Performance Requirement)"}
        tmp = tempfile.mkdtemp()
        make_hwpx(os.path.join(tmp, "d.hwpx"), ["제안요청서", "다. 성능 요구사항(SFR)"])
        write_json(os.path.join(tmp, "r.json"), {"findings": [f]})
        rc, out, err = run("annotate_hwpx.py", "d.hwpx", "r.json", "--doc", "제안요청서", "-o", "o.hwpx", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        with zipfile.ZipFile(os.path.join(tmp, "o.hwpx")) as z:
            root = ET.fromstring(z.read("Contents/section0.xml"))
        memo = [fb for fb in root.iter("{%s}fieldBegin" % HP) if "기타-1" in "".join(fb.itertext())][0]
        lines = ["".join(p.itertext()) for p in memo.find("{%s}subList" % HP).findall("{%s}p" % HP)]
        self.assertEqual(lines, ["[수정 요청] 분류 오기", "■ 현재 문구", ' "성능 요구사항(SFR)"',
                                 "■ 왜 고쳐야 하나", " - 영문 분류가 SFR입니다", " - 다른 항목은 없습니다",
                                 "■ 이렇게 고쳐 주세요", " - 다. 성능 요구사항(PER, Performance Requirement)",
                                 "(점검번호 기타-1)"])

    def test_question_flag_gets_memo(self):
        # 작성자가 답할 확인필요(질의)는 메모를 단고, 내부 확인용 확인필요는 달지 않는다
        base = {"중요도": "확인", "판정": "확인필요", "문서": "제안요청서", "위치": "", "문제점": "x"}
        fs = [dict(base, id="②-3", 항목="불허 사유", 원문="공동도급 허용하지 않음", 요약="불허 사유 없음",
                   조치="사유 회신", 질의=True, 대상="작성자"),
              dict(base, id="②-6", 항목="경쟁제품", 원문="직접생산확인증명서 소지", 요약="지정 여부 확인", 대상="구매팀")]
        m, _ = self.annotate(["제안요청서", "공동도급 허용하지 않음", "직접생산확인증명서 소지"], fs, "제안요청서")
        by = {x[0]: x[2] for x in m}
        self.assertEqual(by["②-3"][0], "[답변 요청] 불허 사유 없음")
        self.assertIn("■ 답변해 주세요", by["②-3"])
        self.assertNotIn("②-6", by)

    def test_refuses_in_place_output(self):
        tmp = tempfile.mkdtemp()
        make_hwpx(os.path.join(tmp, "d.hwpx"), ["가"])
        with open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as fp:
            json.dump({"findings": []}, fp)
        rc, _, _ = run("annotate_hwpx.py", "d.hwpx", "r.json", "--doc", "공고문", "-o", "d.hwpx", cwd=tmp)
        self.assertEqual(rc, 2)
        with zipfile.ZipFile(os.path.join(tmp, "d.hwpx")) as z:
            self.assertIn("Contents/section0.xml", z.namelist())


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False)


class Guidance(unittest.TestCase):
    """지침·체크리스트·스크립트가 서로 어긋나면 모델이 없는 항목·근거를 지어낸다."""

    def test_no_dangling_checklist_refs(self):
        sys.path.insert(0, SCRIPTS)
        from checklist_items import parse
        ids = {i["id"] for i in parse()}
        with open(os.path.join(ROOT, "references", "checklist.md"), encoding="utf-8") as fp:
            refs = set(re.findall(r"[①-⑥]-\d+", fp.read()))
        self.assertEqual(sorted(refs - ids), [])

    def test_script_scope_matches_emitted_ids(self):
        with open(os.path.join(SCRIPTS, "check_numbers.py"), encoding="utf-8") as fp:
            src = fp.read()
        emitted = set(re.findall(r'add\("([①-⑥]-\d+)"', src)) | set(re.findall(r'id_, name = "([①-⑥]-\d+)"', src))
        emitted |= set(re.findall(r'\("[^"]+", "([①-⑥]-\d+)", "', src))
        sys.path.insert(0, SCRIPTS)
        from check_numbers import SCRIPT_SCOPE
        self.assertEqual(sorted(emitted - set(SCRIPT_SCOPE)), [])

    def test_skill_md_mentions_only_existing_files(self):
        with open(os.path.join(ROOT, "SKILL.md"), encoding="utf-8") as fp:
            text = fp.read()
        for rel in set(re.findall(r"(?:scripts|references)/[\w.-]+\.(?:py|md|json)", text)):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)
        desc = re.search(r'^description: "(.*)"$', text, re.M).group(1)
        self.assertLessEqual(len(desc), 500)  # 하네스별 스킬 설명 길이 제한

    def test_checklist_items_files_fit_harness_output(self):
        # 시트 파일·화면 출력이 하네스 출력 한도(~10KB) 안이어야 잘리지 않는다
        tmp = tempfile.mkdtemp()
        rc, out, err = run("checklist_items.py", "①②③④⑤⑥", "--sw", "-o", "items", cwd=tmp)
        self.assertEqual(rc, 0, err)
        self.assertLess(len(out.encode("utf-8")), 2000)
        for name in [n for n in os.listdir(os.path.join(tmp, "items")) if n.endswith(".md")]:  # 모델이 읽는 파일
            self.assertLess(os.path.getsize(os.path.join(tmp, "items", name)), 10000, name)
        with open(os.path.join(tmp, "items", "coverage.json"), encoding="utf-8") as fp:
            sheet_files = json.load(fp)["파일"]
        pieces = []
        for name in sheet_files:
            if name.startswith("②"):
                with open(os.path.join(tmp, "items", name), encoding="utf-8") as fp:
                    pieces.append(fp.read())
        sheet = "\n".join(pieces)
        self.assertIn("②-17 | ★필수 | script+ | ", sheet)
        self.assertIn("②-1 | ★필수 | script+", sheet)  # 역할·기산점 판독은 모델이 맡는다
        with open(os.path.join(tmp, "items", "review_external.json"), encoding="utf-8") as fp:
            ext = json.load(fp)["findings"]
        self.assertTrue(ext and all(x["판정"] == "확인필요" for x in ext))

    def test_outline_flags_numbering_gap(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "t.txt"), "w", encoding="utf-8") as fp:
            fp.write("# 원본: t.hwpx\n[문단 1] Ⅳ. 입찰 일반사항\n[문단 2] 1. 입찰 참가자격\n"
                     "[문단 3 표1 1-1] 2. 표 안은 제외\n[문단 4] 3. 입찰 방식\n[문단 5] Ⅴ. 작성 지침\n"
                     "[문단 6] 1. 제안서의 효력\n")
        rc, out, err = run("outline.py", "t.txt", "--gaps", cwd=tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("[문단 4] 3. 입찰 방식  << 번호 건너뜀: 앞 번호 1", out)
        self.assertIn("번호 문제 1건", out)  # Ⅴ 아래 1.은 새로 셈다

    def test_show_lines_byte_budget(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "t.txt"), "w", encoding="utf-8") as fp:
            fp.write("\n".join("가" * 300 for _ in range(100)))
        rc, out, _ = run("show_lines.py", "t.txt", "1", "--max-bytes", "3000", cwd=tmp)
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(out.encode("utf-8")), 3100)
        self.assertIn("[next: 4 of 100]", out)


class Validate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "ex"))
        with open(os.path.join(self.tmp, "ex", "rfp.txt"), "w", encoding="utf-8") as fp:
            fp.write("# 원본: rfp.hwpx\n[문단 1] 제안서 인쇄본 10부와 USB 1개를 밀봉하여 제출\n"
                     "[문단 2] 사업이해도 35점\n[문단 3] 수행방법론 45점\n[문단 4] CCC+ 이하 3.0\n"
                     "[문단 5] 실적 없음 2.0\n[문단 6] 기술평가 80점, 가격평가 10점\n[문단 7] 하도급 허용\n"
                     "[문단 8] 서울특별시 소재 업체\n[문단 9] 금220,000,000원(부가세 포함)\n[원가!9행] 합계 210,000,000\n"
                     "[문단 10] 공고일 2026-11-03\n[문단 11] 제출마감일 2026-11-10\n"
                     "[문단 12] 공동수급체 구성원수 7인, 최소지분율 5%\n")
        self.good = {"id": "②-20", "항목": "전자입찰 기준 현행화", "중요도": "★필수", "판정": "수정필요",
                     "적용성": "적용", "증거상태": "판독완료", "대상": "작성자", "기준유형": ["법령·공식기준"],
                     "문서": "제안요청서", "위치": "[문단 1]", "원문": "인쇄본 10부와…밀봉하여 제출",
                     "요약": "비전자 제출 문구", "조치": "나라장터 전자제출로", "수정안": "전자 제출(S-07)",
                     "근거": "전자조달법 제11조, 조달청 제안서평가 세부기준 제6조의2"}

    def check(self, findings, *extra):
        write_json(os.path.join(self.tmp, "r.json"), {"findings": findings})
        return run("validate_review.py", "r.json", "--extracted", "ex", *extra, cwd=self.tmp)

    def test_good_finding_passes(self):
        rc, out, _ = self.check([self.good])
        self.assertEqual(rc, 0, out)

    def test_paraphrased_quote_fails(self):
        rc, out, _ = self.check([dict(self.good, 원문="인쇄본 10부, USB를 밀봉 제출")])
        self.assertEqual(rc, 1)
        self.assertIn("원문이 추출 텍스트에 없음", out)

    def test_invented_basis_fails(self):
        rc, out, _ = self.check([dict(self.good, 근거="전자조달법 제11조, 조달청 제안서평가 세부기준 제6조의2 / 실무가이드 p.999")])
        self.assertEqual(rc, 1)
        self.assertIn("실무가이드 p.999", out)

    def test_unknown_id_and_bad_verdict_fail(self):
        rc, out, _ = self.check([dict(self.good, id="②-19", 판정="부적합")])
        self.assertEqual(rc, 1)
        self.assertIn("체크리스트에 없는 id", out)
        self.assertIn("판정 '부적합'", out)

    def test_short_or_object_quote_fails(self):
        rc, out, _ = self.check([dict(self.good, 원문="-"), dict(self.good, 항목="x", 원문="[수식: 평점]")])
        self.assertEqual(rc, 1)
        self.assertIn("너무 짧아", out)
        self.assertIn("개체 표시", out)

    def test_paragraph_number_in_memo_text_warns(self):
        rc, out, _ = self.check([dict(self.good, 문제점="인쇄본은 [문단 1]에 있습니다.")])
        self.assertEqual(rc, 0, out)
        self.assertIn("[문단 n]/S-nn", out)

    def test_question_needs_quote_and_action(self):
        rc, out, _ = self.check([dict(self.good, 판정="확인필요", 문제점="x", 조치="", 질의=True)])
        self.assertEqual(rc, 1)
        self.assertIn("질의 메모", out)

    def test_external_stub_is_valid(self):
        run("checklist_items.py", "①②③⑤", "-o", "items", cwd=self.tmp)
        rc, out, _ = run("validate_review.py", "items/review_external.json", "--extracted", "ex", cwd=self.tmp)
        self.assertEqual(rc, 0, out)

    def test_coverage_reports_missing_items(self):
        rc, out, _ = self.check([self.good], "--sheets", "②")
        self.assertEqual(rc, 1)
        self.assertIn("누락: ②-1 ", out)
        self.assertNotIn("누락: ②-20 ", out)

    def test_script_findings_cite_checklist_basis(self):
        # check_numbers가 쓰는 근거·id도 체크리스트와 맞아야 한다(모델이 그대로 따라 쓴다)
        facts = dict(FACTS, 공고일=sourced_value("2026-11-03", "공고일 2026-11-03", "[문단 10]"),
                     제출마감일=sourced_value("2026-11-10", "제출마감일 2026-11-10", "[문단 11]"),
                     공동계약={"공고문": {"값": "불허"}, "제안요청서": {"값": "허용"},
                           "구성원수": sourced_value(7, "공동수급체 구성원수 7인, 최소지분율 5%", "[문단 12]"),
                           "최소지분율": sourced_value(5, "공동수급체 구성원수 7인, 최소지분율 5%", "[문단 12]")},
                     실적제한={"있음": True, "문서": "공고문", "원문": "", "위치": ""},
                     협상적격자기준_퍼센트={"값": 80}, 평점산식_하한_퍼센트={"값": 60},
                     실적건수평가={"기준금액": 200000000, "최대인정건수": 3, "사업예산": 220000000})
        facts["지역제한"] = dict(facts["지역제한"], 원문="서울특별시 소재 업체")
        write_json(os.path.join(self.tmp, "f.json"), facts)
        rc, _, err = run("check_numbers.py", "f.json", "-o", "n.json", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rc, out, _ = run("validate_review.py", "n.json", "--extracted", "ex", cwd=self.tmp)
        self.assertNotIn("[오류]", out)
        self.assertNotIn("다른 항목의 근거", out)


class ConvertGuard(unittest.TestCase):
    def test_existing_hwpx_not_overwritten(self):
        sys.path.insert(0, SCRIPTS)
        from convert_to_hwpx import convert_hwp_to_hwpx
        tmp = tempfile.mkdtemp()
        src, dst = os.path.join(tmp, "a.hwp"), os.path.join(tmp, "a.hwpx")
        for p in (src, dst):
            with open(p, "wb") as fp:
                fp.write(b"x")
        os.utime(src, (1000, 1000))
        os.utime(dst, (2000, 2000))
        with self.assertRaises(RuntimeError):  # 수정 시각만으로 변환 출처를 증명할 수 없음
            convert_hwp_to_hwpx(src)
        os.utime(dst, (500, 500))
        with self.assertRaises(RuntimeError):  # 더 오래된 같은 이름 파일은 덮어쓰지 않음
            convert_hwp_to_hwpx(src)
        with open(dst, "rb") as fp:
            self.assertEqual(fp.read(), b"x")


class MakeReport(unittest.TestCase):
    def test_reference_rows_merged_into_main(self):
        import openpyxl
        tmp = tempfile.mkdtemp()
        base = {"id": "②-5", "중요도": "★필수", "판정": "수정필요", "문서": "제안요청서"}
        fs = [dict(base, 항목="과업명", 위치="[문단 2]", 원문="1. 과업명"),
              dict(base, 항목="과업명(②-5 참조)", 위치="[문단 9]", 원문="2. 과업명", 중요도="참고", 참조=True)]
        with open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as fp:
            json.dump({"findings": fs}, fp, ensure_ascii=False)
        rc, out, err = run("make_report.py", "r.json", "-o", "x.xlsx", cwd=tmp)
        self.assertEqual(rc, 0, out + err)
        ws = openpyxl.load_workbook(os.path.join(tmp, "x.xlsx"))["수정요청"]
        rows = [r for r in ws.iter_rows(min_row=6, values_only=True) if r[0]]
        self.assertEqual(len(rows), 1)
        self.assertIn("[문단 9]", rows[0][5])


if __name__ == "__main__":
    unittest.main()
