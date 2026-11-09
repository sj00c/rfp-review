"""Focused regression tests for finding audience and rendered result contracts."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def run(script, *args, cwd):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    process = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args], cwd=cwd,
                             capture_output=True, env=env)
    return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)


def make_hwpx(path, paragraphs):
    body = "".join(
        f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
        f"<hp:t>{escape(text)}</hp:t></hp:run></hp:p>"
        for i, text in enumerate(paragraphs)
    )
    section = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
               f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">{body}</hs:sec>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section)


def memo_records(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Contents/section0.xml"))
    records = {}
    for field in root.iter(f"{{{HP}}}fieldBegin"):
        sublist = field.find(f"{{{HP}}}subList")
        if sublist is None:
            continue
        lines = ["".join(paragraph.itertext()) for paragraph in sublist.findall(f"{{{HP}}}p")]
        if not lines:
            continue
        if lines[0].startswith("[입찰서류 검토 요약]"):
            records["summary"] = lines
            continue
        for line in lines:
            if line.startswith("(점검번호 ") and line.endswith(")"):
                records[line[len("(점검번호 "):-1]] = lines
                break
    return records


def base_finding(id_, item, doc, quote, verdict="수정필요", **extra):
    return {
        "id": id_, "항목": item, "중요도": "★필수", "판정": verdict, "문서": doc,
        "위치": "[문단 1]", "원문": quote, "요약": item, "문제점": "문구를 수정해야 합니다.",
        "조치": "문구를 고쳐 주세요.", "수정안": "수정된 문구", "근거": "기준 자료",
        **extra,
    }


class AnnotationContract(unittest.TestCase):
    def test_supplementary_source_quote_is_not_rfp_text(self):
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import annotate_hwpx

        for role in ("기관운영자료", "기타"):
            finding = {"문서": "제안요청서", "원문": f"[{role}] 별도 기준자료의 원문"}
            self.assertIsNone(annotate_hwpx.quote_for_doc(finding, "제안요청서"))

    def test_only_author_findings_are_annotated_even_with_include_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwpx")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "annotated.hwpx")
            quotes = ["작성자 수정 문구", "구매팀 수정 문구", "구매팀 확인 문구", "작성자 답변 문구",
                      "체크리스트 지정 구매팀 문구"]
            make_hwpx(source, ["제안요청서", *quotes])
            findings = [
                base_finding("②-1", "작성자 수정", "제안요청서", quotes[0], 기준유형=["기관운영"]),
                base_finding("②-2", "구매팀 수정", "제안요청서", quotes[1], 대상="구매팀"),
                base_finding("②-3", "구매팀 확인", "제안요청서", quotes[2], verdict="확인필요",
                             대상="구매팀", 질의=True),
                base_finding("②-4", "작성자 질의", "제안요청서", quotes[3], verdict="확인필요",
                             대상="작성자", 질의=True),
                base_finding("②-8", "경쟁제품 여부", "제안요청서", quotes[4]),
            ]
            write_json(findings_path, {"findings": findings})
            rc, out, err = run("annotate_hwpx.py", source, findings_path, "--doc", "제안요청서",
                               "--include-check", "-o", output, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            records = memo_records(output)
            self.assertEqual(records["summary"][0], "[입찰서류 검토 요약] AI 1차 검토 후 구매팀 확인")
            self.assertIn("②-1", records)  # omitted target defaults to author for 수정필요
            self.assertIn("②-4", records)  # explicitly-author question remains actionable
            self.assertNotIn("②-2", records)
            self.assertNotIn("②-3", records)  # --include-check cannot expose buyer-only findings
            self.assertNotIn("②-8", records)  # checklist-specific target overrides the author default

    def test_memo_shows_a_plain_basis_type_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwpx")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "annotated.hwpx")
            make_hwpx(source, ["제안요청서", "표준 문구를 수정합니다"])
            write_json(findings_path, {"findings": [
                base_finding("②-5", "근거 유형 표시", "제안요청서", "표준 문구를 수정합니다",
                             기준유형=["법령·공식기준", "사업요건"])
            ]})
            rc, out, err = run("annotate_hwpx.py", source, findings_path, "--doc", "제안요청서",
                               "-o", output, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            lines = memo_records(output)["②-5"]
            self.assertIn("■ 기준 유형", lines)
            self.assertIn(" - 법령·공식기준", lines)
            self.assertIn(" - 사업요건", lines)

    def test_quotation_tag_for_service_contract_request_form_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "request.hwpx")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "annotated.hwpx")
            quote = "계약기간은 12개월로 한다"
            make_hwpx(source, ["용역계약의뢰서", quote])
            finding = base_finding("①-1", "계약기간 확인", "용역계약의뢰서",
                                   f"[용역계약의뢰서] {quote}", 위치="용역계약의뢰서: [문단 2]")
            write_json(findings_path, {"findings": [finding]})
            rc, out, err = run("annotate_hwpx.py", source, findings_path, "--doc", "용역계약의뢰서",
                               "-o", output, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("①-1", memo_records(output))

    def test_existing_annotation_output_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwpx")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "existing.hwpx")
            make_hwpx(source, ["제안요청서", "원문 문구"])
            write_json(findings_path, {"findings": []})
            with open(output, "wb") as fp:
                fp.write(b"preserve-existing-bytes")
            rc, out, err = run("annotate_hwpx.py", source, findings_path, "--doc", "제안요청서",
                               "-o", output, cwd=tmp)
            self.assertEqual(rc, 2, out + err)
            with open(output, "rb") as fp:
                self.assertEqual(fp.read(), b"preserve-existing-bytes")

            with open(findings_path, "rb") as fp:
                original_input = fp.read()
            rc, out, err = run("make_report.py", findings_path, "-o", findings_path, cwd=tmp)
            self.assertEqual(rc, 2, out + err)
            with open(findings_path, "rb") as fp:
                self.assertEqual(fp.read(), original_input)

    def test_alias_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwpx")
            findings_path = os.path.join(tmp, "findings.json")
            alias = os.path.join(tmp, "missing", "..", "source.hwpx")
            make_hwpx(source, ["제안요청서", "원문 문구"])
            write_json(findings_path, {"findings": []})
            rc, out, err = run("annotate_hwpx.py", source, findings_path, "--doc", "제안요청서",
                               "-o", alias, cwd=tmp)
            self.assertEqual(rc, 2, out + err)
            with zipfile.ZipFile(source) as archive:
                self.assertIn("Contents/section0.xml", archive.namelist())

    def test_hwp_conversion_uses_and_cleans_an_internal_temp_copy(self):
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import annotate_hwpx
        import convert_to_hwpx

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwp")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "annotated.hwpx")
            with open(source, "wb") as fp:
                fp.write(b"hwp source")
            write_json(findings_path, {"findings": []})
            converted = {}

            def fake_convert(src, dst):
                converted["src"] = src
                converted["dst"] = dst
                make_hwpx(dst, ["제안요청서", "원문 문구"])
                return dst

            with patch.object(convert_to_hwpx, "convert_hwp_to_hwpx", side_effect=fake_convert), \
                    patch.object(sys, "argv", ["annotate_hwpx.py", source, findings_path, "--doc",
                                                "제안요청서", "-o", output]):
                rc = annotate_hwpx.main()
            self.assertEqual(rc, 0)
            self.assertNotEqual(os.path.dirname(converted["dst"]), tmp)
            self.assertFalse(os.path.exists(converted["dst"]))
            self.assertFalse(os.path.exists(os.path.join(tmp, "source.hwpx")))

    def test_hwp_conversion_failure_is_reported_without_sibling_artifact(self):
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        import annotate_hwpx
        import convert_to_hwpx

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.hwp")
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "annotated.hwpx")
            with open(source, "wb") as fp:
                fp.write(b"hwp source")
            write_json(findings_path, {"findings": []})
            captured_output = io.StringIO()
            with patch.object(convert_to_hwpx, "convert_hwp_to_hwpx", side_effect=RuntimeError("COM unavailable")), \
                    patch.object(sys, "argv", ["annotate_hwpx.py", source, findings_path, "--doc",
                                                "제안요청서", "-o", output]), \
                    contextlib.redirect_stdout(captured_output):
                rc = annotate_hwpx.main()
            self.assertEqual(rc, 2)
            self.assertIn("HWPX로 변환하지 못했습니다", captured_output.getvalue())
            self.assertFalse(os.path.exists(os.path.join(tmp, "source.hwpx")))


class ReportContract(unittest.TestCase):
    def test_document_quotes_are_not_executable_excel_formulas(self):
        import openpyxl

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "findings.json")
            target = os.path.join(tmp, "report.xlsx")
            quote = '=HYPERLINK("https://example.invalid","원문")'
            write_json(source, {"findings": [
                base_finding("기타-1", "인용 보존", "제안요청서", quote, 대상="작성자")
            ]})
            rc, out, err = run("make_report.py", source, "-o", target, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            book = openpyxl.load_workbook(target)
            self.addCleanup(book.close)
            cell = book["수정요청"]["G6"]
            self.assertEqual(cell.value, quote)
            self.assertEqual(cell.data_type, "s")

    def test_author_requests_exclude_buyers_and_all_internal_actions_are_retained(self):
        import openpyxl

        with tempfile.TemporaryDirectory() as tmp:
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "report.xlsx")
            findings = [
                base_finding("②-1", "작성자 수정", "제안요청서", "작성자 문구"),
                base_finding("②-2", "구매팀 수정", "제안요청서", "구매팀 문구", 대상="구매팀"),
                base_finding("①-3", "구매팀 확인", "", "", verdict="확인필요", 대상="구매팀"),
                base_finding("①-4", "외부 확인", "", "", verdict="확인필요", 대상="외부확인"),
                base_finding("②-8", "경쟁제품 확인", "제안요청서", "품명 확인"),
            ]
            findings[0].update(기준유형=["사업요건"], 적용성="적용", 증거상태="판독완료")
            write_json(findings_path, {"findings": findings})
            rc, out, err = run("make_report.py", findings_path, "-o", output, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            workbook = openpyxl.load_workbook(output, data_only=False)
            author_rows = [row for row in workbook["수정요청"].iter_rows(min_row=6, values_only=True) if row[0]]
            self.assertEqual(len(author_rows), 1)
            self.assertEqual(author_rows[0][3], "작성자 수정")
            self.assertEqual(author_rows[0][5], "[문단 1]")
            self.assertEqual(author_rows[0][12], "작성자")
            self.assertEqual(author_rows[0][13], "사업요건")
            self.assertEqual(author_rows[0][14:16], ("적용", "판독완료"))
            self.assertIn("법령상 필수 여부를 단독으로 뜻하지 않습니다", workbook["수정요청"]["A3"].value)
            actions = workbook["구매팀·외부 조치"]
            action_rows = [row for row in actions.iter_rows(min_row=4, values_only=True) if row[0]]
            self.assertEqual({row[2] for row in action_rows}, {"②-2", "①-3", "①-4", "②-8"})
            self.assertEqual(next(row[1] for row in action_rows if row[2] == "②-8"), "구매팀")
            self.assertNotIn("②-2", {row[1] for row in author_rows})

    def test_existing_report_output_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "existing.xlsx")
            write_json(findings_path, {"findings": []})
            with open(output, "wb") as fp:
                fp.write(b"preserve-existing-bytes")
            rc, out, err = run("make_report.py", findings_path, "-o", output, cwd=tmp)
            self.assertEqual(rc, 2, out + err)
            with open(output, "rb") as fp:
                self.assertEqual(fp.read(), b"preserve-existing-bytes")

    def test_reference_finding_does_not_inflate_summary_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings_path = os.path.join(tmp, "findings.json")
            output = os.path.join(tmp, "report.xlsx")
            base = base_finding("②-5", "기준 항목", "제안요청서", "주 지점")
            reference = base_finding("②-5", "추가 위치(②-5 참조)", "제안요청서", "반복 지점",
                                     중요도="참고", 참조=True, 위치="[문단 9]")
            write_json(findings_path, {"findings": [base, reference]})
            rc, out, err = run("make_report.py", findings_path, "-o", output, cwd=tmp)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("수정요청 1건", out)
            self.assertIn("전체 1건", out)


if __name__ == "__main__":
    unittest.main()
