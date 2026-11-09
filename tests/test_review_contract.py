"""Observed evidence and scope determine whether a verdict is admissible."""
import json
import tempfile
import unittest
from pathlib import Path

from test_scripts import run


class ContextValidation(unittest.TestCase):
    def validate(self, finding, **meta):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ex").mkdir()
            (root / "ex/rfp.txt").write_text("[문단 1] 검토 대상 문구입니다\n", encoding="utf-8")
            (root / "r.json").write_text(json.dumps({"meta": meta, "findings": [finding]}, ensure_ascii=False), encoding="utf-8")
            return run("validate_review.py", "r.json", "--extracted", "ex", cwd=tmp)

    def finding(self, **changes):
        data = {"id": "기타-1", "항목": "문서 불일치", "중요도": "확인", "판정": "수정필요",
                "적용성": "적용", "증거상태": "충돌", "기준유형": ["사업요건"], "대상": "작성자",
                "문서": "제안요청서", "위치": "[문단 1]", "원문": "검토 대상 문구입니다",
                "문제점": "동일 항목의 두 값이 다릅니다.", "조치": "두 값을 확인하고 통일", "수정안": "확인된 값으로 통일", "근거": "-"}
        data.update(changes)
        return data

    def test_unread_content_cannot_be_correction(self):
        rc, out, _ = self.validate(self.finding(증거상태="미판독"))
        self.assertEqual(rc, 1)
        self.assertIn("수정필요에는", out)

    def test_calculator_corrections_also_need_source_anchors(self):
        rc, out, _ = self.validate(self.finding(판정방식="계산", 원문="", 문서="", 위치=""))
        self.assertEqual(rc, 1)
        self.assertIn("원문이 비어", out)
        self.assertIn("문서와 위치", out)

    def test_declared_supplementary_document_roles_are_valid_quote_tags(self):
        for role in ("기관운영자료", "기타"):
            with self.subTest(role=role):
                rc, out, _ = self.validate(self.finding(문서=role, 원문=f"[{role}] 검토 대상 문구입니다"))
                self.assertEqual(rc, 0, out)

    def test_unknown_legal_scope_does_not_hide_document_conflict(self):
        rc, out, _ = self.validate(self.finding(적용성="미확인"))
        self.assertEqual(rc, 0, out)

    def test_example_is_not_authority(self):
        rc, out, _ = self.validate(self.finding(기준유형=["예시피드백"]))
        self.assertEqual(rc, 1)
        self.assertIn("예시피드백만으로", out)

    def test_confirmation_requires_audience(self):
        f = self.finding(판정="확인필요", 증거상태="미판독")
        del f["대상"]
        rc, out, _ = self.validate(f)
        self.assertEqual(rc, 1)
        self.assertIn("명시적인 대상", out)

    def test_buyer_confirmation_is_not_author_question(self):
        rc, out, _ = self.validate(self.finding(판정="확인필요", 대상="구매팀", 질의=True))
        self.assertEqual(rc, 1)
        self.assertIn("대상이 작성자", out)

    def test_nonapplicable_needs_explicit_scope(self):
        rc, out, _ = self.validate(self.finding(판정="해당없음", 적용성="미확인"))
        self.assertEqual(rc, 1)
        self.assertIn("비적용과 사유", out)

    def test_absence_needs_completed_search(self):
        rc, out, _ = self.validate(self.finding(원문="해당 내용 없음", 증거상태="미판독"))
        self.assertEqual(rc, 1)
        self.assertIn("전수검색 완료", out)
        rc, out, _ = self.validate(self.finding(원문="해당 내용 없음", 증거상태="전수검색없음", 문제점="대상 문구와 동의어 검색 결과 없음"))
        self.assertEqual(rc, 0, out)

    def test_unknown_institution_profile_cannot_authorize_threshold(self):
        profile = {"프로필ID": "P", "기관": "기관", "적용범위": "이번 사업", "출처": "기관자료",
                   "원문": "기관 기준", "위치": "[문단 1]", "적용성": "미확인"}
        rc, out, _ = self.validate(self.finding(프로필참조="P", 기준유형=["기관운영"]), 기관프로필=[profile])
        self.assertEqual(rc, 1)
        self.assertIn("기관프로필의 출처", out)

    def test_coverage_cannot_silently_drop_unknown_sw_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc, _, err = run("checklist_items.py", "⑤", "-o", "items", cwd=tmp)
            self.assertEqual(rc, 0, err)
            coverage = json.loads((root / "items/coverage.json").read_text(encoding="utf-8"))
            self.assertIsNone(coverage["SW사업"])
            self.assertIn("⑤-5", coverage["항목"])
            rc, _, err = run("checklist_items.py", "⑤", "--non-sw", "-o", "non", cwd=tmp)
            self.assertEqual(rc, 0, err)
            excluded = json.loads((root / "non/coverage.json").read_text(encoding="utf-8"))
            self.assertNotIn("⑤-5", excluded["항목"])
            self.assertFalse(excluded["SW사업"])

    def test_cross_file_duplicate_cannot_hide_original_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ex").mkdir()
            (root / "ex/input.txt").write_text("검토 대상 문구입니다", encoding="utf-8")
            for name in ("first.json", "second.json"):
                (root / name).write_text(json.dumps({"findings": [self.finding()]}, ensure_ascii=False), encoding="utf-8")
            rc, out, _ = run("validate_review.py", "first.json", "second.json", "--extracted", "ex", cwd=tmp)
            self.assertEqual(rc, 1)
            self.assertIn("(id, 항목) 중복", out)
