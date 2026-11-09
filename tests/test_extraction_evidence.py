"""Object discovery is evidence of presence, not proof of readable content."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from test_scripts import HP, HS, run


class ExtractionEvidence(unittest.TestCase):
    def test_object_sidecar_preserves_location_and_unknown_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "가격평가.hwpx"
            xml = (f'<hs:sec xmlns:hp="{HP}" xmlns:hs="{HS}">'
                   '<hp:p><hp:run><hp:t>가격 산식 기준</hp:t>'
                   '<hp:equation><hp:script>80 * x</hp:script></hp:equation>'
                   '</hp:run></hp:p><hp:p><hp:run><hp:pic/></hp:run></hp:p>'
                   '</hs:sec>')
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("Contents/section0.xml", xml)
            rc, _, err = run("extract_text.py", str(source), "-o", "text", cwd=tmp)
            self.assertEqual(rc, 0, err)
            evidence = json.loads((root / "text/가격평가.objects.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["개체조사"], "완료")
            self.assertEqual([x["위치"] for x in evidence["개체목록"]], ["[문단 1]", "[문단 1 뒤]"])
            self.assertEqual([x["종류"] for x in evidence["개체목록"]], ["수식", "그림"])
            self.assertTrue(all(x["증거상태"] == "미판독" for x in evidence["개체목록"]))
            text = (root / "text/가격평가.txt").read_text(encoding="utf-8")
            self.assertIn("[문단 1] 가격 산식 기준 [수식: 80 * x]", text)

    def test_duplicate_stems_fail_before_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            for folder in ("a", "b"):
                (root / folder / "문서.txt").write_text(folder, encoding="utf-8")
            rc, _, err = run("extract_text.py", "a/문서.txt", "b/문서.txt", "-o", "text", cwd=tmp)
            self.assertNotEqual(rc, 0)
            self.assertIn("동명 입력", err)
            self.assertFalse((root / "text").exists())

    def test_unsupported_object_inventory_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "문서.txt").write_text("검토 대상 본문", encoding="utf-8")
            rc, _, err = run("extract_text.py", "문서.txt", "-o", "text", cwd=tmp)
            self.assertEqual(rc, 0, err)
            data = json.loads((root / "text/문서.objects.json").read_text(encoding="utf-8"))
            self.assertEqual(data["개체조사"], "미지원")
