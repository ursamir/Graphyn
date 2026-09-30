#!/usr/bin/env python3
"""Materialize + validate + smoke-execute marketplace template family samples.

Runs against a live Graphyn API (default http://127.0.0.1:8001). Uses
marketplace materialize so OOB seed binding / fixed_length / epochs apply.
Sets trainer epochs=1 via materializer; aborts runs that exceed timeout.

Usage:
  export GRAPHYN_API_TOKEN=…
  venv/bin/python scripts/smoke_marketplace_templates.py
  venv/bin/python scripts/smoke_marketplace_templates.py --ids tpl-audio-sed-callcenter
  venv/bin/python scripts/smoke_marketplace_templates.py --families audio,rag --limit 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = os.environ.get("GRAPHYN_API", "http://127.0.0.1:8001").rstrip("/")
PROJECT = os.environ.get("GRAPHYN_SMOKE_PROJECT", "tpl-smoke")

# One representative per major family + the SED template that failed in UI.
DEFAULT_IDS = [
    "tpl-audio-sed-callcenter",
    "tpl-audio-kws-smart-home",
    "tpl-vision-yolo-detect-train-retail-shelf",
    "tpl-rag-ingest-fs-recursive-faiss-support",
    "tpl-tinyml-kws-wearable-cortex-m4-ptq-tflm",
    "tpl-wakeword-en-hey-graphyn-data-gen",
    "tpl-video-ingest-scene-caption-security",
    "tpl-agents-run-pipeline-mlops",
    "tpl-mlops-train-eval-ship-audio",
    "tpl-common-http-poll-transform-general",
]


def _load_token() -> str:
    tok = (os.environ.get("GRAPHYN_API_TOKEN") or "").strip()
    if tok:
        return tok
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GRAPHYN_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("GRAPHYN_API_TOKEN not set")


def api(method: str, path: str, body=None, timeout: int = 120, token: str = ""):
    base = DEFAULT_API
    if not path.startswith("/api/"):
        path = "/api/v1" + path
    url = f"{base}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Actor": "tpl-smoke",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, None
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as exc:
        return 0, {"error": str(exc)}


def ensure_project(token: str) -> None:
    code, body = api("GET", f"/projects/{PROJECT}", token=token)
    if code == 200:
        return
    code, body = api("POST", "/projects", {"name": PROJECT}, token=token)
    if code not in (200, 201, 400, 409, 422):
        raise SystemExit(f"project create failed: {code} {body}")


def materialize(token: str, template_id: str) -> dict:
    code, body = api(
        "POST",
        "/pipelines/marketplace/materialize",
        {"template_id": template_id},
        token=token,
        timeout=180,
    )
    if code not in (200, 201) or not isinstance(body, dict):
        raise RuntimeError(f"materialize HTTP {code}: {body}")
    graph = body.get("graph") or body
    if not isinstance(graph, dict) or "nodes" not in graph:
        raise RuntimeError(f"materialize missing graph: {body}")
    return graph


def _stamp_project(graph: dict) -> dict:
    meta = graph.setdefault("metadata", {})
    if isinstance(meta, dict):
        meta["project"] = PROJECT
        meta["name"] = meta.get("name") or f"smoke-{int(time.time())}"
    graph["project"] = PROJECT
    graph["version_tag"] = graph.get("version_tag") or "v1"
    # Discourage cache hits so OOB fixes are exercised
    for node in graph.get("nodes") or []:
        cfg = node.setdefault("config", {})
        if isinstance(cfg, dict) and "use_cache" in cfg:
            cfg["use_cache"] = False
    return graph


def validate(token: str, graph: dict) -> list:
    payload = _stamp_project(graph)
    code, body = api(
        "POST",
        "/pipelines/validate",
        payload,
        token=token,
        timeout=120,
    )
    if code not in (200, 201):
        return [f"validate HTTP {code}: {body}"]
    if isinstance(body, dict):
        if body.get("valid") is True:
            return []
        errs = body.get("errors") or body.get("issues") or []
        if not errs:
            return [str(body)[:400]]
        return [e if isinstance(e, str) else json.dumps(e) for e in errs]
    return []


def execute_and_wait(token: str, graph: dict, timeout_s: int) -> dict:
    payload = _stamp_project(graph)
    code, body = api(
        "POST",
        "/pipelines/run-async",
        payload,
        token=token,
        timeout=60,
    )
    if code not in (200, 201) or not isinstance(body, dict) or not body.get("run_id"):
        return {"ok": False, "phase": "execute", "http": code, "body": body, "error": str(body)[:400]}

    run_id = body["run_id"]
    deadline = time.time() + timeout_s
    last = body
    while time.time() < deadline:
        code, last = api("GET", f"/runs/{run_id}/status", token=token, timeout=60)
        if code != 200:
            code, last = api("GET", f"/runs/{run_id}", token=token, timeout=60)
        if not isinstance(last, dict):
            time.sleep(2)
            continue
        status = str(last.get("status") or (last.get("meta") or {}).get("status") or "").lower()
        if status in ("completed", "succeeded", "success", "ok"):
            return {"ok": True, "phase": "poll", "status": status, "run_id": run_id}
        if status in ("failed", "error", "cancelled", "canceled"):
            err = last.get("error") or last.get("message") or last.get("failure_reason")
            if not err and isinstance(last.get("meta"), dict):
                err = last["meta"].get("error")
            if not err:
                nodes = last.get("nodes") or last.get("node_status") or {}
                if isinstance(nodes, dict):
                    for nid, st in nodes.items():
                        if isinstance(st, dict) and st.get("error"):
                            err = f"{nid}: {st.get('error')}"
                            break
            return {
                "ok": False,
                "phase": "poll",
                "status": status,
                "run_id": run_id,
                "error": err,
                "body": last,
            }
        time.sleep(2)
    return {
        "ok": False,
        "phase": "timeout",
        "run_id": run_id,
        "error": f"timed out after {timeout_s}s",
        "body": last,
    }


def _load_catalog_templates() -> list[dict]:
    for cat in (
        ROOT / "docs" / "PIPELINE_TEMPLATE_CATALOG.json",
        ROOT / "docs" / "_gen" / "marketplace-catalog.json",
        ROOT / "graphyn-ui" / "public" / "marketplace-catalog.json",
    ):
        if cat.is_file():
            data = json.loads(cat.read_text(encoding="utf-8"))
            templates = data.get("templates") or []
            if templates:
                return templates
    return []


def pick_ids(args) -> list[str]:
    if args.ids:
        return [x.strip() for x in args.ids.split(",") if x.strip()]
    templates = _load_catalog_templates()
    if args.all:
        ids = [t["id"] for t in templates if t.get("id")]
        if args.offset:
            ids = ids[args.offset :]
        if args.max > 0:
            ids = ids[: args.max]
        return ids
    if args.families:
        fams = {f.strip().lower() for f in args.families.split(",") if f.strip()}
        by_fam: dict[str, list[str]] = {}
        for t in templates:
            fam = str(t.get("family") or "").lower()
            if fam in fams:
                by_fam.setdefault(fam, []).append(t["id"])
        picked = []
        for fam in sorted(by_fam):
            picked.extend(by_fam[fam][: args.limit])
        return picked
    if args.per_family > 0 and templates:
        by_fam: dict[str, list[str]] = {}
        for t in templates:
            fam = str(t.get("family") or t.get("pack") or "unknown").lower()
            by_fam.setdefault(fam, []).append(t["id"])
        picked = []
        for fam in sorted(by_fam):
            picked.extend(by_fam[fam][: args.per_family])
        return picked
    return list(DEFAULT_IDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="comma-separated template ids")
    ap.add_argument("--families", default="", help="comma-separated families; sample --limit each")
    ap.add_argument("--all", action="store_true", help="every catalog template id")
    ap.add_argument("--per-family", type=int, default=0, help="N templates from every family/pack")
    ap.add_argument("--limit", type=int, default=2, help="per-family sample size with --families")
    ap.add_argument("--max", type=int, default=0, help="cap total ids (0 = no cap)")
    ap.add_argument("--offset", type=int, default=0, help="skip first N ids (with --all)")
    ap.add_argument("--timeout", type=int, default=300, help="per-run seconds")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--skip-execute", action="store_true")
    ap.add_argument("--resume", action="store_true", help="skip ids already succeeded in the ledger")
    ap.add_argument("--ledger", default="", help="jsonl ledger path")
    args = ap.parse_args()

    token = _load_token()
    ensure_project(token)
    ids = pick_ids(args)
    ledger_path = Path(args.ledger) if args.ledger else (ROOT / "workspace" / "reports" / "tpl_execute_ledger.jsonl")
    done: set[str] = set()
    if args.resume and ledger_path.is_file():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ok") and rec.get("id"):
                done.add(rec["id"])
        ids = [i for i in ids if i not in done]
    print(f"api={DEFAULT_API} project={PROJECT} templates={len(ids)} skipped_ok={len(done)}", flush=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_fh = ledger_path.open("a", encoding="utf-8")

    results = []
    ok_n = len(done)
    fail_n = 0
    for i, tid in enumerate(ids, start=1):
        row = {"id": tid, "ok": False}
        t0 = time.time()
        try:
            graph = materialize(token, tid)
            row["nodes"] = len(graph.get("nodes") or [])
            for n in graph.get("nodes") or []:
                if n.get("node_type") == "dataset_builder":
                    row["fixed_length"] = (n.get("config") or {}).get("fixed_length")
                if n.get("node_type") == "dataset_ingest":
                    row["ingest_path"] = (n.get("config") or {}).get("path")
            verrs = validate(token, graph)
            if verrs:
                row["phase"] = "validate"
                row["error"] = verrs[:3]
                fail_n += 1
                print(f"FAIL validate {i}/{len(ids)} {tid}", flush=True)
            elif args.validate_only or args.skip_execute:
                row["ok"] = True
                row["phase"] = "validate"
                ok_n += 1
                print(f"OK   validate {i}/{len(ids)} {tid}", flush=True)
            else:
                timeout = args.timeout
                types = {n.get("node_type") for n in graph.get("nodes") or []}
                if types & {"mcu_train", "tflm_quantize", "yolo_train", "trainer"}:
                    timeout = max(timeout, 600)
                ex = execute_and_wait(token, graph, timeout)
                row.update({k: v for k, v in ex.items() if k != "body"})
                row["secs"] = round(time.time() - t0, 1)
                if ex.get("ok"):
                    ok_n += 1
                    print(f"OK   run {i}/{len(ids)} {tid} {row['secs']}s", flush=True)
                else:
                    fail_n += 1
                    err = ex.get("error")
                    node = None
                    body = ex.get("body") if isinstance(ex.get("body"), dict) else {}
                    node = body.get("current_node")
                    row["failed_node"] = node
                    if isinstance(err, str) and len(err) > 300:
                        row["error"] = err[:300]
                    print(f"FAIL run {i}/{len(ids)} {tid} node={node}", flush=True)
        except Exception as exc:
            row["phase"] = "exception"
            row["error"] = str(exc)[:400]
            row["secs"] = round(time.time() - t0, 1)
            fail_n += 1
            print(f"FAIL exception {i}/{len(ids)} {tid}: {exc}", flush=True)
        results.append(row)
        ledger_fh.write(json.dumps({k: v for k, v in row.items() if k != "body"}) + "\n")
        ledger_fh.flush()
        if i % 25 == 0:
            print(f"progress ok={ok_n} fail={fail_n} seen={i+len(done)}", flush=True)

    ledger_fh.close()
    out = ROOT / "workspace" / "reports" / "marketplace_smoke_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total_this_pass": len(results),
        "skipped_previously_ok": len(done),
        "ok_including_skipped": ok_n,
        "fail_this_pass": fail_n,
        "results": results,
    }
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "results"}, indent=2), flush=True)
    print(f"wrote {out}", flush=True)
    print(f"ledger {ledger_path}", flush=True)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
