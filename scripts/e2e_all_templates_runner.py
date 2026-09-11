#!/usr/bin/env python3
"""Run ALL Graphyn template graphs + classify example folders via local API :8001.

Free-provider path: local_whisper ASR + local_heuristic LLM (no paid keys).
Webhooks stamped to https://httpbin.org/post. External GitHub/Slack → SKIPPED_EXTERNAL.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

ROOT = Path("/workspace/Graphyn")
API = os.environ.get("GRAPHYN_API", "http://127.0.0.1:8001")
TOKEN = Path("/workspace/graphyn-api-token.txt").read_text().strip()
EX_TEMPLATES = ROOT / "examples" / "templates"
WS_TEMPLATES = ROOT / "workspace" / "configs" / "templates"
EXAMPLES = ROOT / "examples"
OUT = ROOT / "docs" / "_e2e_template_matrix.json"
WEBHOOK = "https://httpbin.org/post"

# Named UI templates (examples/templates + workspace copies)
UI_TEMPLATES = [
    "audio-classification",
    "basic-wakeword",
    "audio-quality-check",
    "podcast-leveling",
    "speech-recognition",
    "doc-rag-ingest",
    "edge-deploy",
    "call-analytics",
    "captions",
    "meeting-crm",
]

EPOCH_OVERRIDES = {
    "epochs": 1,
    "num_epochs": 1,
    "max_epochs": 1,
    "n_epochs": 1,
    "batch_size": 4,
    "max_steps": 5,
}

EXTERNAL_HOST_RE = re.compile(
    r"https?://(api\.github\.com|slack\.com|hooks\.slack\.com)",
    re.I,
)


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
    detail = str(body.get("detail") if isinstance(body, dict) else body)
    if code in (400, 409, 422) and "already exists" in detail.lower():
        return True, "exists"
    return False, body


def load_template(name: str) -> tuple[dict, Path]:
    for base in (EX_TEMPLATES, WS_TEMPLATES):
        path = base / f"{name}.graph.json"
        if path.is_file():
            return json.loads(path.read_text()), path
    code, body = api("GET", f"/api/v1/pipelines/templates/{name}")
    if code == 200 and isinstance(body, dict):
        g = body.get("graph") if "graph" in body else body
        return g, Path(f"<api:{name}>")
    raise FileNotFoundError(name)


def stamp_free_providers(graph: dict, project: str) -> dict:
    """Stamp project + force free ASR/LLM + httpbin webhooks at run time."""
    g = deepcopy(graph)
    meta = g.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        g["metadata"] = meta
    meta["project"] = project
    meta.setdefault("version_tag", "v1")

    for node in g.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        cfg = node.get("config")
        if not isinstance(cfg, dict):
            cfg = {}
            node["config"] = cfg
        ntype = str(node.get("type") or node.get("node_type") or "")

        if ntype == "asr_transcribe":
            prov = str(cfg.get("provider") or "").lower()
            if prov in ("deepgram", "assemblyai", "openai_compat", ""):
                cfg["provider"] = "local_whisper"
                cfg["model"] = cfg.get("model") or "tiny"
                cfg.setdefault("language", "en")
            elif prov in ("local_whisper", "faster_whisper"):
                cfg["model"] = cfg.get("model") or "tiny"

        if ntype == "structured_llm":
            prov = str(cfg.get("provider") or "").lower()
            # Prefer Groq if key present and user left openai_compat
            groq = os.environ.get("GROQ_API_KEY", "").strip()
            openai = os.environ.get("OPENAI_API_KEY", "").strip()
            if prov in ("openai_compat", "") and not openai:
                if groq:
                    cfg["provider"] = "openai_compat"
                    cfg["base_url"] = cfg.get("base_url") or "https://api.groq.com/openai/v1"
                    if not cfg.get("model") or str(cfg.get("model")).startswith("gpt-"):
                        cfg["model"] = "llama-3.1-8b-instant"
                else:
                    cfg["provider"] = "local_heuristic"

        if ntype == "http_webhook":
            url = str(cfg.get("url") or "")
            if (not url) or ("example.com" in url) or url.startswith("https://example"):
                cfg["url"] = WEBHOOK
            cfg["timeout_s"] = min(float(cfg.get("timeout_s") or 10.0), 10.0)

        # Stamp project/output_dir carefully (avoid pydantic extra_forbidden /
        # avoid rewriting custom artifact sinks via dataset_versioner.project).
        if "project" in cfg:
            cfg["project"] = project
        if "output_dir" in cfg:
            od = str(cfg.get("output_dir") or "").replace("\\", "/")
            if "/datasets/output/" in od:
                cfg["output_dir"] = f"workspace/datasets/output/{project}"
        if ntype in {"audio_exporter", "export"}:
            cfg["project"] = project
            od = str(cfg.get("output_dir") or "").replace("\\", "/")
            if "/datasets/output/" in od or not od:
                cfg["output_dir"] = f"workspace/datasets/output/{project}"
        if ntype == "dataset_versioner":
            od = str(cfg.get("output_dir") or "").replace("\\", "/")
            if "/datasets/output/" in od or not od:
                cfg["project"] = project
                cfg["output_dir"] = f"workspace/datasets/output/{project}"
            # else keep custom artifacts/* output_dir without injecting project
        if ntype in {"model_builder", "trainer", "evaluator", "edge_optimizer"}:
            if not cfg.get("output_path"):
                cfg["output_path"] = f"workspace/artifacts/{project}/{ntype}"

        if any(k in ntype.lower() for k in ("train", "classifier", "model")):
            for k, v in EPOCH_OVERRIDES.items():
                if k in cfg and isinstance(cfg[k], (int, float)):
                    cfg[k] = v
        for k, v in EPOCH_OVERRIDES.items():
            if k in cfg and isinstance(cfg[k], (int, float)) and cfg[k] > v:
                if "epoch" in k or k == "max_steps":
                    cfg[k] = v
    # Drop explicit nulls so pydantic Field defaults apply (executor may pad schema keys with null).
    for node in g.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        cfg = node.get("config")
        if isinstance(cfg, dict):
            node["config"] = {k: v for k, v in cfg.items() if v is not None}
    return g


def has_external_deps(graph: dict) -> str | None:
    blob = json.dumps(graph)
    if EXTERNAL_HOST_RE.search(blob):
        hosts = sorted(set(EXTERNAL_HOST_RE.findall(blob)))
        return "external HTTP to " + ",".join(hosts) + " (GitHub/Slack) — needs tokens"
    return None


def skip_preflight(name: str, graph: dict) -> tuple[str, str] | None:
    if name == "edge-deploy" or name.endswith("edge-deploy"):
        model = ROOT / "workspace/artifacts/models/saved_model"
        if not model.exists():
            return "SKIPPED_MODEL", "no workspace/artifacts/models/saved_model (train first)"
    ext = has_external_deps(graph)
    # For graphs that are ONLY external (github triage), skip whole run.
    # For nightly-compliance which mixes ASR + slack, still skip if slack required mid-graph.
    if ext and any(x in name for x in ("github", "triage", "compliance", "nightly")):
        return "SKIPPED_EXTERNAL", ext
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
        return body.get("artifacts") or body.get("items") or []
    return []


def run_graph(name: str, source: str = "template") -> dict:
    project = f"e2e-{name}"[:120]
    row = {
        "template": name,
        "source": source,
        "project": project,
        "status": "PENDING",
        "run_id": None,
        "notes": "",
        "artifact_count": 0,
    }
    try:
        graph, path = load_template(name)
        row["path"] = str(path)
    except Exception as e:
        row["status"] = "ERROR_LOAD"
        row["notes"] = str(e)
        return row

    pre = skip_preflight(name, graph)
    if pre:
        row["status"], row["notes"] = pre
        return row

    ok, info = ensure_project(project)
    if not ok:
        row["status"] = "ERROR_PROJECT"
        row["notes"] = str(info)
        return row

    payload = stamp_free_providers(graph, project)
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
    timeout = 900 if any(x in name for x in ("e2e", "train", "edge", "speech-commands", "06")) else 480
    status, sbody = poll_run(run_id, timeout_s=timeout)
    row["status"] = status.upper() if isinstance(status, str) else str(status)
    arts = artifacts(run_id)
    row["artifact_count"] = len(arts) if isinstance(arts, list) else 0
    err = None
    if isinstance(sbody, dict):
        err = sbody.get("error") or sbody.get("message")
        if not err and isinstance(sbody.get("meta"), dict):
            err = sbody["meta"].get("error")
        # dig node errors
        if not err:
            nodes = sbody.get("nodes") or sbody.get("node_status") or {}
            if isinstance(nodes, dict):
                for nid, st in nodes.items():
                    if isinstance(st, dict) and st.get("error"):
                        err = f"{nid}: {st.get('error')}"
                        break
    if err:
        row["notes"] = str(err)[:600]
    elif row["artifact_count"]:
        row["notes"] = f"artifacts={row['artifact_count']}"
    else:
        code, outs = api("GET", f"/api/v1/runs/{run_id}/outputs")
        row["notes"] = f"outputs={str(outs)[:300]}"
    return row


def classify_example_folder(folder: Path) -> dict:
    name = folder.name
    row = {
        "example": name,
        "status": "N/A",
        "notes": "",
        "run_id": None,
        "kind": "unknown",
    }
    graphs = list(folder.glob("*.graph.json")) + list(folder.glob("pipeline*.graph.json"))
    readme = folder / "README.md"
    scripts = list(folder.glob("*.py"))
    if graphs:
        # Prefer live/pipeline graph; map to template run if ex-NN exists
        m = re.match(r"(\d+)_", name)
        if m:
            num = int(m.group(1))
            # find matching ex-NN template
            candidates = sorted(WS_TEMPLATES.glob(f"ex-{num:02d}-*.graph.json"))
            if candidates:
                tname = candidates[0].stem.replace(".graph", "")
                if tname.endswith(".graph"):
                    tname = tname[: -len(".graph")]
                # stem is like ex-01-wake-word.graph → Path.stem gives ex-01-wake-word.graph? 
                # Path('ex-01-wake-word.graph.json').stem = 'ex-01-wake-word.graph'
                tname = candidates[0].name.replace(".graph.json", "")
                row["kind"] = "api_template"
                row["template"] = tname
                result = run_graph(tname, source=f"example:{name}")
                row["status"] = result["status"]
                row["run_id"] = result.get("run_id")
                row["notes"] = result.get("notes", "")
                row["artifact_count"] = result.get("artifact_count", 0)
                return row
        row["kind"] = "local_graph"
        row["notes"] = f"has graph(s) {[g.name for g in graphs[:3]]}; no matching ex-NN workspace template — covered via named UI template if any"
        row["status"] = "COVERED_VIA_TEMPLATE" if any(
            k in name for k in (
                "call_analytics", "meeting_crm", "captions", "doc_rag", "edge_deploy",
                "wake_word", "speech_commands", "environmental", "speaker", "speech_enhancement",
            )
        ) else "N/A_NO_EX_TEMPLATE"
        return row
    if scripts and readme.exists():
        row["kind"] = "script_readme"
        row["status"] = "N/A_SCRIPT"
        row["notes"] = f"scripts={[s.name for s in scripts[:4]]}; run via README if needed (not API template)"
        return row
    if readme.exists():
        row["kind"] = "docs_only"
        row["status"] = "N/A_DOCS"
        row["notes"] = "README only / no runnable graph in folder"
        return row
    row["status"] = "N/A_EMPTY"
    row["notes"] = "no graph/scripts found"
    return row


def list_all_template_names() -> list[str]:
    names: list[str] = []
    for base in (EX_TEMPLATES, WS_TEMPLATES):
        for p in sorted(base.glob("*.graph.json")):
            n = p.name.replace(".graph.json", "")
            if n not in names:
                names.append(n)
    # UI first
    ordered = [n for n in UI_TEMPLATES if n in names]
    ordered += [n for n in names if n not in ordered]
    return ordered


def main():
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    skip_examples = "--templates-only" in sys.argv or bool(only)
    names = only if only else list_all_template_names()
    print("TEMPLATES", names, flush=True)
    results = {"templates": [], "examples": [], "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}

    for name in names:
        print(f"\n=== RUN {name} ===", flush=True)
        row = run_graph(name)
        results["templates"].append(row)
        print(json.dumps(row, indent=2), flush=True)
        OUT.write_text(json.dumps(results, indent=2))

    # example folders (skip when running a targeted template list)
    if skip_examples:
        print("Skipping example folder matrix (targeted template run)", flush=True)
    for folder in ([] if skip_examples else sorted(EXAMPLES.iterdir())):
        if not folder.is_dir():
            continue
        if not re.match(r"^\d{2}_", folder.name):
            continue
        # Skip re-running if we already ran matching ex-NN in templates section
        m = re.match(r"(\d+)_", folder.name)
        ex_already = None
        if m:
            num = int(m.group(1))
            prefix = f"ex-{num:02d}-"
            for t in results["templates"]:
                if str(t.get("template", "")).startswith(prefix):
                    ex_already = t
                    break
        if ex_already is not None:
            results["examples"].append({
                "example": folder.name,
                "status": ex_already["status"],
                "run_id": ex_already.get("run_id"),
                "notes": f"via template {ex_already['template']}: {ex_already.get('notes','')}",
                "kind": "api_template_ref",
                "template": ex_already["template"],
            })
            print(f"EXAMPLE {folder.name} -> ref {ex_already['template']} {ex_already['status']}", flush=True)
            continue
        print(f"\n=== EXAMPLE {folder.name} ===", flush=True)
        row = classify_example_folder(folder)
        results["examples"].append(row)
        print(json.dumps(row, indent=2), flush=True)
        OUT.write_text(json.dumps(results, indent=2))

    print("\n==== TEMPLATE MATRIX ====")
    for r in results["templates"]:
        print(f"{r['template']:32} {r['status']:16} {r.get('run_id') or '-':36} {r.get('notes','')[:100]}")
    print("\n==== EXAMPLE MATRIX ====")
    for r in results["examples"]:
        print(f"{r['example']:32} {r['status']:16} {r.get('run_id') or '-':36} {r.get('notes','')[:100]}")
    OUT.write_text(json.dumps(results, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
