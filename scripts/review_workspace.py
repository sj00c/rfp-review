#!/usr/bin/env python3
"""Private, resumable file lifecycle for an RFP review (not a review runner).

CLI:
  review_workspace.py begin PRIMARY [--input ROLE=PATH ...] [--reference PATH ...]
      [--output-dir DIR]
  review_workspace.py status WORKSPACE
  review_workspace.py checkpoint WORKSPACE ARTIFACT_NAME RELATIVE_FILE [--depends-on NAME ...]
  review_workspace.py checkpoint WORKSPACE handoff
  review_workspace.py publish WORKSPACE ARTIFACT_NAME=OUTPUT_FILENAME [...]
  review_workspace.py cleanup WORKSPACE

A handoff checkpoint records a caller-provided lifecycle marker only. It cannot
prove that a complete message was actually visible in chat.

Put all generated intermediates below ``<workspace>/work``. That dedicated root
is reserved for this run and is recursively removed after the cleanup gate; do
not put user-owned files there. Cleanup rejects unowned paths elsewhere.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

VERSION = 3
MANIFEST = ".review-workspace.json"
OWNER = ".review-workspace-owner"
MANIFEST_TEMP = ".review-workspace-write"
_MANIFEST_TEMP_MAGIC = b'{"workspace_id": '
_MANIFEST_TEMP_NAME = re.compile(r"^\.review-workspace-write-[0-9a-f]{32}\.tmp$")
_MANIFEST_TEMP_SCAN_LIMIT = 128
_HANDOFF_NOTE = "Checkpoint is not evidence of visible chat delivery."
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_MEMO_MARKER = "_검토메모"


class WorkspaceError(RuntimeError):
    """Invalid, stale, or unsafe workspace operation."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError as exc:
        raise WorkspaceError(f"경로를 확인할 수 없습니다: {path}: {exc}") from exc


def _is_link(info):
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse_flag and attributes & reparse_flag)


def _file_fingerprint(path):
    info = _lstat(path)
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        raise WorkspaceError(f"일반 파일만 허용됩니다(심볼릭 링크/특수 파일 불가): {path}")
    try:
        with open(path, "rb") as stream:
            digest, size = _digest_stream(stream)
    except OSError as exc:
        raise WorkspaceError(f"파일을 읽을 수 없습니다: {path}: {exc}") from exc
    return {"sha256": digest, "size": size}


def _reference_fingerprint(path):
    """Hash a reference file or a complete directory tree without following links."""
    info = _lstat(path)
    if _is_link(info):
        raise WorkspaceError(f"참조 경로는 심볼릭 링크일 수 없습니다: {path}")
    if stat.S_ISREG(info.st_mode):
        return {"kind": "file", **_file_fingerprint(path)}
    if not stat.S_ISDIR(info.st_mode):
        raise WorkspaceError(f"파일 또는 디렉터리 참조만 허용됩니다: {path}")

    entries = []

    def visit(directory, relative):
        try:
            with os.scandir(directory) as scan:
                children = sorted(scan, key=lambda entry: entry.name)
        except OSError as exc:
            raise WorkspaceError(f"참조 디렉터리를 읽을 수 없습니다: {directory}: {exc}") from exc
        for child in children:
            rel = f"{relative}/{child.name}" if relative else child.name
            child_info = child.stat(follow_symlinks=False)
            if _is_link(child_info):
                raise WorkspaceError(f"참조 트리에 심볼릭 링크가 있습니다: {os.path.join(directory, child.name)}")
            if stat.S_ISDIR(child_info.st_mode):
                entries.append({"path": rel, "type": "dir"})
                visit(child.path, rel)
            elif stat.S_ISREG(child_info.st_mode):
                fp = _file_fingerprint(child.path)
                entries.append({"path": rel, "type": "file", **fp})
            else:
                raise WorkspaceError(f"참조 트리에 특수 파일이 있습니다: {child.path}")

    visit(path, "")
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"kind": "directory", "sha256": hashlib.sha256(payload).hexdigest(), "files": sum(
        entry["type"] == "file" for entry in entries)}


def _checked_source(path):
    absolute = os.path.abspath(os.fspath(path))
    fingerprint = _file_fingerprint(absolute)
    return absolute, fingerprint


def _copy_input(source, destination, expected):
    """Copy an input exclusively and verify both the copy and stable source."""
    before = _file_fingerprint(source)
    if before != expected:
        raise WorkspaceError(f"입력이 begin 중 변경되었습니다: {source}")
    created_info = None
    try:
        with open(source, "rb") as src, open(destination, "xb") as dst:
            created_info = os.fstat(dst.fileno())
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            dst.flush()
            os.fsync(dst.fileno())
    except Exception:
        if created_info is not None:
            _unlink_if_same(destination, created_info)
        raise
    copied = {"sha256": digest.hexdigest(), "size": size}
    after = _file_fingerprint(source)
    if copied != expected or after != expected:
        _unlink_if_same(destination, created_info)
        raise WorkspaceError(f"복사 중 입력 내용이 변경되었습니다: {source}")
    return copied


def _unlink_if_same(path, original_info):
    if original_info is None:
        return
    try:
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) == (original_info.st_dev, original_info.st_ino):
            os.unlink(path)
    except OSError:
        pass


def _manifest_header(workspace_id):
    return _MANIFEST_TEMP_MAGIC + json.encoder.encode_basestring_ascii(workspace_id).encode("ascii") + b",\n"


def _new_manifest_temp(root):
    for _ in range(128):
        filename = f"{MANIFEST_TEMP}-{secrets.token_hex(16)}.tmp"
        path = os.path.join(root, filename)
        if not os.path.lexists(path):
            return path
    raise WorkspaceError("고유한 manifest transaction 파일명을 확보하지 못했습니다.")


def _write_manifest(root, manifest):
    final = os.path.join(root, MANIFEST)
    if os.path.lexists(final):
        info = os.lstat(final)
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError("manifest 경로가 일반 파일이 아니므로 갱신하지 않습니다.")
    created_info = None
    while True:
        temporary = _new_manifest_temp(root)
        try:
            stream = open(temporary, "xb")
            break
        except FileExistsError:
            # Another writer reserved this opaque name; leave it untouched and try a fresh one.
            continue
    try:
        with stream:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            created_info = os.fstat(stream.fileno())
            # Durable ownership marker lets resume distinguish our interrupted write
            # from an unrelated file at the reserved temporary path.
            stream.write(_manifest_header(manifest["workspace_id"]))
            stream.flush()
            os.fsync(stream.fileno())
            remainder = {key: value for key, value in manifest.items() if key != "workspace_id"}
            payload = json.dumps(remainder, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            stream.write(payload[1:] + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, final)
    except Exception:
        _unlink_if_same(temporary, created_info)
        raise


def _manifest_temp_candidates(root):
    names = []
    omitted = 0
    try:
        with os.scandir(root) as scan:
            for entry in scan:
                if entry.name != MANIFEST_TEMP and not entry.name.startswith(MANIFEST_TEMP + "-"):
                    continue
                if len(names) < _MANIFEST_TEMP_SCAN_LIMIT:
                    names.append(entry.name)
                else:
                    omitted += 1
    except OSError as exc:
        raise WorkspaceError(f"manifest transaction namespace를 읽을 수 없습니다: {exc}") from exc
    return sorted(names), omitted


def _manifest_temp_diagnostics(root, workspace_id):
    marker = _manifest_header(workspace_id)
    names, omitted = _manifest_temp_candidates(root)
    diagnostics = []
    for filename in names:
        path = os.path.join(root, filename)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if _is_link(info):
            diagnostics.append({"filename": filename, "path": path, "reason": "reparse/link; preserved",
                                "identity": _stage_identity(info) if info.st_ino > 0 else None})
            continue
        if not stat.S_ISREG(info.st_mode):
            diagnostics.append({"filename": filename, "path": path, "reason": "not a regular file; preserved",
                                "identity": _stage_identity(info) if info.st_ino > 0 else None})
            continue
        if filename != MANIFEST_TEMP and not _MANIFEST_TEMP_NAME.fullmatch(filename):
            diagnostics.append({"filename": filename, "path": path, "reason": "invalid transaction filename; preserved",
                                "identity": _stage_identity(info) if info.st_ino > 0 else None})
            continue
        try:
            with open(path, "rb") as stream:
                actual = stream.readline(len(marker) + 1)
        except OSError as exc:
            diagnostics.append({"filename": filename, "path": path,
                                "reason": f"header unreadable; preserved: {exc}",
                                "identity": _stage_identity(info) if info.st_ino > 0 else None})
            continue
        current = os.lstat(path)
        identity = _stage_identity(info) if info.st_ino > 0 else None
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            diagnostics.append({"filename": filename, "path": path, "reason": "changed while inspected; preserved",
                                "identity": identity})
            continue
        if actual == marker:
            try:
                os.unlink(path)
            except OSError as exc:
                diagnostics.append({"filename": filename, "path": path,
                                    "reason": f"owned committed header; could not reap: {exc}",
                                    "identity": identity})
            continue
        if not actual:
            reason = "empty transaction file; ownership header not committed; preserved"
        elif marker.startswith(actual):
            reason = "partial ownership header; preserved"
        else:
            reason = "foreign transaction header; preserved"
        diagnostics.append({"filename": filename, "path": path, "reason": reason, "identity": identity})
    if omitted:
        diagnostics.append({"filename": None, "path": root, "reason": "manifest transaction scan limit reached; preserved",
                            "omitted": omitted})
    return diagnostics


def _recover_manifest_temp(root, workspace_id):
    """Reap only transactions with an exact committed workspace-specific JSON header."""
    return _manifest_temp_diagnostics(root, workspace_id)


def _safe_relative(root, relative, *, must_exist=True):
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise WorkspaceError("workspace 상대 경로가 비어 있거나 올바르지 않습니다.")
    normalized = relative.replace("\\", "/")
    windows_path = PureWindowsPath(relative)
    if normalized.startswith("/") or windows_path.is_absolute() or windows_path.drive:
        raise WorkspaceError(f"workspace 밖의 절대 경로는 허용되지 않습니다: {relative}")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise WorkspaceError(f"workspace 상대 경로에 traversal이 있습니다: {relative}")
    current = root
    for part in parts:
        current = os.path.join(current, part)
        if os.path.lexists(current):
            info = os.lstat(current)
            if _is_link(info):
                raise WorkspaceError(f"workspace 경로에 심볼릭 링크가 있습니다: {current}")
        elif must_exist:
            raise WorkspaceError(f"workspace 파일이 없습니다: {relative}")
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(current)
    try:
        if os.path.commonpath((real_root, real_path)) != real_root:
            raise WorkspaceError(f"workspace 경로가 소유 디렉터리 밖을 가리킵니다: {relative}")
    except ValueError as exc:
        raise WorkspaceError(f"workspace 경로가 소유 디렉터리 밖을 가리킵니다: {relative}") from exc
    return current


def _workspace_root(workspace):
    root = os.path.abspath(os.fspath(workspace))
    if not os.path.isdir(root) or _is_link(os.lstat(root)):
        raise WorkspaceError(f"workspace 디렉터리가 없거나 심볼릭 링크입니다: {root}")
    real_root = os.path.realpath(root)
    if os.path.normcase(root) != os.path.normcase(real_root):
        raise WorkspaceError("workspace 경로의 상위 경로에 심볼릭 링크가 있어 안전하게 열 수 없습니다.")
    temp_root = os.path.realpath(tempfile.gettempdir())
    try:
        if os.path.commonpath((temp_root, real_root)) != temp_root or os.path.dirname(real_root) != temp_root:
            raise WorkspaceError("workspace가 OS temp의 직접 하위 소유 디렉터리가 아닙니다.")
    except ValueError as exc:
        raise WorkspaceError("workspace가 OS temp의 직접 하위 소유 디렉터리가 아닙니다.") from exc
    return root


def _load_workspace(workspace, *, verify=True):
    root = _workspace_root(workspace)
    owner_path = os.path.join(root, OWNER)
    manifest_path = os.path.join(root, MANIFEST)
    for path in (owner_path, manifest_path):
        info = _lstat(path)
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError(f"소유권 증명 파일이 일반 파일이 아닙니다: {path}")
    try:
        with open(manifest_path, "r", encoding="utf-8") as stream:
            data = json.load(stream)
        with open(owner_path, "r", encoding="ascii") as stream:
            owner_id = stream.read().strip()
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"workspace manifest를 읽을 수 없습니다: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("workspace manifest가 JSON 객체가 아닙니다.")
    if data.get("version") != VERSION:
        raise WorkspaceError(f"지원하지 않는 workspace manifest version: {data.get('version')}; 기존 workspace는 보존됩니다.")
    if (not data.get("workspace_id") or data.get("workspace_id") != owner_id
            or owner_id != os.path.basename(root)):
        raise WorkspaceError("workspace 소유권 marker와 manifest가 일치하지 않습니다.")
    if (not isinstance(data.get("inputs"), list) or not data["inputs"]
            or not isinstance(data.get("references"), list) or not isinstance(data.get("artifacts"), dict)
            or not isinstance(data.get("publish_receipts"), dict)
            or not isinstance(data.get("preserved_stages", []), list)
            or (data.get("publish_plan") is not None and not isinstance(data["publish_plan"], list))
            or not isinstance(data.get("output_dir"), str)
            or not os.path.isabs(data["output_dir"])
            or not isinstance(data.get("workspace_root"), str)
            or data.get("intermediate_root") != "work"
            or any(not isinstance(item, dict) for item in data["inputs"] + data["references"])
            or any(not isinstance(item, dict) for item in data["artifacts"].values())
            or any(not isinstance(item, dict) for item in data["publish_receipts"].values())
            or any(not isinstance(item, dict) for item in (data.get("publish_plan") or []))
            or any(not isinstance(item, dict) for item in data.get("preserved_stages", []))
            or (data.get("handoff_checkpoint") is not None and not isinstance(data["handoff_checkpoint"], dict))):
        raise WorkspaceError("workspace manifest 구조가 올바르지 않습니다.")
    if (any(not isinstance(item.get("workspace_path"), str) or not isinstance(item.get("fingerprint"), dict)
            for item in data["inputs"] + list(data["artifacts"].values()))
            or any(not isinstance(item.get("source_path"), str) or not isinstance(item.get("fingerprint"), dict)
                   for item in data["inputs"] + data["references"])):
        raise WorkspaceError("workspace manifest에 필수 fingerprint/path가 없습니다.")
    if (any(not item["workspace_path"].replace("\\", "/").startswith("inputs/") for item in data["inputs"])
            or any(not item["workspace_path"].replace("\\", "/").startswith("work/")
                   for item in data["artifacts"].values())):
        raise WorkspaceError("manifest 입력/artifact 경로가 지정된 소유 영역 밖을 가리킵니다.")
    for item in data.get("publish_plan") or []:
        artifact = item.get("artifact")
        if (not isinstance(artifact, str) or artifact not in data["artifacts"]
                or not _NAME_RE.fullmatch(artifact) or not _is_filename(item.get("filename"))
                or (item.get("target_filename") is not None and not _is_filename(item["target_filename"]))
                or "stage_identity" not in item
                or (item.get("stage_filename") is not None
                    and not _is_owned_stage_filename(data, artifact, item["stage_filename"]))
                or not _valid_stage_identity(item.get("stage_identity"))
                or (item.get("stage_identity") is not None and item.get("stage_filename") is None)):
            raise WorkspaceError("workspace manifest의 publish plan에 잘못된 artifact 경로가 있습니다.")
    for item in data.get("preserved_stages", []):
        if (not isinstance(item.get("artifact"), str) or item["artifact"] not in data["artifacts"]
                or not _is_owned_stage_filename(data, item["artifact"], item.get("filename"))
                or not isinstance(item.get("reason"), str)
                or not _valid_stage_identity(item.get("observed_identity"))
                or item.get("observed_identity") is None):
            raise WorkspaceError("workspace manifest의 preserved stage 진단이 올바르지 않습니다.")
    if os.path.normcase(os.path.abspath(data.get("workspace_root", ""))) != os.path.normcase(root):
        raise WorkspaceError("manifest가 현재 workspace 경로를 소유한다고 증명하지 못합니다.")
    _recover_manifest_temp(root, owner_id)
    if verify:
        _verify_live(root, data)
    return root, data


def _verify_live(root, data, *, verify_artifacts=True):
    for item in data.get("inputs", []):
        internal = _safe_relative(root, item.get("workspace_path"))
        if _file_fingerprint(internal) != item.get("fingerprint"):
            raise WorkspaceError(f"workspace 입력 사본이 변경되었습니다: {item.get('id')}")
        try:
            current = _file_fingerprint(item.get("source_path", ""))
        except WorkspaceError as exc:
            raise WorkspaceError(f"입력 원본이 stale 또는 접근 불가입니다 ({item.get('role')}): {exc}") from exc
        if current != item.get("fingerprint"):
            raise WorkspaceError(f"입력 원본이 begin 이후 변경되었습니다: {item.get('source_path')}")
    for item in data.get("references", []):
        try:
            current = _reference_fingerprint(item.get("source_path", ""))
        except WorkspaceError as exc:
            raise WorkspaceError(f"기준자료가 stale 또는 접근 불가입니다: {item.get('source_path')}: {exc}") from exc
        if current != item.get("fingerprint"):
            raise WorkspaceError(f"기준자료가 begin 이후 변경되었습니다: {item.get('source_path')}")
    if verify_artifacts:
        for name, item in data.get("artifacts", {}).items():
            internal = _safe_relative(root, item.get("workspace_path"))
            if _file_fingerprint(internal) != item.get("fingerprint"):
                raise WorkspaceError(f"체크포인트 산출물이 변경되었습니다: {name}")
    _verify_receipts(data)


def _verify_receipts(data):
    receipts = data.get("publish_receipts", {})
    output_dir = data.get("output_dir", "")
    plan = {item.get("artifact"): item for item in data.get("publish_plan") or []}
    for name, receipt in receipts.items():
        filename = receipt.get("filename", "")
        if not _is_filename(filename):
            raise WorkspaceError(f"게시 receipt의 출력 경로가 올바르지 않습니다: {name}")
        planned = plan.get(name)
        artifact = data.get("artifacts", {}).get(name)
        if (planned is None or artifact is None or planned.get("target_filename") != filename
                or artifact.get("fingerprint") != receipt.get("fingerprint")):
            raise WorkspaceError(f"게시 receipt와 checkpoint/publish plan이 일치하지 않습니다: {name}")
        path = os.path.join(output_dir, filename)
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise WorkspaceError(f"게시 receipt 대상이 없어 stale 상태입니다: {path}") from exc
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError(f"게시 receipt 대상이 일반 파일이 아닙니다: {path}")
        if _file_fingerprint(path) != receipt.get("fingerprint"):
            raise WorkspaceError(f"게시된 파일이 receipt 이후 변경되었습니다: {path}")


def begin(primary, *, inputs=(), references=(), output_dir=None):
    """Create a private workspace and return its manifest summary."""
    primary_path, primary_fp = _checked_source(primary)
    all_inputs = [("primary", primary_path, primary_fp)]
    if isinstance(inputs, dict):
        inputs = list(inputs.items())
    for role, path in inputs:
        role = str(role).strip()
        if not role or role == "primary" or "\x00" in role:
            raise WorkspaceError(f"입력 role이 올바르지 않습니다: {role!r}")
        source_path, fingerprint = _checked_source(path)
        all_inputs.append((role, source_path, fingerprint))
    reference_records = []
    for reference in references:
        path = os.path.abspath(os.fspath(reference))
        reference_records.append({"source_path": path, "fingerprint": _reference_fingerprint(path)})

    destination = os.path.abspath(os.fspath(output_dir)) if output_dir else os.path.join(
        os.path.dirname(primary_path), "output")
    root = os.path.realpath(tempfile.mkdtemp(prefix="rfp-review-"))
    root_info = os.lstat(root)
    owned_files = []
    owned_dirs = []
    try:
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        workspace_id = os.path.basename(root)
        owner_path = os.path.join(root, OWNER)
        with open(owner_path, "x", encoding="ascii", newline="\n") as stream:
            try:
                os.chmod(owner_path, 0o600)
            except OSError:
                pass
            stream.write(workspace_id + "\n")
            owned_files.append((owner_path, os.fstat(stream.fileno())))
        input_dir = os.path.join(root, "inputs")
        os.mkdir(input_dir)
        owned_dirs.append((input_dir, os.lstat(input_dir)))
        intermediate_dir = os.path.join(root, "work")
        os.mkdir(intermediate_dir)
        owned_dirs.append((intermediate_dir, os.lstat(intermediate_dir)))
        records = []
        for index, (role, source_path, fingerprint) in enumerate(all_inputs, 1):
            extension = os.path.splitext(source_path)[1]
            filename = f"input-{index:04d}{extension}"
            relative = f"inputs/{filename}"
            internal_path = os.path.join(input_dir, filename)
            _copy_input(source_path, internal_path, fingerprint)
            owned_files.append((internal_path, os.lstat(internal_path)))
            records.append({
                "id": f"input-{index:04d}",
                "role": role,
                "source_path": source_path,
                "source_name": os.path.basename(source_path),
                "workspace_path": relative,
                "fingerprint": fingerprint,
            })
        manifest = {
            "version": VERSION,
            "workspace_id": workspace_id,
            "workspace_root": os.path.abspath(root),
            "created_at": _now(),
            "primary_input": records[0]["id"],
            "inputs": records,
            "references": reference_records,
            "intermediate_root": "work",
            "output_dir": destination,
            "artifacts": {},
            "publish_plan": None,
            "publish_receipts": {},
            "preserved_stages": [],
            "handoff_checkpoint": None,
        }
        _write_manifest(root, manifest)
        owned_files.append((os.path.join(root, MANIFEST), os.lstat(os.path.join(root, MANIFEST))))
    except Exception as exc:
        # Remove only paths this call created and whose filesystem identity still matches.
        for path, original in reversed(owned_files):
            _unlink_if_same(path, original)
        for path, original in reversed(owned_dirs):
            try:
                current = os.lstat(path)
                if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino) and stat.S_ISDIR(current.st_mode):
                    os.rmdir(path)
            except OSError:
                pass
        try:
            current = os.lstat(root)
            if (current.st_dev, current.st_ino) == (root_info.st_dev, root_info.st_ino):
                os.rmdir(root)
        except OSError:
            pass
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError(f"workspace 생성 실패: {exc}") from exc
    return {"workspace": root, "manifest": manifest}


def status(workspace):
    """Verify sources, checkpoints, and publication receipts; reject stale runs."""
    root, data = _load_workspace(workspace, verify=True)
    manifest_temporaries = _manifest_temp_diagnostics(root, data["workspace_id"])
    return {
        "workspace": data["workspace_root"],
        "workspace_id": data["workspace_id"],
        "primary_input": data["primary_input"],
        "inputs": data["inputs"],
        "references": data["references"],
        "intermediate_root": data["intermediate_root"],
        "artifacts": data["artifacts"],
        "preserved_stages": [dict(item, path=_stage_path(data, item["filename"]),
                                  exists=os.path.lexists(_stage_path(data, item["filename"])))
                             for item in data.get("preserved_stages", [])],
        "manifest_temporaries": manifest_temporaries,
        "output_dir": data["output_dir"],
        "publish_plan": data["publish_plan"],
        "publish_receipts": data["publish_receipts"],
        "handoff_checkpoint": data["handoff_checkpoint"],
        "visible_chat_proof": False,
    }


def _artifact_name(name):
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or name == "handoff":
        raise WorkspaceError(f"artifact 이름은 안전한 ASCII label이어야 합니다: {name!r}")
    return name


def _dependent_artifacts(artifacts, name):
    affected = {name}
    changed = True
    while changed:
        changed = False
        for candidate, record in artifacts.items():
            if candidate not in affected and affected.intersection(record.get("depends_on", [])):
                affected.add(candidate)
                changed = True
    return affected


def _check_dependency_graph(artifacts, name, dependencies):
    graph = {key: list(record.get("depends_on", [])) for key, record in artifacts.items()}
    graph[name] = dependencies
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise WorkspaceError("artifact checkpoint 의존성에 순환이 있습니다.")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, []):
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def checkpoint(workspace, name, artifact_path=None, *, depends_on=None):
    """Hash an internal artifact, or record the non-attesting handoff marker."""
    # Inputs and references remain strict, but stale artifact hashes must be refreshable.
    root, data = _load_workspace(workspace, verify=False)
    _verify_live(root, data, verify_artifacts=False)
    if data.get("handoff_checkpoint") is not None:
        raise WorkspaceError("handoff checkpoint 이후에는 workspace를 변경할 수 없습니다.")
    if name == "handoff":
        if artifact_path is not None or depends_on is not None:
            raise WorkspaceError("handoff checkpoint에는 artifact 경로나 depends_on을 지정하지 않습니다.")
        _verify_live(root, data, verify_artifacts=True)
        plan = data.get("publish_plan") or []
        receipts = data.get("publish_receipts", {})
        if not plan or any(item["artifact"] not in receipts for item in plan):
            raise WorkspaceError("요청한 모든 산출물 게시 receipt가 확인된 뒤 handoff checkpoint를 기록하세요.")
        _verify_receipts(data)
        data["handoff_checkpoint"] = {
            "checkpointed_at": _now(),
            "visible_chat_proof": False,
            "note": _HANDOFF_NOTE,
        }
        _write_manifest(root, data)
        return data["handoff_checkpoint"]

    name = _artifact_name(name)
    if artifact_path is None:
        raise WorkspaceError("artifact checkpoint에는 workspace 내부 파일 경로가 필요합니다.")
    relative = os.fspath(artifact_path)
    path = _safe_relative(root, relative)
    normalized = relative.replace("\\", "/")
    if not normalized.startswith(data.get("intermediate_root", "work") + "/"):
        raise WorkspaceError("artifact checkpoint는 소유 intermediate root(work/) 안에 있어야 합니다.")
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceError(f"artifact는 일반 파일이어야 합니다: {relative}")
    record = {"workspace_path": normalized, "fingerprint": _file_fingerprint(path)}
    old = data["artifacts"].get(name)
    if depends_on is None:
        dependencies = list(old.get("depends_on", [])) if old else []
    else:
        dependencies = list(dict.fromkeys(depends_on))
    if name in dependencies or any(dependency not in data["artifacts"] for dependency in dependencies):
        raise WorkspaceError("depends_on에는 이미 checkpoint된 다른 artifact만 지정할 수 있습니다.")
    for dependency in dependencies:
        dependency_record = data["artifacts"][dependency]
        dependency_path = _safe_relative(root, dependency_record["workspace_path"])
        if _file_fingerprint(dependency_path) != dependency_record["fingerprint"]:
            raise WorkspaceError(f"의존 artifact가 stale 상태입니다. 먼저 갱신하세요: {dependency}")
    _check_dependency_graph(data["artifacts"], name, dependencies)
    record["depends_on"] = dependencies
    old_semantics = old and (old.get("workspace_path"), old.get("fingerprint"), old.get("depends_on", []))
    new_semantics = (record["workspace_path"], record["fingerprint"], dependencies)
    if old is not None and old_semantics == new_semantics:
        return old
    if old is not None:
        affected = _dependent_artifacts(data["artifacts"], name)
        planned = {item["artifact"] for item in data.get("publish_plan") or []}
        if affected.intersection(planned):
            raise WorkspaceError(
                "게시 plan이 시작된 artifact 또는 선행 artifact는 수정할 수 없습니다. "
                "기존 staging과 plan을 보존하고 새 workspace에서 다시 시작하세요."
            )
        for dependent in affected - {name}:
            data["artifacts"].pop(dependent, None)
    record["checkpointed_at"] = _now()
    data["artifacts"][name] = record
    _write_manifest(root, data)
    return record


def _is_filename(filename):
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        return False
    if (filename.endswith((" ", ".")) or any(ord(ch) < 32 for ch in filename)
            or any(ch in '<>:"/\\|?*' for ch in filename)
            or re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", filename)):
        return False
    windows_path = PureWindowsPath(filename)
    return (filename not in (".", "..") and "/" not in filename and "\\" not in filename
            and ":" not in filename and not windows_path.drive and not windows_path.is_absolute())


def _filename_for_number(filename, number):
    stem, extension = os.path.splitext(filename)
    if stem.endswith(_MEMO_MARKER):
        return f"{stem[:-len(_MEMO_MARKER)]}_{number}{_MEMO_MARKER}{extension}"
    return f"{stem}_{number}{extension}"


def _choose_filename(directory, requested, start=1):
    if not _is_filename(requested):
        raise WorkspaceError(f"출력 파일명은 경로 구분자 없는 파일명이어야 합니다: {requested!r}")
    try:
        names = {name.casefold() for name in os.listdir(directory)}
    except OSError as exc:
        raise WorkspaceError(f"출력 디렉터리를 읽을 수 없습니다: {directory}: {exc}") from exc
    number = start
    while True:
        candidate = requested if number == 1 else _filename_for_number(requested, number)
        if candidate.casefold() not in names and not os.path.lexists(os.path.join(directory, candidate)):
            return candidate
        number = 2 if number == 1 else number + 1


def _copy_exclusive(source, target, expected, *, on_created=None):
    """Write a binary file exclusively; commit its inode before writing any payload."""
    if _file_fingerprint(source) != expected:
        raise WorkspaceError(f"게시 직전 artifact가 변경되었습니다: {source}")
    descriptor = None
    created_info = None
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        created_info = os.fstat(descriptor)
        if on_created is not None:
            on_created(_stage_identity(created_info))
        with open(source, "rb") as stream, os.fdopen(descriptor, "wb") as output:
            descriptor = None
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual = {"sha256": digest.hexdigest(), "size": size}
        completed_stage = _file_fingerprint(target)
        if actual != expected or completed_stage != expected or _file_fingerprint(source) != expected:
            raise WorkspaceError(f"게시 중 artifact가 변경되었습니다: {source}")
        return completed_stage
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if created_info is not None:
            _unlink_if_same(target, created_info)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _stage_identity(info):
    if info.st_ino <= 0:
        raise WorkspaceError("파일시스템이 안정적인 staging inode identity를 제공하지 않습니다.")
    return {"device": int(info.st_dev), "inode": int(info.st_ino)}


def _valid_stage_identity(identity):
    if identity is None:
        return True
    return (isinstance(identity, dict) and set(identity) == {"device", "inode"}
            and all(isinstance(identity[key], int) and not isinstance(identity[key], bool)
                    and identity[key] >= (1 if key == "inode" else 0) for key in ("device", "inode")))


def _identity_matches(info, identity):
    return _valid_stage_identity(identity) and identity is not None \
        and (info.st_dev, info.st_ino) == (identity["device"], identity["inode"])


def _stage_filename(data, artifact):
    return f".rfp-stage-{data['workspace_id']}-{artifact}-{secrets.token_hex(16)}.tmp"


def _is_owned_stage_filename(data, artifact, filename):
    prefix = f".rfp-stage-{data.get('workspace_id')}-{artifact}-"
    return (_is_filename(filename) and filename.startswith(prefix) and filename.endswith(".tmp")
            and len(filename) == len(prefix) + 32 + 4
            and all(char in "0123456789abcdef" for char in filename[len(prefix):-4]))


def _stage_path(data, filename):
    return os.path.join(data["output_dir"], filename)


def _remove_owned_stage(data, artifact, filename, identity):
    if not _is_owned_stage_filename(data, artifact, filename):
        raise WorkspaceError(f"manifest stage 소유권 증명이 올바르지 않습니다: {filename}")
    if not _valid_stage_identity(identity) or identity is None:
        raise WorkspaceError(f"staging 파일 생성 identity가 없어 삭제하지 않습니다: {filename}")
    path = _stage_path(data, filename)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        raise WorkspaceError(f"소유 staging 경로가 일반 파일이 아닙니다: {path}")
    if not _identity_matches(info, identity):
        raise WorkspaceError(f"staging 생성 identity가 달라 파일을 보존합니다: {path}")
    try:
        current = os.lstat(path)
        if not _identity_matches(current, identity):
            raise WorkspaceError(f"staging 파일이 검사 중 교체되었습니다: {path}")
        os.unlink(path)
    except OSError as exc:
        raise WorkspaceError(f"소유 staging 파일을 정리할 수 없습니다: {path}: {exc}") from exc


def _prepare_stage(root, data, item, source, expected):
    artifact = item["artifact"]
    filename = item.get("stage_filename")
    if filename is not None and not _is_owned_stage_filename(data, artifact, filename):
        raise WorkspaceError(f"manifest stage 소유권 증명이 올바르지 않습니다: {filename}")
    if filename is not None:
        path = _stage_path(data, filename)
        if os.path.lexists(path):
            info = os.lstat(path)
            if _is_link(info) or not stat.S_ISREG(info.st_mode):
                raise WorkspaceError(f"소유 staging 경로가 일반 파일이 아닙니다: {path}")
            identity = item.get("stage_identity")
            if identity is None or not _identity_matches(info, identity):
                reason = "identity 미기록" if identity is None else "device/inode 불일치"
                _record_preserved_stage(data, item, info, reason)
                item["stage_filename"] = None
                item["stage_identity"] = None
                _write_manifest(root, data)
                filename = None
            elif _file_fingerprint(path) == expected:
                if _file_fingerprint(source) != expected:
                    raise WorkspaceError(f"staging 준비 중 checkpoint artifact가 변경되었습니다: {source}")
                return path
            else:
                _remove_owned_stage(data, artifact, filename, identity)
                item["stage_filename"] = None
                item["stage_identity"] = None
                _write_manifest(root, data)
                filename = None
        elif item.get("stage_identity") is not None:
            # Our prior staging file disappeared. Drop its stale identity before retrying O_EXCL.
            item["stage_identity"] = None
            _write_manifest(root, data)
    while True:
        if filename is None:
            filename = _stage_filename(data, artifact)
            path = _stage_path(data, filename)
            item["stage_filename"] = filename
            item["stage_identity"] = None
            _write_manifest(root, data)  # Reserve opaque name before O_EXCL creation.
        else:
            path = _stage_path(data, filename)

        def commit_identity(identity):
            item["stage_identity"] = identity
            _write_manifest(root, data)

        try:
            _copy_exclusive(source, path, expected, on_created=commit_identity)
        except FileExistsError:
            # The exclusive create did not happen; retain the colliding path as an unclaimed diagnostic.
            if os.path.lexists(path):
                info = os.lstat(path)
                _record_preserved_stage(data, item, info, "O_EXCL 충돌: 이 실행이 생성하지 않은 경로")
            item["stage_filename"] = None
            item["stage_identity"] = None
            _write_manifest(root, data)
            filename = None
            continue
        actual = _file_fingerprint(path)
        if actual != expected or _file_fingerprint(source) != expected:
            _remove_owned_stage(data, artifact, filename, item["stage_identity"])
            item["stage_filename"] = None
            item["stage_identity"] = None
            _write_manifest(root, data)
            raise WorkspaceError(f"staging 파일의 완료 hash가 checkpoint와 다릅니다: {source}")
        return path


def _record_preserved_stage(data, plan_item, info, reason):
    filename = plan_item["stage_filename"]
    artifact = plan_item["artifact"]
    entry = {"artifact": artifact, "filename": filename, "reason": reason,
             "observed_identity": _stage_identity(info)}
    if entry not in data.setdefault("preserved_stages", []):
        data["preserved_stages"].append(entry)


def _publish_stage(stage, target, expected):
    """Expose a completed same-filesystem stage with atomic no-replace semantics."""
    if _file_fingerprint(stage) != expected:
        raise WorkspaceError(f"staging 파일 hash가 checkpoint와 다릅니다: {stage}")
    try:
        os.link(stage, target)
    except FileExistsError:
        raise
    except OSError as exc:
        raise WorkspaceError(
            f"파일시스템이 원자적 no-replace 게시(hard link)를 지원하지 않아 게시를 중단했습니다: {exc}"
        ) from exc
    try:
        info = os.lstat(target)
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError(f"원자 게시 결과가 일반 파일이 아닙니다: {target}")
        actual = _file_fingerprint(target)
        if actual != expected:
            raise WorkspaceError(f"게시 완료 파일 hash가 checkpoint와 다릅니다: {target}")
        return actual
    except BaseException:
        try:
            if os.path.samefile(stage, target):
                os.unlink(target)
        except OSError:
            pass
        raise


def _record_receipt(root, data, item, target, expected, *, recovered):
    actual = _file_fingerprint(target)
    if actual != expected:
        raise WorkspaceError(f"게시 대상 hash가 checkpoint와 다릅니다: {target}")
    receipt = {"filename": item["target_filename"], "fingerprint": actual,
               "published_at": _now(), "recovered": recovered}
    data["publish_receipts"][item["artifact"]] = receipt
    _write_manifest(root, data)
    stage_name = item.get("stage_filename")
    if stage_name and _is_owned_stage_filename(data, item["artifact"], stage_name):
        stage = _stage_path(data, stage_name)
        try:
            if os.path.exists(stage) and os.path.samefile(stage, target):
                _remove_owned_stage(data, item["artifact"], stage_name, item.get("stage_identity"))
        except (OSError, WorkspaceError):
            # The valid receipt survives; cleanup() must remove this stage or fail
            # without deleting the workspace. Publication is not a cleanup claim.
            pass
    return receipt


def publish(workspace, artifacts):
    """Publish named checkpoints, no-clobber, with per-file retry receipts."""
    root, data = _load_workspace(workspace, verify=True)
    if data.get("handoff_checkpoint") is not None:
        raise WorkspaceError("handoff checkpoint 이후에는 게시할 수 없습니다.")
    if isinstance(artifacts, dict):
        requested = list(artifacts.items())
    else:
        requested = list(artifacts)
    if not requested:
        raise WorkspaceError("게시할 artifact=파일명 항목이 필요합니다.")
    plan = []
    seen = set()
    for name, filename in requested:
        name = _artifact_name(name)
        if name in seen:
            raise WorkspaceError(f"게시 요청에 artifact가 중복되었습니다: {name}")
        seen.add(name)
        if name not in data["artifacts"]:
            raise WorkspaceError(f"먼저 artifact checkpoint가 필요합니다: {name}")
        if not _is_filename(filename):
            raise WorkspaceError(f"게시 출력은 파일명만 허용됩니다: {filename!r}")
        plan.append({"artifact": name, "filename": filename, "target_filename": None,
                     "stage_filename": None, "stage_identity": None})
    old_plan = data.get("publish_plan")
    if old_plan is not None:
        comparable = [(item["artifact"], item["filename"]) for item in old_plan]
        if comparable != [(item["artifact"], item["filename"]) for item in plan]:
            raise WorkspaceError("게시 재시도 요청이 저장된 publish plan과 다릅니다.")
        plan = old_plan
    else:
        data["publish_plan"] = plan
        _write_manifest(root, data)
        plan = data["publish_plan"]

    output_dir = data["output_dir"]
    try:
        if os.path.commonpath((root, os.path.abspath(output_dir))) == root:
            raise WorkspaceError("게시 위치를 workspace 내부로 지정할 수 없습니다.")
    except ValueError:
        pass
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise WorkspaceError(f"출력 디렉터리를 만들 수 없습니다: {output_dir}: {exc}") from exc
    if not os.path.isdir(output_dir):
        raise WorkspaceError(f"출력 경로가 디렉터리가 아닙니다: {output_dir}")

    results = []
    receipts = data["publish_receipts"]
    for item in plan:
        name = item["artifact"]
        record = data["artifacts"][name]
        if name in receipts:
            receipt = receipts[name]
            stage_name = item.get("stage_filename")
            if stage_name and _is_owned_stage_filename(data, name, stage_name):
                try:
                    stage = _stage_path(data, stage_name)
                    target = os.path.join(output_dir, receipt["filename"])
                    stage_info = os.lstat(stage)
                    if not _is_link(stage_info) and stat.S_ISREG(stage_info.st_mode) \
                            and _identity_matches(stage_info, item.get("stage_identity")) \
                            and os.path.samefile(stage, target):
                        _remove_owned_stage(data, name, stage_name, item.get("stage_identity"))
                except (OSError, WorkspaceError):
                    pass
            results.append({"artifact": name, "path": os.path.join(output_dir, receipt["filename"]),
                            "sha256": receipt["fingerprint"]["sha256"], "already_published": True})
            continue
        source = _safe_relative(root, record["workspace_path"])
        expected = record["fingerprint"]
        while True:
            filename = item.get("target_filename")
            if filename is None:
                filename = _choose_filename(output_dir, item["filename"])
                item["target_filename"] = filename
                _write_manifest(root, data)
            target = os.path.join(output_dir, filename)
            stage = _prepare_stage(root, data, item, source, expected)
            if os.path.lexists(target):
                try:
                    committed_stage = os.path.samefile(stage, target)
                except OSError:
                    committed_stage = False
                if committed_stage:
                    receipt = _record_receipt(root, data, item, target, expected, recovered=True)
                    results.append({"artifact": name, "path": target, "sha256": receipt["fingerprint"]["sha256"],
                                    "already_published": True})
                    break
                item["target_filename"] = _choose_filename(output_dir, item["filename"], start=2)
                _write_manifest(root, data)
                continue
            try:
                actual = _publish_stage(stage, target, expected)
            except FileExistsError:
                try:
                    committed_stage = os.path.samefile(stage, target)
                except OSError:
                    committed_stage = False
                if committed_stage:
                    receipt = _record_receipt(root, data, item, target, expected, recovered=True)
                    results.append({"artifact": name, "path": target,
                                    "sha256": receipt["fingerprint"]["sha256"], "already_published": True})
                    break
                item["target_filename"] = _choose_filename(output_dir, item["filename"], start=2)
                _write_manifest(root, data)
                continue
            receipt = _record_receipt(root, data, item, target, expected, recovered=False)
            results.append({"artifact": name, "path": target, "sha256": receipt["fingerprint"]["sha256"],
                            "already_published": False})
            break
    return {"output_dir": output_dir, "published": results, "receipts": data["publish_receipts"],
            "preserved_stages": _preserved_stage_views(data),
            "manifest_temporaries": _manifest_temp_diagnostics(root, data["workspace_id"])}


def _preserved_stage_views(data):
    return [dict(item, path=_stage_path(data, item["filename"]),
                 exists=os.path.lexists(_stage_path(data, item["filename"])))
            for item in data.get("preserved_stages", [])]


def _workspace_inventory(root, data):
    owned_root = data.get("intermediate_root")
    if owned_root != "work":
        raise WorkspaceError("manifest의 owned intermediate root가 올바르지 않습니다.")
    expected_files = {OWNER, MANIFEST}
    for item in data.get("inputs", []):
        expected_files.add(item["workspace_path"])
    for item in data.get("artifacts", {}).values():
        expected_files.add(item["workspace_path"])
    actual_files, actual_dirs = set(), set()
    def visit(directory, relative):
        try:
            with os.scandir(directory) as scan:
                children = sorted(scan, key=lambda entry: entry.name)
        except OSError as exc:
            raise WorkspaceError(f"cleanup 거부: workspace 디렉터리를 읽을 수 없습니다: {directory}: {exc}") from exc
        for entry in children:
            child_relative = f"{relative}/{entry.name}" if relative else entry.name
            info = entry.stat(follow_symlinks=False)
            if _is_link(info):
                raise WorkspaceError(f"cleanup 거부: workspace 내부 링크는 따라가지 않습니다: {entry.path}")
            if stat.S_ISDIR(info.st_mode):
                actual_dirs.add(child_relative)
                visit(entry.path, child_relative)
            elif stat.S_ISREG(info.st_mode):
                actual_files.add(child_relative)
            else:
                raise WorkspaceError(f"cleanup 거부: 특수 파일을 정리할 수 없습니다: {entry.path}")

    visit(root, "")
    owned_files = {path for path in actual_files if path.startswith(owned_root + "/")}
    owned_dirs = {path for path in actual_dirs if path == owned_root or path.startswith(owned_root + "/")}
    allowed_files = expected_files | owned_files
    expected_dirs = {owned_root} | owned_dirs
    for relative in allowed_files:
        parent = PurePosixPath(relative).parent
        while str(parent) not in (".", ""):
            expected_dirs.add(str(parent))
            parent = parent.parent
    if actual_files != allowed_files or actual_dirs != expected_dirs:
        unknown = sorted(actual_files - allowed_files) + sorted(actual_dirs - expected_dirs)
        missing = sorted(allowed_files - actual_files) + sorted(expected_dirs - actual_dirs)
        detail = f"unknown={unknown[:5]}, missing={missing[:5]}"
        raise WorkspaceError(f"cleanup 거부: manifest가 소유하지 않는 항목이 있거나 관리 파일이 없습니다 ({detail}).")
    return sorted(actual_files), sorted(actual_dirs)


def _cleanup_owned_stages(data):
    for item in data.get("publish_plan") or []:
        filename = item.get("stage_filename")
        if filename is None:
            continue
        artifact = item.get("artifact")
        if not _is_owned_stage_filename(data, artifact, filename):
            raise WorkspaceError(f"manifest stage 소유권 증명이 올바르지 않습니다: {filename}")
        stage = _stage_path(data, filename)
        if not os.path.lexists(stage):
            continue
        info = os.lstat(stage)
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError(f"cleanup이 소유 staging 경로를 검증하지 못했습니다: {stage}")
        receipt = data["publish_receipts"].get(artifact)
        if receipt is None:
            raise WorkspaceError(f"게시되지 않은 staging을 자동 삭제하지 않습니다: {stage}")
        target = os.path.join(data["output_dir"], receipt["filename"])
        if (not os.path.samefile(stage, target)
                or _file_fingerprint(stage) != receipt["fingerprint"]):
            raise WorkspaceError(f"staging이 검증된 게시 파일과 일치하지 않아 보존합니다: {stage}")
        _remove_owned_stage(data, artifact, filename, item.get("stage_identity"))
    for entry in data.get("preserved_stages", []):
        path = _stage_path(data, entry["filename"])
        if os.path.lexists(path):
            raise WorkspaceError(f"출처를 확인할 수 없는 staging diagnostic을 보존합니다: {path}")


def cleanup(workspace):
    """Delete only a verified workspace whose published outputs and handoff marker remain valid."""
    root, data = _load_workspace(workspace, verify=True)
    manifest_temporaries = _manifest_temp_diagnostics(root, data["workspace_id"])
    if manifest_temporaries:
        raise WorkspaceError(f"cleanup 거부: manifest transaction diagnostic을 보존합니다: {manifest_temporaries}")
    plan = data.get("publish_plan") or []
    receipts = data.get("publish_receipts", {})
    if not plan or any(item["artifact"] not in receipts for item in plan):
        raise WorkspaceError("모든 요청 산출물이 게시되고 receipt가 검증되기 전에는 cleanup할 수 없습니다.")
    if data.get("handoff_checkpoint") is None:
        raise WorkspaceError("handoff checkpoint 전에는 cleanup할 수 없습니다. 실제 가시 채팅 전달은 별도 확인입니다.")
    if data["handoff_checkpoint"].get("visible_chat_proof") is not False:
        raise WorkspaceError("handoff checkpoint를 실제 채팅 증거로 사용할 수 없습니다.")
    inventory_files, inventory_dirs = _workspace_inventory(root, data)
    _cleanup_owned_stages(data)

    # Paths are derived only from the verified manifest and are rechecked before removal.
    files = sorted(inventory_files, key=lambda value: value.count("/"), reverse=True)
    directories = sorted(inventory_dirs, key=lambda value: value.count("/"), reverse=True)
    for relative in files:
        path = _safe_relative(root, relative)
        info = os.lstat(path)
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            raise WorkspaceError(f"cleanup 중 파일 소유권을 다시 확인할 수 없습니다: {path}")
        os.unlink(path)
    for relative in directories:
        path = os.path.join(root, *relative.split("/"))
        if os.path.lexists(path):
            info = os.lstat(path)
            if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise WorkspaceError(f"cleanup 중 디렉터리 소유권을 다시 확인할 수 없습니다: {path}")
            os.rmdir(path)
    os.rmdir(root)
    return {"cleaned": True, "workspace": root, "visible_chat_proof": False}


def _parse_assignment(value, description):
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"{description}은 NAME=VALUE 형식이어야 합니다: {value}")
    name, content = value.split("=", 1)
    if not name or not content:
        raise argparse.ArgumentTypeError(f"{description}의 이름과 값은 비어 있을 수 없습니다: {value}")
    return name, content


def main(argv=None):
    parser = argparse.ArgumentParser(description="검토 파일의 private workspace lifecycle helper (모델 runner 아님)")
    commands = parser.add_subparsers(dest="command", required=True)
    begin_parser = commands.add_parser("begin", help="입력을 fingerprint하고 OS temp workspace/work 생성")
    begin_parser.add_argument("primary", help="주 입력 파일")
    begin_parser.add_argument("--input", action="append", default=[], metavar="ROLE=PATH", help="보조 입력; 반복 가능")
    begin_parser.add_argument("--reference", action="append", default=[], metavar="PATH", help="기준 파일/디렉터리 fingerprint; 반복 가능")
    begin_parser.add_argument("--output-dir", help="게시 위치 (기본: 주 입력 부모/output)")
    status_parser = commands.add_parser("status", help="입력·기준·artifact·게시 receipt stale 여부 확인")
    status_parser.add_argument("workspace")
    checkpoint_parser = commands.add_parser("checkpoint", help="내부 artifact hash 또는 handoff lifecycle marker 저장")
    checkpoint_parser.add_argument("workspace")
    checkpoint_parser.add_argument("name")
    checkpoint_parser.add_argument("artifact", nargs="?", help="workspace 상대 파일 경로; handoff에는 지정하지 않음")
    checkpoint_parser.add_argument("--depends-on", action="append", default=[], metavar="NAME")
    publish_parser = commands.add_parser("publish", help="checkpoint artifact를 collision-safe no-clobber 게시")
    publish_parser.add_argument("workspace")
    publish_parser.add_argument("artifacts", nargs="+", metavar="NAME=FILENAME")
    cleanup_parser = commands.add_parser("cleanup", help="receipt와 handoff marker 확인 후 소유 workspace만 정리")
    cleanup_parser.add_argument("workspace")
    args = parser.parse_args(argv)
    try:
        if args.command == "begin":
            inputs = [_parse_assignment(item, "--input") for item in args.input]
            result = begin(args.primary, inputs=inputs, references=args.reference, output_dir=args.output_dir)
        elif args.command == "status":
            result = status(args.workspace)
        elif args.command == "checkpoint":
            result = checkpoint(args.workspace, args.name, args.artifact,
                                depends_on=args.depends_on or None)
        elif args.command == "publish":
            artifacts = [_parse_assignment(item, "artifact") for item in args.artifacts]
            result = publish(args.workspace, artifacts)
        else:
            result = cleanup(args.workspace)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (WorkspaceError, OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print(f"review_workspace: 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
