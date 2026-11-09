"""Focused lifecycle tests. Run explicitly with unittest discovery for this file."""
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import review_workspace as workspace


class ReviewWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.old_tempdir = tempfile.tempdir
        tempfile.tempdir = self.temporary.name
        self.addCleanup(setattr, tempfile, "tempdir", self.old_tempdir)
        self.base = self.temporary.name

    def write(self, relative, content):
        path = os.path.join(self.base, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(content)
        return path

    def start(self, primary=None, **kwargs):
        primary = primary or self.write("source/제안요청서.hwp", b"primary source")
        return workspace.begin(primary, **kwargs)

    def artifact(self, root, name="memo", path="work/artifacts/검토.hwpx", content=b"memo output"):
        target = os.path.join(root, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as stream:
            stream.write(content)
        workspace.checkpoint(root, name, path)
        return target

    def test_begin_maps_same_stem_inputs_and_defaults_to_primary_parent_output(self):
        primary = self.write("primary/같은이름.hwp", b"primary")
        supporting = self.write("supplement/같은이름.hwp", b"support")
        reference = self.write("refs/thresholds.json", b'{"limit": 1}')
        result = self.start(primary, inputs=[("notice", supporting)], references=[reference])
        manifest = result["manifest"]
        self.assertEqual(manifest["output_dir"], os.path.join(os.path.dirname(primary), "output"))
        self.assertEqual(manifest["intermediate_root"], "work")
        self.assertEqual([item["role"] for item in manifest["inputs"]], ["primary", "notice"])
        self.assertNotEqual(manifest["inputs"][0]["workspace_path"], manifest["inputs"][1]["workspace_path"])
        self.assertEqual(manifest["inputs"][0]["source_name"], manifest["inputs"][1]["source_name"])
        for item, expected in zip(manifest["inputs"], (b"primary", b"support")):
            self.assertEqual(item["fingerprint"], {
                "sha256": hashlib.sha256(expected).hexdigest(), "size": len(expected)})
            with open(os.path.join(result["workspace"], *item["workspace_path"].split("/")), "rb") as stream:
                self.assertEqual(stream.read(), expected)
        self.assertEqual(manifest["references"][0]["fingerprint"], {
            "kind": "file", "sha256": hashlib.sha256(b'{"limit": 1}').hexdigest(),
            "size": len(b'{"limit": 1}')})
        self.assertEqual(workspace.status(result["workspace"])["workspace_id"], manifest["workspace_id"])

    def test_explicit_output_directory_is_honored(self):
        primary = self.write("source/request.hwp", b"input")
        requested = os.path.join(self.base, "deliverables")
        manifest = self.start(primary, output_dir=requested)["manifest"]
        self.assertEqual(manifest["output_dir"], requested)

    def test_reserved_or_ambiguous_output_names_are_rejected(self):
        root = self.start()["workspace"]
        self.artifact(root)
        for filename in ("CON.hwpx", "LPT1.txt", "memo.hwpx ", "memo.", "../outside.hwpx", "a:b.hwpx"):
            with self.subTest(filename=filename):
                with self.assertRaises(workspace.WorkspaceError):
                    workspace.publish(root, {"memo": filename})

    def test_collision_suffix_is_before_memo_marker_and_retry_does_not_duplicate(self):
        result = self.start()
        root = result["workspace"]
        original = self.write("source/output/보고서_검토메모.hwpx", b"user file")
        self.artifact(root, path="work/artifacts/memo.hwpx", content=b"review memo")
        requested = "보고서_검토메모.hwpx"
        first = workspace.publish(root, {"memo": requested})
        second = workspace.publish(root, {"memo": requested})
        published = os.path.join(os.path.dirname(original), "보고서_2_검토메모.hwpx")
        self.assertEqual(os.path.normpath(first["published"][0]["path"]), os.path.normpath(published))
        self.assertTrue(second["published"][0]["already_published"])
        self.assertEqual(sorted(os.listdir(os.path.dirname(original))),
                         ["보고서_2_검토메모.hwpx", "보고서_검토메모.hwpx"])
        with open(original, "rb") as stream:
            self.assertEqual(stream.read(), b"user file")
        with open(published, "rb") as stream:
            self.assertEqual(stream.read(), b"review memo")

    def test_stale_primary_input_is_rejected(self):
        primary = self.write("source/request.hwp", b"before")
        root = self.start(primary)["workspace"]
        self.write("source/request.hwp", b"after")
        with self.assertRaisesRegex(workspace.WorkspaceError, "변경되었습니다"):
            workspace.status(root)

    def test_keyboard_interrupt_during_manifest_write_recovers_prior_manifest(self):
        root = self.start()["workspace"]
        original_output = workspace.status(root)["output_dir"]
        _, candidate = workspace._load_workspace(root, verify=False)
        candidate["output_dir"] = os.path.join(self.base, "not-committed")
        with mock.patch.object(workspace.json, "dumps", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                workspace._write_manifest(root, candidate)
        temporary_manifests = [os.path.join(root, name) for name in os.listdir(root)
                               if name.startswith(workspace.MANIFEST_TEMP + "-")]
        self.assertEqual(len(temporary_manifests), 1)
        temporary_manifest = temporary_manifests[0]
        self.assertTrue(os.path.isfile(temporary_manifest))

        resumed = workspace.status(root)

        self.assertEqual(resumed["output_dir"], original_output)
        self.assertFalse(os.path.exists(temporary_manifest))

    def test_owned_actual_leftover_manifest_is_removed_and_prior_state_resumes(self):
        root = self.start()["workspace"]
        before = workspace.status(root)
        workspace_id = before["workspace_id"]
        temporary_manifest = workspace._new_manifest_temp(root)
        with open(temporary_manifest, "xb") as stream:
            stream.write(workspace._manifest_header(workspace_id))
            stream.write(b'{"interrupted":')

        resumed = workspace.status(root)

        self.assertEqual(resumed["output_dir"], before["output_dir"])
        self.assertFalse(os.path.exists(temporary_manifest))

    def test_unowned_manifest_temporary_is_rejected_and_preserved(self):
        root = self.start()["workspace"]
        temporary_manifest = workspace._new_manifest_temp(root)
        with open(temporary_manifest, "xb") as stream:
            stream.write(b"not an owned workspace write")
        state = workspace.status(root)
        self.assertEqual(state["manifest_temporaries"][0]["reason"], "foreign transaction header; preserved")
        self.assertEqual(state["manifest_temporaries"][0]["path"], temporary_manifest)
        with open(temporary_manifest, "rb") as stream:
            self.assertEqual(stream.read(), b"not an owned workspace write")

    def test_malformed_primary_manifest_stays_rejected_and_is_not_replaced_by_temp(self):
        root = self.start()["workspace"]
        manifest_path = os.path.join(root, workspace.MANIFEST)
        with open(manifest_path, "wb") as stream:
            stream.write(b'{"truncated":')
        temporary_manifest = workspace._new_manifest_temp(root)
        with open(temporary_manifest, "xb") as stream:
            stream.write(workspace._manifest_header(os.path.basename(root)))
        with self.assertRaisesRegex(workspace.WorkspaceError, "manifest를 읽을 수 없습니다"):
            workspace.status(root)
        with open(manifest_path, "rb") as stream:
            self.assertEqual(stream.read(), b'{"truncated":')
        self.assertTrue(os.path.exists(temporary_manifest))

    def test_mismatched_owner_marker_fails_closed_without_reaping_manifest_temp(self):
        root = self.start()["workspace"]
        owner_path = os.path.join(root, workspace.OWNER)
        temporary_manifest = workspace._new_manifest_temp(root)
        with open(temporary_manifest, "xb") as stream:
            stream.write(workspace._manifest_header(os.path.basename(root)))
        with open(owner_path, "w", encoding="ascii") as stream:
            stream.write("other-workspace\n")

        with self.assertRaisesRegex(workspace.WorkspaceError, "소유권 marker와 manifest가 일치"):
            workspace.status(root)

        self.assertTrue(os.path.exists(temporary_manifest))
        with open(temporary_manifest, "rb") as stream:
            self.assertTrue(stream.read().startswith(workspace._manifest_header(os.path.basename(root))))

    def test_child_exit_before_manifest_header_preserves_empty_temp_and_prior_state_remains_usable(self):
        root = self.start()["workspace"]
        draft = os.path.join(root, "work", "draft.txt")
        with open(draft, "wb") as stream:
            stream.write(b"draft")
        code = r'''
import os, sys, tempfile
tempfile.tempdir = os.path.dirname(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import review_workspace as workspace
import builtins
real_open = builtins.open
def die_after_exclusive_create(path, mode="r", *args, **kwargs):
    stream = real_open(path, mode, *args, **kwargs)
    if mode == "xb" and os.path.basename(path).startswith(workspace.MANIFEST_TEMP + "-"):
        os._exit(74)
    return stream
builtins.open = die_after_exclusive_create
workspace.checkpoint(sys.argv[1], "draft", "work/draft.txt")
'''
        child = subprocess.run([sys.executable, "-c", code, root, SCRIPTS], timeout=30, check=False)
        self.assertEqual(child.returncode, 74)

        state = workspace.status(root)
        self.assertEqual(len(state["manifest_temporaries"]), 1)
        diagnostic = state["manifest_temporaries"][0]
        self.assertEqual(diagnostic["reason"], "empty transaction file; ownership header not committed; preserved")
        empty_temp = diagnostic["path"]
        self.assertEqual(os.path.getsize(empty_temp), 0)

        workspace.checkpoint(root, "draft", "work/draft.txt")
        memo = os.path.join(root, "work", "memo.hwpx")
        with open(memo, "wb") as stream:
            stream.write(b"published after recovery")
        workspace.checkpoint(root, "memo", "work/memo.hwpx")
        result = workspace.publish(root, {"memo": "after_recovery_검토메모.hwpx"})
        with open(result["published"][0]["path"], "rb") as stream:
            self.assertEqual(stream.read(), b"published after recovery")
        self.assertTrue(os.path.exists(empty_temp))
        workspace.checkpoint(root, "handoff")
        with self.assertRaisesRegex(workspace.WorkspaceError, "manifest transaction diagnostic"):
            workspace.cleanup(root)
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(os.path.exists(empty_temp))

    def test_partial_header_foreign_text_and_reparse_transaction_files_are_preserved_and_reported(self):
        root = self.start()["workspace"]
        workspace_id = workspace.status(root)["workspace_id"]
        partial = workspace._new_manifest_temp(root)
        with open(partial, "xb") as stream:
            stream.write(workspace._manifest_header(workspace_id)[:7])
        foreign = workspace._new_manifest_temp(root)
        with open(foreign, "xb") as stream:
            stream.write(b"another process data")
        link = workspace._new_manifest_temp(root)
        outside = self.write("outside/target.txt", b"do not follow")
        link_created = False
        try:
            os.symlink(outside, link)
            link_created = True
        except (OSError, NotImplementedError):
            pass

        diagnostics = {item["path"]: item for item in workspace.status(root)["manifest_temporaries"]}

        self.assertEqual(diagnostics[partial]["reason"], "partial ownership header; preserved")
        self.assertEqual(diagnostics[foreign]["reason"], "foreign transaction header; preserved")
        if link_created:
            self.assertEqual(diagnostics[link]["reason"], "reparse/link; preserved")
            self.assertTrue(os.path.islink(link))
        with open(partial, "rb") as stream:
            self.assertEqual(stream.read(), workspace._manifest_header(workspace_id)[:7])
        with open(foreign, "rb") as stream:
            self.assertEqual(stream.read(), b"another process data")
        with open(outside, "rb") as stream:
            self.assertEqual(stream.read(), b"do not follow")
        with self.assertRaisesRegex(workspace.WorkspaceError, "manifest transaction diagnostic"):
            workspace.cleanup(root)
        self.assertTrue(os.path.exists(partial))
        self.assertTrue(os.path.exists(foreign))

    def test_malformed_stage_identity_is_rejected_without_touching_staging(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/memo.hwpx", content=b"memo")
        workspace.publish(root, {"memo": "identity_검토메모.hwpx"})
        _, manifest = workspace._load_workspace(root, verify=False)
        plan = manifest["publish_plan"][0]
        stage_name = workspace._stage_filename(manifest, "memo")
        stage = os.path.join(manifest["output_dir"], stage_name)
        with open(stage, "wb") as stream:
            stream.write(b"foreign staging diagnostic")
        plan["stage_filename"] = stage_name
        plan["stage_identity"] = {"device": "not-an-integer", "inode": 0}
        workspace._write_manifest(root, manifest)
        with self.assertRaisesRegex(workspace.WorkspaceError, "publish plan"):
            workspace.status(root)
        self.assertTrue(os.path.exists(stage))

    def test_concurrent_publish_never_overwrites_other_run(self):
        primary = self.write("source/request.hwp", b"unchanged input")
        roots = [self.start(primary)["workspace"] for _ in range(2)]
        for root, content in zip(roots, (b"first review", b"second review")):
            self.artifact(root, content=content)
        barrier = threading.Barrier(2)
        local = threading.local()
        copy_exclusive = workspace._copy_exclusive

        def synchronized_copy(*args, **kwargs):
            if not getattr(local, "arrived", False):
                local.arrived = True
                barrier.wait(timeout=10)
            return copy_exclusive(*args, **kwargs)

        with mock.patch.object(workspace, "_copy_exclusive", side_effect=synchronized_copy):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda root: workspace.publish(root, {"memo": "결과_검토메모.hwpx"}), roots))
        paths = [result["published"][0]["path"] for result in results]
        self.assertEqual(len(set(paths)), 2)
        for path, expected in zip(paths, (b"first review", b"second review")):
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), expected)

    def test_stale_artifact_is_rejected(self):
        root = self.start()["workspace"]
        artifact = self.artifact(root)
        with open(artifact, "wb") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(workspace.WorkspaceError, "산출물이 변경"):
            workspace.status(root)

    def test_checkpoint_correction_refreshes_hash_and_invalidates_dependents(self):
        root = self.start()["workspace"]
        facts = os.path.join(root, "work", "facts.json")
        review = os.path.join(root, "work", "review.json")
        memo = os.path.join(root, "work", "memo.hwpx")
        for path, content in ((facts, b"facts v1"), (review, b"review v1"), (memo, b"memo v1")):
            with open(path, "wb") as stream:
                stream.write(content)
        workspace.checkpoint(root, "facts", "work/facts.json")
        workspace.checkpoint(root, "review", "work/review.json", depends_on=["facts"])
        workspace.checkpoint(root, "memo", "work/memo.hwpx", depends_on=["review"])
        with open(facts, "wb") as stream:
            stream.write(b"facts corrected")
        with self.assertRaisesRegex(workspace.WorkspaceError, "산출물이 변경"):
            workspace.status(root)
        workspace.checkpoint(root, "facts", "work/facts.json")
        self.assertEqual(set(workspace.status(root)["artifacts"]), {"facts"})
        self.assertTrue(os.path.exists(review))
        self.assertTrue(os.path.exists(memo))

    def test_checkpoint_refresh_still_rejects_stale_source(self):
        primary = self.write("source/request.hwp", b"input before")
        root = self.start(primary)["workspace"]
        artifact = self.artifact(root, "facts", "work/facts.json", b"facts before")
        with open(primary, "wb") as stream:
            stream.write(b"input after")
        with open(artifact, "wb") as stream:
            stream.write(b"facts corrected")
        with self.assertRaisesRegex(workspace.WorkspaceError, "입력 원본이 begin 이후 변경"):
            workspace.checkpoint(root, "facts", "work/facts.json")

    def test_stale_reference_directory_is_rejected(self):
        reference = self.write("references/thresholds.json", b"original")
        root = self.start(references=[os.path.dirname(reference)])["workspace"]
        self.write("references/new-rule.json", b"added")
        with self.assertRaisesRegex(workspace.WorkspaceError, "기준자료가 begin 이후 변경"):
            workspace.status(root)

    def test_failed_publication_can_be_retried(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/artifacts/table.xlsx", content=b"xlsx")
        with mock.patch.object(workspace, "_copy_exclusive", side_effect=PermissionError("simulated")):
            with self.assertRaises(PermissionError):
                workspace.publish(root, {"memo": "table.xlsx"})
        self.assertEqual(workspace.status(root)["publish_receipts"], {})
        result = workspace.publish(root, {"memo": "table.xlsx"})
        self.assertEqual(len(result["published"]), 1)
        self.assertEqual(os.listdir(result["output_dir"]), ["table.xlsx"])

    def test_binary_publication_preserves_exact_bytes_and_first_receipt_hashes_destination(self):
        root = self.start()["workspace"]
        payload = b"line one\n\x00\xff\xfe\r\nline three\n" * 257
        artifact = self.artifact(root, path="work/memo.hwpx", content=payload)
        result = workspace.publish(root, {"memo": "memo_검토메모.hwpx"})
        destination = result["published"][0]["path"]
        with open(destination, "rb") as stream:
            self.assertEqual(stream.read(), payload)
        receipt = workspace.status(root)["publish_receipts"]["memo"]
        self.assertEqual(receipt["fingerprint"], workspace._file_fingerprint(destination))
        self.assertEqual(receipt["fingerprint"], workspace._file_fingerprint(artifact))
        self.assertEqual(result["published"][0]["sha256"], hashlib.sha256(payload).hexdigest())

    def test_abrupt_child_interruption_never_exposes_partial_final_and_retry_recovers_stage(self):
        root = self.start()["workspace"]
        payload = b"complete memo\n\x00\xff" * 40000
        self.artifact(root, path="work/memo.hwpx", content=payload)
        code = r'''
import os, sys, tempfile
tempfile.tempdir = os.path.dirname(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import review_workspace as workspace
def stop_after_partial(source, stage, expected, *, on_created=None):
    descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    info = os.fstat(descriptor)
    on_created({"device": info.st_dev, "inode": info.st_ino})
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(b"partial")
        stream.flush()
        os.fsync(stream.fileno())
    os._exit(73)
workspace._copy_exclusive = stop_after_partial
workspace.publish(sys.argv[1], {"memo": "interrupted_검토메모.hwpx"})
'''
        child = subprocess.run([sys.executable, "-c", code, root, SCRIPTS], timeout=30, check=False)
        self.assertEqual(child.returncode, 73)
        _, interrupted_manifest = workspace._load_workspace(root, verify=False)
        interrupted_plan = interrupted_manifest["publish_plan"][0]
        self.assertIsNotNone(interrupted_plan["stage_identity"])
        interrupted_stage = os.path.join(interrupted_manifest["output_dir"], interrupted_plan["stage_filename"])
        self.assertTrue(workspace._identity_matches(os.lstat(interrupted_stage),
                                                    interrupted_plan["stage_identity"]))
        output_dir = workspace.status(root)["output_dir"]
        target = os.path.join(output_dir, "interrupted_검토메모.hwpx")
        self.assertFalse(os.path.exists(target))
        self.assertTrue(any(name.endswith(".tmp") and name.startswith(".rfp-stage-")
                            for name in os.listdir(output_dir)))

        result = workspace.publish(root, {"memo": "interrupted_검토메모.hwpx"})

        self.assertTrue(os.path.exists(target))
        with open(target, "rb") as stream:
            self.assertEqual(stream.read(), payload)
        self.assertEqual(workspace.status(root)["publish_receipts"]["memo"]["fingerprint"],
                         workspace._file_fingerprint(target))
        self.assertEqual(os.listdir(output_dir), ["interrupted_검토메모.hwpx"])
        self.assertFalse(result["published"][0]["already_published"])

    def test_unsupported_atomic_noreplace_fails_clearly_and_preserves_user_output(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/memo.hwpx", content=b"memo bytes")
        output_dir = workspace.status(root)["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        occupied = os.path.join(output_dir, "memo_검토메모.hwpx")
        with open(occupied, "wb") as stream:
            stream.write(b"user-owned output")
        final = os.path.join(output_dir, "memo_2_검토메모.hwpx")
        with mock.patch.object(workspace.os, "link", side_effect=OSError("operation unsupported")):
            with self.assertRaisesRegex(workspace.WorkspaceError, "원자적 no-replace 게시.*operation unsupported"):
                workspace.publish(root, {"memo": "memo_검토메모.hwpx"})
        self.assertFalse(os.path.exists(final))
        self.assertTrue(any(name.endswith(".tmp") and name.startswith(".rfp-stage-")
                            for name in os.listdir(output_dir)))
        result = workspace.publish(root, {"memo": "memo_검토메모.hwpx"})
        self.assertFalse(result["published"][0]["already_published"])
        with open(final, "rb") as stream:
            self.assertEqual(stream.read(), b"memo bytes")
        with open(occupied, "rb") as stream:
            self.assertEqual(stream.read(), b"user-owned output")

    def test_recheckpoint_of_planned_artifact_and_ancestor_is_rejected_after_link_failure(self):
        scenarios = ("planned artifact", "ancestor")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                root = self.start()["workspace"]
                if scenario == "planned artifact":
                    planned_path = self.artifact(root, "memo", "work/memo.hwpx", b"original memo")
                    changed_name, changed_path = "memo", planned_path
                else:
                    facts = os.path.join(root, "work", "facts.json")
                    with open(facts, "wb") as stream:
                        stream.write(b"original facts")
                    workspace.checkpoint(root, "facts", "work/facts.json")
                    review = os.path.join(root, "work", "review.json")
                    with open(review, "wb") as stream:
                        stream.write(b"review")
                    workspace.checkpoint(root, "review", "work/review.json", depends_on=["facts"])
                    memo = os.path.join(root, "work", "memo.hwpx")
                    with open(memo, "wb") as stream:
                        stream.write(b"original memo")
                    workspace.checkpoint(root, "memo", "work/memo.hwpx", depends_on=["review"])
                    changed_name, changed_path = "facts", facts

                with mock.patch.object(workspace.os, "link", side_effect=OSError("unsupported")):
                    with self.assertRaisesRegex(workspace.WorkspaceError, "원자적 no-replace"):
                        workspace.publish(root, {"memo": "immutable_검토메모.hwpx"})
                _, before = workspace._load_workspace(root, verify=False)
                before_item = next(item for item in before["publish_plan"] if item["artifact"] == "memo")
                stage = os.path.join(before["output_dir"], before_item["stage_filename"])
                stage_info = os.lstat(stage)
                with open(stage, "rb") as stream:
                    stage_bytes = stream.read()
                self.assertEqual(before_item["stage_identity"], workspace._stage_identity(stage_info))
                self.assertFalse(before["publish_receipts"])

                with open(changed_path, "wb") as stream:
                    stream.write(b"corrected")
                with self.assertRaisesRegex(workspace.WorkspaceError, "plan이 시작된 artifact 또는 선행 artifact"):
                    workspace.checkpoint(root, changed_name, os.path.relpath(changed_path, root).replace(os.sep, "/"))

                _, after = workspace._load_workspace(root, verify=False)
                after_item = next(item for item in after["publish_plan"] if item["artifact"] == "memo")
                self.assertEqual(after_item, before_item)
                self.assertEqual(os.path.samefile(stage, os.path.join(after["output_dir"], after_item["stage_filename"])), True)
                self.assertEqual(workspace._stage_identity(os.lstat(stage)), after_item["stage_identity"])
                with open(stage, "rb") as stream:
                    self.assertEqual(stream.read(), stage_bytes)
                self.assertFalse(after["publish_receipts"])

    def test_failed_partial_stage_is_not_public_and_retry_preserves_collision(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/memo.hwpx", content=b"final memo bytes")
        output_dir = workspace.status(root)["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        requested = "memo_검토메모.hwpx"
        occupied = os.path.join(output_dir, requested)
        with open(occupied, "wb") as stream:
            stream.write(b"user-owned collision")

        def partial_failure(_source, stage, _expected, *, on_created=None):
            with open(stage, "xb") as stream:
                stream.write(b"partial stage")
            raise OSError("simulated staging write failure")

        with mock.patch.object(workspace, "_copy_exclusive", side_effect=partial_failure):
            with self.assertRaisesRegex(OSError, "staging write failure"):
                workspace.publish(root, {"memo": requested})
        self.assertFalse(os.path.exists(os.path.join(output_dir, "memo_2_검토메모.hwpx")))
        with open(occupied, "rb") as stream:
            self.assertEqual(stream.read(), b"user-owned collision")

        retried = workspace.publish(root, {"memo": requested})

        published = os.path.join(output_dir, "memo_2_검토메모.hwpx")
        self.assertEqual(retried["published"][0]["path"], published)
        with open(published, "rb") as stream:
            self.assertEqual(stream.read(), b"final memo bytes")
        with open(occupied, "rb") as stream:
            self.assertEqual(stream.read(), b"user-owned collision")

    def test_interrupted_unclaimed_foreign_stage_is_preserved_reported_and_not_adopted(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/memo.hwpx", content=b"validated memo")
        output_dir = workspace.status(root)["output_dir"]
        foreign = []

        def foreign_then_interrupt(_source, stage, _expected, *, on_created=None):
            with open(stage, "xb") as stream:
                # Matching content must not be treated as proof that we created this file.
                stream.write(b"validated memo")
            foreign.append(stage)
            raise KeyboardInterrupt

        with mock.patch.object(workspace, "_copy_exclusive", side_effect=foreign_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                workspace.publish(root, {"memo": "collision_검토메모.hwpx"})
        with open(foreign[0], "rb") as stream:
            self.assertEqual(stream.read(), b"validated memo")

        result = workspace.publish(root, {"memo": "collision_검토메모.hwpx"})

        with open(foreign[0], "rb") as stream:
            self.assertEqual(stream.read(), b"validated memo")
        self.assertEqual(len(result["preserved_stages"]), 1)
        diagnostic = result["preserved_stages"][0]
        self.assertEqual(diagnostic["path"], foreign[0])
        self.assertTrue(diagnostic["exists"])
        self.assertEqual(diagnostic["reason"], "identity 미기록")
        self.assertEqual(len(result["published"]), 1)
        with open(result["published"][0]["path"], "rb") as stream:
            self.assertEqual(stream.read(), b"validated memo")
        self.assertNotEqual(result["published"][0]["path"], foreign[0])
        workspace.checkpoint(root, "handoff")
        with self.assertRaisesRegex(workspace.WorkspaceError, "staging diagnostic을 보존"):
            workspace.cleanup(root)
        self.assertTrue(os.path.exists(foreign[0]))

    def test_replaced_owned_stage_identity_is_preserved_and_fresh_stage_publishes(self):
        root = self.start()["workspace"]
        self.artifact(root, path="work/memo.hwpx", content=b"validated memo")
        output_dir = workspace.status(root)["output_dir"]
        stage_paths = []

        def owned_partial_then_interrupt(_source, stage, _expected, *, on_created=None):
            descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            info = os.fstat(descriptor)
            on_created({"device": info.st_dev, "inode": info.st_ino})
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"owned partial stage")
                stream.flush()
                os.fsync(stream.fileno())
            stage_paths.append(stage)
            raise KeyboardInterrupt

        with mock.patch.object(workspace, "_copy_exclusive", side_effect=owned_partial_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                workspace.publish(root, {"memo": "replaced_검토메모.hwpx"})
        old_stage = stage_paths[0]
        replacement_source = os.path.join(output_dir, "replacement-source.tmp")
        with open(replacement_source, "wb") as stream:
            # Equal bytes still do not transfer ownership across a device/inode change.
            stream.write(b"validated memo")
        os.replace(replacement_source, old_stage)

        result = workspace.publish(root, {"memo": "replaced_검토메모.hwpx"})

        with open(old_stage, "rb") as stream:
            self.assertEqual(stream.read(), b"validated memo")
        self.assertTrue(any(item["path"] == old_stage and item["exists"]
                            for item in result["preserved_stages"]))
        self.assertEqual(result["published"][0]["path"],
                         os.path.join(output_dir, "replaced_검토메모.hwpx"))
        with open(result["published"][0]["path"], "rb") as stream:
            self.assertEqual(stream.read(), b"validated memo")

    def test_partial_publication_retry_keeps_first_receipt_and_adds_only_second(self):
        root = self.start()["workspace"]
        self.artifact(root, "memo", "work/artifacts/memo.hwpx", b"memo")
        self.artifact(root, "xlsx", "work/artifacts/table.xlsx", b"xlsx")
        original_copy = workspace._copy_exclusive
        calls = []

        def fail_second(source, target, expected, *, on_created=None):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("simulated second-file failure")
            return original_copy(source, target, expected, on_created=on_created)

        request = {"memo": "memo_검토메모.hwpx", "xlsx": "수정요청표_요청.xlsx"}
        with mock.patch.object(workspace, "_copy_exclusive", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second-file"):
                workspace.publish(root, request)
        self.assertEqual(set(workspace.status(root)["publish_receipts"]), {"memo"})
        with self.assertRaisesRegex(workspace.WorkspaceError, "receipt가 확인된 뒤 handoff"):
            workspace.checkpoint(root, "handoff")
        retried = workspace.publish(root, request)
        self.assertTrue(retried["published"][0]["already_published"])
        self.assertFalse(retried["published"][1]["already_published"])
        self.assertEqual(len(os.listdir(retried["output_dir"])), 2)

    def test_checkpoint_rejects_path_escape(self):
        root = self.start()["workspace"]
        outside = self.write("outside.txt", b"keep")
        with self.assertRaisesRegex(workspace.WorkspaceError, "traversal"):
            workspace.checkpoint(root, "escape", "../outside.txt")
        with self.assertRaisesRegex(workspace.WorkspaceError, "drive|절대 경로"):
            workspace.checkpoint(root, "drive", "C:outside.txt")
        with self.assertRaisesRegex(workspace.WorkspaceError, "intermediate root"):
            workspace.checkpoint(root, "outside", "inputs/input-0001.hwp")
        with open(outside, "rb") as stream:
            self.assertEqual(stream.read(), b"keep")

    def test_cleanup_requires_receipts_and_handoff_and_never_deletes_unknown_files(self):
        root = self.start()["workspace"]
        with self.assertRaisesRegex(workspace.WorkspaceError, "게시되고 receipt"):
            workspace.cleanup(root)
        self.artifact(root)
        workspace.publish(root, {"memo": "결과_검토메모.hwpx"})
        with self.assertRaisesRegex(workspace.WorkspaceError, "handoff checkpoint"):
            workspace.cleanup(root)
        marker = workspace.checkpoint(root, "handoff")
        self.assertFalse(marker["visible_chat_proof"])
        self.assertIn("not evidence", marker["note"])
        unknown = os.path.join(root, "user-note.txt")
        with open(unknown, "w", encoding="utf-8") as stream:
            stream.write("preserve")
        with self.assertRaisesRegex(workspace.WorkspaceError, "소유하지 않는 항목"):
            workspace.cleanup(root)
        with open(unknown, encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "preserve")

    def test_cleanup_succeeds_only_after_verified_publication_and_marker(self):
        root = self.start()["workspace"]
        self.artifact(root)
        workspace.publish(root, {"memo": "검토_검토메모.hwpx"})
        workspace.checkpoint(root, "handoff")
        result = workspace.cleanup(root)
        self.assertTrue(result["cleaned"])
        self.assertFalse(result["visible_chat_proof"])
        self.assertFalse(os.path.exists(root))

    def test_staging_cleanup_failure_preserves_receipt_and_workspace(self):
        root = self.start()["workspace"]
        self.artifact(root, content=b"binary\n\x00\xff")
        with mock.patch.object(workspace, "_remove_owned_stage", side_effect=PermissionError("locked stage")):
            receipt = workspace.publish(root, {"memo": "검토_검토메모.hwpx"})
            workspace.checkpoint(root, "handoff")
            with self.assertRaises(PermissionError):
                workspace.cleanup(root)
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(os.path.isfile(receipt["published"][0]["path"]))
        self.assertTrue(workspace.cleanup(root)["cleaned"])

    def test_owned_intermediate_root_cleans_uncheckpointed_generated_files(self):
        root = self.start()["workspace"]
        generated = (
            ("extracted/rfp.txt", b"text"),
            ("extracted/rfp.objects.json", b"{}"),
            ("items/1.md", b"items"),
            ("review_notes.json", b"{}"),
            ("trial.hwpx", b"trial"),
        )
        for relative, content in generated:
            path = os.path.join(root, "work", relative.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as stream:
                stream.write(content)
        self.artifact(root, path="work/final/memo.hwpx")
        workspace.publish(root, {"memo": "검토_검토메모.hwpx"})
        workspace.checkpoint(root, "handoff")
        workspace.cleanup(root)
        self.assertFalse(os.path.exists(root))

    def test_cleanup_refuses_symlink_to_external_file_without_touching_target(self):
        root = self.start()["workspace"]
        self.artifact(root)
        workspace.publish(root, {"memo": "검토_검토메모.hwpx"})
        workspace.checkpoint(root, "handoff")
        outside = self.write("outside.txt", b"do not follow")
        link = os.path.join(root, "external-link")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.cleanup(root)
        with open(outside, "rb") as stream:
            self.assertEqual(stream.read(), b"do not follow")

    def test_optional_txt_and_xlsx_exports_use_same_checkpoint_contract(self):
        root = self.start()["workspace"]
        self.artifact(root, "memo", "work/artifacts/memo.hwpx", b"memo")
        self.artifact(root, "xlsx", "work/artifacts/table.xlsx", b"xlsx")
        self.artifact(root, "txt", "work/artifacts/reply.txt", "회신".encode("utf-8"))
        result = workspace.publish(root, {
            "memo": "request_검토메모.hwpx",
            "xlsx": "수정요청표_request.xlsx",
            "txt": "request_검토회신.txt",
        })
        self.assertEqual(len(result["published"]), 3)
        self.assertEqual(set(workspace.status(root)["publish_receipts"]), {"memo", "xlsx", "txt"})

    def test_converter_rejects_existing_default_or_explicit_output_without_touching_source(self):
        from convert_to_hwpx import convert_hwp_to_hwpx

        source = self.write("convert/original.hwp", b"source bytes")
        sibling = os.path.splitext(source)[0] + ".hwpx"
        with open(sibling, "wb") as stream:
            stream.write(b"existing sibling")
        os.utime(sibling, (4102444800, 4102444800))  # A newer mtime is not proof of a conversion.
        with self.assertRaisesRegex(RuntimeError, "출력 파일이 이미 있습니다"):
            convert_hwp_to_hwpx(source)
        explicit = os.path.join(self.base, "internal", "converted.hwpx")
        os.makedirs(os.path.dirname(explicit), exist_ok=True)
        with open(explicit, "wb") as stream:
            stream.write(b"existing explicit output")
        with self.assertRaisesRegex(RuntimeError, "출력 파일이 이미 있습니다"):
            convert_hwp_to_hwpx(source, explicit)
        with open(source, "rb") as stream:
            self.assertEqual(stream.read(), b"source bytes")
        with open(sibling, "rb") as stream:
            self.assertEqual(stream.read(), b"existing sibling")
        with open(explicit, "rb") as stream:
            self.assertEqual(stream.read(), b"existing explicit output")


class HancomIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def fake_com(self, hwp=None, dispatch_error=None):
        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = mock.Mock()
        pythoncom.CoUninitialize = mock.Mock()
        client = types.ModuleType("win32com.client")
        client.DispatchEx = mock.Mock(side_effect=dispatch_error) if dispatch_error else mock.Mock(return_value=hwp)
        client.Dispatch = mock.Mock(name="legacy_dispatch")
        client.gencache = types.SimpleNamespace(EnsureDispatch=mock.Mock(name="legacy_ensure_dispatch"))
        win32com = types.ModuleType("win32com")
        win32com.__path__ = []
        win32com.client = client
        modules = {"pythoncom": pythoncom, "win32com": win32com, "win32com.client": client}
        return mock.patch.dict(sys.modules, modules), pythoncom, client

    def hwp_stub(self, save_result=True, saved_bytes=b"fresh output"):
        hwp = mock.Mock()
        hwp.Open.return_value = True

        def save_as(path, *_args):
            with open(path, "wb") as stream:
                stream.write(saved_bytes)
            return save_result

        hwp.SaveAs.side_effect = save_as
        return hwp

    def test_converter_uses_dispatch_ex_and_rejects_false_saveas_with_partial_output(self):
        from convert_to_hwpx import convert_hwp_to_hwpx
        import convert_to_hwpx as converter

        source = os.path.join(self.temporary.name, "original.hwp")
        output = os.path.join(self.temporary.name, "internal", "converted.hwpx")
        os.makedirs(os.path.dirname(output))
        with open(source, "wb") as stream:
            stream.write(b"unchanged source")
        hwp = self.hwp_stub(save_result=False, saved_bytes=b"partial")
        context, pythoncom, client = self.fake_com(hwp)
        with context, mock.patch.object(converter, "_ensure_security_module"):
            with self.assertRaisesRegex(RuntimeError, "변환 결과 저장에 실패"):
                convert_hwp_to_hwpx(source, output)
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        hwp.Quit.assert_called_once_with()
        pythoncom.CoUninitialize.assert_called_once_with()
        with open(source, "rb") as stream:
            self.assertEqual(stream.read(), b"unchanged source")
        with open(output, "rb") as stream:
            self.assertEqual(stream.read(), b"partial")

    def test_converter_surfaces_dispatch_ex_failure_without_attach_fallback(self):
        from convert_to_hwpx import convert_hwp_to_hwpx
        import convert_to_hwpx as converter

        source = os.path.join(self.temporary.name, "original.hwp")
        output = os.path.join(self.temporary.name, "converted.hwpx")
        with open(source, "wb") as stream:
            stream.write(b"source")
        context, pythoncom, client = self.fake_com(dispatch_error=OSError("COM unavailable"))
        with context, mock.patch.object(converter, "_ensure_security_module"):
            with self.assertRaisesRegex(RuntimeError, "독립 인스턴스를 시작하지 못했습니다.*COM unavailable"):
                convert_hwp_to_hwpx(source, output)
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        pythoncom.CoUninitialize.assert_called_once_with()
        self.assertFalse(os.path.exists(output))

    def test_resave_uses_dispatch_ex_and_rejects_false_saveas_without_replacing_source(self):
        import resave_hwpx

        source = os.path.join(self.temporary.name, "annotated.hwpx")
        with open(source, "wb") as stream:
            stream.write(b"original annotated copy")
        hwp = self.hwp_stub(save_result=False, saved_bytes=b"partial resave")
        context, pythoncom, client = self.fake_com(hwp)
        with context, mock.patch.object(resave_hwpx, "_ensure_security_module"):
            with self.assertRaisesRegex(RuntimeError, "메모본 재저장에 실패"):
                resave_hwpx.resave(source)
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        hwp.Quit.assert_called_once_with()
        pythoncom.CoUninitialize.assert_called_once_with()
        with open(source, "rb") as stream:
            self.assertEqual(stream.read(), b"original annotated copy")
        with open(source + ".resave.hwpx", "rb") as stream:
            self.assertEqual(stream.read(), b"partial resave")

    def test_resave_surfaces_dispatch_ex_failure_without_attach_fallback(self):
        import resave_hwpx

        source = os.path.join(self.temporary.name, "annotated.hwpx")
        with open(source, "wb") as stream:
            stream.write(b"source")
        context, pythoncom, client = self.fake_com(dispatch_error=OSError("COM unavailable"))
        with context, mock.patch.object(resave_hwpx, "_ensure_security_module"):
            with self.assertRaisesRegex(RuntimeError, "독립 인스턴스를 시작하지 못했습니다.*COM unavailable"):
                resave_hwpx.resave(source)
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        pythoncom.CoUninitialize.assert_called_once_with()
        with open(source, "rb") as stream:
            self.assertEqual(stream.read(), b"source")

    def test_safe_annotate_opener_uses_and_quits_only_dispatch_ex_instance(self):
        import safe_annotate

        hwp = self.hwp_stub()
        context, pythoncom, client = self.fake_com(hwp)
        with context:
            with mock.patch("convert_to_hwpx._ensure_security_module"):
                opener = safe_annotate.HwpOpener()
                self.assertTrue(opener.opens(os.path.join(self.temporary.name, "trial.hwpx")))
                opener.close()
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        hwp.Quit.assert_called_once_with()
        pythoncom.CoUninitialize.assert_called_once_with()

    def test_safe_annotate_opener_surfaces_creation_failure_and_uninitializes_com(self):
        import safe_annotate

        context, pythoncom, client = self.fake_com(dispatch_error=OSError("COM unavailable"))
        with context, mock.patch("convert_to_hwpx._ensure_security_module"):
            with self.assertRaisesRegex(RuntimeError, "독립 인스턴스를 시작하지 못했습니다.*COM unavailable"):
                safe_annotate.HwpOpener()
        client.DispatchEx.assert_called_once_with("HWPFrame.HwpObject")
        client.Dispatch.assert_not_called()
        client.gencache.EnsureDispatch.assert_not_called()
        pythoncom.CoUninitialize.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
