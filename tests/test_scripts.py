"""scripts/ 회귀 테스트. 실행: python -m unittest discover -s tests

한/글 없이 돌아가도록 HWPX는 최소 구조(zip + section XML)로 직접 만든다.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"

RFP = ["제안요청서", "사업명: 연구장비 유지보수 용역", "사업예산: 금330,000,000원(부가세 포함)",
       "사업기간: 계약일로부터 12개월", "제안서는 인쇄본 10부를 제출한다", "기술평가 합계 90점"]
NOTICE = ["입찰공고", "추정가격: 300,000,000원(부가세 별도)"]
GUIDE = ["[검토지침]", "제안서는 전자 제출을 원칙으로 하며 인쇄본 제출을 요구하지 않는다"]


def run(script, *args, cwd):
    """하네스처럼 파이프로 실행한다(PYTHONIOENCODING 없이). stdout은 UTF-8이어야 한다."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args], cwd=cwd,
                       capture_output=True, env=env)
    return p.returncode, p.stdout.decode("utf-8") + p.stderr.decode("utf-8")


def make_hwpx(path, paragraphs):
    body = "".join(f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
                   f"<hp:t>{escape(t)}</hp:t></hp:run></hp:p>" for i, t in enumerate(paragraphs))
    sec = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
           f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)


def memos(path):
    """[(메모 줄 목록, 메모가 달린 문단 텍스트, 형광펜 색)]"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("Contents/section0.xml"))
    out = []
    for p in root.findall("{%s}p" % HP):
        memo_ts = {id(t) for fb in p.iter("{%s}fieldBegin" % HP) for t in fb.iter("{%s}t" % HP)}
        # 형광펜 표시 뒤의 글자는 하위 요소의 tail에 있다
        text = "".join((t.text or "") + "".join(x.tail or "" for x in t)
                       for t in p.iter("{%s}t" % HP) if id(t) not in memo_ts)
        colors = [m.get("color") for m in p.iter("{%s}markpenBegin" % HP)]
        for fb in p.iter("{%s}fieldBegin" % HP):
            lines = ["".join(x.itertext()) for x in fb.find("{%s}subList" % HP).findall("{%s}p" % HP)]
            out.append((lines, text, colors))
    return out


def sha(path):
    with open(path, "rb") as fp:
        return hashlib.sha256(fp.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def path(self, name):
        return os.path.join(self.d, name)

    def write_json(self, name, data):
        with open(self.path(name), "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)
        return self.path(name)

    def finding(self, **kw):
        f = {"id": "R1", "판정": "수정필요", "문서": "제안요청서", "위치": "[문단 5]",
             "원문": "인쇄본 10부를 제출한다", "요약": "인쇄본 제출 요구 삭제",
             "문제점": "지침은 전자 제출을 원칙으로 합니다.", "수정안": "\"전자 제출\"로 바꿔 주세요.",
             "근거": "제안서는 전자 제출을 원칙으로 하며 인쇄본 제출을 요구하지 않는다"}
        f.update(kw)
        return f

    def extract_all(self):
        make_hwpx(self.path("제안요청서.hwpx"), RFP)
        make_hwpx(self.path("공고문.hwpx"), NOTICE)
        with open(self.path("지침.txt"), "w", encoding="utf-8") as fp:
            fp.write("\n".join(GUIDE) + "\n")
        rc, out = run("extract_text.py", "제안요청서.hwpx", "공고문.hwpx", "지침.txt", "-o", "extracted", cwd=self.d)
        self.assertEqual(rc, 0, out)

    def validate(self, *files):
        return run("validate_review.py", *files, "--guide", "extracted/지침.txt",
                   "--doc", "제안요청서=extracted/제안요청서.txt", "--doc", "공고문=extracted/공고문.txt", cwd=self.d)


class Extract(Base):
    def test_hwpx_lines_have_paragraph_tags_and_resume_check_detects_change(self):
        self.extract_all()
        with open(self.path("extracted/제안요청서.txt"), encoding="utf-8") as fp:
            text = fp.read()
        self.assertIn("[문단 5] 제안서는 인쇄본 10부를 제출한다", text)
        self.assertEqual(run("extract_text.py", "--check", "-o", "extracted", cwd=self.d)[0], 0)
        with open(self.path("지침.txt"), "a", encoding="utf-8") as fp:
            fp.write("새 지침 항목\n")
        rc, out = run("extract_text.py", "--check", "-o", "extracted", cwd=self.d)
        self.assertEqual(rc, 1)
        self.assertIn("지침.txt", out)

    def test_check_without_manifest_requires_restart(self):
        rc, out = run("extract_text.py", "--check", "-o", "extracted", cwd=self.d)
        self.assertEqual(rc, 1)
        self.assertIn("재시작", out)

    def test_xlsx_formula_without_cached_value_is_not_dropped(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl 없음")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "용역 지침"
        ws["A1"], ws["B1"], ws["C1"] = "배점", 10, "=B1*2"
        wb.save(self.path("지침.xlsx"))  # openpyxl은 계산값을 저장하지 않는다
        rc, out = run("extract_text.py", "지침.xlsx", "-o", "extracted", cwd=self.d)
        self.assertEqual(rc, 0, out)
        with open(self.path("extracted/지침.txt"), encoding="utf-8") as fp:
            text = fp.read()
        self.assertIn("[용역 지침!1행] A1=배점 | B1=10 | C1==B1*2(계산값 없음)", text)


class Numbers(Base):
    def entry(self, doc, where, quote, value):
        return {"문서": doc, "위치": where, "원문": quote, "값": value}

    def numbers(self, facts):
        self.write_json("facts.json", facts)
        rc, out = run("check_numbers.py", "facts.json", "-o", "numeric.json", cwd=self.d)
        if rc != 0:
            return rc, out, None
        with open(self.path("numeric.json"), encoding="utf-8") as fp:
            return rc, out, json.load(fp)["findings"]

    def test_vat_expression_makes_equal_amounts_match(self):
        rc, out, found = self.numbers({"일치": [{"항목": "사업금액", "값": [
            self.entry("제안요청서", "[문단 3]", "금330,000,000원", "330,000,000"),
            self.entry("공고문", "[문단 2]", "300,000,000원", "300,000,000*1.1")]}]})
        self.assertEqual(rc, 0, out)
        self.assertEqual(found, [])

    def test_mismatch_marks_every_location(self):
        rc, out, found = self.numbers({"일치": [{"항목": "사업금액", "값": [
            self.entry("제안요청서", "[문단 3]", "금330,000,000원", 330000000),
            self.entry("공고문", "[문단 2]", "320,000,000원", 320000000)]}]})
        self.assertEqual(rc, 0, out)
        self.assertEqual([(f["문서"], f["판정"], f["근거"]) for f in found],
                         [("제안요청서", "수정필요", "문서 자체 오류"), ("공고문", "수정필요", "문서 자체 오류")])
        self.assertIn("320,000,000", found[0]["문제점"])

    def test_wrong_total_is_reported_at_total(self):
        rc, out, found = self.numbers({"합계": [{"항목": "기술평가 배점 합계", "근거": "지침 문구",
                                                "부분": [self.entry("제안요청서", "[문단 9]", "40", 40),
                                                         self.entry("제안요청서", "[문단 10]", "60", "30+30")],
                                                "합계": self.entry("제안요청서", "[문단 6]", "합계 90점", 90)}]})
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["위치"], found[0]["근거"]), ("[문단 6]", "지침 문구"))
        self.assertIn("100", found[0]["문제점"])

    def test_non_arithmetic_value_is_rejected_without_output(self):
        rc, out, _ = self.numbers({"일치": [{"항목": "x", "값": [
            self.entry("제안요청서", "[문단 3]", "abcd", "__import__('os')"),
            self.entry("공고문", "[문단 2]", "abcd", 1)]}]})
        self.assertEqual(rc, 1)
        self.assertIn("사칙연산 식이 아님", out)
        self.assertFalse(os.path.exists(self.path("numeric.json")))


class Validate(Base):
    def setUp(self):
        super().setUp()
        self.extract_all()

    def test_grounded_finding_passes(self):
        rc, out = self.validate(self.write_json("r.json", {"findings": [
            self.finding(), self.finding(id="R2", 판정="확인필요", 위치="[문단 2]", 원문="연구장비 유지보수 용역",
                                         근거="문서 자체 오류", 수정안="정확한 사업명을 알려 주세요.")]}))
        self.assertEqual(rc, 0, out)

    def test_fabricated_quote_and_basis_and_ok_verdict_are_rejected(self):
        rc, out = self.validate(self.write_json("r.json", {"findings": [
            self.finding(원문="인쇄본 5부를 제출한다"),
            self.finding(id="R2", 근거="국가계약법 시행령 제43조"),
            self.finding(id="R3", 판정="적합")]}))
        self.assertEqual(rc, 1)
        self.assertIn("R1: 원문이 제안요청서 텍스트에 없습니다", out)
        self.assertIn("R2: 근거가 지침에 없습니다", out)
        self.assertIn("R3: 판정 '적합'", out)

    def test_quote_from_other_document_and_duplicate_id_are_rejected(self):
        a = self.write_json("a.json", {"findings": [self.finding(원문="추정가격: 300,000,000원")]})
        b = self.write_json("b.json", {"findings": [self.finding()]})
        rc, out = self.validate(a, b)
        self.assertEqual(rc, 1)
        self.assertIn("원문이 제안요청서 텍스트에 없습니다", out)
        self.assertIn("id 중복", out)


class Annotate(Base):
    def setUp(self):
        super().setUp()
        make_hwpx(self.path("제안요청서.hwpx"), RFP)

    def annotate(self, findings, out="output/제안요청서_검토메모.hwpx"):
        f = self.write_json("r.json", {"findings": findings})
        return run("annotate_hwpx.py", "제안요청서.hwpx", f, "--doc", "제안요청서", "-o", out, cwd=self.d)

    def test_memos_mark_quotes_and_keep_original(self):
        before = sha(self.path("제안요청서.hwpx"))
        rc, out = self.annotate([
            self.finding(),
            self.finding(id="R2", 판정="확인필요", 위치="[문단 4]", 원문="계약일로부터 12개월",
                         요약="착수 기준일 확인", 수정안="착수일 기준인지 알려 주세요.", 근거="문서 자체 오류"),
            self.finding(id="R3", 원문="해당 내용 없음", 위치="[문단 6] 근처", 요약="평가표 누락"),
            self.finding(id="R4", 문서="공고문", 원문="입찰공고")])
        self.assertEqual(rc, 0, out)
        self.assertEqual(sha(self.path("제안요청서.hwpx")), before)
        got = memos(self.path("output/제안요청서_검토메모.hwpx"))
        by_text = {text: (lines, colors) for lines, text, colors in got}
        lines, colors = by_text["제안서는 인쇄본 10부를 제출한다"]
        self.assertEqual(lines[0], "[수정 필요] 인쇄본 제출 요구 삭제")
        self.assertIn("■ 근거(검토 지침)", lines)
        self.assertEqual(colors, ["#FFFF00"])
        lines, colors = by_text["사업기간: 계약일로부터 12개월"]
        self.assertEqual(lines[0], "[확인 요청] 착수 기준일 확인")
        self.assertIn(" - 문서 내용 대조(오타·빈칸·불일치)", lines)
        self.assertEqual(colors, ["#9FE2FF"])
        summary = by_text["제안요청서"][0]
        self.assertIn("이 문서에 고칠 곳 2건, 확인이 필요한 곳 1건에 메모를 달았습니다.", summary)
        self.assertIn(" ([문단 6] 근처) [수정 필요] 평가표 누락", summary)
        self.assertFalse(any("입찰공고" in " ".join(lines) for lines, _, _ in got))  # 다른 문서의 지적

    def test_existing_output_is_kept_and_new_name_is_used(self):
        os.makedirs(self.path("output"))
        with open(self.path("output/제안요청서_검토메모.hwpx"), "wb") as fp:
            fp.write(b"previous result")
        rc, out = self.annotate([self.finding()])
        self.assertEqual(rc, 0, out)
        self.assertIn("제안요청서_검토메모_2.hwpx", out)
        with open(self.path("output/제안요청서_검토메모.hwpx"), "rb") as fp:
            self.assertEqual(fp.read(), b"previous result")
        self.assertEqual(sorted(os.listdir(self.path("output"))),
                         ["제안요청서_검토메모.hwpx", "제안요청서_검토메모_2.hwpx"])

    def test_output_equal_to_source_is_refused(self):
        before = sha(self.path("제안요청서.hwpx"))
        rc, out = self.annotate([self.finding()], out="제안요청서.hwpx")
        self.assertEqual(rc, 2)
        self.assertEqual(sha(self.path("제안요청서.hwpx")), before)


class Pipeline(Base):
    def test_extract_numbers_validate_annotate(self):
        self.extract_all()
        self.write_json("facts.json", {"일치": [{"항목": "사업금액", "값": [
            {"문서": "제안요청서", "위치": "[문단 3]", "원문": "금330,000,000원", "값": "330,000,000"},
            {"문서": "공고문", "위치": "[문단 2]", "원문": "300,000,000원", "값": "300,000,000*1.2"}]}]})
        rc, out = run("check_numbers.py", "facts.json", "-o", "numeric.json", cwd=self.d)
        self.assertEqual(rc, 0, out)
        review = self.write_json("review.json", {"findings": [self.finding()]})
        rc, out = self.validate("numeric.json", review)
        self.assertEqual(rc, 0, out)
        rc, out = run("annotate_hwpx.py", "제안요청서.hwpx", "numeric.json", review, "--doc", "제안요청서",
                      "-o", "output/제안요청서_검토메모.hwpx", cwd=self.d)
        self.assertEqual(rc, 0, out)
        titles = [lines[0] for lines, _, _ in memos(self.path("output/제안요청서_검토메모.hwpx"))]
        self.assertIn("[수정 필요] 사업금액 불일치", titles)
        self.assertIn("[수정 필요] 인쇄본 제출 요구 삭제", titles)


if __name__ == "__main__":
    unittest.main()
