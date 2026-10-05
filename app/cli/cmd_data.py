# app/cli/cmd_data.py
"""
Bounded Context:  CLI Interface
Responsibility:   ``graphyn data ls|upload|snapshot|download`` — input/output
                  dataset management from the terminal.
Owns:             cmd_data_ls, cmd_data_upload, cmd_data_snapshot, cmd_data_download
Public Surface:   cmd_data_ls, cmd_data_upload, cmd_data_snapshot, cmd_data_download
Must NOT:         Contain dataset storage logic (delegates to
                  app.core.mlops.dataset_inputs / dataset_versions locally, or
                  to the REST /data endpoints when --api-url / GRAPHYN_API_URL
                  is set). Must not import app.api.
Dependencies:     app.core.config, app.core.mlops.dataset_inputs,
                  app.core.mlops.dataset_versions, app.core.trust.audit,
                  stdlib (urllib, json, uuid).
Reason To Change: Data subcommand flags or output change.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from app.cli.exit_codes import EXIT_GENERAL, EXIT_NOT_FOUND, EXIT_VALIDATION, CliError


# ── helpers ──────────────────────────────────────────────────────────────────


def _api() -> tuple[str | None, str | None]:
    url = (os.environ.get("GRAPHYN_API_URL") or "").strip().rstrip("/")
    return (url or None), (os.environ.get("GRAPHYN_API_TOKEN") or None)


def _actor() -> str:
    return (os.environ.get("GRAPHYN_ACTOR") or "").strip()[:128] or "cli"


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json", "X-Actor": _actor()}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _request(method: str, path: str, *, body: bytes | None = None, ctype: str | None = None):
    base, token = _api()
    headers = _headers(token)
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(f"{base}/api/v1{path}", data=body, headers=headers, method=method)
    try:
        return urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        code = EXIT_NOT_FOUND if exc.code == 404 else EXIT_VALIDATION if exc.code in (400, 409, 413, 422) else EXIT_GENERAL
        raise CliError(f"{method} {path} failed ({exc.code}): {detail[:500]}", code) from exc


def _remote_json(method: str, path: str, **kw) -> Any:
    with _request(method, path, **kw) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def _audit(action: str, resource_type: str, resource_id: str, meta: dict) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(actor=_actor(), action=action, resource_type=resource_type, resource_id=resource_id, meta={**meta, "via": "cli"})
    except Exception:
        pass


def _print(args, payload: Any, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(text)


# ── ls ───────────────────────────────────────────────────────────────────────


def cmd_data_ls(args):
    """List input labels (no arg), files of a label, or output versions (--outputs)."""
    base, _ = _api()
    label = getattr(args, "label", None)
    outputs = getattr(args, "outputs", False)
    if base:
        if outputs:
            data = _remote_json("GET", "/data/outputs?envelope=0&limit=500")
        elif label:
            data = _remote_json("GET", f"/data/inputs/{urllib.parse.quote(label)}")
        else:
            data = _remote_json("GET", "/data/inputs")
    else:
        from app.core.config import datasets_input_dir, datasets_output_dir
        from app.core.mlops.dataset_inputs import label_counts, label_file_rows, list_input_snapshots
        from app.core.mlops.dataset_versions import VERSION_RE

        in_root, out_root = datasets_input_dir(), datasets_output_dir()
        if outputs:
            data = []
            if out_root.is_dir():
                for p in sorted(out_root.iterdir()):
                    if p.is_dir() and not p.name.startswith((".", "_inputs")):
                        data.append({"project": p.name, "versions": sorted(v.name for v in p.iterdir() if v.is_dir() and VERSION_RE.match(v.name))})
                data.extend(list_input_snapshots(out_root))
        elif label:
            if not (in_root / label).is_dir():
                raise CliError(f"Input label '{label}' not found", EXIT_NOT_FOUND)
            data = label_file_rows(in_root, in_root / label, label)
        else:
            data = []
            if in_root.is_dir():
                for p in sorted(in_root.iterdir()):
                    if p.is_dir() and not p.name.startswith("."):
                        data.append({"label": p.name, **label_counts(p)})
    if outputs:
        text = "\n".join(f"{o['project']}: {', '.join(o.get('versions') or []) or '—'}" for o in data) or "No output datasets."
    elif label:
        text = "\n".join(f"{r['path']}\t{r.get('kind', '')}\t{r.get('size_bytes', '')}" for r in data) or "No files."
    else:
        text = "\n".join(f"{r['label']}\t{r['file_count']} files ({r.get('audio_count', 0)} audio)" for r in data) or "No input labels."
    _print(args, data, text)


# ── upload ───────────────────────────────────────────────────────────────────


def _expand(paths: list[str]) -> list[tuple[str, Path]]:
    """``(relative_name, path)``; a directory keeps its folder name as the first segment."""
    out: list[tuple[str, Path]] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part.startswith(".") for part in f.relative_to(p).parts):
                    out.append((f"{p.name}/{f.relative_to(p).as_posix()}", f))
        elif p.is_file():
            out.append((p.name, p))
        else:
            raise CliError(f"No such file or directory: {raw}", EXIT_NOT_FOUND)
    return out


def _multipart(fields: dict[str, str], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for k, v in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, path in files:
        safe = name.replace('"', "_")
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{safe}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def cmd_data_upload(args):
    """Upload files / folders / zip-tar archives into an input label."""
    items = _expand(list(args.paths))
    if not items:
        raise CliError("Nothing to upload", EXIT_VALIDATION)
    fal = getattr(args, "folders_as_labels", None)
    base, _ = _api()
    if base:
        fields = {"label": args.label}
        if fal is not None:
            fields["folders_as_labels"] = "true" if fal else "false"
        body, ctype = _multipart(fields, items)
        summary = _remote_json("POST", "/data/inputs/upload", body=body, ctype=ctype)
    else:
        from app.core.config import datasets_input_dir
        from app.core.mlops.dataset_inputs import UploadError, UploadSession, audit_file_meta

        root = datasets_input_dir()
        root.mkdir(parents=True, exist_ok=True)
        try:
            session = UploadSession(input_root=root, target_label=args.label, folders_as_labels=fal)
            handles = [(name, open(path, "rb")) for name, path in items]
            try:
                session.add_files(handles)
            finally:
                for _, fh in handles:
                    fh.close()
        except UploadError as exc:
            try:
                session.rollback()
            except UnboundLocalError:
                pass
            raise CliError(exc.message, EXIT_VALIDATION) from exc
        summary = session.summary()
        _audit(
            "dataset.upload",
            "dataset_input",
            ",".join(summary["labels"]) or args.label,
            {"label": args.label, "labels": summary["labels"], "count": summary["count"],
             "total_bytes": summary["total_bytes"], "content_hash": summary["content_hash"],
             **audit_file_meta(summary["files"])},
        )
    skipped = summary.get("skipped") or []
    text = (
        f"Stored {summary.get('count', 0)} file(s), {summary.get('total_bytes', 0)} bytes in "
        f"{', '.join(summary.get('labels') or []) or args.label} (content hash {summary.get('content_hash')})"
        + (f"\nSkipped {len(skipped)}: " + "; ".join(f"{s['name']}: {s['reason']}" for s in skipped[:10]) if skipped else "")
    )
    _print(args, summary, text)


# ── snapshot ─────────────────────────────────────────────────────────────────


def cmd_data_snapshot(args):
    """Freeze an input label as datasets/output/_inputs/<label>/vN."""
    base, _ = _api()
    if base:
        snap = _remote_json("POST", f"/data/inputs/{urllib.parse.quote(args.label)}/snapshot")
    else:
        from app.core.config import datasets_input_dir, datasets_output_dir
        from app.core.mlops.dataset_inputs import is_valid_label, snapshot_input_label

        if not is_valid_label(args.label):
            raise CliError("Label name cannot be snapshotted (letters, digits, _ and - only)", EXIT_VALIDATION)
        snap = snapshot_input_label(args.label, input_root=datasets_input_dir(), output_root=datasets_output_dir())
        _audit("dataset.snapshot", "dataset_version", f"{snap['project']}/{snap['version']}",
               {"label": args.label, "file_count": snap["file_count"], "total_bytes": snap["total_bytes"],
                "content_hash": snap["content_hash"]})
    _print(args, snap, f"Frozen {args.label} as {snap['project']}/{snap['version']} ({snap['file_count']} files, content hash {snap['content_hash']})")


# ── download ─────────────────────────────────────────────────────────────────


def cmd_data_download(args):
    """Zip an input label (``<label>``) or output version (``<project>/<version>``)."""
    target = args.target.strip().strip("/")
    is_output = "/" in target
    if is_output:
        project, version = target.rsplit("/", 1)
        out_name = f"{project.replace('/', '_')}_{version}.zip"
    else:
        project = version = None
        out_name = f"{target}.zip"
    out = Path(args.output or out_name)
    base, _ = _api()
    if base:
        quoted = "/".join(urllib.parse.quote(p) for p in target.split("/"))
        path = f"/data/outputs/{quoted}/zip" if is_output else f"/data/inputs/{quoted}/zip"
        with _request("GET", path) as resp, open(out, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
    else:
        from app.core.config import datasets_input_dir, datasets_output_dir
        from app.core.mlops.dataset_inputs import iter_files, iter_zip_stream
        from app.core.mlops.dataset_versions import VERSION_RE, read_manifest

        if is_output:
            if not VERSION_RE.match(version or ""):
                raise CliError(f"Invalid version {version!r}", EXIT_VALIDATION)
            src = datasets_output_dir().joinpath(*project.split("/"), version)
            if not src.is_dir() or ".." in project.split("/"):
                raise CliError(f"Dataset {target} not found", EXIT_NOT_FOUND)
            read_manifest(src, ensure=True, enforce_sha256=True)
            prefix = out_name[:-4] + "/"
            gen = iter_zip_stream(iter_files(src, jail=datasets_output_dir()), prefix=prefix)
        else:
            src = datasets_input_dir() / target
            if not src.is_dir() or "/" in target or target.startswith("."):
                raise CliError(f"Input label '{target}' not found", EXIT_NOT_FOUND)
            gen = iter_zip_stream(iter_files(src, jail=datasets_input_dir()), prefix=f"{target}/",
                                  manifest_name="manifest.json",
                                  manifest_extra={"source": {"kind": "input_label", "label": target}})
        with open(out, "wb") as fh:
            for chunk in gen:
                fh.write(chunk)
        _audit("dataset.download", "dataset_version" if is_output else "dataset_input", target, {"format": "zip", "to": str(out)})
    _print(args, {"target": target, "path": str(out), "bytes": out.stat().st_size}, f"Wrote {out} ({out.stat().st_size} bytes)")
    sys.stdout.flush()
