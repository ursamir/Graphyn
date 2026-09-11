#!/usr/bin/env python3
"""Run Graphyn template matrix via local API (port 8001)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

ROOT = Path("/workspace/Graphyn")
API = os.environ.get("GRAPHYN_API", "http://127.0.0.1:8001")
TOKEN = Path("/workspace/graphyn-api-token.txt").read_text().strip()
TEMPLATES_DIR = ROOT / "examples" / "templates"
OUT = ROOT / "docs" / "_e2e_audio_matrix.json"

# Prefer local/preprocess first
PRIORITY = [
    "audio-classification",
    "basic-wakeword",
    "audio-quality-check",
    "podcast-leveling",
    "speech-recognition",
    "edge-deploy",
    "doc-rag-ingest",
]

# Templates that need paid cloud keys
KEY_TEMPLATES = {
    # Historical key gates — free path now available via local_whisper / local_heuristic.
    # Kept empty so the legacy runner no longer auto-skips; prefer e2e_all_templates_runner.py.
}

# Small epoch overrides where ML train appears
EPOCH_OVERRIDES = {
    "epochs": 1,
    "num_epochs": 1,
    "max_epochs": 1,
    "n_epochs": 1,
    "batch_size": 4,
    "max_steps": 5,
}


def api(method: str, path: str, body=None, timeout=120):
    url = f"{API}{path}"
    data = None
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
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


def ensure_project(name: str):
    code, body = api("GET", f"/api/v1/projects/{name}")
    if code == 200:
        return True, "exists"
    code, body = api("POST", "/api/v1/projects", {"name": name})
    if code in (200, 201):
        return True, "created"
    # already exists (some servers 400/409/422)
    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body)
    else:
        detail = str(body)
    if code in (400, 409, 422) and "already exists" in detail.lower():
        return True, "exists"
    return False, body


def load_template(name: str) -> dict:
    path = TEMPLATES_DIR / f"{name}.graph.json"
    if not path.is_file():
        # try API
        code, body = api("GET", f"/api/v1/pipelines/templates/{name}")
        if code != 200:
            raise FileNotFoundError(name)
        if isinstance(body, dict) and "nodes" in body:
            return body
        if isinstance(body, dict) and "graph" in body:
            return body["graph"]
        raise FileNotFoundError(f"unexpected template payload for {name}")
    return json.loads(path.read_text())


def stamp(graph: dict, project: str) -> dict:
    g = deepcopy(graph)
    meta = g.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        g["metadata"] = meta
    meta["project"] = project
    meta.setdefault("version_tag", "v1")
    # Always stamp Library project onto exporters / dataset sinks
    for node in g.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        cfg = node.get("config")
        if not isinstance(cfg, dict):
            continue
        ntype = str(node.get("type") or node.get("node_type") or "")
        if "project" in cfg:
            cfg["project"] = project
        if "output_dir" in cfg:
            od = str(cfg.get("output_dir") or "").replace("\\", "/")
            if "/datasets/output/" in od:
                cfg["output_dir"] = f"workspace/datasets/output/{project}"
        if ntype in {"audio_exporter", "export", "dataset_versioner"}:
            cfg["project"] = project
            od = str(cfg.get("output_dir") or "").replace("\\", "/")
            # Keep artifact-sink exports under artifacts/; rewrite Library dataset sinks.
            if "/datasets/output/" in od or not od:
                cfg["output_dir"] = f"workspace/datasets/output/{project}"
        # small epoch overrides for train nodes
        ntype = node.get("type") or node.get("node_type") or ""
        if any(k in str(ntype).lower() for k in ("train", "classifier", "model")):
            for k, v in EPOCH_OVERRIDES.items():
                if k in cfg and isinstance(cfg[k], (int, float)):
                    cfg[k] = v
        for k, v in EPOCH_OVERRIDES.items():
            if k in cfg and isinstance(cfg[k], (int, float)) and cfg[k] > v:
                if "epoch" in k or k == "max_steps":
                    cfg[k] = v
    return g



def skip_reason(name: str, graph: dict) -> str | None:
    """Return skip reason for keys OR missing local model deps."""
    k = needs_keys(name, graph)
    if k:
        return f"missing paid API keys: {k}"
    if name == "edge-deploy":
        from pathlib import Path as P
        model = P("/workspace/Graphyn/workspace/artifacts/models/saved_model")
        if not model.exists():
            return "SKIPPED_MODEL: no workspace/artifacts/models/saved_model (train first); tensorflow/onnx not installed in API venv"
    return None

def needs_keys(name: str, graph: dict) -> str | None:
    """Paid-key gate. Free local_whisper / local_heuristic graphs are never skipped."""
    blob = json.dumps(graph).lower()
    if "local_whisper" in blob or "faster_whisper" in blob or "local_heuristic" in blob:
        return None
    if name in KEY_TEMPLATES:
        return KEY_TEMPLATES[name]
    reasons = []
    if "deepgram" in blob and not os.environ.get("DEEPGRAM_API_KEY"):
        reasons.append("Deepgram")
    if ("openai_compat" in blob) and not (
        os.environ.get("OPENAI_API_KEY") or os.environ.get("GRAPHYN_OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    ):
        if any(x in name for x in ("call", "caption", "meeting", "crm", "triage", "compliance")):
            reasons.append("OpenAI")
    if reasons:
        return "+".join(reasons)
    return None


def poll_run(run_id: str, timeout_s: float = 600.0):
    start = time.time()
    last = None
    while time.time() - start < timeout_s:
        code, body = api("GET", f"/api/v1/runs/{run_id}/status")
        if code != 200:
            code, body = api("GET", f"/api/v1/runs/{run_id}")
        last = body
        status = None
        if isinstance(body, dict):
            status = body.get("status") or (body.get("meta") or {}).get("status")
        if status in ("completed", "failed", "error", "cancelled", "canceled"):
            return status, body
        time.sleep(1.5)
    return "timeout", last


def artifacts(run_id: str):
    code, body = api("GET", f"/api/v1/runs/{run_id}/artifacts")
    if code != 200:
        return []
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("artifacts") or body.get("items") or body
    return []


def run_one(name: str) -> dict:
    project = f"e2e-{name}"[:120]
    row = {"template": name, "project": project, "status": "PENDING", "run_id": None, "notes": ""}
    try:
        graph = load_template(name)
    except Exception as e:
        row["status"] = "ERROR_LOAD"
        row["notes"] = str(e)
        return row

    reason = skip_reason(name, graph)
    if reason:
        row["status"] = "SKIPPED_KEYS" if "API keys" in reason else "SKIPPED_MODEL"
        row["notes"] = reason
        return row

    ok, info = ensure_project(project)
    if not ok:
        row["status"] = "ERROR_PROJECT"
        row["notes"] = str(info)
        return row

    payload = stamp(graph, project)
    # also top-level project for stamp helper
    payload["project"] = project
    payload["version_tag"] = "v1"

    code, vbody = api("POST", "/api/v1/pipelines/validate", payload)
    if not (code == 200 and isinstance(vbody, dict) and vbody.get("valid")):
        row["status"] = "INVALID"
        row["notes"] = str(vbody)[:500]
        return row

    code, rbody = api("POST", "/api/v1/pipelines/run-async", payload)
    if code not in (200, 201) or not isinstance(rbody, dict) or not rbody.get("run_id"):
        row["status"] = "ERROR_START"
        row["notes"] = str(rbody)[:500]
        return row

    run_id = rbody["run_id"]
    row["run_id"] = run_id
    # Longer timeout for train-ish; shorter for preprocess
    timeout = 900 if any(x in name for x in ("e2e", "train", "edge", "speech-commands")) else 420
    status, sbody = poll_run(run_id, timeout_s=timeout)
    row["status"] = status.upper() if isinstance(status, str) else str(status)
    arts = artifacts(run_id)
    row["artifact_count"] = len(arts) if isinstance(arts, list) else 0
    err = None
    if isinstance(sbody, dict):
        err = sbody.get("error") or sbody.get("message")
        if not err and isinstance(sbody.get("meta"), dict):
            err = sbody["meta"].get("error")
    if err:
        row["notes"] = str(err)[:600]
    elif row["artifact_count"]:
        row["notes"] = f"artifacts={row['artifact_count']}"
    else:
        # check outputs
        code, outs = api("GET", f"/api/v1/runs/{run_id}/outputs")
        row["notes"] = f"outputs={str(outs)[:300]}"
    return row


def main():
    files = sorted(p.stem.replace(".graph", "") for p in TEMPLATES_DIR.glob("*.graph.json"))
    # de-dup stem
    names = []
    for f in files:
        n = f[:-6] if f.endswith(".graph") else f
        if n not in names:
            names.append(n)
    # order: priority first, then rest
    ordered = [n for n in PRIORITY if n in names] + [n for n in names if n not in PRIORITY]
    print("TEMPLATES", ordered)
    results = []
    for name in ordered:
        print(f"\n=== RUN {name} ===", flush=True)
        row = run_one(name)
        results.append(row)
        print(json.dumps(row, indent=2), flush=True)
        OUT.write_text(json.dumps(results, indent=2))
    print("\n==== MATRIX ====")
    for r in results:
        print(f"{r['template']:28} {r['status']:14} {r.get('run_id') or '-'}  {r.get('notes','')[:120]}")
    OUT.write_text(json.dumps(results, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
