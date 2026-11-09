"""Mocked safe_annotate lifecycle regressions; no Hancom COM is started."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import safe_annotate


class CapturedText(io.StringIO):
    def reconfigure(self, **_kwargs):
        pass


class SafeAnnotateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.source = os.path.join(self.root, "input.hwpx")
        self.findings_path = os.path.join(self.root, "findings.json")
        with open(self.source, "wb") as stream:
            stream.write(b"source document")
        with open(self.findings_path, "w", encoding="utf-8") as stream:
            json.dump({"findings": []}, stream)
        self.output = os.path.join(self.root, "work", "memo.hwpx")
        os.makedirs(os.path.dirname(self.output))

    @staticmethod
    def finding(identifier, doc="제안요청서", verdict="수정필요", **extra):
        result = {
            "id": identifier,
            "판정": verdict,
            "문서": doc,
            "원문": "원문 내용",
            "요약": f"요약 {identifier}",
            "수정안": f"수정안 {identifier}",
        }
        result.update(extra)
        return result

    def invoke(self, findings, output=None, opens=(True,), run=None):
        output = output or self.output
        stdout, stderr = CapturedText(), CapturedText()
        opener = mock.Mock()
        opener.opens.side_effect = list(opens)
        calls = []

        def run_annotate(_source, current_findings, _doc, destination):
            calls.append((destination, [dict(finding) for finding in current_findings]))
            if run is not None:
                return run(destination, current_findings)
            with open(destination, "xb") as stream:
                stream.write(f"trial-{len(calls)}".encode("ascii"))
            return True

        argv = [self.source, self.findings_path, "--doc", "제안요청서", "-o", output]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with mock.patch.object(safe_annotate, "load_merged", return_value=findings), \
                    mock.patch.object(safe_annotate, "HwpOpener", return_value=opener) as opener_factory, \
                    mock.patch.object(safe_annotate, "run_annotate", side_effect=run_annotate):
                result = safe_annotate.main(argv)
        return result, calls, opener, opener_factory, stdout.getvalue(), stderr.getvalue()

    def test_successful_first_trial_publishes_exclusively_and_preserves_user_sibling_trial(self):
        findings = [self.finding("R1")]
        sibling_trial = self.output + ".trial.hwpx"
        with open(sibling_trial, "wb") as stream:
            stream.write(b"user sibling trial")

        result, calls, opener, _, _, _ = self.invoke(findings)

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        trial_path = calls[0][0]
        self.assertNotEqual(trial_path, sibling_trial)
        self.assertTrue(os.path.basename(os.path.dirname(trial_path)).startswith(".safe-annotate-"))
        opener.opens.assert_called_once_with(trial_path)
        with open(self.output, "rb") as stream:
            self.assertEqual(stream.read(), b"trial-1")
        with open(sibling_trial, "rb") as stream:
            self.assertEqual(stream.read(), b"user sibling trial")
        self.assertFalse(os.path.exists(os.path.dirname(trial_path)))

    def test_fallback_uses_fresh_private_trial_per_attempt_and_preserves_other_documents(self):
        author_1 = self.finding("R1")
        author_2 = self.finding("R2", verdict="확인필요")
        other_doc = self.finding("R3", doc="공고문")
        findings = [author_1, author_2, other_doc]

        result, calls, opener, _, _, _ = self.invoke(findings, opens=(False, False, True, True))

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 4)  # all-inline, two per-finding probes, final artifact
        trial_paths = [path for path, _ in calls]
        self.assertEqual(len(set(trial_paths)), len(trial_paths))
        self.assertEqual(opener.opens.call_count, 4)
        self.assertTrue(all(path.startswith(os.path.join(self.root, "work", ".safe-annotate-"))
                            for path in trial_paths))

        # The failed inline probe is summarized; the passing one and other documents stay unchanged.
        final_findings = calls[-1][1]
        by_id = {finding["id"]: finding for finding in final_findings}
        self.assertEqual(by_id[author_1["id"]]["원문"], "해당 내용 없음")
        self.assertEqual(by_id[author_2["id"]], author_2)
        self.assertEqual(by_id[other_doc["id"]], other_doc)

    def test_existing_output_is_refused_before_com_and_preserved(self):
        with open(self.output, "wb") as stream:
            stream.write(b"user output")
        findings = [self.finding("R1")]
        stdout, stderr = CapturedText(), CapturedText()
        argv = [self.source, self.findings_path, "--doc", "제안요청서", "-o", self.output]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with mock.patch.object(safe_annotate, "load_merged", return_value=findings), \
                    mock.patch.object(safe_annotate, "HwpOpener") as opener:
                result = safe_annotate.main(argv)
        self.assertEqual(result, 2)
        opener.assert_not_called()
        self.assertIn("출력 파일이 이미 있습니다", stderr.getvalue())
        with open(self.output, "rb") as stream:
            self.assertEqual(stream.read(), b"user output")

    def test_output_created_after_precheck_is_not_clobbered_at_publish(self):
        findings = [self.finding("R1")]
        stdout, stderr = CapturedText(), CapturedText()
        opener = mock.Mock()

        def create_user_output(_trial):
            with open(self.output, "xb") as stream:
                stream.write(b"concurrent user output")
            return True

        def create_trial(*args):
            with open(args[-1], "xb") as stream:
                stream.write(b"annotated trial")
            return True

        opener.opens.side_effect = create_user_output
        argv = [self.source, self.findings_path, "--doc", "제안요청서", "-o", self.output]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with mock.patch.object(safe_annotate, "load_merged", return_value=findings), \
                    mock.patch.object(safe_annotate, "HwpOpener", return_value=opener), \
                    mock.patch.object(safe_annotate, "run_annotate", side_effect=create_trial):
                result = safe_annotate.main(argv)
        self.assertEqual(result, 2)
        self.assertIn("출력 파일이 이미 있습니다", stderr.getvalue())
        with open(self.output, "rb") as stream:
            self.assertEqual(stream.read(), b"concurrent user output")

    def test_output_alias_of_source_is_refused_before_loading_or_com(self):
        try:
            os.link(self.source, self.output)
        except OSError as exc:
            self.skipTest(f"hard-link aliases unavailable: {exc}")
        stdout, stderr = CapturedText(), CapturedText()
        argv = [self.source, self.findings_path, "--doc", "제안요청서", "-o", self.output]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with mock.patch.object(safe_annotate, "load_merged") as loader, \
                    mock.patch.object(safe_annotate, "HwpOpener") as opener:
                result = safe_annotate.main(argv)
        self.assertEqual(result, 2)
        loader.assert_not_called()
        opener.assert_not_called()
        self.assertIn("alias", stderr.getvalue())
        with open(self.source, "rb") as stream:
            self.assertEqual(stream.read(), b"source document")
        with open(self.output, "rb") as stream:
            self.assertEqual(stream.read(), b"source document")

    def test_failed_attempt_preserves_private_trial_and_diagnostics(self):
        findings = [self.finding("R1")]

        def fail_run(destination, _findings):
            with open(destination, "xb") as stream:
                stream.write(b"partial trial")
            with open(destination + ".findings.json", "w", encoding="utf-8") as stream:
                stream.write("diagnostic findings")
            with open(destination + ".log", "w", encoding="utf-8") as stream:
                stream.write("annotate failure")
            return False

        result, calls, _, _, _, stderr = self.invoke(findings, run=fail_run)

        self.assertEqual(result, 2)
        self.assertEqual(len(calls), 1)
        trial = calls[0][0]
        self.assertTrue(os.path.isfile(trial))
        self.assertTrue(os.path.isfile(trial + ".findings.json"))
        self.assertTrue(os.path.isfile(trial + ".log"))
        self.assertIn(os.path.dirname(trial), stderr)
        self.assertFalse(os.path.exists(self.output))

    def test_findings_for_other_documents_are_passed_through_unchanged(self):
        other = self.finding("R3", doc="공고문")
        result, calls, _, _, _, _ = self.invoke([other], opens=(True,))
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][1], [other])

if __name__ == "__main__":
    unittest.main()
