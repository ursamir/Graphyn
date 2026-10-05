# Getting Started

Graphyn runs typed DAG pipelines (Graph IR) from a console, SDK, CLI, REST API, or MCP.

**This guide owns:** install, first run, and how to operate Graphyn (single machine vs multi-machine).
Deep design: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md). Docker: [DEPLOYMENT.md](./DEPLOYMENT.md).

**Server-99 / Docker:** after `docker compose up`, prove the IDE loop with
`scripts/docker_ide_loop_smoke.sh` (see [DEPLOYMENT.md](./DEPLOYMENT.md#prove-the-ide-loop-server-99--docker)).
Local uvicorn alone does not close the goal env gap.

The API process binds `:8001` immediately (`GET /health` / `/api/v1/system/health`).
Plugin catalog load (and any remaining light venv bootstrap) runs in a background
thread — poll `/api/v1/system/readiness` until `registry_ready: true`. Empty
`docker logs` during a long first boot usually meant the old blocking import-time
install; current images print `graphyn: …` progress on stderr.

## Choose an operating mode

| Mode | When | Backend | Who runs nodes |
|---|---|---|---|
| **A — Single machine** | Dev laptop, one box, all plugins here | `LocalPythonBackend` (default) | This process runs every node |
| **B — Multi machine** | Split light work and GPU/specialized workers | `GRAPHYN_BACKEND=distributed` | Control plane schedules; workers claim by labels/capabilities |

In mode B you can run a **full-capability** worker (all plugins) or **specialized** workers (e.g. `--labels gpu` with only GPU plugins). IR `placement` on each node routes work.

---

## Prerequisites

- Python 3.11+
- Node.js 20+ (console only)
- Mode B: same Graphyn version + needed plugins on every worker host

## Install (once per machine)

```bash
git clone https://github.com/ursamir/Graphyn.git
cd Graphyn
python3 -m venv venv
venv/bin/pip install -U pip
# setup.py is the dependency source of truth; [dev] adds pytest/hypothesis
venv/bin/pip install -e ".[dev]"
# Optional extras: mcp | redis | events | vad | hf | tf | all
# Docker / locked pins: pip install -r requirements.txt && pip install -e . --no-deps
venv/bin/python -c "from pathlib import Path; from app.core.plugins.manager import PluginManager as M; m=M(); [m.install(str(p), upgrade=True) for d in ('Audio','Common') for p in Path('PluginPackage', d).iterdir() if (p / 'plugin.toml').exists()]"
```

Dependency model: see root README / AGENTS.md. Validate sync with `venv/bin/python scripts/check_deps.py`.

---

## Mode A — Single machine (full catalog locally)

Default local backend. Do not set GRAPHYN_BACKEND.


### Start API and console

Ensure `GRAPHYN_SKIP_PLUGIN_LOAD` is **unset** (if set to `1`, `/api/v1/nodes` returns `[]` and the Builder catalog is empty). Optional: `export GRAPHYN_HOME=$PWD/.graphyn-e2e` when using the e2e plugin tree, or rely on `~/.graphyn/plugins/installed/`.

- API: `venv/bin/uvicorn app.api.main:app --reload --port 8001`
- Console: `cd graphyn-ui && npm install && npm run dev`
  (or Docker UI-only rebuild — never recreate the API for frontend work: see [DEPLOYMENT.md](./DEPLOYMENT.md))
- API URL: `http://localhost:8001/api/v1/`
- UI URL: `http://localhost:5173`

### Seed local input data (first run)

Example graphs ingest from `workspace/datasets/input/…`, which is gitignored on a fresh clone. Run once:

```bash
venv/bin/python scripts/heal_e2e_local_data.py
```

If ingest fails with `FileNotFoundError`, re-run the heal script or point `dataset_ingest` / `stream_ingest` at a WAV under `examples/*/data/`.

### Getting data in

Input datasets are folders under `workspace/datasets/input/<label>/` (one label =
one folder; sub-folders are usually classes). Output datasets are immutable
versions under `workspace/datasets/output/<workspace>/vN/`, each with a
`manifest.json` (sha256 per file + `content_hash`).

- **Console → Datasets → Inputs → Manage… → Upload**: pick files, a whole folder,
  or `.zip` / `.tar(.gz)` archives; choose an existing label or type a new one.
  With *Subfolders are labels* on, `yes/a.wav` lands in label `yes`. Allowed types:
  audio, CSV/TSV, JSON/JSONL, TXT, MD, PDF, PNG/JPG, Parquet (default 100 MB per
  request — `GRAPHYN_UPLOAD_MAX_BYTES`; archives are unpacked with file / size caps).
- **Import tab**: URLs, or a HuggingFace dataset (split, audio / label column, max
  rows, revision). HuggingFace needs the `hf` extra on the API host
  (`venv/bin/pip install -e ".[hf]"`); the tab says so when it is missing.
- **Freeze as version** on an input label copies it to
  `datasets/output/_inputs/<label>/vN` — point a pipeline at that path and its run
  records the exact dataset version. Editing the label afterwards never changes it.
- **Download zip** works for an input label or any output version (includes
  `manifest.json`).
- Pipelines that export (`audio_exporter`) never overwrite an existing version:
  a taken `version_tag` goes to the next free one (v1 → v2) unless *Overwrite* is on,
  and versions referenced by runs or packages can never be overwritten or appended to.
- CLI (local, or remote with `--api-url`):

```bash
venv/bin/python -m app.cli.main data upload ./my_clips --label keywords --folders-as-labels
venv/bin/python -m app.cli.main data ls            # labels; `data ls keywords`, `data ls --outputs`
venv/bin/python -m app.cli.main data snapshot keywords
venv/bin/python -m app.cli.main data download _inputs/keywords/v1 -o keywords_v1.zip
```

Every upload, import, freeze, merge, delete and download shows up in
**Admin → Audit** under the **Data** category.

### Run a graph

- `venv/bin/python -m app.cli.main run --graph examples/templates/basic-wakeword.graph.json`

### SDK

Use `Pipeline` and `PipelineNode` from `app.core.sdk`; call pipeline.run(). See [SDK_AND_CLI.md](./SDK_AND_CLI.md) for full examples.

### MCP

- `venv/bin/python -m app.mcp.server`

Console groups (global shell): **Projects** · **Build** (Templates, Agent inbox) · **Library** (Datasets, Plugins, Models, Artifacts) · **Deploy** (Ship, Worker fleet) · **Admin** (Credentials, Ops, Access). With a workspace open: **Home · Editor · Runs · Models · Ship · Datasets** (Runs includes History, Live, outputs, lineage, compare).

**Data vs Projects:** Data is files in/out (`workspace/datasets/`). Projects is the dataset workspace over the same output folder (versions/snapshots/lineage). Loop: Upload in Data → Build/ingest in Builder → Runs/Artifacts → manage in Projects → compare in Experiments / package in Edge.

---

## Mode B — Multi machine (control plane + workers)

Use when some nodes need another host (GPU, edge, specialized plugins).

### B1 — Control plane

- Set env GRAPHYN_BACKEND=distributed (optional GRAPHYN_API_TOKEN)
- Start API with host 0.0.0.0 port 8001 (control plane)
- Local / unconstrained nodes run on the control plane; GPU-tagged nodes wait for a worker

### B2 — Worker hosts

Install Graphyn plus plugins that worker should own, then start a worker against the control URL (/api/v1) with worker-id, labels, and optional pool.

Example:

- `venv/bin/python -m app.cli.main worker start --control-url http://<CONTROL_IP>:8001/api/v1 --worker-id gpu-1 --labels gpu,lab --pool gpu-lab`

| Worker style | How |
|---|---|
| **Full-capability** | Install all bundled packs (`PluginPackage/*/*/plugin.toml`); broad labels; can claim most node types |
| **Specialized** | Install only needed plugins; labels like gpu and pool like gpu-lab; only matching jobs claimed |

Check Deploy → Workers in the console. Demo: examples/29_distributed_placement/pipeline.graph.json with GRAPHYN_BACKEND=distributed.

IR placement (schema 1.2): mode auto|local|worker|pool, plus tags, require_gpu, min_vram_mib, pool, worker. Full contracts: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md).

### Same-host smoke

Run distributed API locally, then start a worker with control-url http://127.0.0.1:8001/api/v1, worker-id local-gpu, labels gpu, and --once.

Exact flags and env table: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) (CLI + runbook sections).

---

## Using a Ship package

**Ship** (workspace → Ship) turns a trained model into a package: pick the training run → Configure (backend, quantization, target) → Package run → **Download**. Step 4 lists the package contents with sha256, a copyable *How to run* snippet and the packager's self-test result; the same summary appears on the package run's Overview in Runs.

An **edge** package (`<name>_edge.tar.gz`) runs on real audio without Graphyn:

```bash
sha256sum <name>_edge.tar.gz          # compare with the checksum shown in Ship
mkdir model && tar -xzf <name>_edge.tar.gz -C model && cd model
sha256sum -c SHA256SUMS               # every file matches provenance.json
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt       # numpy, librosa (training version), soundfile, TFLite runtime
python run_inference.py clip.wav      # → "clip.wav: yes (0.97)  [no 0.02, up 0.01]"
python run_inference.py a.wav b.wav --top-k 6 --json
```

* Input: any WAV/FLAC/OGG; it is mixed to mono and resampled to the training rate (16 kHz for Example 06). The model sees `frames.fixed_length` frames (101 ≈ 1 s); shorter clips are zero-padded, longer ones cut — trim recordings to the spoken word.
* `preprocessing.json` holds the exact Feature Frontend + Dataset Builder settings of the training run (MFCC/log-mel parameters, normalisation, frame count), the model's input tensor (shape, dtype, int8 scale/zero point) and the label order — use it when porting the pipeline to another language or device. `run_inference.py` applies it (including int8 quantization) and is the reference implementation.
* `README.md` (labels, source-run test accuracy, input requirements), `provenance.json` (source run + record hash, registered model, model and dataset hashes, graphyn version, build time, package run id, sha256 of every file) and `selftest.json` (the shipped script verified on real clips of the training data against the platform's Feature Frontend and the model's input shape).
* Optional HTTP endpoint: `pip install -r requirements-serve.txt && uvicorn serve:app --port 8080`, then `curl --data-binary @clip.wav -H 'Content-Type: audio/wav' localhost:8080/predict`. A **docker** package adds a `Dockerfile` for the same endpoint; **mobile** is a ZIP of the same files plus an Android snippet.
* No `tflite-runtime` / `ai-edge-litert` wheel for your platform? `pip install tensorflow` — the script falls back to `tensorflow.lite`.

Downloads from the console are recorded in the audit log (who, which file, size, sha256). Field-by-field details: [EXAMPLE_06_COVERAGE.md](./EXAMPLE_06_COVERAGE.md) §4 item 22.

---

## Next reading

| Need | Doc |
|---|---|
| Product direction | [PRODUCT_VISION.md](./PRODUCT_VISION.md) |
| Distributed contracts | [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) |
| Docker Compose | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Architecture | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Nodes | [NODE_CATALOGUE.md](./NODE_CATALOGUE.md) |
| Plugins | [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) |
| REST / SDK / CLI / MCP | [API_REFERENCE.md](./API_REFERENCE.md), [SDK_AND_CLI.md](./SDK_AND_CLI.md), [MCP_SERVER.md](./MCP_SERVER.md) |
| Limits | [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) |
